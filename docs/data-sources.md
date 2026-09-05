# Data Sources

skywatch depends on a number of external datasets and services, each doing
one specific job — resolving a callsign to an airline, badging a notable
airframe, looking up who was probably overhead, showing where every
aircraft in range is right now, drawing a basemap, and judging whether a
transcript is worth a listen. Each is optional in the sense that its
absence degrades one feature rather than the whole station: the pipeline
is designed so that a missing dataset or an unreachable service disables
what it was doing and nothing else.

This document is also the project's attribution reference. Where a
licensing fact is stated below, it reflects what is verified in this
repository's own source and scripts.

## Flight data

### OpenSky Network — state vectors (per-clip enrichment and OpenSky fallback)

| | |
|---|---|
| **Provides** | Live and short-history ADS-B state vectors (position, altitude, ground speed, callsign) for a bounding box, via `/api/states/all`. |
| **Used for** | Per-clip enrichment (matching a clip's capture time and location against probable aircraft) and as the last-resort fallback leg of the Sky view's live map. |
| **Authentication** | OAuth2 client-credentials (`opensky_client_id` / `opensky_client_secret` in `.env`). Access tokens are short-lived (roughly 30 minutes) and refreshed automatically just before expiry (`providers/flightdata/opensky.py`). |
| **Rate limits** | Each bounding-box query costs one credit against OpenSky's account-level daily allowance. skywatch layers its own, smaller self-imposed budgets on top of that account limit: `enrichment.daily_credit_cap` (default 3000) for per-clip enrichment, metered separately from `sky.opensky_daily_cap` (default 500) for the live-map fallback leg, so a quiet map can never starve per-clip enrichment of its share, or vice versa. Per-clip lookups are additionally cached in fixed time buckets (`enrichment.bucket_seconds`, default 30s) so multiple clips captured close together share one query. |
| **Licensing** | The states endpoint itself is a live query, not a redistributed dataset; OpenSky's own terms apply to the data returned, and its authors ask to be cited when their data is redistributed. |
| **Fallback when unavailable** | Enrichment: a lookup that fails or runs out of daily credit simply leaves a clip's aircraft-identity columns null; enrichment failures never block transcription or classification. Sky view: OpenSky is only ever consulted after the three community aggregators below have all failed or returned nothing; if it also fails, the live map returns an honest empty result rather than an error. |

### airplanes.live, adsb.lol, adsb.fi — live positions (Sky view primary sources)

| | |
|---|---|
| **Provides** | Live aircraft positions within a radius of a point, in a `dump1090`/`tar1090`-shaped JSON response. Three independently-run, keyless community aggregators, each normalized to the same internal shape (`providers/flightdata/sky.py`). |
| **Used for** | The Sky view's live "what's overhead right now" map. Tried in this order — airplanes.live, then adsb.lol, then adsb.fi — before the station falls back to OpenSky. |
| **Authentication** | None — all three are keyless, non-commercial-use community services. Every request carries an identifying `User-Agent` string naming the station, as each aggregator's usage policy asks for. |
| **Rate limits** | Not independently configured per source in this codebase; a shared 8-second server-side cache (`api/services/sky.py::CACHE_TTL_S`) collapses repeated requests from any number of open dashboard tabs into one upstream fetch per window, which is the mechanism keeping request volume low regardless of how many clients are polling. |
| **Licensing** | adsb.lol publishes its data under the Open Database License (ODbL) 1.0. airplanes.live's and adsb.fi's terms govern their own data; neither is redistributed by this repository — all three are live, uncached-beyond-8-seconds queries, not vendored datasets. |
| **Fallback when unavailable** | A failure on any one leg (timeout, HTTP error, an unparseable body) falls through to the next leg in the chain automatically; a failure on all three falls through to OpenSky. |

### OpenSky Network aircraft database — aircraft identity

| | |
|---|---|
| **Provides** | A mapping from a 24-bit ICAO hex address to registration, aircraft type, and operator. |
| **Used for** | Filling in a probable-aircraft candidate's identity columns once enrichment has matched a state vector. |
| **Authentication** | None — a plain CSV download. |
| **Rate limits** | Not applicable; fetched on demand, not polled. |
| **Licensing** | OpenSky requests citation when the data is redistributed; this repository does not name a specific license for the metadata file itself. |
| **Redistribution** | **Not redistributed.** The file is large (~70 MB) and is never committed; `scripts/fetch_aircraft_db.sh` downloads it at runtime from `https://opensky-network.org/datasets/metadata/aircraftDatabase.csv` into `data/aircraft_db.csv`, which is gitignored. |
| **Fallback when unavailable** | A missing file yields an empty lookup table (`AircraftDb.load`); enrichment simply leaves the registration/type/operator columns null for every match. Nothing else in the pipeline depends on it. |

### OpenFlights — airline directory

| | |
|---|---|
| **Provides** | A directory mapping an airline's three-letter ICAO radio operator code to its name, IATA code, and spoken radiotelephony callsign (e.g. `BAW` → British Airways, radio callsign "SPEEDBIRD"). |
| **Used for** | Resolving a heard callsign's airline for display, guessing the marketed flight number (`BAW472` + British Airways → `BA472`, presented as a clearly-labelled guess rather than fact, since the marketed number frequently differs from the radio callsign's numeric suffix), and generating spoken-form callsign hotwords for ASR boosting. |
| **Authentication** | None — a static CSV. |
| **Rate limits** | Not applicable. |
| **Licensing** | **Open Database License (ODbL) 1.0**; the data content itself is under the Database Contents License 1.0. |
| **Redistribution** | **Redistributed in this repository** at `content/airlines.dat`, committed as-is from OpenFlights' published `airlines.dat`. |
| **Fallback when unavailable** | Not applicable in normal operation — the file ships with the repository. A callsign that doesn't match a known ICAO prefix simply resolves to no airline. |

### plane-alert-db — notable-airframe badges

| | |
|---|---|
| **Provides** | A community-curated list of notable aircraft (military, government, historic airframes, and similar), keyed by ICAO 24-bit hex, each tagged with a category. |
| **Used for** | Badging a probable-aircraft candidate with its curated category, and as an input to the classification prefilter that flags a clip as interesting when a notable airframe is nearby. |
| **Authentication** | None — a plain CSV download. |
| **Rate limits** | Not applicable; fetched on demand, not polled. |
| **Licensing** | Published under the **Open Database License (ODbL) 1.0** by SDR-Enthusiasts, Ramon F. Kolb (kx1t), and contributors. |
| **Redistribution** | **Not redistributed.** This repository ships only the CSV **header row** at `content/plane_alert_db.csv`; the actual dataset is downloaded at runtime by `scripts/update_plane_alert_db.sh` from the upstream `sdr-enthusiasts/plane-alert-db` GitHub repository and overwrites that file locally; only the header row is committed, so a populated copy shows up as an uncommitted local modification. |
| **Fallback when unavailable** | A missing or header-only file yields an empty lookup (`PlaneAlertDb.load`); enrichment simply attaches no category badge to any candidate. |

## Map tiles

### OpenStreetMap — Sky view basemap

| | |
|---|---|
| **Provides** | Raster basemap tiles (`tile.openstreetmap.org`) underlying the Sky view's live map. |
| **Used for** | The map background in both dashboard themes. Dark mode does not use a separate dark tile set — it applies a CSS filter (invert, hue-rotate, and brightness/contrast/saturation adjustments) to the same light-theme raster tiles, specifically so that one tile source, one attribution, and one licence apply regardless of theme. |
| **Authentication** | None — OpenStreetMap's standard tile server is used directly, with attribution rendered on the map as required by OSM's copyright notice. |
| **Rate limits** | Governed by OpenStreetMap's tile usage policy for the standard tile server; the project does not run its own tile cache or CDN. |
| **Licensing** | Map data © OpenStreetMap contributors, under the Open Database License. |
| **Fallback when unavailable** | None implemented; a tile-fetch failure degrades to blank/missing map tiles in the browser, the same as any Leaflet deployment against a slow or unreachable tile host. |

A pre-styled dark basemap (CARTO's dark tiles) was considered and rejected
for this project specifically because CARTO's basemap terms weren't a
clean fit for skywatch's receive-only, personal-use posture, unlike OSM's
tile usage policy — hence the CSS-filter approach above rather than a
second tile provider.

## LLM classification providers

The classifier chain is configurable (`llm.provider` plus an ordered
`llm.fallback` list) and every provider in it is metered against an
app-level daily call cap (`llm.daily_call_cap`, default 900 calls/day,
tracked per provider in the `api_usage` table) independent of whatever
rate limits or quotas the provider itself imposes on the account.

### Google Gemini (default provider)

| | |
|---|---|
| **Provides** | Structured JSON classification verdicts via the Generative Language REST API. |
| **Authentication** | API key (`gemini_api_key` in `.env`), sent as a query parameter/header per Google's API. |
| **Rate limits** | Governed by whichever Gemini API tier the operator's key is provisioned on; skywatch's own `daily_call_cap` is an independent, smaller ceiling layered on top. |
| **Licensing / data use** | The default free tier's terms allow Google to use submitted content — here, transcribed radio text, never audio — to improve their products. An operator who finds that unacceptable can configure a paid tier, switch to an alternative provider, or set `llm.provider: none` for prefilter-only classification. |
| **Fallback when unavailable** | Missing credentials, an exhausted daily budget, or a request failure moves to the next provider in `llm.fallback`; if every provider in the chain is exhausted or fails, the clip's prefilter verdict is stored as `deferred` and upgraded by a later backfill pass once budget resets. |

### Groq (first fallback)

| | |
|---|---|
| **Provides** | The same structured classification, via Groq's OpenAI-compatible chat completions API. |
| **Authentication** | API key (`groq_api_key` in `.env`). |
| **Rate limits** | Governed by the operator's Groq account tier; metered independently against the same app-level `daily_call_cap`. |
| **Licensing / data use** | Governed by Groq's own terms for the account tier in use. |
| **Fallback when unavailable** | Missing credentials are logged and the provider is skipped when building the classifier chain, rather than failing at runtime; a request failure falls through to the next provider in the chain. |

### Ollama (second fallback, local)

| | |
|---|---|
| **Provides** | The same structured classification, run against a local Ollama server (`llm.ollama_url`, default `http://localhost:11434`). |
| **Authentication** | None — a local, unauthenticated HTTP endpoint. |
| **Rate limits** | None beyond local hardware throughput; this leg exists specifically as a zero-cost, zero-cloud fallback. |
| **Licensing / data use** | Nothing leaves the local machine on this leg. |
| **Fallback when unavailable** | An unreachable local server raises a classifier error and the chain falls through to whatever comes after it (or to prefilter-only, if `none` is next). |

### `none` — prefilter-only

Setting `llm.provider: none` (or exhausting `llm.fallback` down to `none`)
terminates the chain entirely: every clip is classified by the
deterministic prefilters alone, with no network call and no data leaving
the station. This is the appropriate configuration for an operator who
wants zero dependency on any cloud classification service.
