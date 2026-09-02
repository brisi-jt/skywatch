"""Deterministic prefilters that run on every clip before any LLM call.

Three families of flags: distress/urgency keywords in the transcript, the
guard frequency itself, and per-channel duration outliers. A prefilter
verdict is a floor — the LLM may upgrade a clip to interesting but can
never downgrade one the prefilters flagged.

Keyword phrases are deliberately conservative: a false-positive here is
permanent (never downgraded), so bare words with routine uses ("fuel",
"pan" inside company names) do not appear — only their distress phrasings.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from skywatch.db.enums import ClassificationCategory, FrequencyCategory

GUARD_FLAG = "guard_frequency"
DURATION_OUTLIER_FLAG = "duration_outlier"
WATCH_PHRASE_PREFIX = "watch_phrase:"
_WATCH_PHRASE_CONFIDENCE = 0.9
INTERESTING_AIRCRAFT_PREFIX = "interesting_aircraft:"


def _aircraft_alert_confidence(rank: int) -> float:
    """Confidence for an interesting-aircraft flag, strongest for rank 1."""
    return max(0.4, 0.8 - 0.1 * (max(1, rank) - 1))


# (canonical keyword, matching variants, category). Matching is
# case-insensitive on hyphen-normalised text; every variant of a keyword
# raises the same canonical flag.
_KEYWORD_RULES: list[tuple[str, tuple[str, ...], ClassificationCategory]] = [
    ("mayday", ("mayday",), ClassificationCategory.EMERGENCY),
    ("pan pan", ("pan pan",), ClassificationCategory.URGENCY),
    (
        "declaring emergency",
        ("declaring an emergency", "declare an emergency", "declaring emergency"),
        ClassificationCategory.EMERGENCY,
    ),
    ("7700", ("7700", "seven seven zero zero"), ClassificationCategory.EMERGENCY),
    ("7600", ("7600", "seven six zero zero"), ClassificationCategory.UNUSUAL),
    ("7500", ("7500", "seven five zero zero"), ClassificationCategory.EMERGENCY),
    ("hijack", ("hijack",), ClassificationCategory.EMERGENCY),
    ("engine failure", ("engine failure",), ClassificationCategory.EMERGENCY),
    ("engine fire", ("engine fire",), ClassificationCategory.EMERGENCY),
    (
        "go around",
        ("go around", "going around", "missed approach"),
        ClassificationCategory.GO_AROUND,
    ),
    ("minimum fuel", ("minimum fuel",), ClassificationCategory.FUEL),
    (
        "fuel emergency",
        ("fuel emergency", "low fuel", "short of fuel"),
        ClassificationCategory.FUEL,
    ),
    ("medical", ("medical", "paramedic", "unconscious"), ClassificationCategory.MEDICAL),
    ("bird strike", ("bird strike",), ClassificationCategory.UNUSUAL),
    ("runway incursion", ("runway incursion",), ClassificationCategory.UNUSUAL),
    (
        "rejected takeoff",
        ("rejected takeoff", "aborted takeoff", "rejecting takeoff"),
        ClassificationCategory.UNUSUAL,
    ),
    ("tcas", ("tcas", "resolution advisory"), ClassificationCategory.UNUSUAL),
    ("diverting", ("diverting to", "request diversion"), ClassificationCategory.UNUSUAL),
    (
        "unlawful interference",
        ("unlawful interference",),
        ClassificationCategory.EMERGENCY,
    ),
]

KEYWORD_CATEGORIES: dict[str, ClassificationCategory] = {
    canonical: category for canonical, _variants, category in _KEYWORD_RULES
}

# Category ordering when several flags fire: most severe first.
_CATEGORY_SEVERITY = [
    ClassificationCategory.EMERGENCY,
    ClassificationCategory.URGENCY,
    ClassificationCategory.MEDICAL,
    ClassificationCategory.FUEL,
    ClassificationCategory.GO_AROUND,
    ClassificationCategory.UNUSUAL,
    ClassificationCategory.GUARD_ACTIVITY,
    ClassificationCategory.OTHER,
]

_KEYWORD_CONFIDENCE = 0.9
_GUARD_CONFIDENCE = 0.7
_OUTLIER_CONFIDENCE = 0.4
_ROUTINE_CONFIDENCE = 0.6

OUTLIER_MIN_SAMPLES = 10
OUTLIER_SIGMA = 3.0


@dataclass(frozen=True)
class PrefilterVerdict:
    """The deterministic floor verdict for one clip."""

    flags: list[str] = field(default_factory=list)
    is_interesting: bool = False
    category: ClassificationCategory = ClassificationCategory.ROUTINE
    confidence: float = _ROUTINE_CONFIDENCE
    reason: str = "no prefilter flags"


def _normalise(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def keyword_flags(text: str) -> list[str]:
    """Distress-keyword flags found in a transcript, in rule order."""
    haystack = _normalise(text)
    return [
        f"keyword:{canonical}"
        for canonical, variants, _category in _KEYWORD_RULES
        if any(variant in haystack for variant in variants)
    ]


def watch_phrase_flags(text: str, watch_phrases: Sequence[str]) -> list[str]:
    """Configured watch phrases present in a transcript, in configured order."""
    haystack = _normalise(text)
    flags: list[str] = []
    for phrase in watch_phrases:
        needle = _normalise(phrase)
        if needle and needle in haystack and phrase not in flags:
            flags.append(phrase)
    return flags


def duration_is_outlier(
    duration_s: float,
    recent_durations: Sequence[float],
    *,
    min_samples: int = OUTLIER_MIN_SAMPLES,
    sigma: float = OUTLIER_SIGMA,
) -> bool:
    """Whether a clip runs unusually long for its channel.

    Uses rolling mean + sigma·stdev over the channel's recent clips and
    stays quiet until enough history exists to say anything meaningful.
    """
    if len(recent_durations) < min_samples:
        return False
    mean = statistics.fmean(recent_durations)
    stdev = statistics.pstdev(recent_durations)
    return duration_s > mean + sigma * max(stdev, 1.0)


def run_prefilters(
    *,
    transcript_text: str | None,
    duration_s: float,
    freq_category: FrequencyCategory,
    recent_durations: Sequence[float] = (),
    watch_phrases: Sequence[str] = (),
    aircraft_alert: tuple[str, int] | None = None,
) -> PrefilterVerdict:
    flags: list[str] = []
    categories: list[ClassificationCategory] = []
    reasons: list[str] = []
    confidence = 0.0

    if transcript_text:
        kw_flags = keyword_flags(transcript_text)
        if kw_flags:
            flags.extend(kw_flags)
            categories.extend(
                KEYWORD_CATEGORIES[flag.removeprefix("keyword:")] for flag in kw_flags
            )
            reasons.append(f"distress keywords: {', '.join(kw_flags)}")
            confidence = max(confidence, _KEYWORD_CONFIDENCE)

        matched_phrases = watch_phrase_flags(transcript_text, watch_phrases)
        if matched_phrases:
            flags.extend(f"{WATCH_PHRASE_PREFIX}{phrase}" for phrase in matched_phrases)
            categories.extend(ClassificationCategory.OTHER for _ in matched_phrases)
            quoted = ", ".join(f"'{phrase}'" for phrase in matched_phrases)
            reasons.append(f"watch phrase heard: {quoted}")
            confidence = max(confidence, _WATCH_PHRASE_CONFIDENCE)

    if freq_category is FrequencyCategory.GUARD:
        flags.append(GUARD_FLAG)
        categories.append(ClassificationCategory.GUARD_ACTIVITY)
        reasons.append("transmission on the guard frequency")
        confidence = max(confidence, _GUARD_CONFIDENCE)

    if duration_is_outlier(duration_s, recent_durations):
        flags.append(DURATION_OUTLIER_FLAG)
        categories.append(ClassificationCategory.UNUSUAL)
        reasons.append(f"duration {duration_s:.1f}s is a channel outlier")
        confidence = max(confidence, _OUTLIER_CONFIDENCE)

    if aircraft_alert is not None:
        category_name, rank = aircraft_alert
        flags.append(f"{INTERESTING_AIRCRAFT_PREFIX}{category_name}")
        categories.append(ClassificationCategory.UNUSUAL)
        reasons.append(f"interesting aircraft nearby: {category_name} (rank {rank})")
        confidence = max(confidence, _aircraft_alert_confidence(rank))

    if not flags:
        return PrefilterVerdict()

    category = min(categories, key=_CATEGORY_SEVERITY.index)
    return PrefilterVerdict(
        flags=flags,
        is_interesting=True,
        category=category,
        confidence=confidence,
        reason="; ".join(reasons),
    )
