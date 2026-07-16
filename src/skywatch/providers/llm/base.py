"""The contract every LLM classifier honours, plus verdict parsing."""

import json
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from skywatch.db.enums import ApiProvider, ClassificationCategory, FrequencyCategory


class ClassifierError(RuntimeError):
    """The provider could not produce a verdict; try the next in the chain."""


@dataclass(frozen=True)
class ClassifyRequest:
    """Everything a classifier is told about one clip."""

    transcript: str
    duration_s: float
    frequency_label: str
    frequency_category: FrequencyCategory
    prefilter_flags: list[str]
    asr_avg_logprob: float | None


@dataclass(frozen=True)
class LLMVerdict:
    """A classifier's structured answer."""

    is_interesting: bool
    category: ClassificationCategory
    confidence: float
    reason: str
    model: str


@runtime_checkable
class Classifier(Protocol):
    provider: ApiProvider
    model: str

    def classify(self, request: ClassifyRequest) -> LLMVerdict:
        """Classify one clip; raises ``ClassifierError`` on any failure."""
        ...


def parse_verdict(text: str, model: str) -> LLMVerdict:
    """Parse a provider's JSON verdict into an ``LLMVerdict``.

    Unknown categories map to ``other`` (models occasionally invent labels);
    anything structurally wrong raises ``ClassifierError`` so the fallback
    chain can take over.
    """
    try:
        payload = json.loads(text)
        is_interesting = bool(payload["is_interesting"])
        raw_category = str(payload["category"]).strip().lower()
        confidence = float(payload["confidence"])
        reason = str(payload["reason"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ClassifierError(f"unparseable verdict: {text[:200]!r}") from exc
    try:
        category = ClassificationCategory(raw_category)
    except ValueError:
        category = ClassificationCategory.OTHER
        reason = f"{reason} (model category {raw_category!r})"
    return LLMVerdict(
        is_interesting=is_interesting,
        category=category,
        confidence=min(1.0, max(0.0, confidence)),
        reason=reason,
        model=model,
    )
