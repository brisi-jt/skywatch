#!/bin/bash
# Fetch the free ATCO2 ASR sample corpus (real ATC audio) for local testing.
#
# USAGE:
#   scripts/fetch_samples.sh --accept-license
#
# Downloads land in fixtures/fetched/ (gitignored). Nothing fetched here is
# ever committed: the samples carry their own license, which you must read
# and accept before this script will download anything.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="$REPO_ROOT/fixtures/fetched"
TERMS_URL="https://www.atco2.org/data"
SAMPLE_URL="https://www.replaywell.com/atco2/download/ATCO2-ASRdataset-v1_beta.tgz"
ARCHIVE="$DEST_DIR/$(basename "$SAMPLE_URL")"

accept=0
for arg in "$@"; do
    case "$arg" in
        --accept-license) accept=1 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

echo "ATCO2 sample corpus fetcher"
echo "  terms:   $TERMS_URL"
echo "  archive: $SAMPLE_URL"
echo

# Verify the terms page is reachable before anything else: if the project's
# licensing page cannot be checked, the terms are unclear and we stop.
if ! curl -fsSL --max-time 30 -o /dev/null "$TERMS_URL"; then
    echo "ABORT: could not reach the ATCO2 data/terms page ($TERMS_URL)." >&2
    echo "The sample corpus's license terms cannot be verified, so nothing" >&2
    echo "will be downloaded. Check the URL in a browser and try again." >&2
    exit 1
fi

if [ "$accept" -ne 1 ]; then
    cat >&2 <<EOF
ABORT: license not accepted.

The ATCO2 sample corpus is distributed by the ATCO2 project under its own
end-user terms (research/evaluation use; the full corpus is licensed
separately through ELDA). This station only ever uses it locally as test
audio and never redistributes it — but you still have to read and accept
the terms yourself:

    $TERMS_URL

Then re-run:

    scripts/fetch_samples.sh --accept-license
EOF
    exit 1
fi

mkdir -p "$DEST_DIR"
if [ -f "$ARCHIVE" ]; then
    echo "archive already present: $ARCHIVE (delete it to re-download)"
else
    echo "downloading (~1 GB)..."
    curl -fL --progress-bar -o "$ARCHIVE.part" "$SAMPLE_URL"
    mv "$ARCHIVE.part" "$ARCHIVE"
fi

echo "extracting..."
tar -xzf "$ARCHIVE" -C "$DEST_DIR"
echo
echo "done. Samples are in $DEST_DIR (gitignored; local use only)."
find "$DEST_DIR" -name '*.wav' | head -5
