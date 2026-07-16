# Extensions

Ideas deliberately left out of the first version, with enough design notes
that each can be picked up later without re-deriving the groundwork. Ordered
roughly by bang-for-buck for this station.

## Second dongle: local ADS-B + OpenSky feeding

The single biggest upgrade. A second RTL-SDR dongle dedicated to 1090 MHz
(ADS-B) makes aircraft matching local, instant, and free — and feeding the
received data to OpenSky improves the station's API standing.

**Receive side.** Run `dump1090` (or `readsb`) as a fourth launchd service
against the second dongle (`device_index: 1`, or better, set distinct
serials with `rtl_eeprom` and select by serial). It serves decoded positions
as JSON on `http://localhost:8080/data/aircraft.json` refreshed every
second. Implement a `LocalAdsbSource` conforming to the existing
`FlightDataSource` seam in `src/skywatch/providers/flightdata/` and select
it with `enrichment.provider: local_adsb`. Enrichment then queries localhost
instead of OpenSky: no credits, no OAuth, no 1-hour historical wall, and
candidates can be captured at the exact clip timestamp. Keep the OpenSky
client as fallback for periods the local receiver is down.

**Feed side.** The same decoder output can feed OpenSky (their feeder client
wraps readsb). Two payoffs: feeders receive a larger daily API credit
allowance than standard accounts, and feeders may query the state vectors
seen by their own sensor via the `/states/own` endpoint at **zero credit
cost**. Even before `LocalAdsbSource` exists, pointing the current OpenSky
enricher at `/states/own` for a feeding station removes the credit budget
from the picture for all nearby traffic — which is exactly the traffic this
station cares about.

**The deferred `GET /aircraft/live` route.** Intentionally not present in
v1 (no stub endpoints). When a local decoder exists, add:

- `GET /aircraft/live` → `200 OK`
  ```json
  {
    "aircraft": [
      {
        "icao24": "4009f9",
        "callsign": "BAW2761",
        "airline_name": "British Airways",
        "lat": 51.7,
        "lon": 0.1,
        "alt_ft": 3200,
        "gs_kt": 180,
        "track_deg": 274,
        "vertical_rate_fpm": -800,
        "distance_km": 3.1,
        "seen_s": 0.4
      }
    ],
    "source": "local_adsb",
    "queried_at": "2027-01-01T12:00:00Z",
    "_links": {"self": {"href": "/aircraft/live"}}
  }
  ```
- Sorted by `distance_km` ascending; `aircraft` empty (not an error) when
  nothing is in range; `503` problem detail with code `adsb_unavailable`
  when the decoder itself is unreachable.
- Dashboard consumer: a live map view (the reason this route exists at
  all). Push updates belong on the existing `WS /stream` as a new
  `aircraft.live` envelope type, throttled to ~1 Hz.

## Scan mode tradeoffs

Scan mode (`capture.mode: scan`) is already implemented end-to-end: the
receiver hops across an arbitrary list of frequencies instead of watching
one ~2 MHz window. Use it when the frequencies you want simply cannot share
a window (e.g. Stansted Tower + a distant airfield). The cost is inherent,
not a bug: while parked on one frequency the receiver is deaf to all the
others, so simultaneous transmissions are lost, and clip starts can be
clipped mid-word. Multichannel records everything in its window
concurrently and should stay the default; scan is for coverage breadth over
completeness. A second dongle running a second rtl_airband instance is the
real answer to "both, please".

## ACARS / VDL2

Aircraft also send short digital telex-style messages (ACARS on ~131.725
MHz AM, VDL Mode 2 on 136.975 MHz): out-of-gate/off-ground timestamps,
weather requests, company messages. `acarsdec` and `dumpvdl2` decode these
with the same RTL-SDR hardware and emit JSON. A natural fit as another
capture source feeding a new `acars_messages` table keyed to the same
frequency plan — text arrives pre-decoded, so the whole ASR/classification
pipeline is bypassed. Pairs well with the second dongle since the ACARS
frequencies sit outside the airband voice window.

## NOAA weather satellites

The same dongle can receive NOAA APT weather satellite imagery on ~137 MHz
with a V-dipole antenna. It's a different hobby wearing the same hardware:
passes must be predicted (satellites are only overhead ~15 minutes at a
time), the dongle must be retuned for the pass, and the output is images,
not audio. If pursued, run it as a scheduled borrower of the capture dongle
(pause rtl_airband, record the pass with `satdump`, resume) rather than
integrating it into the pipeline.

## Alerting and push notifications

The worker already knows the moment a clip is classified interesting; today
that knowledge only reaches the dashboard. An `alerts` module subscribed at
the same point could push via [ntfy](https://ntfy.sh) (simplest:
`httpx.post("https://ntfy.sh/<topic>", ...)` — free, no account, apps on
everything), Pushover, or email. Design constraints learned from the
classifier: alert only on high-confidence categories (emergency, guard
activity) and rate-limit to avoid a mistranscribed "mayday" waking the
house at 3 a.m. A per-category threshold in `config.yaml` plus a daily cap
would cover it.

## LLM batching (quota escape hatch)

Classification currently spends one API call per clip, bounded by
`llm.daily_call_cap`. If traffic outgrows the free tier, batch instead:
accumulate transcripts for N minutes (or until K clips), send them as one
numbered list, and ask for a JSON array of verdicts — 10–20 clips per call
is realistic within Gemini's context limits, cutting call volume by an
order of magnitude at the cost of latency. The seam is
`pipeline/stages/classify.py`: the provider interface takes one transcript
today, so add a `classify_many` alongside it with per-item fallback to
single calls when a batch response fails to parse. Deferred-backfill
already tolerates late verdicts, so batching composes cleanly with the
existing budget machinery.

## ATC-finetuned speech recognition

Whisper `base.en` was trained on ordinary speech; ATC radio is clipped,
noisy, jargon-dense, and read at speed. A Whisper `medium.en` fine-tuned on
ATC audio exists with a ready-made faster-whisper conversion
(`jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper`, roughly 15%
word error rate on ATC test sets vs ~80%+ for stock models). It's a
config-only swap (`asr.model`), but a medium model is beyond the 2015
production laptop's CPU and RAM. Two viable shapes: run it on the M4
development box for re-transcribing interesting clips after the fact
(quality where it matters, batch-friendly), or make it the default if the
station ever migrates to Apple Silicon hardware. The per-transcript
`engine`/`model` provenance columns exist precisely so mixed-model history
stays honest.

## Speaker separation

Transcripts currently interleave pilot and controller as one stream of
text. Ideas in ascending effort: cheap heuristic — controller transmissions
are ground-level and weaker, so received signal level per clip correlates
with who's talking (rtl_airband doesn't expose per-clip signal level in
filenames today, so this needs a metadata hook); mid — speaker-turn
segmentation on pauses plus alternation priors; heavy — a diarization model
(pyannote) over each clip, far beyond the production box but plausible on
the M4 for interesting clips only. Presentation matters more than
perfection: even "Voice A / Voice B" labels would make readbacks much
easier to follow.

## Antenna and filter upgrades

In rough order of effect per pound:

1. **Get the antenna outside or loft-mounted.** Every wall is worth more
   than any gadget below.
2. **FM band-stop filter** (~£10–15) between antenna and dongle if strong
   broadcast FM is overloading the front end — symptoms and diagnosis are
   in the runbook.
3. **Airband band-pass filter** for deeper interference problems
   (paging/DAB/mobile masts), at the cost of hearing anything outside
   118–137 MHz — which forecloses the ADS-B/NOAA ideas above on this
   dongle.
4. **A tuned airband antenna or homemade quarter-wave ground plane** (five
   wires and a connector) mounted high; a dipole cut for ~127 MHz
   noticeably beats the telescopic whip.
5. **LNA (low-noise amplifier)** at the antenna only after the above — more
   gain amplifies interference too, and the dongle's own gain is rarely the
   limiting factor here.

## Progressive Web App

The dashboard is a static Next.js export behind FastAPI, so PWA is mostly
manifest work: add a web manifest + icons + a service worker (Serwist is
the maintained Next.js fit), and "install" it on a phone home screen over
Tailscale. Offline caching adds little (the data is live by nature), so
scope it to installability and app feel. Pairs naturally with push
notifications from the alerting extension above.

## Analytics

The database is already a tidy time series: every transmission with
frequency, timestamp, duration, category, and aircraft candidates. Cheap
wins queryable with SQL alone: busiest hours per frequency,
transmissions-per-day trend, go-around frequency by month, top airlines
heard, interesting-clip rate over time. A `GET /stats` route feeding a
dashboard charts view is the natural shape — compute on demand; at this
write rate SQLite aggregation is instant. Purely additive; needs no schema
changes until someone wants long-horizon rollups.

## Appendix: deploying on a Raspberry Pi

The codebase avoids macOS assumptions everywhere except service management
and packaging, so a Pi port is a bootstrap problem, not a code problem. The
deltas:

- **Packages**: `apt install rtl-sdr librtlsdr-dev libconfig++-dev cmake
  build-essential libmp3lame-dev libshout3-dev pkg-config sqlite3` replaces
  the Homebrew list. `uv` installs via its official script. ffmpeg via apt
  if fixtures are ever regenerated on the Pi.
- **rtl_airband build**: identical (`cmake -DPLATFORM=generic`); on a Pi 4+
  you can use the NEON platform flag instead for cheaper CPU.
- **udev, not permissions-by-default**: install the rtl-sdr udev rules and
  add the service user to `plugdev`, or the dongle opens for root only.
- **systemd, not launchd**: three unit files replace the plists —
  `Restart=always`, `WantedBy=multi-user.target`, `WorkingDirectory=` the
  repo, `ExecStart=` the venv binaries, plus
  `ConditionPathExists=<data>/rtl_airband.conf` on the rtl_airband unit to
  mirror the launchd PathState gate. `journalctl -u` replaces
  `data/logs/*.log` unless `StandardOutput=append:` is set to keep
  file-based logs.
- **Keep-awake**: unnecessary — no lid, no sleep. Drop the `pmset` step.
- **ASR reality check**: a Pi 4 transcribes `base.en` several times slower
  than real time. The architecture already tolerates that (the queue drains
  overnight), but expect deeper backlogs than the reference laptop; a Pi 5
  or an external accelerator changes the picture.
- **Thermals**: a Pi decoding audio and running Whisper wants a heatsink or
  fan; sustained throttling stretches the backlog further.
