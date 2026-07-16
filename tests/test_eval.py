"""Classifier accuracy evaluation against the labelled fixture set.

Run manually (never in CI) after any prompt or model change:

    uv run pytest -m eval -s

Uses the real ASR engine and the real classifier chain from your local
configuration, so it needs the ASR extra installed and (unless llm.provider
is none) an API key in the environment.
"""

from pathlib import Path

import pytest
import yaml

from skywatch.db.enums import ClassificationCategory, FrequencyCategory
from skywatch.pipeline.prefilters import run_prefilters
from skywatch.pipeline.stages.classify import evaluate_clip
from skywatch.providers.asr import create_asr_engine
from skywatch.providers.llm import build_classifier_chain
from skywatch.settings import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_SET = REPO_ROOT / "content" / "eval_set.yaml"

pytestmark = pytest.mark.eval


def _load_clips() -> list[dict]:
    manifest = yaml.safe_load(EVAL_SET.read_text())
    return manifest["clips"]


def test_eval_set_manifest_is_valid():
    clips = _load_clips()
    assert clips, "eval set is empty"
    for clip in clips:
        assert (REPO_ROOT / clip["file"]).exists(), clip["file"]
        FrequencyCategory(clip["frequency_category"])
        ClassificationCategory(clip["expected_category"])
        assert isinstance(clip["expected_interesting"], bool)


def test_classifier_verdicts_match_labels():
    settings = Settings()
    asr = create_asr_engine(settings.asr)
    chain = build_classifier_chain(
        settings.llm,
        gemini_api_key=settings.gemini_api_key,
        groq_api_key=settings.groq_api_key,
    )

    results = []
    for clip in _load_clips():
        audio = REPO_ROOT / clip["file"]
        transcription = asr.transcribe(audio)
        category = FrequencyCategory(clip["frequency_category"])
        prefilter = run_prefilters(
            transcript_text=transcription.text,
            duration_s=clip.get("duration_s", 10.0),
            freq_category=category,
        )
        verdict = evaluate_clip(
            transcript_text=transcription.text,
            duration_s=clip.get("duration_s", 10.0),
            frequency_label=clip.get("frequency_label", category.value),
            freq_category=category,
            prefilter=prefilter,
            chain=chain,
            asr_avg_logprob=transcription.avg_logprob,
        )
        ok = verdict.is_interesting == clip["expected_interesting"]
        results.append((clip["file"], ok, verdict, transcription.text))

    print("\n--- eval report ---")
    for file, ok, verdict, text in results:
        mark = "PASS" if ok else "FAIL"
        print(
            f"{mark} {file}: interesting={verdict.is_interesting} "
            f"category={verdict.category} confidence={verdict.confidence:.2f}"
        )
        print(f"     transcript: {text[:100]}")

    failures = [file for file, ok, *_ in results if not ok]
    assert not failures, f"verdict mismatches: {failures}"
