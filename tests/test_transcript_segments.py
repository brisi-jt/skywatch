"""Transcript segments: model round-trip, engine output, and the API surface."""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from skywatch.db.enums import AsrEngine
from skywatch.db.models import Recording, Transcript, TranscriptSegment
from skywatch.pipeline.stages.transcribe import run_transcribe
from skywatch.providers.asr.base import TranscriptionResult, TranscriptionSegment
from skywatch.providers.asr.whisper_cpp import WhisperCppEngine

T1 = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class _FakeEngine:
    """An ASR engine double that returns a fixed result and records kwargs."""

    def __init__(self, result: TranscriptionResult) -> None:
        self._result = result
        self.calls: list[dict] = []

    def transcribe(self, audio_path, *, hotwords=None, initial_prompt=None):
        self.calls.append({"hotwords": hotwords, "initial_prompt": initial_prompt})
        return self._result


def _seed_transcript(session: Session, seed) -> Recording:
    freq = seed.frequency()
    return seed.recording(freq)


def test_segment_round_trip(session, seed):
    recording = _seed_transcript(session, seed)
    transcript = seed.transcript(recording)
    session.add(
        TranscriptSegment(
            transcript_id=transcript.id,
            start_s=1.25,
            end_s=3.5,
            text="speedbird two seven six one",
            avg_word_prob=0.8123,
            created_at=T1,
            updated_at=T1,
        )
    )
    session.commit()

    row = session.exec(select(TranscriptSegment)).one()
    assert row.transcript_id == transcript.id
    assert isinstance(row.start_s, float) and row.start_s == 1.25
    assert isinstance(row.end_s, float) and row.end_s == 3.5
    assert row.text == "speedbird two seven six one"
    assert isinstance(row.avg_word_prob, float) and row.avg_word_prob == 0.8123
    assert isinstance(row.created_at, datetime)
    assert isinstance(row.updated_at, datetime)


def test_segment_avg_word_prob_nullable(session, seed):
    recording = _seed_transcript(session, seed)
    transcript = seed.transcript(recording)
    session.add(
        TranscriptSegment(transcript_id=transcript.id, start_s=0.0, end_s=1.0, text="tower")
    )
    session.commit()
    assert session.exec(select(TranscriptSegment)).one().avg_word_prob is None


def test_transcribe_stores_segments(session, seed, tmp_path):
    freq = seed.frequency()
    recording = seed.recording(freq, stage="captured")
    fake = _FakeEngine(
        TranscriptionResult(
            text="mayday speedbird",
            avg_logprob=-0.4,
            language="en",
            engine=AsrEngine.FASTER_WHISPER,
            model="base.en",
            segments=(
                TranscriptionSegment(0.0, 1.2, "mayday", 0.91),
                TranscriptionSegment(1.2, 2.4, "speedbird", None),
            ),
        )
    )
    run_transcribe(session, recording, engine=fake, data_root=tmp_path)
    session.commit()

    transcript = session.exec(select(Transcript)).one()
    segs = session.exec(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == transcript.id)
        .order_by(TranscriptSegment.start_s)
    ).all()
    assert [s.text for s in segs] == ["mayday", "speedbird"]
    assert segs[0].avg_word_prob == 0.91
    assert segs[1].avg_word_prob is None


def test_re_transcribe_replaces_segments_without_orphans(session, seed, tmp_path):
    freq = seed.frequency()
    recording = seed.recording(freq, stage="captured")
    first = _FakeEngine(
        TranscriptionResult(
            text="one two",
            avg_logprob=-0.4,
            language="en",
            engine=AsrEngine.FASTER_WHISPER,
            model="base.en",
            segments=(TranscriptionSegment(0.0, 1.0, "one two", 0.5),),
        )
    )
    run_transcribe(session, recording, engine=first, data_root=tmp_path)
    session.commit()
    second = _FakeEngine(
        TranscriptionResult(
            text="three",
            avg_logprob=-0.3,
            language="en",
            engine=AsrEngine.FASTER_WHISPER,
            model="base.en",
            segments=(TranscriptionSegment(0.0, 0.8, "three", 0.9),),
        )
    )
    run_transcribe(session, recording, engine=second, data_root=tmp_path)
    session.commit()

    assert len(session.exec(select(Transcript)).all()) == 1
    segs = session.exec(select(TranscriptSegment)).all()
    assert [s.text for s in segs] == ["three"]


def test_whisper_cpp_parses_segment_offsets(tmp_path):
    def runner(cmd, **kwargs):
        prefix = cmd[cmd.index("-of") + 1]
        payload = {
            "result": {"language": "en"},
            "transcription": [
                {"offsets": {"from": 0, "to": 1200}, "text": " Mayday."},
                {"offsets": {"from": 1200, "to": 2600}, "text": " Engine failure."},
                {"text": " no offsets here"},
            ],
        }

        class _Done:
            returncode = 0
            stderr = b""
            stdout = b""

        Path(f"{prefix}.json").write_text(json.dumps(payload))
        return _Done()

    engine = WhisperCppEngine(
        binary=Path("/opt/whisper/whisper-cli"),
        model_path=Path("/models/ggml-base.en.bin"),
        model_name="base.en",
        runner=runner,
    )
    audio = tmp_path / "clip.mp3"
    audio.write_bytes(b"fake")
    result = engine.transcribe(audio)
    assert len(result.segments) == 2  # the offset-less entry is dropped
    assert result.segments[0].start_s == 0.0
    assert result.segments[0].end_s == 1.2
    assert result.segments[0].text == "Mayday."
    assert all(seg.avg_word_prob is None for seg in result.segments)


def test_whisper_cpp_accepts_and_ignores_hotwords(tmp_path):
    """whisper.cpp cannot bias; passing hotwords must neither error nor change output."""

    def runner(cmd, **kwargs):
        prefix = cmd[cmd.index("-of") + 1]
        Path(f"{prefix}.json").write_text(
            json.dumps({"result": {"language": "en"}, "transcription": [{"text": " tower"}]})
        )

        class _Done:
            returncode = 0
            stderr = b""
            stdout = b""

        return _Done()

    engine = WhisperCppEngine(
        binary=Path("/opt/whisper/whisper-cli"),
        model_path=Path("/models/ggml-base.en.bin"),
        model_name="base.en",
        runner=runner,
    )
    audio = tmp_path / "clip.mp3"
    audio.write_bytes(b"fake")
    plain = engine.transcribe(audio)
    boosted = engine.transcribe(
        audio, hotwords=["speedbird"], initial_prompt="callsigns: speedbird"
    )
    assert plain.text == boosted.text == "tower"


def test_recording_detail_exposes_segments(client: TestClient, seed, session):
    freq = seed.frequency()
    recording = seed.recording(freq)
    transcript = seed.transcript(recording, text="speedbird two seven six one")
    session.add(
        TranscriptSegment(
            transcript_id=transcript.id,
            start_s=0.0,
            end_s=2.0,
            text="speedbird two seven six one",
            avg_word_prob=0.77,
        )
    )
    session.commit()

    body = client.get(f"/recordings/{recording.id}").json()
    segments = body["transcript"]["segments"]
    assert len(segments) == 1
    assert segments[0]["start_s"] == 0.0
    assert segments[0]["end_s"] == 2.0
    assert segments[0]["text"] == "speedbird two seven six one"
    assert segments[0]["avg_word_prob"] == 0.77
