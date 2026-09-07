# Installation

This is the full path from an empty machine to a running skywatch station.
It covers getting the code, installing dependencies, configuring a station,
running the pipeline against fixture audio with no radio hardware at all,
and then going live with a dongle.

This document is about **getting the software installed and running**. Once
a station is up, day-to-day operation — starting and stopping it, placing
the antenna, tuning, reading the dashboard, backups, and what to try when
something looks wrong — is covered by
[`content/RUNBOOK.md`](../content/RUNBOOK.md), which this guide points to
rather than repeats. For how the pieces fit together, see
[Architecture](architecture.md); for every external dataset and service,
its licensing, and its fallback behaviour, see [Data sources](data-sources.md).

## 1. What you need

### Hardware — optional

Hardware is only needed to receive real radio traffic. Skip this section
entirely to try skywatch first: the shipped default runs the whole pipeline
against fixture audio with nothing plugged in (see
[First run, no radio required](#5-first-run-no-radio-required-replay-mode)
below).

To go live, you need:

- An RTL-SDR USB dongle.
- A VHF airband antenna — a telescopic whip extended to roughly 55–60 cm is
  enough to get started; see the "Antenna" section of the runbook for
  placement.

### Software

- **[uv](https://docs.astral.sh/uv/)** — manages the Python 3.12
  environment. Never install Python packages with `pip` directly in this
  repository.
- **[bun](https://bun.sh)** — builds the web dashboard. Never use `npm`.
- macOS is the only platform `scripts/bootstrap.sh` and the launchd service
  files target. The reference production machine is a 2015 dual-core Intel
  Mac on macOS 12; development happens on Apple Silicon, and nothing in the
  codebase should hardcode an architecture or a Homebrew prefix. For a
  non-macOS deployment (a Raspberry Pi, for instance), see the appendix in
  [`EXTENSIONS.md`](../EXTENSIONS.md).
- **[Homebrew](https://brew.sh)**, on macOS — `scripts/bootstrap.sh` uses it
  to install everything else in this section, including `uv` itself.
- **rtl_airband** and the RTL-SDR drivers — required for live capture only.
  `scripts/bootstrap.sh` builds `rtl_airband` from source and installs the
  `rtl-sdr` Homebrew package that provides the drivers and `rtl_test`.

## 2. Prerequisites

If you already have Homebrew, `uv`, and `bun` on this machine, skip ahead to
[Get the code](#3-get-the-code-and-install-dependencies) — everything below
is what `scripts/bootstrap.sh` needs before it can run.

1. Install Homebrew, if it isn't already present:

   ```sh
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. Install bun (`scripts/bootstrap.sh` does not do this — it only sets up
   the Python side):

   ```sh
   curl -fsSL https://bun.sh/install | bash
   ```

`uv`, `rtl_airband`, and the RTL-SDR drivers are all installed for you by
`scripts/bootstrap.sh` in the next step — there's nothing to do for them by
hand.

## 3. Get the code and install dependencies

```sh
git clone https://github.com/brisi-jt/skywatch.git
cd skywatch
```

The fastest path to a fully working checkout — Python environment, radio
tooling, database, and the three background services — is
`scripts/bootstrap.sh`. It is safe to run more than once: every step checks
the current state of the machine first and only does what's missing.

```sh
scripts/bootstrap.sh --dry-run   # preview every action first, changes nothing
scripts/bootstrap.sh
```

`scripts/bootstrap.sh` will:

- install `coreutils`, `libconfig`, `rtl-sdr`, `cmake`, `pkg-config`, and
  `uv` via Homebrew;
- clone and build `rtl_airband` into `bin/rtl_airband`;
- run `uv sync --extra asr` (with `MACOSX_DEPLOYMENT_TARGET=12.0` set), and
  fall back to a plain `uv sync` with a warning if the ASR extra's wheel
  isn't available on this machine — see
  [Troubleshooting](#9-troubleshooting);
- create the station's config and secrets files from their example
  templates, if they don't exist yet (see [Configure](#4-configure) below);
- create `data/logs` and `data/recordings`, run the database migrations,
  and seed the default frequency plan;
- install and load the three launchd services from `deploy/launchd/`; and
- disable system sleep on AC power, and check the system clock against
  `time.apple.com`.

Pass `--with-whisper-cpp` to also build the whisper.cpp fallback
transcriber and download its `base.en` model:

```sh
scripts/bootstrap.sh --with-whisper-cpp
```

If you'd rather just get a working Python environment without the radio
tooling, database, or services — for example, to read code or run the test
suite — that's the same command the project's CI uses:

```sh
uv sync --all-extras
make test
```

`--all-extras` additionally pulls in `pytest` and the other `dev`-extra
tooling that `scripts/bootstrap.sh`'s `--extra asr` sync does not, since
that path is meant for running the station rather than developing it.

Finally, build the web dashboard:

```sh
cd web
bun install --frozen-lockfile
bun run build
cd ..
```

This produces `web/out`, a static export. The API serves it automatically
from `/` if it's present (`skywatch/api/app.py::create_app`); if you skip
this step, the API still runs and its endpoints and interactive docs at
`/docs` still work, but `/` has no dashboard to show.

## 4. Configure

### Copy the config files

`scripts/bootstrap.sh` does this for you if the files don't already exist.
By hand, from the repository root:

```sh
cp config/config.yaml.example config/config.yaml
cp config/.env.example .env
```

`config/config.yaml` holds station configuration; the repository-root
`.env` holds secrets and per-machine overrides. Any setting in
`config.yaml` can also be overridden by an environment variable of the
same name, uppercased, with `__` separating nested fields (e.g.
`SERVER__PORT`) — see `src/skywatch/settings.py` for the full precedence
order.

### Set the station's location — required

`config/config.yaml.example` ships with `receiver.lat` and `receiver.lon`
set to `null` on purpose. Until they're filled in, two features stay
switched off: per-clip flight-data enrichment (matching a clip against a
probable aircraft) and the live Sky map. This is the single most common
thing a new station gets stuck on, so do it before your first run.

Get your coordinates from a UK postcode:

```sh
uv run python scripts/geocode.py "<your postcode>"
```

This prints a `receiver:` block with `lat` and `lon` filled in — paste it
over the `receiver:` section of `config/config.yaml`. It's a one-time
lookup; the running pipeline never calls out for geocoding itself.

### API keys — and what stays off without them

Every external dependency is optional in the sense that skipping it
disables one feature rather than the whole station. Set only what you want
working; the rest degrades quietly rather than failing. The `.env` file
holds these as environment variables (see `src/skywatch/settings.py` for
the exact field list); for where to get each one, its rate limits, and its
precise fallback behaviour, see [Data sources](data-sources.md).

| Env var (in `.env`) | Powers | Without it |
|---|---|---|
| `GEMINI_API_KEY` | Cloud LLM classification (default provider) | That provider is skipped in the classifier chain; falls through to the next configured provider, or to prefilter-only classification if none is left |
| `GROQ_API_KEY` | Cloud LLM classification (first fallback) | Same as above — skipped, chain falls through |
| `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` | Per-clip flight-data enrichment; last-resort fallback leg of the Sky map | Enrichment stays disabled (also needs `receiver.lat`/`lon` set); the Sky map still works from its three keyless community sources, just without the OpenSky fallback leg |
| `SMTP_HOST` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` | The weekly email digest | Nothing changes — the digest is off by default (`digest.email.enabled: false` in `config.yaml`) until both these and that flag are set |

Setting `llm.provider: none` in `config/config.yaml` (instead of the
default `gemini`) skips cloud classification entirely: every clip is
judged by the deterministic prefilters alone (distress phrasing, the
emergency guard frequency, unusually long transmissions, notable
airframes), with no network call and no data leaving the station.

## 5. First run, no radio required (replay mode)

`capture.source: replay` is the shipped default in
`config/config.yaml.example` — the whole pipeline runs with no dongle
attached, feeding fixture audio (`fixtures/*.mp3`) through the identical
path a real recording takes. This is the fastest way to see the station
work before deciding whether to buy hardware.

With the config files in place (see [Configure](#4-configure) above) and
migrations applied — `scripts/bootstrap.sh` does both, or run them by hand:

```sh
make migrate
make seed
```

start the two long-running processes, each in its own terminal:

```sh
make run-api      # FastAPI backend + dashboard, http://localhost:8000
make run-worker   # transcription, classification, enrichment
```

The API process serves the dashboard (if you built it in step 3) and the
API itself; a quick way to confirm it's up without a browser:

```sh
curl http://localhost:8000/status
```

The worker process is what actually drives replay capture: on start, it
drops the four fixture clips (`fixtures/blip.mp3`,
`fixtures/guard_121500.mp3`, `fixtures/mayday.mp3`,
`fixtures/routine_clearance.mp3`) into `data/recordings`, two seconds
apart, then stops dropping new ones — restart `make run-worker` to see them
again. Each clip is picked up, transcribed, and classified exactly as a
real recording would be, and should appear in the dashboard's Today view
within moments, complete with a transcript. Aircraft matches and the Sky
map will stay empty until `receiver.lat`/`lon` are set (see
[Configure](#4-configure)), same as they would on a live station.

## 6. Going live with a dongle

Switching from fixture audio to a real receiver is a one-line change in
`config/config.yaml`:

```yaml
capture:
  source: live
```

`capture.supervisor: subprocess` runs `rtl_airband` as a direct child
process of the worker, which is the right choice for development and for
running things by hand. The deployed topology instead uses
`capture.supervisor: launchctl`, so the worker starts and stops
`rtl_airband` through the `com.skywatch.rtl-airband` launchd service — see
[Running it permanently](#8-running-it-permanently).

Before trusting the pipeline, confirm the dongle itself is seen:

```sh
rtl_test -t
```

The frequency plan lives in the database (seeded from
`content/default_frequencies.yaml`) and is switched on and off from the
dashboard's Station view, not edited in `config.yaml` — the receiver can
only watch about 2 MHz of the dial at once, and the dashboard enforces
which combinations of frequencies fit together. `capture.gain`,
`capture.squelch_snr_threshold`, and `capture.ppm` in `config.yaml` only
seed those values the first time the station starts; after that, the
dashboard's tuning bench owns them.

Antenna placement, verifying the frequency plan against official sources,
and the gain/squelch tuning loop are all covered by the "First-time setup
(remote admin)" section of [`content/RUNBOOK.md`](../content/RUNBOOK.md) —
follow it end to end the first time you go live.

## 7. Optional data downloads

Two datasets are fetched on demand rather than committed to the
repository, because of their size or how often they need refreshing.
Neither is required to run a station; both simply leave a gap filled in
once you run them.

```sh
scripts/fetch_aircraft_db.sh          # -> data/aircraft_db.csv (~70 MB)
scripts/update_plane_alert_db.sh      # -> content/plane_alert_db.csv
```

- **`scripts/fetch_aircraft_db.sh`** downloads the OpenSky aircraft
  database (ICAO hex → registration, type, operator). Without it, matched
  candidates still show up, just with those identity fields left blank.
- **`scripts/update_plane_alert_db.sh`** downloads the community
  plane-alert-db list used to badge notable airframes (military,
  government, historic, and so on). The repository ships only the CSV
  header, so without running this, no clip ever gets a badge.

Both scripts are safe to re-run whenever you want a fresher snapshot, and
both leave the existing file untouched if the download comes back empty.

## 8. Running it permanently

`scripts/bootstrap.sh` installs three launchd services into
`~/Library/LaunchAgents`, each restarted automatically on crash:

- `com.skywatch.api` — the FastAPI backend and dashboard.
- `com.skywatch.worker` — transcription, classification, enrichment.
- `com.skywatch.rtl-airband` — the radio capture process. It only starts
  once a rendered `data/rtl_airband.conf` exists, which the worker writes
  the first time `capture.source: live` is running; on a station still in
  replay mode it stays quietly stopped rather than crash-looping against a
  config file that doesn't exist yet, so it's harmless to leave installed
  before going live.

`scripts/bootstrap.sh` also disables system sleep while the laptop is on
AC power (the station is meant to run continuously with the lid closed on
mains power) and checks the system clock against `time.apple.com`, since
recordings are matched to aircraft by timestamp and a badly wrong clock
quietly ruins that matching.

Re-running `scripts/bootstrap.sh` after a `git pull` re-renders and
reloads any service whose plist has changed, and leaves the others alone.
For restarting, stopping, or starting the services individually day to
day, see "Starting and stopping the station" in
[`content/RUNBOOK.md`](../content/RUNBOOK.md).

The API is **unauthenticated by design** and meant to be reachable only
from a private network — a home LAN, or a private overlay network such as
Tailscale for remote access. Nothing in the request path enforces this; do
not expose it to the public internet.

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `scripts/bootstrap.sh` exits immediately with "This bootstrap targets macOS" | Running on Linux or another non-Darwin platform | See the Raspberry Pi appendix in `EXTENSIONS.md` for the non-macOS deltas |
| `scripts/bootstrap.sh` exits with "Homebrew is required but not installed" | Homebrew isn't on this machine yet | Install it from <https://brew.sh>, then re-run |
| `uv sync --extra asr` fails during bootstrap, with a warning about the ASR extra | The `faster-whisper`/`ctranslate2` wheel doesn't support this machine | Bootstrap already falls back to a plain `uv sync` automatically; switch `asr.engine: whisper_cpp` in `config/config.yaml` and re-run `scripts/bootstrap.sh --with-whisper-cpp` |
| The dashboard at `http://localhost:8000/` is blank or 404s, but `curl http://localhost:8000/status` works | `web/out` was never built | `cd web && bun install --frozen-lockfile && bun run build` |
| Clips show up with no aircraft match, and the Sky map is always empty | `receiver.lat`/`receiver.lon` are still `null` | Run `uv run python scripts/geocode.py "<postcode>"` and paste the result into `config/config.yaml` |
| Every clip lands classified only by prefilters, never by the LLM | No LLM API key set in `.env`, or `llm.provider: none` | Add a key to `.env` (see [Data sources](data-sources.md) for where to get one), or leave it as-is — prefilter-only is a supported, zero-cloud configuration |
| `scripts/bootstrap.sh` warns the clock is several seconds off | The Mac isn't syncing its clock automatically | Enable "Set date and time automatically" in System Settings before trusting aircraft matches |
| Building `rtl_airband` fails during bootstrap | A build dependency (`cmake`, `libconfig`, `pkg-config`) didn't install cleanly | Re-run `scripts/bootstrap.sh`; it checks and reinstalls each Homebrew package it needs |

For anything that comes up once a station is already running day to day —
a missing dongle, no new clips, junk clips, low disk, an unreachable
dashboard — see "When something looks wrong" in
[`content/RUNBOOK.md`](../content/RUNBOOK.md).
