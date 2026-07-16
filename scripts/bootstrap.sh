#!/bin/bash
# Set up (or update) a skywatch station on this Mac.
#
# USAGE:
#   scripts/bootstrap.sh [--dry-run] [--with-whisper-cpp]
#
#   --dry-run           print every action that would change the machine,
#                       change nothing
#   --with-whisper-cpp  also build the whisper.cpp fallback transcriber and
#                       download its base.en model
#
# Safe to run repeatedly: every step checks the current state first and
# skips work that is already done, so a re-run after an interruption (or a
# git pull) only performs what is missing or stale.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

DRY_RUN=0
WITH_WHISPER_CPP=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --with-whisper-cpp) WITH_WHISPER_CPP=1 ;;
        -h|--help)
            sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say()  { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }

# Every mutating command goes through run(): in dry-run mode it is printed
# instead of executed, so --dry-run walks the full plan without touching
# the machine.
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'would run: %s\n' "$*"
    else
        "$@"
    fi
}

# --- Platform ---------------------------------------------------------------

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This bootstrap targets macOS (launchd, Homebrew, pmset)." >&2
    echo "For Linux, see the Raspberry Pi appendix in EXTENSIONS.md." >&2
    exit 1
fi

# --- Homebrew ---------------------------------------------------------------

if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required but not installed." >&2
    echo "Install it first: https://brew.sh — then re-run this script." >&2
    exit 1
fi
BREW_PREFIX="$(brew --prefix)"
say "Homebrew found at $BREW_PREFIX"

BREW_PACKAGES=(coreutils libconfig rtl-sdr cmake pkg-config uv)
for pkg in "${BREW_PACKAGES[@]}"; do
    if brew list --versions "$pkg" >/dev/null 2>&1; then
        say "$pkg already installed"
    else
        run brew install "$pkg"
    fi
done

# --- rtl_airband ------------------------------------------------------------

RTL_AIRBAND_REPO="https://github.com/rtl-airband/RTLSDR-Airband.git"
RTL_AIRBAND_SRC="$REPO_ROOT/build/rtl-airband"
RTL_AIRBAND_BIN="$REPO_ROOT/bin/rtl_airband"

if [ -x "$RTL_AIRBAND_BIN" ]; then
    say "rtl_airband already built ($RTL_AIRBAND_BIN)"
else
    say "building rtl_airband"
    if [ ! -d "$RTL_AIRBAND_SRC" ]; then
        run git clone --depth 1 "$RTL_AIRBAND_REPO" "$RTL_AIRBAND_SRC"
    fi
    run cmake -S "$RTL_AIRBAND_SRC" -B "$RTL_AIRBAND_SRC/build" \
        -DPLATFORM=generic -DCMAKE_BUILD_TYPE=Release
    run cmake --build "$RTL_AIRBAND_SRC/build" --parallel
    run mkdir -p "$REPO_ROOT/bin"
    run install -m 755 "$RTL_AIRBAND_SRC/build/src/rtl_airband" "$RTL_AIRBAND_BIN"
fi

# --- whisper.cpp (optional fallback transcriber) ------------------------------

if [ "$WITH_WHISPER_CPP" -eq 1 ]; then
    WHISPER_REPO="https://github.com/ggml-org/whisper.cpp.git"
    WHISPER_SRC="$REPO_ROOT/build/whisper.cpp"
    WHISPER_BIN="$REPO_ROOT/bin/whisper-cli"
    WHISPER_MODEL="$WHISPER_SRC/models/ggml-base.en.bin"

    if [ -x "$WHISPER_BIN" ] && [ -f "$WHISPER_MODEL" ]; then
        say "whisper.cpp already built ($WHISPER_BIN)"
    else
        say "building whisper.cpp"
        if [ ! -d "$WHISPER_SRC" ]; then
            run git clone --depth 1 "$WHISPER_REPO" "$WHISPER_SRC"
        fi
        run cmake -S "$WHISPER_SRC" -B "$WHISPER_SRC/build" -DCMAKE_BUILD_TYPE=Release
        run cmake --build "$WHISPER_SRC/build" --parallel
        run mkdir -p "$REPO_ROOT/bin"
        run install -m 755 "$WHISPER_SRC/build/bin/whisper-cli" "$WHISPER_BIN"
        if [ ! -f "$WHISPER_MODEL" ]; then
            run bash "$WHISPER_SRC/models/download-ggml-model.sh" base.en
        fi
    fi
    say "to use it, set in config/config.yaml:"
    say "  asr.engine: whisper_cpp"
    say "  asr.whisper_cpp_binary: $WHISPER_BIN"
    say "  asr.whisper_cpp_model: $WHISPER_MODEL"
fi

# --- Python environment -------------------------------------------------------

cd "$REPO_ROOT"
say "syncing Python environment (uv)"
if ! run env MACOSX_DEPLOYMENT_TARGET=12.0 uv sync --extra asr; then
    warn "uv sync with the ASR extra failed — the faster-whisper wheel may not"
    warn "support this macOS. Installing without it; use the whisper.cpp"
    warn "fallback instead (re-run with --with-whisper-cpp and flip"
    warn "asr.engine: whisper_cpp in config/config.yaml)."
    run env MACOSX_DEPLOYMENT_TARGET=12.0 uv sync
fi

# --- Configuration files ------------------------------------------------------

if [ -f "$REPO_ROOT/config/config.yaml" ]; then
    say "config/config.yaml already present"
else
    run cp "$REPO_ROOT/config/config.yaml.example" "$REPO_ROOT/config/config.yaml"
    say "created config/config.yaml from the example — review it"
fi

if [ -f "$REPO_ROOT/.env" ]; then
    say ".env already present"
else
    run cp "$REPO_ROOT/config/.env.example" "$REPO_ROOT/.env"
    warn ".env created from the example: add your API keys before going live"
fi

# --- Data directories, database ------------------------------------------------

run mkdir -p "$REPO_ROOT/data/logs" "$REPO_ROOT/data/recordings"
say "applying database migrations"
run uv run alembic upgrade head
say "seeding the frequency plan (no-op if already seeded)"
run uv run python -m skywatch.db.seed

# --- launchd services -----------------------------------------------------------

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
GUI_DOMAIN="gui/$(id -u)"

for template in "$REPO_ROOT"/deploy/launchd/*.plist; do
    name="$(basename "$template")"
    label="${name%.plist}"
    target="$LAUNCH_AGENTS/$name"
    rendered="$(sed -e "s|__SKYWATCH_ROOT__|$REPO_ROOT|g" \
                    -e "s|__HOMEBREW_PREFIX__|$BREW_PREFIX|g" \
                    "$template")"

    if [ -f "$target" ] && [ "$(cat "$target")" = "$rendered" ]; then
        say "$label already installed and current"
        continue
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'would install: %s (and reload %s)\n' "$target" "$label"
        continue
    fi

    say "installing $label"
    mkdir -p "$LAUNCH_AGENTS"
    printf '%s\n' "$rendered" > "$target"
    plutil -lint "$target" >/dev/null
    launchctl bootout "$GUI_DOMAIN/$label" 2>/dev/null || true
    launchctl bootstrap "$GUI_DOMAIN" "$target"
done

# --- Keep the laptop awake on mains power ---------------------------------------

ac_sleep="$(pmset -g custom | awk '/AC Power/{ac=1} ac && $1=="sleep"{print $2; exit}')"
if [ "$ac_sleep" = "0" ]; then
    say "system sleep already disabled on AC power"
else
    say "disabling system sleep on AC power (needs your password for sudo)"
    run sudo pmset -c sleep 0
fi

# --- Clock sanity ----------------------------------------------------------------

# Recordings are matched to aircraft by timestamp, so a badly wrong clock
# quietly ruins the aircraft matching. Read-only check; runs even in dry-run.
if sntp_out="$(sntp time.apple.com 2>/dev/null)"; then
    offset="$(printf '%s\n' "$sntp_out" \
        | awk '{for (i = 1; i <= NF; i++) if ($i ~ /^[+-][0-9]+\.[0-9]+$/) {print $i; exit}}')"
    if [ -n "$offset" ] && awk -v o="$offset" 'BEGIN {exit (o < 5 && o > -5) ? 0 : 1}'; then
        say "clock offset ${offset}s — fine"
    elif [ -n "$offset" ]; then
        warn "clock is ${offset}s off — enable 'Set date and time automatically'"
        warn "in System Preferences before trusting aircraft matches"
    fi
else
    warn "could not reach time.apple.com to check the clock (offline?)"
fi

# --- Done ------------------------------------------------------------------------

say "bootstrap complete"
say "next steps:"
say "  1. put real API keys in .env (OpenSky, Gemini)"
say "  2. review config/config.yaml"
say "  3. follow the first-time setup section of content/RUNBOOK.md"
say "     (antenna, frequency verification, gain/squelch tuning, go live)"
