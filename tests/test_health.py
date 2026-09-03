"""Contract tests for GET /health/history and the health-history builder."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlmodel import Session

from skywatch.api.services.health import build_health_history
from skywatch.db.models import Heartbeat

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _heartbeat(session: Session, *, age_days: float, anchor: datetime = NOW, **kwargs) -> Heartbeat:
    defaults = dict(
        capture_running=True,
        queue_depths={"captured": 1},
        disk_free_gb=20.0,
        llm_remaining=900,
        opensky_remaining=3000,
    )
    defaults.update(kwargs)
    row = Heartbeat(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    session.exec(
        update(Heartbeat)
        .where(Heartbeat.id == row.id)
        .values(created_at=anchor - timedelta(days=age_days))
    )
    session.commit()
    session.refresh(row)
    return row


class TestBuildHealthHistory:
    def test_empty_history(self, session):
        result = build_health_history(session, now=NOW)
        assert result.items == []
        assert result.until == NOW
        assert result.since == NOW - timedelta(days=7)

    def test_orders_oldest_first_within_default_window(self, session):
        newer = _heartbeat(session, age_days=1)
        older = _heartbeat(session, age_days=5)
        result = build_health_history(session, now=NOW)
        assert [item.recorded_at for item in result.items] == [
            older.created_at,
            newer.created_at,
        ]

    def test_excludes_snapshots_outside_the_window(self, session):
        _heartbeat(session, age_days=10)  # older than the default 7-day window
        in_window = _heartbeat(session, age_days=2)
        result = build_health_history(session, now=NOW)
        assert len(result.items) == 1
        assert result.items[0].recorded_at == in_window.created_at

    def test_explicit_since_and_until(self, session):
        _heartbeat(session, age_days=30)
        target = _heartbeat(session, age_days=15)
        _heartbeat(session, age_days=1)
        result = build_health_history(
            session,
            since=NOW - timedelta(days=20),
            until=NOW - timedelta(days=10),
            now=NOW,
        )
        assert len(result.items) == 1
        assert result.items[0].recorded_at == target.created_at

    def test_limit_caps_the_result(self, session):
        for i in range(5):
            _heartbeat(session, age_days=i)
        result = build_health_history(session, limit=2, now=NOW)
        assert len(result.items) == 2

    def test_resource_shape_matches_the_row(self, session):
        _heartbeat(
            session,
            age_days=1,
            capture_running=False,
            queue_depths={"captured": 3, "classified": 7},
            disk_free_gb=1.25,
            llm_remaining=None,
            opensky_remaining=None,
        )
        result = build_health_history(session, now=NOW)
        item = result.items[0]
        assert item.capture_running is False
        assert item.queue_depths == {"captured": 3, "classified": 7}
        assert item.disk_free_gb == 1.25
        assert item.llm_remaining is None
        assert item.opensky_remaining is None


class TestHealthHistoryRoute:
    def test_fresh_station_returns_empty_list(self, client):
        response = client.get("/health/history")
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["_links"]["self"]["href"] == "/health/history"

    def test_reflects_written_heartbeats(self, client, session):
        real_now = datetime.now(UTC)
        _heartbeat(session, age_days=1, anchor=real_now)
        body = client.get("/health/history").json()
        assert len(body["items"]) == 1
        assert body["items"][0]["disk_free_gb"] == 20.0

    def test_since_and_until_query_params_narrow_the_range(self, client, session):
        real_now = datetime.now(UTC)
        _heartbeat(session, age_days=30, anchor=real_now)
        _heartbeat(session, age_days=1, anchor=real_now)
        response = client.get(
            "/health/history",
            params={"since": (real_now - timedelta(days=2)).isoformat()},
        )
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1

    def test_limit_query_param_is_bounded(self, client):
        response = client.get("/health/history", params={"limit": 0})
        assert response.status_code == 422
