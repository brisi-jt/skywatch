"""The weekly digest email: input building, rendering, scheduling, and sending."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import select

from skywatch.db.enums import ClassificationCategory
from skywatch.db.models import Setting
from skywatch.pipeline import narrative, weekly_email
from skywatch.pipeline.weekly_email import EmailDigestConfig
from skywatch.pipeline.worker import PipelineWorker

LONDON = ZoneInfo("Europe/London")


def _seed_week(seed, *, base=datetime(2026, 7, 12, 9, 0, tzinfo=UTC)):
    """A Sunday-anchored week: one routine clip, one emergency, one go-around."""
    freq = seed.frequency(label="Tower", mhz=123.8)
    routine = seed.recording(freq, started=base)
    seed.classification(routine, is_interesting=False)
    emergency = seed.recording(freq, started=base.replace(hour=11))
    seed.transcript(emergency, text="Mayday mayday mayday.")
    seed.classification(
        emergency,
        is_interesting=True,
        category=ClassificationCategory.EMERGENCY,
        confidence=0.95,
        reason="Mayday call",
    )
    go_around = seed.recording(freq, started=base.replace(hour=14))
    seed.classification(
        go_around,
        is_interesting=True,
        category=ClassificationCategory.GO_AROUND,
        confidence=0.7,
        reason="Went around",
    )
    return freq, routine, emergency, go_around


class TestIsDue:
    def test_matches_configured_day_and_hour(self):
        sunday_8am = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)  # a Sunday
        assert weekly_email.is_due(day="sun", hour=8, now_local=sunday_8am) is True

    def test_wrong_day_is_not_due(self):
        monday_8am = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
        assert weekly_email.is_due(day="sun", hour=8, now_local=monday_8am) is False

    def test_before_the_hour_is_not_due(self):
        sunday_7am = datetime(2026, 7, 12, 7, 0, tzinfo=UTC)
        assert weekly_email.is_due(day="sun", hour=8, now_local=sunday_7am) is False

    def test_stays_due_for_the_rest_of_the_day(self):
        sunday_11pm = datetime(2026, 7, 12, 23, 0, tzinfo=UTC)
        assert weekly_email.is_due(day="sun", hour=8, now_local=sunday_11pm) is True


class TestBuildWeeklyEmailInput:
    def test_counts_and_top_clips(self, session, seed):
        _seed_week(seed)
        now = datetime(2026, 7, 12, 20, 0, tzinfo=UTC)

        result = weekly_email.build_weekly_email_input(session, tz=LONDON, now=now)

        assert result.total_count == 3
        assert result.interesting_count == 2
        assert result.category_counts == {"emergency": 1, "go_around": 1}
        # the emergency (weight 5 * confidence 0.95) outranks the go-around
        # (weight 3 * confidence 0.7), even though both are "interesting"
        assert [c.category for c in result.top_clips] == ["emergency", "go_around"]

    def test_quiet_week_has_no_clips(self, session, seed):
        seed.frequency()
        now = datetime(2026, 7, 12, 20, 0, tzinfo=UTC)

        result = weekly_email.build_weekly_email_input(session, tz=LONDON, now=now)

        assert result.total_count == 0
        assert result.interesting_count == 0
        assert result.top_clips == []
        assert result.narrative_text is None

    def test_stitches_cached_daily_narratives(self, session, seed):
        _seed_week(seed)
        narrative._store(
            session,
            date(2026, 7, 10),
            narrative.Narrative(
                text="A quiet Friday.",
                generated_at=datetime(2026, 7, 10, 23, 0, tzinfo=UTC),
                rolling=False,
            ),
        )
        session.commit()
        now = datetime(2026, 7, 12, 20, 0, tzinfo=UTC)

        result = weekly_email.build_weekly_email_input(session, tz=LONDON, now=now)

        assert result.narrative_text is not None
        assert "A quiet Friday." in result.narrative_text
        assert "Friday" in result.narrative_text


class TestRenderWeeklyEmail:
    def test_quiet_week_renders_plainly(self):
        result = weekly_email.WeeklyEmailInput(
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 13),
            total_count=0,
            interesting_count=0,
            category_counts={},
            top_clips=[],
            narrative_text=None,
        )
        subject, html = weekly_email.render_weekly_email(
            result, station_name="My Airband Station", base_url=None
        )
        assert "My Airband Station" in subject
        assert "quiet week" in html

    def test_full_week_renders_narrative_stats_and_clip_links(self):
        result = weekly_email.WeeklyEmailInput(
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 13),
            total_count=3,
            interesting_count=2,
            category_counts={"emergency": 1, "go_around": 1},
            top_clips=[
                weekly_email.WeeklyTopClip(
                    recording_id=42,
                    local_time="Sun 11:00",
                    freq_label="Tower",
                    category="emergency",
                    reason="Mayday call",
                )
            ],
            narrative_text="Sunday: a mayday call kept things exciting.",
        )
        subject, html = weekly_email.render_weekly_email(
            result, station_name="My Airband Station", base_url="https://sky.example.ts.net"
        )
        assert "3" in html and "2" in html
        assert "a mayday call kept things exciting" in html
        assert 'https://sky.example.ts.net/clips/?clip=42"' in html
        assert "Mayday call" in html

    def test_falls_back_to_relative_links_without_a_base_url(self):
        result = weekly_email.WeeklyEmailInput(
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 13),
            total_count=1,
            interesting_count=1,
            category_counts={"emergency": 1},
            top_clips=[
                weekly_email.WeeklyTopClip(
                    recording_id=7,
                    local_time="Mon 09:00",
                    freq_label="Tower",
                    category="emergency",
                    reason="Mayday call",
                )
            ],
            narrative_text=None,
        )
        _, html = weekly_email.render_weekly_email(result, station_name=None, base_url=None)
        assert '"/clips/?clip=7"' in html

    def test_html_escapes_untrusted_text(self):
        result = weekly_email.WeeklyEmailInput(
            week_start=date(2026, 7, 6),
            week_end=date(2026, 7, 13),
            total_count=1,
            interesting_count=1,
            category_counts={"emergency": 1},
            top_clips=[
                weekly_email.WeeklyTopClip(
                    recording_id=1,
                    local_time="Mon 09:00",
                    freq_label="Tower",
                    category="emergency",
                    reason="<script>alert(1)</script>",
                )
            ],
            narrative_text=None,
        )
        _, html = weekly_email.render_weekly_email(result, station_name=None, base_url=None)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class FakeSMTP:
    """A drop-in for smtplib.SMTP that records the send instead of dialling out."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_args = None
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, from_addr, to_addrs, message):
        self.sent = (from_addr, to_addrs, message)


class RaisingSMTP(FakeSMTP):
    def sendmail(self, from_addr, to_addrs, message):
        raise OSError("connection refused")


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    FakeSMTP.instances.clear()
    yield
    FakeSMTP.instances.clear()


class TestSendEmail:
    def test_sends_via_smtp_with_starttls_and_login(self, monkeypatch):
        monkeypatch.setattr(weekly_email.smtplib, "SMTP", FakeSMTP)
        cfg = EmailDigestConfig(
            enabled=True,
            to=("a@example.com", "b@example.com"),
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user",
            smtp_password="pass",
            smtp_from="skywatch@example.com",
        )

        weekly_email.send_email(cfg, subject="Test", html_body="<p>hi</p>")

        smtp = FakeSMTP.instances[0]
        assert smtp.host == "smtp.example.com"
        assert smtp.started_tls is True
        assert smtp.login_args == ("user", "pass")
        from_addr, to_addrs, message = smtp.sent
        assert from_addr == "skywatch@example.com"
        assert to_addrs == ["a@example.com", "b@example.com"]
        assert "Test" in message

    def test_skips_login_without_credentials(self, monkeypatch):
        monkeypatch.setattr(weekly_email.smtplib, "SMTP", FakeSMTP)
        cfg = EmailDigestConfig(enabled=True, to=("a@example.com",), smtp_host="smtp.example.com")

        weekly_email.send_email(cfg, subject="Test", html_body="<p>hi</p>")

        assert FakeSMTP.instances[0].login_args is None

    def test_send_failure_propagates(self, monkeypatch):
        monkeypatch.setattr(weekly_email.smtplib, "SMTP", RaisingSMTP)
        cfg = EmailDigestConfig(enabled=True, to=("a@example.com",), smtp_host="smtp.example.com")

        with pytest.raises(OSError):
            weekly_email.send_email(cfg, subject="Test", html_body="<p>hi</p>")


def _worker(engine, tmp_path, monkeypatch, *, wall_clock, email_config):
    monkeypatch.setattr(weekly_email.smtplib, "SMTP", FakeSMTP)
    return PipelineWorker(
        engine,
        data_root=tmp_path,
        asr_engine=object(),
        classifier_chain=[],
        enricher=None,
        daily_call_cap=900,
        retention_days=14,
        min_free_disk_gb=0.001,
        station_tz=UTC,
        email_config=email_config,
        wall_clock=wall_clock,
    )


class TestMaintenancePassScheduledTrigger:
    def test_sends_on_the_configured_day_and_hour(self, engine, seed, tmp_path, monkeypatch):
        _seed_week(seed)
        sunday_9am = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)
        cfg = EmailDigestConfig(
            enabled=True, to=("owner@example.com",), day="sun", hour=8, smtp_host="smtp.example.com"
        )
        worker = _worker(
            engine, tmp_path, monkeypatch, wall_clock=lambda: sunday_9am, email_config=cfg
        )

        worker._maybe_send_weekly_email()

        assert len(FakeSMTP.instances) == 1
        assert FakeSMTP.instances[0].sent is not None

    def test_does_not_send_twice_the_same_day(self, engine, seed, tmp_path, monkeypatch):
        _seed_week(seed)
        sunday_9am = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)
        cfg = EmailDigestConfig(
            enabled=True, to=("owner@example.com",), day="sun", hour=8, smtp_host="smtp.example.com"
        )
        worker = _worker(
            engine, tmp_path, monkeypatch, wall_clock=lambda: sunday_9am, email_config=cfg
        )

        worker._maybe_send_weekly_email()
        worker._maybe_send_weekly_email()

        assert len(FakeSMTP.instances) == 1

    def test_does_not_send_on_the_wrong_day(self, engine, seed, tmp_path, monkeypatch):
        _seed_week(seed)
        monday_9am = datetime(2026, 7, 13, 9, 0, tzinfo=UTC)
        cfg = EmailDigestConfig(
            enabled=True, to=("owner@example.com",), day="sun", hour=8, smtp_host="smtp.example.com"
        )
        worker = _worker(
            engine, tmp_path, monkeypatch, wall_clock=lambda: monday_9am, email_config=cfg
        )

        worker._maybe_send_weekly_email()

        assert FakeSMTP.instances == []

    def test_disabled_never_sends(self, engine, seed, tmp_path, monkeypatch):
        _seed_week(seed)
        sunday_9am = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)
        cfg = EmailDigestConfig(enabled=False, to=("owner@example.com",), day="sun", hour=8)
        worker = _worker(
            engine, tmp_path, monkeypatch, wall_clock=lambda: sunday_9am, email_config=cfg
        )

        worker._maybe_send_weekly_email()

        assert FakeSMTP.instances == []


class TestMaintenancePassFailureIsolation:
    def test_send_failure_does_not_crash_the_maintenance_pass(
        self, engine, seed, tmp_path, monkeypatch
    ):
        _seed_week(seed)
        sunday_9am = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)
        cfg = EmailDigestConfig(
            enabled=True, to=("owner@example.com",), day="sun", hour=8, smtp_host="smtp.example.com"
        )
        monkeypatch.setattr(weekly_email.smtplib, "SMTP", RaisingSMTP)
        worker = PipelineWorker(
            engine,
            data_root=tmp_path,
            asr_engine=object(),
            classifier_chain=[],
            enricher=None,
            daily_call_cap=900,
            retention_days=14,
            min_free_disk_gb=0.001,
            station_tz=UTC,
            email_config=cfg,
            wall_clock=lambda: sunday_9am,
        )

        worker._maintenance_pass()  # must not raise

        # the pass ran to completion despite the email failure: the heartbeat
        # write (an earlier step in the same pass) still happened
        from sqlmodel import Session

        from skywatch.db.models import Heartbeat

        with Session(engine) as check_session:
            assert len(check_session.exec(select(Heartbeat)).all()) == 1

    def test_failed_send_leaves_no_sent_marker_so_it_retries(
        self, engine, seed, tmp_path, monkeypatch
    ):
        _seed_week(seed)
        sunday_9am = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)
        cfg = EmailDigestConfig(
            enabled=True, to=("owner@example.com",), day="sun", hour=8, smtp_host="smtp.example.com"
        )
        monkeypatch.setattr(weekly_email.smtplib, "SMTP", RaisingSMTP)
        worker = PipelineWorker(
            engine,
            data_root=tmp_path,
            asr_engine=object(),
            classifier_chain=[],
            enricher=None,
            daily_call_cap=900,
            retention_days=14,
            min_free_disk_gb=0.001,
            station_tz=UTC,
            email_config=cfg,
            wall_clock=lambda: sunday_9am,
        )

        worker._maintenance_pass()

        from sqlmodel import Session

        with Session(engine) as check_session:
            marker = check_session.get(Setting, weekly_email.sent_marker_key(sunday_9am.date()))
        assert marker is None
