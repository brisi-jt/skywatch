# skywatch

A self-contained, receive-only aviation monitoring station for a single RTL-SDR
dongle. It records squelch-split VHF airband voice clips, transcribes them
locally with Whisper-family models, classifies routine vs non-routine traffic
with layered prefilters plus a cloud LLM, enriches each clip with probable
aircraft from OpenSky, and serves everything through a documented FastAPI
backend and a web dashboard.

Everything runs on modest hardware: the reference deployment is a 2015
dual-core MacBook Pro. Development needs no radio hardware at all — a replay
capture source feeds fixture audio through the identical pipeline.

## Legal (United Kingdom)

This project is receive-only and intended for personal, private use. Under the
Wireless Telegraphy Act 2006 it is an offence in the UK to disclose the
contents of radio transmissions not intended for you, or to act on them.
skywatch never transmits, and you must not rebroadcast, publish, or share
recorded communications. You are responsible for ensuring your own use is
lawful in your jurisdiction.

## Data use with free LLM tiers

The default classifier uses the Gemini API free tier, whose terms allow Google
to use submitted content (here: transcribed radio text) to improve their
products. If that is unacceptable, configure a paid tier, an alternative
provider, or `llm.provider: none` for prefilter-only classification.

## Data attribution

`content/airlines.dat` is the airlines database from
[OpenFlights](https://openflights.org/data), used to map radio callsign
prefixes to airline names. It is made available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/);
the data itself is under the Database Contents License 1.0.

`content/plane_alert_db.csv` badges probable aircraft with a curated category
(military, government, historic, and so on) from
[plane-alert-db](https://github.com/sdr-enthusiasts/plane-alert-db), keyed by
ICAO hex. The repository ships only the header; run
`scripts/update_plane_alert_db.sh` to download the current list.

Probable-aircraft identity (registration, type, operator) comes from the
[OpenSky Network aircraft database](https://opensky-network.org/data/aircraft).
It is large and never committed; run `scripts/fetch_aircraft_db.sh` to download
it to `data/aircraft_db.csv`. Please cite the OpenSky Network as its authors
request when redistributing derived data.

The Sky view's live positions come from a chain of keyless, non-commercial
aggregators — [airplanes.live](https://airplanes.live/),
[adsb.lol](https://adsb.lol/) (data under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/)),
and [adsb.fi](https://adsb.fi/) — with
[The OpenSky Network](https://opensky-network.org/) as a last-resort fallback
when all three are unavailable.

## Quickstart

Requires Python 3.12 managed by [uv](https://docs.astral.sh/uv/).

```sh
uv sync --all-extras
make test
```

Configuration lives in `config/config.yaml` (copy from
`config/config.yaml.example`) with secrets in a repository-root `.env` (copy
from `config/.env.example`).
