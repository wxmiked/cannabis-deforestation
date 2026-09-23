#!/usr/bin/env bash
# Registers Planetary Computer NAIP mosaics for each year used by the story
# map and prints the resulting search IDs to paste into NAIP_SEARCH_IDS in
# blog-interactive/js/app.js.
#
# This must be run from a non-browser client (curl, here) because Planetary
# Computer's /api/data/v1/mosaic/register endpoint fails the CORS preflight
# (OPTIONS returns 405) for any browser origin, even though the POST itself
# succeeds and returns a deterministic, durable search ID hash. Re-run this
# whenever PARCEL_BBOX or the year list in app.js changes.
set -euo pipefail

BBOX='[[-120.98,37.92],[-120.31,37.92],[-120.31,38.46],[-120.98,38.46],[-120.98,37.92]]'
YEARS=(2014 2016 2018)

for year in "${YEARS[@]}"; do
  body=$(cat <<EOF
{"collections":["naip"],"filter-lang":"cql2-json","filter":{"op":"and","args":[{"op":"s_intersects","args":[{"property":"geometry"},{"type":"Polygon","coordinates":[${BBOX}]}]},{"op":">=","args":[{"property":"datetime"},"${year}-01-01T00:00:00Z"]},{"op":"<=","args":[{"property":"datetime"},"${year}-12-31T23:59:59Z"]}]}}
EOF
)
  id=$(curl -s -X POST "https://planetarycomputer.microsoft.com/api/data/v1/mosaic/register" \
    -H "Content-Type: application/json" \
    -d "$body" | python3 -c "import json,sys; print(json.load(sys.stdin)['searchid'])")
  echo "$year: $id"
done
