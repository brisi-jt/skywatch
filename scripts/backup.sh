#!/bin/bash
# Back up the station: the database plus the audio of every interesting clip.
#
# USAGE:
#   scripts/backup.sh /path/to/backup/folder
#
# The target folder is created if needed. Re-runs are incremental where
# rsync is available, so backing up often is cheap. Routine-clip audio is
# deliberately not included (it expires on the station anyway); the
# database — which keeps every transcript and detail forever — always is.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_ROOT="${SKYWATCH_DATA_ROOT:-$REPO_ROOT/data}"
DB_PATH="$DATA_ROOT/station.db"

if [ $# -ne 1 ] || [ -z "$1" ]; then
    echo "usage: $0 /path/to/backup/folder" >&2
    echo "refusing to run without a target folder" >&2
    exit 2
fi
TARGET="$1"

if [ ! -f "$DB_PATH" ]; then
    echo "no station database found at $DB_PATH — nothing to back up" >&2
    exit 1
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "sqlite3 is required (it ships with macOS) but was not found" >&2
    exit 1
fi

mkdir -p "$TARGET/audio"

# 1. Database: sqlite's own backup command produces a consistent snapshot
#    even while the station is writing.
echo "backing up database -> $TARGET/station.db"
sqlite3 "$DB_PATH" ".backup '$TARGET/station.db'"

# 2. Interesting audio: every clip whose latest classification says
#    interesting and whose audio has not been pruned.
list_all="$(mktemp)"
list_existing="$(mktemp)"
trap 'rm -f "$list_all" "$list_existing"' EXIT

sqlite3 -noheader "$DB_PATH" "
    SELECT r.file_path
    FROM recordings r
    JOIN classifications c ON c.recording_id = r.id
    WHERE c.id = (
        SELECT c2.id FROM classifications c2
        WHERE c2.recording_id = r.id
        ORDER BY c2.created_at DESC, c2.id DESC
        LIMIT 1
    )
    AND c.is_interesting = 1
    AND r.audio_deleted_at IS NULL
    ORDER BY r.file_path;
" > "$list_all"

missing=0
while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    if [ -f "$DATA_ROOT/$rel" ]; then
        printf '%s\n' "$rel" >> "$list_existing"
    else
        echo "WARNING: listed in database but missing on disk: $rel" >&2
        missing=$((missing + 1))
    fi
done < "$list_all"

count="$(wc -l < "$list_existing" | tr -d ' ')"
if [ "$count" -eq 0 ]; then
    echo "no interesting clips to copy (yet)"
else
    echo "copying $count interesting clip(s) -> $TARGET/audio/"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --files-from="$list_existing" "$DATA_ROOT/" "$TARGET/audio/"
    else
        while IFS= read -r rel; do
            mkdir -p "$TARGET/audio/$(dirname "$rel")"
            cp "$DATA_ROOT/$rel" "$TARGET/audio/$rel"
        done < "$list_existing"
    fi
fi

if [ "$missing" -gt 0 ]; then
    echo "done, with $missing file(s) skipped as missing (see warnings above)"
else
    echo "backup complete: $TARGET"
fi
