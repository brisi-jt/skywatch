"""The optional real-time ntfy push: cooldown, disabled state, HTTP contract."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from skywatch.db.models import Setting
from skywatch.pipeline.ntfy import NTFY_MIN_INTERVAL_S, NtfyConfig, push_interesting_clip

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


class TestDisabledOrUnconfigured:
    def test_disabled_makes_no_call(self, session):
        cfg = NtfyConfig(enabled=False, topic="skywatch")
        with respx.mock:
            sent = push_interesting_clip(
                cfg, session, title="t", message="m", category="emergency", now=NOW
            )
        assert sent is False

    def test_no_topic_makes_no_call(self, session):
        cfg = NtfyConfig(enabled=True, topic=None)
        with respx.mock:
            sent = push_interesting_clip(
                cfg, session, title="t", message="m", category="emergency", now=NOW
            )
        assert sent is False


class TestPush:
    @respx.mock
    def test_posts_to_the_topic_with_title_and_click_headers(self, session):
        cfg = NtfyConfig(enabled=True, topic="skywatch", server="https://ntfy.sh")
        route = respx.post("https://ntfy.sh/skywatch").mock(return_value=httpx.Response(200))

        sent = push_interesting_clip(
            cfg,
            session,
            title="Skywatch — emergency",
            message="14:07 on Tower: mayday declared",
            category="emergency",
            click_url="/clips/?clip=42",
            now=NOW,
        )

        assert sent is True
        assert route.called
        request = route.calls[0].request
        # the em dash is not ASCII, so the header is percent-encoded per
        # ntfy's documented workaround — this is what regressed first
        assert request.headers["Title"] == "Skywatch%20%E2%80%94%20emergency"
        assert request.headers["Click"] == "/clips/?clip=42"
        assert request.headers["Priority"] == "urgent"
        assert request.content == b"14:07 on Tower: mayday declared"

    @respx.mock
    def test_routine_severity_has_no_urgent_priority(self, session):
        cfg = NtfyConfig(enabled=True, topic="skywatch")
        route = respx.post("https://ntfy.sh/skywatch").mock(return_value=httpx.Response(200))

        push_interesting_clip(cfg, session, title="t", message="m", category="unusual", now=NOW)

        assert "Priority" not in route.calls[0].request.headers

    @respx.mock
    def test_http_failure_raises(self, session):
        cfg = NtfyConfig(enabled=True, topic="skywatch")
        respx.post("https://ntfy.sh/skywatch").mock(return_value=httpx.Response(500))

        with pytest.raises(httpx.HTTPStatusError):
            push_interesting_clip(
                cfg, session, title="t", message="m", category="emergency", now=NOW
            )

    @respx.mock
    def test_records_the_last_sent_timestamp(self, session):
        cfg = NtfyConfig(enabled=True, topic="skywatch")
        respx.post("https://ntfy.sh/skywatch").mock(return_value=httpx.Response(200))

        push_interesting_clip(cfg, session, title="t", message="m", category="emergency", now=NOW)
        session.commit()

        row = session.get(Setting, "ntfy:last_sent_at")
        assert row is not None
        assert row.value == NOW.isoformat()


class TestCooldown:
    @respx.mock
    def test_second_push_within_cooldown_is_skipped(self, session):
        cfg = NtfyConfig(enabled=True, topic="skywatch")
        route = respx.post("https://ntfy.sh/skywatch").mock(return_value=httpx.Response(200))

        first = push_interesting_clip(
            cfg, session, title="t", message="first", category="emergency", now=NOW
        )
        session.commit()
        second = push_interesting_clip(
            cfg,
            session,
            title="t",
            message="second",
            category="emergency",
            now=NOW + timedelta(seconds=NTFY_MIN_INTERVAL_S - 1),
        )

        assert first is True
        assert second is False
        assert route.call_count == 1

    @respx.mock
    def test_push_after_the_cooldown_elapses_sends(self, session):
        cfg = NtfyConfig(enabled=True, topic="skywatch")
        route = respx.post("https://ntfy.sh/skywatch").mock(return_value=httpx.Response(200))

        push_interesting_clip(
            cfg, session, title="t", message="first", category="emergency", now=NOW
        )
        session.commit()
        second = push_interesting_clip(
            cfg,
            session,
            title="t",
            message="second",
            category="emergency",
            now=NOW + timedelta(seconds=NTFY_MIN_INTERVAL_S + 1),
        )

        assert second is True
        assert route.call_count == 2
