"""Ask the station: retrieval, budget/rate-limit gating, and the /ask route."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlmodel import Session

from skywatch.api.deps import get_classifier_chain
from skywatch.api.errors import ProblemException
from skywatch.api.services import ask as ask_service
from skywatch.db.engine import create_db_engine
from skywatch.db.enums import ApiProvider
from skywatch.pipeline import budget

_ALEMBIC_ROOT = Path(__file__).resolve().parent.parent / "src" / "skywatch" / "db" / "alembic"

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


class FakeNarrator:
    """A classifier-chain member that only narrates (mirrors test_narrative.py)."""

    def __init__(self, *, provider=ApiProvider.GEMINI, text="The station heard nothing unusual."):
        self.provider = provider
        self.model = "fake-model"
        self.text = text
        self.system_seen: str | None = None
        self.user_seen: str | None = None
        self.calls = 0

    def classify(self, request):  # pragma: no cover - not exercised here
        raise NotImplementedError

    def narrate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.system_seen = system_prompt
        self.user_seen = user_prompt
        return self.text


def _seed_clips(seed):
    freq = seed.frequency()
    mayday = seed.recording(freq, started=NOW - timedelta(hours=1))
    seed.transcript(mayday, text="Mayday mayday mayday, engine failure, Speedbird 12.")
    routine = seed.recording(freq, started=NOW - timedelta(hours=2))
    seed.transcript(routine, text="Tower, good morning, request taxi.")
    return mayday, routine


class TestAnswering:
    def test_answers_grounded_in_relevant_clips(self, session, seed):
        mayday, _routine = _seed_clips(seed)
        narrator = FakeNarrator(text="Yes — an aircraft declared a mayday for engine failure.")

        result = ask_service.answer_question(
            session,
            question="Was there a mayday today?",
            chain=[narrator],
            daily_call_cap=900,
            fts_available=False,
            now=NOW,
        )

        assert result.answer == "Yes — an aircraft declared a mayday for engine failure."
        assert [s.recording_id for s in result.sources] == [mayday.id]
        assert narrator.calls == 1
        assert "mayday" in narrator.user_seen.lower()
        assert "Was there a mayday today?" in narrator.user_seen

    def test_irrelevant_clip_is_not_retrieved(self, session, seed):
        _mayday, routine = _seed_clips(seed)
        narrator = FakeNarrator()

        result = ask_service.answer_question(
            session,
            question="Was there a mayday today?",
            chain=[narrator],
            daily_call_cap=900,
            fts_available=False,
            now=NOW,
        )

        assert routine.id not in [s.recording_id for s in result.sources]

    def test_no_matching_clips_still_answers_honestly(self, session, seed):
        _seed_clips(seed)
        narrator = FakeNarrator(text="Nothing like that has been heard.")

        result = ask_service.answer_question(
            session,
            question="Was there a helicopter rescue?",
            chain=[narrator],
            daily_call_cap=900,
            fts_available=False,
            now=NOW,
        )

        assert result.sources == []
        assert result.answer == "Nothing like that has been heard."
        assert narrator.calls == 1
        assert "No recorded clips matched" in narrator.user_seen

    def test_context_is_capped(self, session, seed):
        freq = seed.frequency()
        for i in range(ask_service.MAX_CONTEXT_CLIPS + 3):
            rec = seed.recording(freq, started=NOW - timedelta(minutes=i))
            seed.transcript(rec, text=f"Speedbird {i}, mayday, mayday.")
        narrator = FakeNarrator()

        result = ask_service.answer_question(
            session,
            question="mayday",
            chain=[narrator],
            daily_call_cap=900,
            fts_available=False,
            now=NOW,
        )

        assert len(result.sources) == ask_service.MAX_CONTEXT_CLIPS

    def test_falls_through_to_second_provider(self, session, seed):
        _seed_clips(seed)
        budget.record_call(session, ApiProvider.GEMINI, NOW.date(), count=900)
        session.commit()
        primary = FakeNarrator(provider=ApiProvider.GEMINI)
        fallback = FakeNarrator(provider=ApiProvider.GROQ, text="Fallback answered this.")

        result = ask_service.answer_question(
            session,
            question="mayday",
            chain=[primary, fallback],
            daily_call_cap=900,
            fts_available=False,
            now=NOW,
        )

        assert result.answer == "Fallback answered this."
        assert primary.calls == 0
        assert fallback.calls == 1


class TestUnavailable:
    def test_budget_exhausted_is_a_503(self, session, seed):
        _seed_clips(seed)
        budget.record_call(session, ApiProvider.GEMINI, NOW.date(), count=900)
        session.commit()
        narrator = FakeNarrator()

        with pytest.raises(ProblemException) as exc:
            ask_service.answer_question(
                session,
                question="mayday",
                chain=[narrator],
                daily_call_cap=900,
                fts_available=False,
                now=NOW,
            )

        assert exc.value.status_code == 503
        assert exc.value.code == "ask_unavailable"
        assert narrator.calls == 0

    def test_no_classifier_configured_is_a_503(self, session, seed):
        _seed_clips(seed)

        with pytest.raises(ProblemException) as exc:
            ask_service.answer_question(
                session,
                question="mayday",
                chain=[],
                daily_call_cap=900,
                fts_available=False,
                now=NOW,
            )

        assert exc.value.status_code == 503
        assert exc.value.code == "ask_unavailable"

    def test_blank_question_is_a_validation_error(self, session, seed):
        with pytest.raises(ProblemException) as exc:
            ask_service.answer_question(
                session,
                question="   ",
                chain=[FakeNarrator()],
                daily_call_cap=900,
                fts_available=False,
                now=NOW,
            )

        assert exc.value.status_code == 422
        assert exc.value.code == "validation_error"


class TestRateLimit:
    def test_second_question_too_soon_is_rate_limited(self, session, seed):
        _seed_clips(seed)
        ask_service.answer_question(
            session,
            question="mayday",
            chain=[FakeNarrator(text="First answer.")],
            daily_call_cap=900,
            fts_available=False,
            now=NOW,
        )

        with pytest.raises(ProblemException) as exc:
            ask_service.answer_question(
                session,
                question="mayday again",
                chain=[FakeNarrator()],
                daily_call_cap=900,
                fts_available=False,
                now=NOW + timedelta(seconds=1),
            )

        assert exc.value.status_code == 429
        assert exc.value.code == "ask_rate_limited"
        assert exc.value.extensions["retry_after_s"] > 0

    def test_rate_limit_clears_after_the_cooldown(self, session, seed):
        _seed_clips(seed)
        ask_service.answer_question(
            session,
            question="mayday",
            chain=[FakeNarrator(text="First answer.")],
            daily_call_cap=900,
            fts_available=False,
            now=NOW,
        )

        result = ask_service.answer_question(
            session,
            question="mayday again",
            chain=[FakeNarrator(text="Second answer.")],
            daily_call_cap=900,
            fts_available=False,
            now=NOW + timedelta(seconds=ask_service.MIN_ASK_INTERVAL_S + 1),
        )

        assert result.answer == "Second answer."


class TestAskRoute:
    """The wired-up HTTP contract, via the standard station/client fixtures."""

    def _use_chain(self, station, chain):
        station.app.dependency_overrides[get_classifier_chain] = lambda: chain

    def test_ask_returns_a_grounded_answer(self, station, client, seed):
        _seed_clips(seed)
        self._use_chain(station, [FakeNarrator(text="Yes, one mayday call.")])

        response = client.post("/ask", json={"question": "Was there a mayday?"})

        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "Yes, one mayday call."
        assert body["question"] == "Was there a mayday?"
        assert len(body["sources"]) == 1

    def test_empty_question_is_rejected(self, station, client, seed):
        self._use_chain(station, [FakeNarrator()])

        response = client.post("/ask", json={"question": ""})

        assert response.status_code == 422

    def test_no_classifier_is_a_503(self, station, client, seed):
        _seed_clips(seed)
        self._use_chain(station, [])

        response = client.post("/ask", json={"question": "Was there a mayday?"})

        assert response.status_code == 503
        assert response.json()["code"] == "ask_unavailable"

    def test_asking_twice_quickly_is_rate_limited(self, station, client, seed):
        _seed_clips(seed)
        self._use_chain(station, [FakeNarrator()])

        assert client.post("/ask", json={"question": "one"}).status_code == 200
        second = client.post("/ask", json={"question": "two"})

        assert second.status_code == 429
        assert second.json()["code"] == "ask_rate_limited"


def _migrate(db_path):
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_ROOT))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


class TestFtsRetrieval:
    """The bm25-ranked path, against a real FTS5-migrated database."""

    def test_ranks_the_best_match_first(self, tmp_path, monkeypatch):
        from conftest import Seeder

        monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
        data_root = tmp_path / "data"
        data_root.mkdir()
        db_path = data_root / "station.db"
        _migrate(db_path)
        engine = create_db_engine(db_path)

        with Session(engine) as session:
            seed = Seeder(session, data_root=data_root)
            freq = seed.frequency()
            strong = seed.recording(freq, started=NOW - timedelta(hours=1))
            seed.transcript(strong, text="Mayday mayday mayday, engine failure.")
            weak = seed.recording(freq, started=NOW - timedelta(hours=2))
            seed.transcript(weak, text="Tower, mayday relay for another aircraft.")
            seed.recording(freq, started=NOW - timedelta(hours=3))  # no transcript, no match

            recordings = ask_service._retrieve(session, "mayday", fts_available=True)

            assert [r.id for r in recordings] == [strong.id, weak.id]
