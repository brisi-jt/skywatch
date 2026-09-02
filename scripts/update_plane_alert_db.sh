#!/usr/bin/env bash
# Refresh the vendored plane-alert database.
#
# Downloads the community-maintained list of interesting airframes (keyed by
# ICAO 24-bit hex, with a category per aircraft) and writes it to
# content/plane_alert_db.csv, which enrichment reads to badge candidates.
# The repository ships only the CSV header; run this to populate it.
set -euo pipefail

SOURCE_URL="${PLANE_ALERT_DB_URL:-https://raw.githubusercontent.com/sdr-enthusiasts/plane-alert-db/main/plane-alert-db.csv}"
DEST="$(cd "$(dirname "$0")/.." && pwd)/content/plane_alert_db.csv"

echo "Fetching plane-alert database from $SOURCE_URL"
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
