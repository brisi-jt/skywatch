#!/usr/bin/env bash
# Fetch the OpenSky aircraft database (icao24 -> registration, type, operator).
#
# The file is large (~70 MB) and is never committed; enrichment reads it from
# data/aircraft_db.csv to fill in each candidate's identity. Re-run whenever
# you want a fresher snapshot.
set -euo pipefail

SOURCE_URL="${AIRCRAFT_DB_URL:-https://opensky-network.org/datasets/metadata/aircraftDatabase.csv}"
DATA_ROOT="${DATA_ROOT:-$(cd "$(dirname "$0")/.." && pwd)/data}"
DEST="$DATA_ROOT/aircraft_db.csv"

mkdir -p "$DATA_ROOT"
echo "Fetching aircraft database from $SOURCE_URL"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

curl -fsSL "$SOURCE_URL" -o "$tmp"

if [ ! -s "$tmp" ]; then
    echo "Downloaded file is empty; leaving the existing database untouched." >&2
    exit 1
fi

mv "$tmp" "$DEST"
trap - EXIT
rows="$(($(wc -l <"$DEST") - 1))"
echo "Wrote $rows aircraft to $DEST"
