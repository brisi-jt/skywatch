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
