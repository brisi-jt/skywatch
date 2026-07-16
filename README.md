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

## Quickstart

Requires Python 3.12 managed by [uv](https://docs.astral.sh/uv/).

```sh
uv sync --all-extras
make test
```

Configuration lives in `config/config.yaml` (copy from
`config/config.yaml.example`) with secrets in a repository-root `.env` (copy
from `config/.env.example`).
