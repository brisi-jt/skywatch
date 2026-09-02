"""Compare two ASR models on the labelled eval set (dev-box only).

Transcribes every clip in ``content/eval_set.yaml`` with two faster-whisper
models and reports, per model, how often the prefilter's verdict matches the
labelled ``expected_interesting`` / ``expected_category`` plus the raw
transcripts side by side so callsign fidelity can be eyeballed.

This needs the ``asr`` extra installed and downloads each model on first use,
so it never runs in CI. Example:

    uv run python scripts/eval_asr.py \
        --model-a base.en \
        --model-b jlvdoorn/whisper-base.en-atco2-asr

The jacktol / ATCO2 fine-tunes are faster-whisper-compatible; pass any
Hugging Face repo id or local CTranslate2 model directory.
"""

import argparse
from pathlib import Path

import yaml

from skywatch.db.enums import FrequencyCategory
from skywatch.pipeline.prefilters import run_prefilters
from skywatch.providers.asr.faster_whisper import FasterWhisperEngine

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_SET = REPO_ROOT / "content" / "eval_set.yaml"


def _load_clips() -> list[dict]:
    return yaml.safe_load(EVAL_SET.read_text())["clips"]


def _score(model_name: str, compute_type: str) -> None:
    engine = FasterWhisperEngine(model=model_name, compute_type=compute_type)
    clips = _load_clips()
    interesting_hits = 0
    category_hits = 0
    print(f"\n=== {model_name} ({compute_type}) ===")
    for clip in clips:
        result = engine.transcribe(REPO_ROOT / clip["file"])
        category = FrequencyCategory(clip["frequency_category"])
        verdict = run_prefilters(
            transcript_text=result.text,
            duration_s=clip.get("duration_s", 10.0),
            freq_category=category,
        )
        interesting_ok = verdict.is_interesting == clip["expected_interesting"]
        category_ok = verdict.category.value == clip["expected_category"]
        interesting_hits += interesting_ok
        category_hits += category_ok
        mark = "OK " if interesting_ok else "MISS"
        print(f"  [{mark}] {clip['file']}")
        print(f"        heard: {result.text[:110]}")
    total = len(clips)
    print(f"  interesting accuracy: {interesting_hits}/{total}")
    print(f"  category accuracy:    {category_hits}/{total}")


def main() -> None:
    parser = argparse.ArgumentParser(description="A/B two ASR models on the eval set")
    parser.add_argument("--model-a", default="base.en", help="baseline model")
    parser.add_argument(
        "--model-b",
        default="jlvdoorn/whisper-base.en-atco2-asr",
        help="candidate ATC-tuned model (HF repo id or local CT2 dir)",
    )
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()

    _score(args.model_a, args.compute_type)
    _score(args.model_b, args.compute_type)
    print(
        "\nKeep prod on base.en; flip the dev default only if the candidate is "
        "clearly better on both metrics AND its transcripts read cleaner."
    )


if __name__ == "__main__":
    main()
