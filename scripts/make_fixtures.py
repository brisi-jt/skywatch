#!/usr/bin/env python3
"""Generate the committed tier-1 fixture clips.

USAGE:
    python scripts/make_fixtures.py [--output-dir fixtures] [--voice Daniel]

Each clip is macOS ``say`` speech pushed through a radio-ish band-pass,
mixed with pink noise, and encoded exactly the way rtl_airband writes
clips: 8 kHz mono MP3. Needs macOS (for ``say``) and ffmpeg on PATH.

The clips are committed, so regeneration is only needed when the scripted
transmissions change. Content is invented for testing — the callsigns and
phraseology are plausible, not real traffic.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CLIPS: dict[str, dict[str, str | float | None]] = {
    "mayday": {
        "text": (
            "Mayday, mayday, mayday, Speedbird four seven two, engine failure, "
            "descending through flight level one two zero, request immediate "
            "return to Stansted."
        ),
        "trim_s": None,
    },
    "routine_clearance": {
        "text": (
            "Ryanair eight one five bravo, cleared to land runway two two, "
            "wind two one zero degrees at eight knots."
        ),
        "trim_s": None,
    },
    "guard_121500": {
        "text": (
            "Aircraft calling on guard, this is London Centre, you are "
            "transmitting on one two one decimal five, check your frequency."
        ),
        "trim_s": None,
    },
    "blip": {
        # A sub-1.5-second squelch blip: the classifier floor skips these.
        "text": "Roger.",
        "trim_s": 1.0,
    },
}


def synthesize(text: str, voice: str, aiff_path: Path) -> None:
    subprocess.run(["say", "-v", voice, "-o", str(aiff_path), text], check=True)


def radioize(aiff_path: Path, mp3_path: Path, trim_s: float | None) -> None:
    """Band-limit, add pink noise, and encode as rtl_airband-shaped MP3."""
    voice_chain = "highpass=f=300,lowpass=f=3400,volume=1.4"
    if trim_s is not None:
        # Cut or noise-pad to an exact length (used for the sub-1.5 s blip).
        voice_chain += f",atrim=end={trim_s},apad=whole_dur={trim_s}"
    filter_complex = (
        f"[0:a]{voice_chain}[voice];"
        "[voice][1:a]amix=inputs=2:duration=first:dropout_transition=0[mixed];"
        "[mixed]aresample=8000[out]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(aiff_path),
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=colour=pink:amplitude=0.04:sample_rate=8000:duration=60",
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "16k",
            str(mp3_path),
        ],
        check=True,
    )


def pick_voice(preferred: str) -> str:
    listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True)
    voices = {line.split()[0] for line in listing.stdout.splitlines() if line.strip()}
    if preferred in voices:
        return preferred
    fallback = sorted(voices)[0] if voices else preferred
    print(f"voice {preferred!r} not installed; using {fallback!r}", file=sys.stderr)
    return fallback


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=Path("fixtures"))
    parser.add_argument("--voice", default="Daniel", help="macOS `say` voice (British default)")
    args = parser.parse_args()

    for tool in ("say", "ffmpeg"):
        if shutil.which(tool) is None:
            print(f"error: {tool} not found on PATH; fixture generation needs it", file=sys.stderr)
            return 1

    voice = pick_voice(args.voice)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, spec in CLIPS.items():
            aiff = Path(tmp) / f"{name}.aiff"
            mp3 = args.output_dir / f"{name}.mp3"
            synthesize(str(spec["text"]), voice, aiff)
            trim = spec["trim_s"]
            radioize(aiff, mp3, float(trim) if trim is not None else None)
            print(f"wrote {mp3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
