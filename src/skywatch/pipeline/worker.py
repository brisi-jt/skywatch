"""The pipeline worker: drives every captured clip through to classified.

Consumes ``recordings`` rows (the watcher owns file → row), never files.
Two logical paths per clip share one stage column:

- fast path: enrichment runs promptly after capture because OpenSky's
  historical window is only one hour; its failures are retried briefly and
  then recorded, but they never block the slow path;
- slow path: transcription (strictly sequential — ASR is slower than real
  time on the production machine) then budgeted classification, with
  prefilter-flagged clips classified first.

Single process. Stage claims are committed before work starts, so a crash
leaves rows in an in-flight stage; ``reset_in_flight`` rolls those back on
startup and every stage is idempotent on re-run.
"""

import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from skywatch.db.engine import create_db_engine, default_db_path, session_scope
from skywatch.db.enums import RecordingStage
from skywatch.db.models import Classification, Frequency, Recording, Setting, Transcript
from skywatch.pipeline import budget
from skywatch.pipeline.prefilters import run_prefilters
from skywatch.pipeline.retention import CAPTURE_PAUSED_KEY, check_disk, prune_routine_audio
from skywatch.pipeline.stages.classify import run_classify
from skywatch.pipeline.stages.enrich import run_enrich
from skywatch.pipeline.stages.transcribe import run_transcribe
from skywatch.settings import Settings

logger = logging.getLogger(__name__)

_ENRICH = "enrich"
_TRANSCRIBE = "transcribe"
_CLASSIFY = "classify"

RECENT_DURATION_WINDOW = 50
"""How many recent clips per channel feed the duration-outlier statistics."""


def queue_depths(session: Session) -> dict[str, int]:
    """Recordings per stage — the API's queue-depth view of the pipeline."""
    depths = {stage.value: 0 for stage in RecordingStage}
    rows = session.exec(select(Recording.stage, func.count()).group_by(Recording.stage)).all()
    for stage, count in rows:
        depths[RecordingStage(stage).value] = count
    return depths


def _recent_durations(
    session: Session, freq_id: int, exclude_id: int, limit: int = RECENT_DURATION_WINDOW
) -> list[float]:
    return list(
        session.exec(
            select(Recording.duration_s)
            .where(Recording.freq_id == freq_id, Recording.id != exclude_id)
            .order_by(Recording.id.desc())  # type: ignore[union-attr]
            .limit(limit)
        ).all()
    )


class PipelineWorker:
    def __init__(
        self,
        engine,
        *,
        data_root: Path,
        asr_engine,
        classifier_chain: list,
        enricher,
        daily_call_cap: int,
        retention_days: int,
        min_free_disk_gb: float,
        capture_source=None,
        watcher=None,
        max_attempts: int = 3,
        backoff_base_s: float = 30.0,
        maintenance_interval_s: float = 900.0,
        backfill_batch: int = 20,
        monotonic=time.monotonic,
    ) -> None:
        self._engine = engine
        self._data_root = Path(data_root)
        self._asr = asr_engine
        self._chain = classifier_chain
        self._enricher = enricher
        self.daily_call_cap = daily_call_cap
        self._retention_days = retention_days
        self._min_free_disk_gb = min_free_disk_gb
        self._capture_source = capture_source
        self._watcher = watcher
        self._max_attempts = max(1, max_attempts)
        self._backoff_base_s = backoff_base_s
        self._maintenance_interval_s = maintenance_interval_s
        self._backfill_batch = backfill_batch
        self._monotonic = monotonic
        self._attempts: dict[tuple[int, str], int] = {}
        self._retry_at: dict[tuple[int, str], float] = {}
        self._last_maintenance: float | None = None
        self._paused_for_disk = False
        self._stop_event = threading.Event()

    # -- retry bookkeeping (in-memory: a restart simply retries) ------------

    def _due(self, rec_id: int, stage_key: str) -> bool:
        return self._monotonic() >= self._retry_at.get((rec_id, stage_key), 0.0)

    def _exhausted(self, rec_id: int, stage_key: str) -> bool:
        return self._attempts.get((rec_id, stage_key), 0) >= self._max_attempts

    def _register_failure(self, rec_id: int, stage_key: str) -> int:
        key = (rec_id, stage_key)
        attempts = self._attempts.get(key, 0) + 1
        self._attempts[key] = attempts
        self._retry_at[key] = self._monotonic() + self._backoff_base_s * (2 ** (attempts - 1))
        return attempts

    def _clear_failures(self, rec_id: int, stage_key: str) -> None:
        self._attempts.pop((rec_id, stage_key), None)
        self._retry_at.pop((rec_id, stage_key), None)

    @staticmethod
    def _clear_own_error(recording: Recording, prefix: str) -> None:
        """Clear a stage's own recorded error on success — never another
        stage's (an abandoned enrichment failure must survive a later
        successful transcription)."""
        if recording.stage_error and recording.stage_error.startswith(prefix):
            recording.stage_error = None

    # -- lifecycle -----------------------------------------------------------

    def reset_in_flight(self) -> None:
        """Roll interrupted stage claims back to their queue states."""
        rollback = {
            RecordingStage.ENRICHING: RecordingStage.CAPTURED,
            RecordingStage.CLASSIFYING: RecordingStage.TRANSCRIBED,
        }
        with session_scope(self._engine) as session:
            rows = session.exec(
                select(Recording).where(
                    Recording.stage.in_(list(rollback))  # type: ignore[attr-defined]
                )
            ).all()
            for recording in rows:
                logger.info(
                    "resuming recording %s: %s -> %s",
                    recording.id,
                    recording.stage.value,
                    rollback[recording.stage].value,
                )
                recording.stage = rollback[recording.stage]
                session.add(recording)

    def tick(self) -> None:
        """One pass over every queue; safe to call as often as you like."""
        self._enrich_pass()
        self._transcribe_pass()
        self._classify_pass()
        self._backfill_pass()
        self._maintenance_pass()

    def run(self, *, poll_seconds: float = 1.0) -> None:
        """Startup, then tick until stopped; owns the watcher and source."""
        self.reset_in_flight()
        if self._watcher is not None:
            self._watcher.start()
        if self._capture_source is not None:
            self._capture_source.start()
        logger.info("pipeline worker running (data root %s)", self._data_root)
        try:
            while not self._stop_event.is_set():
                try:
                    self.tick()
                except Exception:
                    logger.exception("tick failed; continuing")
                self._stop_event.wait(poll_seconds)
        finally:
            if self._capture_source is not None:
                self._capture_source.stop()
            if self._watcher is not None:
                self._watcher.stop()
            logger.info("pipeline worker stopped")

    def request_stop(self) -> None:
        self._stop_event.set()

    # -- fast path: enrichment ------------------------------------------------

    def _enrich_pass(self) -> None:
        with Session(self._engine) as session:
            rows = session.exec(
                select(Recording.id, Recording.stage)
                .where(
                    Recording.stage.in_(  # type: ignore[attr-defined]
                        [RecordingStage.CAPTURED, RecordingStage.FAILED_ENRICH]
                    )
                )
                .order_by(Recording.id)
            ).all()
        for rec_id, stage in rows:
            if stage == RecordingStage.FAILED_ENRICH and not self._due(rec_id, _ENRICH):
                continue
            self._enrich_one(rec_id)

    def _enrich_one(self, rec_id: int) -> None:
        with session_scope(self._engine) as session:
            recording = session.get(Recording, rec_id)
            if recording is None or recording.stage not in (
                RecordingStage.CAPTURED,
                RecordingStage.FAILED_ENRICH,
            ):
                return
            recording.stage = RecordingStage.ENRICHING
            session.add(recording)
        try:
            with session_scope(self._engine) as session:
                recording = session.get(Recording, rec_id)
                frequency = session.get(Frequency, recording.freq_id)
                outcome = run_enrich(
                    session, recording, enricher=self._enricher, frequency=frequency
                )
                recording.stage = RecordingStage.TRANSCRIBING
                recording.stage_error = None
                session.add(recording)
            self._clear_failures(rec_id, _ENRICH)
            if outcome.skipped_reason:
                logger.debug("recording %s not enriched: %s", rec_id, outcome.skipped_reason)
        except Exception as exc:
            attempts = self._register_failure(rec_id, _ENRICH)
            with session_scope(self._engine) as session:
                recording = session.get(Recording, rec_id)
                if attempts >= self._max_attempts:
                    # Enrichment never blocks the slow path: give up and move on.
                    recording.stage = RecordingStage.TRANSCRIBING
                    recording.stage_error = f"enrichment failed after {attempts} attempt(s): {exc}"
                    logger.warning(
                        "recording %s: enrichment abandoned after %d attempts: %s",
                        rec_id,
                        attempts,
                        exc,
                    )
                else:
                    recording.stage = RecordingStage.FAILED_ENRICH
                    recording.stage_error = f"enrichment failed: {exc}"
                    logger.info(
                        "recording %s: enrichment attempt %d failed, will retry: %s",
                        rec_id,
                        attempts,
                        exc,
                    )
                session.add(recording)

    # -- slow path: transcription ---------------------------------------------

    def _transcribe_pass(self) -> None:
        with Session(self._engine) as session:
            rows = session.exec(
                select(Recording.id, Recording.stage)
                .where(
                    Recording.stage.in_(  # type: ignore[attr-defined]
                        [RecordingStage.TRANSCRIBING, RecordingStage.FAILED_TRANSCRIBE]
                    )
                )
                .order_by(Recording.id)
            ).all()
        # Strictly sequential: one clip at a time through the ASR engine.
        for rec_id, stage in rows:
            if stage == RecordingStage.FAILED_TRANSCRIBE and (
                self._exhausted(rec_id, _TRANSCRIBE) or not self._due(rec_id, _TRANSCRIBE)
            ):
                continue
            self._transcribe_one(rec_id)

    def _transcribe_one(self, rec_id: int) -> None:
        try:
            with session_scope(self._engine) as session:
                recording = session.get(Recording, rec_id)
                if recording is None or recording.stage not in (
                    RecordingStage.TRANSCRIBING,
                    RecordingStage.FAILED_TRANSCRIBE,
                ):
                    return
                run_transcribe(session, recording, engine=self._asr, data_root=self._data_root)
                recording.stage = RecordingStage.TRANSCRIBED
                self._clear_own_error(recording, "transcription")
                session.add(recording)
            self._clear_failures(rec_id, _TRANSCRIBE)
        except Exception as exc:
            attempts = self._register_failure(rec_id, _TRANSCRIBE)
            with session_scope(self._engine) as session:
                recording = session.get(Recording, rec_id)
                recording.stage = RecordingStage.FAILED_TRANSCRIBE
                recording.stage_error = f"transcription failed: {exc}"
                session.add(recording)
            level = logging.ERROR if attempts >= self._max_attempts else logging.INFO
            logger.log(
                level,
                "recording %s: transcription attempt %d/%d failed: %s",
                rec_id,
                attempts,
                self._max_attempts,
                exc,
            )

    # -- slow path: classification ---------------------------------------------

    def _classify_pass(self) -> None:
        with Session(self._engine) as session:
            rows = session.exec(
                select(Recording)
                .where(
                    Recording.stage.in_(  # type: ignore[attr-defined]
                        [RecordingStage.TRANSCRIBED, RecordingStage.FAILED_CLASSIFY]
                    )
                )
                .order_by(Recording.id)
            ).all()
            candidates: list[tuple[bool, int]] = []
            for recording in rows:
                if recording.stage == RecordingStage.FAILED_CLASSIFY and (
                    self._exhausted(recording.id, _CLASSIFY)
                    or not self._due(recording.id, _CLASSIFY)
                ):
                    continue
                transcript = self._latest_transcript(session, recording.id)
                frequency = session.get(Frequency, recording.freq_id)
                verdict = run_prefilters(
                    transcript_text=transcript.text if transcript else None,
                    duration_s=recording.duration_s,
                    freq_category=frequency.category,
                )
                candidates.append((verdict.is_interesting, recording.id))
        # Prefilter-flagged clips go through the (budgeted) LLM first.
        candidates.sort(key=lambda item: (not item[0], item[1]))
        for _, rec_id in candidates:
            self._classify_one(rec_id)

    @staticmethod
    def _latest_transcript(session: Session, recording_id: int) -> Transcript | None:
        return session.exec(
            select(Transcript)
            .where(Transcript.recording_id == recording_id)
            .order_by(Transcript.id.desc())  # type: ignore[union-attr]
        ).first()

    def _classify_one(self, rec_id: int) -> None:
        with session_scope(self._engine) as session:
            recording = session.get(Recording, rec_id)
            if recording is None or recording.stage not in (
                RecordingStage.TRANSCRIBED,
                RecordingStage.FAILED_CLASSIFY,
            ):
                return
            recording.stage = RecordingStage.CLASSIFYING
            session.add(recording)
        try:
            with session_scope(self._engine) as session:
                recording = session.get(Recording, rec_id)
                frequency = session.get(Frequency, recording.freq_id)
                transcript = self._latest_transcript(session, rec_id)
                run_classify(
                    session,
                    recording,
                    transcript,
                    frequency=frequency,
                    chain=self._chain,
                    daily_call_cap=self.daily_call_cap,
                    recent_durations=_recent_durations(session, recording.freq_id, rec_id),
                )
                recording.stage = RecordingStage.CLASSIFIED
                self._clear_own_error(recording, "classification")
                session.add(recording)
            self._clear_failures(rec_id, _CLASSIFY)
        except Exception as exc:
            attempts = self._register_failure(rec_id, _CLASSIFY)
            with session_scope(self._engine) as session:
                recording = session.get(Recording, rec_id)
                recording.stage = RecordingStage.FAILED_CLASSIFY
                recording.stage_error = f"classification failed: {exc}"
                session.add(recording)
            level = logging.ERROR if attempts >= self._max_attempts else logging.INFO
            logger.log(
                level,
                "recording %s: classification attempt %d/%d failed: %s",
                rec_id,
                attempts,
                self._max_attempts,
                exc,
            )

    # -- deferred backfill -------------------------------------------------------

    def _backfill_pass(self) -> None:
        """Upgrade quota-deferred verdicts once LLM budget is available again."""
        if not self._chain:
            return
        today = datetime.now(UTC).date()
        with Session(self._engine) as session:
            if all(
                budget.remaining(session, clf.provider, today, self.daily_call_cap) <= 0
                for clf in self._chain
            ):
                return
            deferred_ids = self._deferred_recording_ids(session)
        for rec_id in deferred_ids[: self._backfill_batch]:
            try:
                with session_scope(self._engine) as session:
                    recording = session.get(Recording, rec_id)
                    frequency = session.get(Frequency, recording.freq_id)
                    transcript = self._latest_transcript(session, rec_id)
                    row = run_classify(
                        session,
                        recording,
                        transcript,
                        frequency=frequency,
                        chain=self._chain,
                        daily_call_cap=self.daily_call_cap,
                        recent_durations=_recent_durations(session, recording.freq_id, rec_id),
                        backfill=True,
                    )
                if row is not None:
                    logger.info("backfilled deferred classification for recording %s", rec_id)
            except Exception:
                logger.exception("backfill failed for recording %s", rec_id)

    @staticmethod
    def _deferred_recording_ids(session: Session) -> list[int]:
        """Recordings whose LATEST classification is still deferred."""
        deferred = session.exec(
            select(Classification.recording_id).where(Classification.status == "deferred")
        ).all()
        result = []
        for rec_id in sorted(set(deferred)):
            latest = session.exec(
                select(Classification)
                .where(Classification.recording_id == rec_id)
                .order_by(Classification.id.desc())  # type: ignore[union-attr]
            ).first()
            if latest is not None and latest.status == "deferred":
                result.append(rec_id)
        return result

    # -- maintenance: retention + disk guard --------------------------------------

    def _maintenance_pass(self) -> None:
        now = self._monotonic()
        if (
            self._last_maintenance is not None
            and now - self._last_maintenance < self._maintenance_interval_s
        ):
            return
        self._last_maintenance = now
        disk = check_disk(self._data_root, self._min_free_disk_gb)
        with session_scope(self._engine) as session:
            paused_row = session.get(Setting, CAPTURE_PAUSED_KEY)
            currently_paused = paused_row is not None and paused_row.value == "1"
            if disk.low and not currently_paused:
                logger.warning(
                    "free disk %.2f GB below the %.2f GB floor; pausing capture",
                    disk.free_gb,
                    disk.min_free_gb,
                )
                if self._capture_source is not None:
                    self._capture_source.stop()
                self._set_paused(session, paused_row, "1")
                self._paused_for_disk = True
            elif not disk.low and currently_paused:
                logger.info("disk space recovered (%.2f GB free); resuming capture", disk.free_gb)
                if self._capture_source is not None:
                    self._capture_source.start()
                self._set_paused(session, paused_row, "0")
                self._paused_for_disk = False
            else:
                self._paused_for_disk = currently_paused
        try:
            with session_scope(self._engine) as session:
                prune_routine_audio(
                    session,
                    data_root=self._data_root,
                    retention_days=self._retention_days,
                )
        except Exception:
            logger.exception("retention pruning failed; will retry next pass")

    @staticmethod
    def _set_paused(session: Session, row: Setting | None, value: str) -> None:
        if row is None:
            session.add(Setting(key=CAPTURE_PAUSED_KEY, value=value))
        else:
            row.value = value
            session.add(row)

    # -- status ---------------------------------------------------------------------

    def status_snapshot(self) -> dict:
        """Queue depths, budget usage, disk, and capture state in one shape.

        The API process derives the same view from the database plus
        ``check_disk``; this method is the worker-side convenience.
        """
        today = datetime.now(UTC).date()
        with Session(self._engine) as session:
            queues = queue_depths(session)
            budgets: dict[str, dict] = {}
            for classifier in self._chain:
                budgets[classifier.provider.value] = {
                    "calls": budget.calls_today(session, classifier.provider, today),
                    "cap": self.daily_call_cap,
                }
            if self._enricher is not None:
                from skywatch.db.enums import ApiProvider

                budgets[ApiProvider.OPENSKY.value] = {
                    "calls": budget.calls_today(session, ApiProvider.OPENSKY, today),
                    "cap": getattr(self._enricher, "daily_credit_cap", None),
                }
        disk = check_disk(self._data_root, self._min_free_disk_gb)
        source_status = self._capture_source.status() if self._capture_source is not None else None
        return {
            "queues": queues,
            "budget": budgets,
            "disk": {
                "free_gb": disk.free_gb,
                "total_gb": disk.total_gb,
                "min_free_gb": disk.min_free_gb,
                "low": disk.low,
            },
            "capture": {
                "running": source_status.running if source_status else False,
                "detail": source_status.detail if source_status else "no capture source",
                "paused_for_disk": self._paused_for_disk,
            },
        }


# -- wiring ------------------------------------------------------------------------


def _repo_relative(name: str) -> Path:
    """Resolve a repo-tree directory (content/, fixtures/) from cwd or source."""
    candidates = [Path(name), Path(__file__).resolve().parents[3] / name]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"cannot locate the {name!r} directory; run from the repo root")


def build_worker(settings: Settings, engine=None) -> PipelineWorker:
    """Wire a worker from settings: providers, watcher, and capture source."""
    from skywatch.capture.live import LiveSDRSource
    from skywatch.capture.replay import ReplaySource
    from skywatch.capture.watcher import RecordingWatcher
    from skywatch.providers.asr import create_asr_engine
    from skywatch.providers.flightdata.airlines import AirlineDirectory
    from skywatch.providers.flightdata.opensky import OpenSkyClient, OpenSkyEnricher
    from skywatch.providers.llm import build_classifier_chain

    if engine is None:
        engine = create_db_engine(default_db_path(settings.data_root))
    data_root = settings.data_root.resolve()
    recordings_dir = settings.capture.output_dir
    if not recordings_dir.is_absolute():
        recordings_dir = recordings_dir.resolve()

    asr_engine = create_asr_engine(settings.asr)
    chain = build_classifier_chain(
        settings.llm,
        gemini_api_key=settings.gemini_api_key,
        groq_api_key=settings.groq_api_key,
    )

    enricher = None
    if settings.enrichment.provider == "opensky":
        missing = []
        if not (settings.opensky_client_id and settings.opensky_client_secret):
            missing.append("OPENSKY_CLIENT_ID/OPENSKY_CLIENT_SECRET")
        if settings.receiver.lat is None or settings.receiver.lon is None:
            missing.append("receiver.lat/receiver.lon")
        if missing:
            logger.warning("enrichment disabled: %s not configured", ", ".join(missing))
        else:
            enricher = OpenSkyEnricher(
                OpenSkyClient(settings.opensky_client_id, settings.opensky_client_secret),
                receiver_lat=settings.receiver.lat,
                receiver_lon=settings.receiver.lon,
                radius_km=settings.enrichment.radius_km,
                bucket_seconds=settings.enrichment.bucket_seconds,
                daily_credit_cap=settings.enrichment.daily_credit_cap,
                airlines=AirlineDirectory.load(_repo_relative("content") / "airlines.dat"),
            )

    watcher = RecordingWatcher(engine, recordings_dir, data_root=data_root)

    if settings.capture.source == "replay":
        fixtures = sorted(_repo_relative("fixtures").glob("*.mp3"))
        with Session(engine) as session:
            active = session.exec(
                select(Frequency).where(Frequency.is_active.is_(True))  # type: ignore[attr-defined]
            ).all()
        freqs_hz = [round(f.mhz * 1_000_000) for f in active] or [121_500_000]
        capture_source = ReplaySource(fixtures, recordings_dir, freqs_hz=freqs_hz, pacing_s=2.0)
    else:
        capture_source = LiveSDRSource(
            engine,
            settings.capture,
            conf_path=data_root / "rtl_airband.conf",
            recordings_dir=recordings_dir,
        )

    return PipelineWorker(
        engine,
        data_root=data_root,
        asr_engine=asr_engine,
        classifier_chain=chain,
        enricher=enricher,
        daily_call_cap=settings.llm.daily_call_cap,
        retention_days=settings.retention.routine_audio_days,
        min_free_disk_gb=settings.retention.min_free_disk_gb,
        capture_source=capture_source,
        watcher=watcher,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings()
    worker = build_worker(settings)
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.request_stop()


if __name__ == "__main__":
    main()
