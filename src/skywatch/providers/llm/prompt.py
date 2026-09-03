"""The shared classification prompt and JSON verdict schema.

Every provider sends the same system prompt and per-clip user prompt, so a
provider swap changes cost and quality but never the task definition.
"""

from skywatch.db.enums import ClassificationCategory
from skywatch.providers.llm.base import ClassifyRequest

_CATEGORIES = ", ".join(member.value for member in ClassificationCategory)

SYSTEM_PROMPT = f"""You classify short VHF airband radio transmissions as routine or \
non-routine for an aviation monitoring station near London Stansted.

ROUTINE traffic (the overwhelming majority) sounds like standard ICAO phraseology:
- clearances and readbacks: "cleared to land runway 22", "cleared for takeoff",
  "line up and wait", "hold short", taxi instructions
- frequency changes and handoffs: "contact London 118.825", "with you passing 2400"
- altimeter/QNH settings, transition levels, squawk code assignments
- ATIS broadcasts, wind checks, position reports, standard departures/arrivals
- routine pushback, start-up, and taxi requests

NON-ROUTINE traffic is anything a human would want surfaced:
- distress and urgency: MAYDAY, PAN PAN, emergency declarations
- emergency squawks spoken aloud: 7700 (emergency), 7600 (radio failure),
  7500 (unlawful interference)
- go-arounds and missed approaches, runway incursions or rejected takeoffs
- medical situations, fuel concerns (minimum fuel and beyond), diversions
- bird strikes, technical failures, TCAS resolution advisories
- any transmission on the 121.5 guard frequency beyond routine radio checks

The transcript comes from automatic speech recognition of noisy AM radio; it
will contain errors. Weigh garbled fragments accordingly and do not invent
detail that is not in the text.

Reply with ONLY a JSON object, no prose, matching:
{{"is_interesting": boolean, "category": one of [{_CATEGORIES}],
"confidence": number 0..1, "reason": short string}}"""

VERDICT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "is_interesting": {"type": "boolean"},
        "category": {
            "type": "string",
            "enum": [member.value for member in ClassificationCategory],
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["is_interesting", "category", "confidence", "reason"],
}


def build_user_prompt(request: ClassifyRequest) -> str:
    lines = [
        f"Frequency: {request.frequency_label} ({request.frequency_category.value})",
        f"Clip duration: {request.duration_s:.1f} seconds",
    ]
    if request.prefilter_flags:
        lines.append(f"Keyword prefilter flags: {', '.join(request.prefilter_flags)}")
    if request.asr_avg_logprob is not None and request.asr_avg_logprob < -0.8:
        lines.append(
            "Transcription quality: LOW (the recogniser reported weak confidence; "
            "treat the words sceptically)"
        )
    lines.append(f"Transcript:\n{request.transcript}")
    return "\n".join(lines)


# -- daily narrative ----------------------------------------------------------------

NARRATIVE_SYSTEM_PROMPT = """\
You write a short, warm daily note for the owner of an aviation radio station \
near London Stansted, who likes to know what the day sounded like on the air. \
You are given the day's totals and its most interesting moments, taken from \
automatic transcripts of noisy AM radio — so the wording is approximate, and you \
must never invent detail that is not in what you are given.

Write three or four plain sentences a non-expert would enjoy: roughly how busy \
the day was, what (if anything) stood out, and the shape of it — a quiet \
afternoon, a busy morning rush, a lone go-around. Warm and readable, never \
breathless; a go-around is usually routine caution, not a drama. No lists, no \
headings, no jargon you have not been handed, and no preamble — reply with the \
paragraph only."""


def build_narrative_prompt(
    *,
    day_label: str,
    total_count: int,
    interesting_count: int,
    moments: list[str],
) -> str:
    """Assemble the per-day user prompt for the daily narrative.

    ``moments`` is a list of already-formatted one-line descriptions of the
    day's interesting clips (time, frequency, category, reason, snippet).
    """
    lines = [
        f"Day: {day_label}",
        f"Transmissions recorded: {total_count}",
        f"Flagged interesting: {interesting_count}",
    ]
    if moments:
        lines.append("Notable moments:")
        lines.extend(f"- {moment}" for moment in moments)
    else:
        lines.append("Nothing was flagged interesting today.")
    return "\n".join(lines)


# -- ask ------------------------------------------------------------------------------

ASK_SYSTEM_PROMPT = """\
You answer a listener's question about what an aviation radio station near \
London Stansted has heard, using only the numbered clips you are given as \
evidence. The clips are automatic transcripts of noisy AM radio, so the \
wording is approximate — never invent detail that is not in what you are \
given, and never answer from general aviation knowledge alone. When the \
clips do not answer the question, say so plainly rather than guessing.

Write two or three plain sentences, no lists, no headings, no preamble —
reply with the answer only."""


def build_ask_prompt(*, question: str, clips: list[str]) -> str:
    """Assemble the user prompt for a question: the retrieved clips, then the question.

    ``clips`` is a list of already-formatted one-line clip descriptions (time,
    frequency, transcript snippet), best match first, or empty when nothing
    relevant was found.
    """
    lines: list[str] = []
    if clips:
        lines.append("Relevant clips, best match first:")
        lines.extend(f"{i}. {clip}" for i, clip in enumerate(clips, start=1))
    else:
        lines.append("No recorded clips matched this question.")
    lines.append(f"\nQuestion: {question}")
    return "\n".join(lines)
