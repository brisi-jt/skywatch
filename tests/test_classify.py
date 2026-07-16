"""Classification stage tests: skip rules, budget, fallback, upgrade-only."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from skywatch.db.enums import (
    ApiProvider,
    AsrEngine,
    ClassificationCategory,
    ClassificationSource,
    ClassificationStatus,
    FrequencyCategory,
    RecordingStage,
)
from skywatch.db.models import Classification, Frequency, Recording, Transcript
from skywatch.pipeline import budget
from skywatch.pipeline.stages.classify import (
    MIN_LLM_CLIP_SECONDS,
    ClassifyFailed,
    downweight_confidence,
    run_classify,
)
from skywatch.providers.llm.base import ClassifierError, LLMVerdict


class FakeClassifier:
    def __init__(
        self,
        verdict: LLMVerdict | None = None,
        *,
        error: bool = False,
        provider: ApiProvider = ApiProvider.GEMINI,
        model: str = "fake-model",
    ):
        self.provider = provider
        self.model = model
        self._verdict = verdict
        self._error = error
        self.calls = 0

    def classify(self, request) -> LLMVerdict:
        self.calls += 1
        if self._error:
            raise ClassifierError("provider unavailable")
        assert self._verdict is not None
        return self._verdict


def _routine_verdict(model="fake-model"):
    return LLMVerdict(
        is_interesting=False,
        category=ClassificationCategory.ROUTINE,
        confidence=0.9,
        reason="standard clearance readback",
        model=model,
    )


def _interesting_verdict(model="fake-model"):
    return LLMVerdict(
        is_interesting=True,
        category=ClassificationCategory.EMERGENCY,
        confidence=0.95,
        reason="mayday declared",
        model=model,
    )


def _seed(
    session,
    *,
    duration_s=8.0,
    text="cleared to land runway two two",
    category=FrequencyCategory.TOWER,
    avg_logprob=-0.3,
):
    freq = Frequency(label="Twr", mhz=123.805, facility="f", category=category, tuner_group=1)
    session.add(freq)
    session.commit()
    started = datetime.now(UTC)
    rec = Recording(
        freq_id=freq.id,
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=duration_s),
        duration_s=duration_s,
        file_path="recordings/x.mp3",
        sample_rate=8000,
        stage=RecordingStage.TRANSCRIBED,
    )
    session.add(rec)
    session.commit()
    transcript = Transcript(
        recording_id=rec.id,
        engine=AsrEngine.FASTER_WHISPER,
        model="base.en",
        text=text,
        avg_logprob=avg_logprob,
    )
    session.add(transcript)
    session.commit()
    return rec, freq, transcript


class TestDownweight:
    def test_none_logprob_unchanged(self):
        assert downweight_confidence(0.9, None) == 0.9

    def test_good_asr_unchanged(self):
        assert downweight_confidence(0.9, -0.1) == pytest.approx(0.9)

    def test_poor_asr_reduces_confidence(self):
        assert downweight_confidence(0.9, -1.5) < 0.6

    def test_never_below_half(self):
        assert downweight_confidence(0.9, -9.0) >= 0.9 * 0.5


class TestSkipRules:
    def test_blip_skips_llm(self, session):
        rec, freq, transcript = _seed(session, duration_s=1.0, text="roger")
        assert rec.duration_s < MIN_LLM_CLIP_SECONDS
        clf = FakeClassifier(_routine_verdict())
        row = run_classify(
            session, rec, transcript, frequency=freq, chain=[clf], daily_call_cap=900
        )
        assert clf.calls == 0
        assert row.source is ClassificationSource.PREFILTER
        assert row.status is ClassificationStatus.FINAL

    def test_empty_transcript_skips_llm(self, session):
        rec, freq, transcript = _seed(session, text="   ")
        clf = FakeClassifier(_routine_verdict())
        row = run_classify(
            session, rec, transcript, frequency=freq, chain=[clf], daily_call_cap=900
        )
        assert clf.calls == 0
        assert row.status is ClassificationStatus.FINAL


class TestVerdicts:
    def test_llm_verdict_recorded(self, session):
        rec, freq, transcript = _seed(session)
        clf = FakeClassifier(_routine_verdict())
        row = run_classify(
            session, rec, transcript, frequency=freq, chain=[clf], daily_call_cap=900
        )
        assert row.source is ClassificationSource.LLM
        assert row.model == "fake-model"
        assert row.is_interesting is False
        assert row.category is ClassificationCategory.ROUTINE
        assert budget.calls_today(session, ApiProvider.GEMINI, datetime.now(UTC).date()) == 1

    def test_llm_cannot_downgrade_prefilter(self, session):
        rec, freq, transcript = _seed(session, text="mayday mayday mayday engine failure")
        clf = FakeClassifier(_routine_verdict())  # LLM wrongly says routine
        row = run_classify(
            session, rec, transcript, frequency=freq, chain=[clf], daily_call_cap=900
        )
        assert row.is_interesting is True
        assert row.category is ClassificationCategory.EMERGENCY
        assert "keyword:mayday" in row.prefilter_flags

    def test_llm_can_upgrade_routine_prefilter(self, session):
        rec, freq, transcript = _seed(session, text="uh we've got a slight problem here")
        clf = FakeClassifier(_interesting_verdict())
        row = run_classify(
            session, rec, transcript, frequency=freq, chain=[clf], daily_call_cap=900
        )
        assert row.is_interesting is True
        assert row.category is ClassificationCategory.EMERGENCY

    def test_confidence_downweighted_by_poor_asr(self, session):
        rec, freq, transcript = _seed(session, avg_logprob=-1.5)
        clf = FakeClassifier(_routine_verdict())
        row = run_classify(
            session, rec, transcript, frequency=freq, chain=[clf], daily_call_cap=900
        )
        assert row.confidence < 0.9


class TestBudgetAndFallback:
    def test_quota_exhaustion_defers(self, session):
        rec, freq, transcript = _seed(session)
        clf = FakeClassifier(_routine_verdict())
        row = run_classify(session, rec, transcript, frequency=freq, chain=[clf], daily_call_cap=0)
        assert clf.calls == 0
        assert row.source is ClassificationSource.PREFILTER
        assert row.status is ClassificationStatus.DEFERRED

    def test_fallback_provider_used_on_error(self, session):
        rec, freq, transcript = _seed(session)
        broken = FakeClassifier(error=True, provider=ApiProvider.GEMINI)
        backup = FakeClassifier(
            _routine_verdict(model="backup"), provider=ApiProvider.GROQ, model="backup"
        )
        row = run_classify(
            session,
            rec,
            transcript,
            frequency=freq,
            chain=[broken, backup],
            daily_call_cap=900,
        )
        assert broken.calls == 1
        assert backup.calls == 1
        assert row.model == "backup"
        assert row.status is ClassificationStatus.FINAL

    def test_all_providers_error_raises_for_retry(self, session):
        rec, freq, transcript = _seed(session)
        with pytest.raises(ClassifyFailed):
            run_classify(
                session,
                rec,
                transcript,
                frequency=freq,
                chain=[FakeClassifier(error=True)],
                daily_call_cap=900,
            )

    def test_empty_chain_is_prefilter_only_final(self, session):
        rec, freq, transcript = _seed(session)
        row = run_classify(session, rec, transcript, frequency=freq, chain=[], daily_call_cap=900)
        assert row.source is ClassificationSource.PREFILTER
        assert row.status is ClassificationStatus.FINAL

    def test_backfill_appends_final_after_deferral(self, session):
        rec, freq, transcript = _seed(session)
        deferred = run_classify(
            session,
            rec,
            transcript,
            frequency=freq,
            chain=[FakeClassifier()],
            daily_call_cap=0,
        )
        assert deferred.status is ClassificationStatus.DEFERRED
        session.commit()
        clf = FakeClassifier(_routine_verdict())
        row = run_classify(
            session,
            rec,
            transcript,
            frequency=freq,
            chain=[clf],
            daily_call_cap=900,
            backfill=True,
        )
        assert row is not None
        assert row.status is ClassificationStatus.FINAL
        assert row.source is ClassificationSource.LLM
        rows = session.exec(select(Classification)).all()
        assert len(rows) == 2  # history kept; latest wins

    def test_backfill_without_budget_is_noop(self, session):
        rec, freq, transcript = _seed(session)
        run_classify(
            session,
            rec,
            transcript,
            frequency=freq,
            chain=[FakeClassifier()],
            daily_call_cap=0,
        )
        session.commit()
        row = run_classify(
            session,
            rec,
            transcript,
            frequency=freq,
            chain=[FakeClassifier()],
            daily_call_cap=0,
            backfill=True,
        )
        assert row is None
        assert len(session.exec(select(Classification)).all()) == 1
