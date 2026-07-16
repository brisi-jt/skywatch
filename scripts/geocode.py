"""Geocode a UK postcode via postcodes.io and print receiver coordinates.

USAGE:
    uv run python scripts/geocode.py "SW1A 1AA"

Prints the latitude/longitude to paste into config.yaml's receiver block.
Run once during station setup; the pipeline itself never calls out for
geocoding.
"""

import argparse
import sys

import httpx

API_URL = "https://api.postcodes.io/postcodes/{postcode}"


def geocode(postcode: str) -> tuple[float, float, str]:
    response = httpx.get(API_URL.format(postcode=postcode.strip().replace(" ", "%20")))
    response.raise_for_status()
    result = response.json()["result"]
    return result["latitude"], result["longitude"], result.get("parish") or ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("postcode", help='UK postcode, e.g. "SW1A 1AA"')
    args = parser.parse_args()
    try:
        lat, lon, parish = geocode(args.postcode)
    except (httpx.HTTPError, KeyError) as exc:
        print(f"geocoding failed: {exc}", file=sys.stderr)
        return 1
    suffix = f"  # {parish}" if parish else ""
    print(f"receiver:{suffix}")
    print(f'  postcode: "{args.postcode.upper()}"')
    print(f"  lat: {lat}")
    print(f"  lon: {lon}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
