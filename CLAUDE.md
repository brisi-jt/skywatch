# skywatch — repo conventions

## Portability (production floor: 2015 dual-core i5, 8 GB RAM, macOS 12)

- Never hardcode CPU architecture, Homebrew prefixes, or `-march` flags —
  development happens on Apple Silicon, production is Intel.
- Production installs set `MACOSX_DEPLOYMENT_TARGET=12.0`.
- The 2015 machine is the performance floor: keep memory footprints small
  (Whisper `base.en` int8, never `medium` on prod) and treat ASR as
  slower-than-real-time by design.

## Toolchain

- Python 3.12 via `uv` for everything — never call pip directly.
- Dashboard (`web/`) uses `bun`, not npm.
- Lint/format via ruff: `make lint`. Tests: `make test` (excludes `eval` and
  `network` markers; those run manually with credentials).

## House rules

- TDD: write the failing test before the implementation, for every stage,
  provider, and route.
- Single `settings.py` (pydantic-settings) — no scattered env reads.
- No stub routes or placeholder functions in committed code.
