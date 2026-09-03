"""The daily narrative: generation, caching, budget-awareness, and digest wiring."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from skywatch.db.enums import ApiProvider
from skywatch.pipeline import budget, narrative
from skywatch.pipeline.worker import PipelineWorker

LONDON = ZoneInfo("Europe/London")
DAY = date(2026, 7, 10)


class FakeNarrator:
    """A classifier-chain member that only narrates."""

    def __init__(self, *, provider=ApiProvider.GEMINI, text="A calm morning on the airwaves."):
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


def _seed_day(seed):
    freq = seed.frequency()
    routine = seed.recording(freq, started=datetime(2026, 7, 10, 8, 0, tzinfo=UTC))
    seed.classification(routine, is_interesting=False)
    exciting = seed.recording(freq, started=datetime(2026, 7, 10, 10, 30, tzinfo=UTC))
    seed.transcript(exciting, text="Stansted Tower, going around, Speedbird 12.")
    seed.classification(exciting, is_interesting=True)
    return freq


class TestGeneration:
    def test_generates_and_caches(self, session, seed):
        _seed_day(seed)
        narrator = FakeNarrator(text="Two transmissions, one go-around.")

        result = narrative.generate_narrative(
            session, day=DAY, tz=LONDON, chain=[narrator], daily_call_cap=900
        )
        session.commit()

        assert result is not None
        assert result.text == "Two transmissions, one go-around."
        assert result.rolling is False
        assert narrator.calls == 1
        # the day's counts and the interesting moment reached the model
        assert "Transmissions recorded: 2" in narrator.user_seen
        assert "going around" in narrator.user_seen.lower()

        cached = narrative.cached_narrative(session, DAY)
        assert cached is not None
        assert cached.text == "Two transmissions, one go-around."

    def test_no_recordings_returns_none(self, session, seed):
        seed.frequency()
        narrator = FakeNarrator()

        result = narrative.generate_narrative(
            session, day=DAY, tz=LONDON, chain=[narrator], daily_call_cap=900
        )

        assert result is None
        assert narrator.calls == 0

    def test_empty_chain_returns_none(self, session, seed):
        _seed_day(seed)
        assert (
            narrative.generate_narrative(session, day=DAY, tz=LONDON, chain=[], daily_call_cap=900)
            is None
        )

    def test_budget_exhausted_returns_none(self, session, seed):
        _seed_day(seed)
        budget.record_call(session, ApiProvider.GEMINI, datetime.now(UTC).date(), count=900)
        session.commit()
        narrator = FakeNarrator()

        result = narrative.generate_narrative(
            session, day=DAY, tz=LONDON, chain=[narrator], daily_call_cap=900
        )

        assert result is None
        assert narrator.calls == 0  # never called once the cap is reached

    def test_falls_through_to_second_provider(self, session, seed):
        _seed_day(seed)
        budget.record_call(session, ApiProvider.GEMINI, datetime.now(UTC).date(), count=900)
        session.commit()
        primary = FakeNarrator(provider=ApiProvider.GEMINI)
        fallback = FakeNarrator(provider=ApiProvider.GROQ, text="Fallback wrote this.")

        result = narrative.generate_narrative(
            session, day=DAY, tz=LONDON, chain=[primary, fallback], daily_call_cap=900
        )
        session.commit()

        assert result is not None
        assert result.text == "Fallback wrote this."
        assert primary.calls == 0
        assert fallback.calls == 1

    def test_call_is_metered(self, session, seed):
        _seed_day(seed)
        narrator = FakeNarrator()

        narrative.generate_narrative(
            session, day=DAY, tz=LONDON, chain=[narrator], daily_call_cap=900
        )
        session.commit()

        assert budget.calls_today(session, ApiProvider.GEMINI, datetime.now(UTC).date()) == 1


class TestOncePerDayViaWorker:
    def test_maintenance_generates_once(self, engine, seed, tmp_path):
        _seed_day(seed)
        # the worker generates for "today" — seed a recording for the real today
        freq = seed.frequency(label="Second freq", mhz=118.5)
        seed.recording(freq, started=datetime.now(UTC))
        narrator = FakeNarrator(text="Today's story.")
        worker = PipelineWorker(
            engine,
            data_root=tmp_path,
            asr_engine=object(),
            classifier_chain=[narrator],
            enricher=None,
            daily_call_cap=900,
            retention_days=14,
            min_free_disk_gb=0.001,
            station_tz=ZoneInfo("UTC"),
        )

        worker._maybe_generate_narrative()
        worker._maybe_generate_narrative()

        assert narrator.calls == 1  # the cache hit prevents a second call


class TestDigestWiring:
    def test_digest_carries_the_narrative(self, client, seed, session):
        _seed_day(seed)
        narrative.generate_narrative(
            session,
            day=DAY,
            tz=LONDON,
            chain=[FakeNarrator(text="A quiet but eventful day.")],
            daily_call_cap=900,
        )
        session.commit()

        body = client.get("/digest", params={"date": "2026-07-10"}).json()

        assert body["narrative"]["text"] == "A quiet but eventful day."
        assert body["narrative"]["rolling"] is False

    def test_digest_narrative_null_when_absent(self, client, seed):
        _seed_day(seed)
        body = client.get("/digest", params={"date": "2026-07-10"}).json()
        assert body["narrative"] is None
