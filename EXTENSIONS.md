# Extensions

Ideas deliberately left out of the first version, with enough design notes
that each can be picked up later without re-deriving the groundwork. Ordered
roughly by bang-for-buck for this station.

## Second dongle: local ADS-B, sharper matches, and OpenSky feeding

Live aircraft positions are already on the dashboard — the Sky view pulls
them from keyless community aggregators (airplanes.live, adsb.lol, adsb.fi,
falling back to OpenSky), so a second dongle is no longer the prerequisite
for a live map it once looked like. What a second RTL-SDR dongle dedicated
to 1090 MHz (ADS-B) still buys is a *better per-clip aircraft match*: local,
instant, and free, plus a better standing with OpenSky if the same feed is
shared back.

**Receive side.** Run `dump1090` (or `readsb`) as a fourth launchd service
against the second dongle (`device_index: 1`, or better, set distinct
serials with `rtl_eeprom` and select by serial). It serves decoded positions
as JSON on `http://localhost:8080/data/aircraft.json` refreshed every
second. Implement a `LocalAdsbSource` conforming to the existing
`FlightDataSource` seam in `src/skywatch/providers/flightdata/` and select
it with `enrichment.provider: local_adsb`. Enrichment then queries localhost
instead of OpenSky: no credits, no OAuth, no 1-hour historical wall, and
candidates can be captured at the exact clip timestamp — sharper matches
than OpenSky's snapshot cadence allows today. Keep the OpenSky client as
fallback for periods the local receiver is down.

**Feed side.** The same decoder output can feed OpenSky (their feeder client
wraps readsb). Two payoffs: feeders receive a larger daily API credit
allowance than standard accounts, and feeders may query the state vectors
seen by their own sensor via the `/states/own` endpoint at **zero credit
cost**. Even before `LocalAdsbSource` exists, pointing the current OpenSky
enricher at `/states/own` for a feeding station removes the credit budget
from the picture for all nearby traffic — which is exactly the traffic this
station cares about.

**Joining the Sky view.** The live map's source chain
(`providers/flightdata/sky.py`) already normalizes four different aggregator
shapes into one `SkyAircraft` record; a local receiver would simply be a
fifth source — and, being on the same machine with no round trip, the
natural first one to try rather than the last. Nothing about the map, the
aircraft glyphs, or the clip-fusion panel would need to change: they only
ever see the normalized shape, never the source behind it.

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

## Live audio monitor in Deep Tune

The tuning bench's Deep Tune scope already holds the receiver exclusively
and streams spectrum frames; the same pyrtlsdr session could demodulate one
selected channel (AM at these frequencies is a vectorised numpy one-liner:
magnitude, DC-strip, decimate) and stream it to the browser for live
listening while tuning — "click a channel marker, hear it now". Transport
is the open question worth solving first: the existing `WS /stream` is a
JSON event bus, so audio wants either a second binary WebSocket or
MediaSource-friendly chunks over HTTP. Everything else (session lifecycle,
timeouts, capture restart) is already built.

## Rejected approaches

Ideas that were seriously considered and turned down, recorded here so the
conclusion isn't re-derived from scratch.

- **Permanent IQ fan-out** (`rtl_tcp` → `rtlmux` → SoapyRTLTCP plugin, with
  rtl_airband and a metering client both consuming the mux): every hop is
  real, but the chain costs 8-bit samples, a shared gain setting, three
  always-on processes, and a low-maturity Soapy plugin — a Rube Goldberg
  machine guarding a ~5-second capture restart. Rejected on
  complexity-to-benefit.
- **ka9q-radio (`radiod`)**, the elegant multichannel answer: its author
  ships and supports it as Linux-only, and this station's production host
  is a Mac. Eliminated on platform.
- **CARTO dark basemap tiles** for the Sky view's dark theme: the obvious
  choice on looks alone (a pre-styled dark map needs no filter trickery),
  but CARTO's basemap terms are not clean for this station's receive-only,
  personal-use posture the way OSM's tile usage policy is. Dark mode
  instead applies a CSS filter (invert, hue-rotate) to the same OSM raster
  tiles light mode uses, so attribution and licensing stay identical
  across both themes.

Deep Tune's stop-meter-restart model is the deliberate outcome of the first
two rejections above, not a stopgap: one dongle has one USB claimant, and
the honest costs (a confirm, an amber banner, an auto-timeout) beat a
permanently degraded capture chain.

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
station ever migrates to Apple Silicon hardware. An A/B harness now exists
(`make eval-asr`, dev-box only, models gitignored) to run the same eval
manifest through both models side by side; production hasn't switched
because the case for the medium model's CPU and RAM cost hasn't been made
conclusively either way on the 2015 laptop — re-run the harness with a
larger manifest before deciding. The per-transcript `engine`/`model`
provenance columns exist precisely so mixed-model history stays honest.

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
scope it to installability and app feel. Pairs naturally with the ntfy push
the station already sends for interesting clips — a home-screen icon and a
phone notification cover most of what a native app would add.

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
