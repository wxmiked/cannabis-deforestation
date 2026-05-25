"""County-scale NAIP inference planning utilities.

This module is intentionally light on geospatial dependencies for the first
planning step. It can parse the Calaveras County KML boundary enough to derive
a WGS84 bbox for STAC discovery, then writes a durable manifest that later
workers can consume. Polygon-window intersection belongs in the next worker
layer where Rasterio/Shapely are available.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PLANETARY_COMPUTER_SEARCH_URL = (
    "https://planetarycomputer.microsoft.com/api/stac/v1/search"
)


@dataclass(frozen=True)
class CountyBoundary:
    """Minimal county boundary metadata needed for STAC planning."""

    path: str
    bbox_wgs84: list[float]
    coordinate_count: int


def parse_kml_coordinates(path: Path) -> list[tuple[float, float]]:
    """Read all lon/lat coordinate pairs from a KML file."""

    tree = ET.parse(path)
    root = tree.getroot()
    coordinates: list[tuple[float, float]] = []

    for element in root.iter():
        if element.tag.split("}")[-1] != "coordinates" or not element.text:
            continue
        for raw_coord in element.text.split():
            parts = raw_coord.split(",")
            if len(parts) < 2:
                continue
            try:
                lon = float(parts[0])
                lat = float(parts[1])
            except ValueError:
                continue
            coordinates.append((lon, lat))

    if not coordinates:
        raise ValueError(f"No KML coordinates found in {path}")
    return coordinates


def county_boundary_from_kml(path: Path) -> CountyBoundary:
    """Return WGS84 bbox and coordinate count for a KML county boundary."""

    coordinates = parse_kml_coordinates(path)
    lons = [coord[0] for coord in coordinates]
    lats = [coord[1] for coord in coordinates]
    return CountyBoundary(
        path=str(path),
        bbox_wgs84=[min(lons), min(lats), max(lons), max(lats)],
        coordinate_count=len(coordinates),
    )


def stac_search_payload(
    year: int, bbox: list[float], limit: int = 100
) -> dict[str, Any]:
    """Build a Microsoft Planetary Computer NAIP STAC search payload."""

    return {
        "collections": ["naip"],
        "bbox": bbox,
        "datetime": f"{year}-01-01/{year}-12-31",
        "limit": limit,
    }


def fetch_stac_items(
    payload: dict[str, Any],
    *,
    search_url: str = PLANETARY_COMPUTER_SEARCH_URL,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    """Fetch all STAC features for a search payload.

    The STAC API may return pagination links. Persisting these item records in
    the manifest keeps downstream GPU workers away from repeated STAC queries.
    """

    items: list[dict[str, Any]] = []
    current_url: str | None = search_url
    current_payload: dict[str, Any] | None = payload

    while current_url:
        request_data = (
            json.dumps(current_payload).encode("utf-8")
            if current_payload is not None
            else None
        )
        request = urllib.request.Request(
            current_url,
            data=request_data,
            headers={"Content-Type": "application/json"},
            method="POST" if request_data else "GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            page = json.loads(response.read().decode("utf-8"))

        items.extend(page.get("features", []))
        next_link = next(
            (link for link in page.get("links", []) if link.get("rel") == "next"),
            None,
        )
        if not next_link:
            current_url = None
            continue

        current_url = urllib.parse.urljoin(current_url, next_link["href"])
        current_payload = next_link.get("body")

    return items


def load_stac_items(path: Path | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Load STAC item fixtures or query Planetary Computer."""

    if path is None:
        return fetch_stac_items(payload)

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "features" in data:
        return list(data["features"])
    if isinstance(data, list):
        return data
    raise ValueError(f"Unsupported STAC item JSON shape in {path}")


def asset_href(item: dict[str, Any], asset_key: str) -> str:
    """Extract an asset href from a STAC item."""

    assets = item.get("assets") or {}
    asset = assets.get(asset_key)
    if not asset or not asset.get("href"):
        raise KeyError(f"Item {item.get('id', '<unknown>')} lacks asset {asset_key!r}")
    return str(asset["href"])


def item_shard(item: dict[str, Any], year: int, asset_key: str) -> dict[str, Any]:
    """Create the first manifest shard shape: one source item per shard."""

    geometry = item.get("geometry") or {}
    return {
        "shard_id": None,
        "year": year,
        "naip_item_id": item["id"],
        "asset_key": asset_key,
        "asset_href": asset_href(item, asset_key),
        "item_bbox_wgs84": item.get("bbox"),
        "geometry_type": geometry.get("type"),
        "properties": {
            key: item.get("properties", {}).get(key)
            for key in ("datetime", "gsd", "proj:epsg", "naip:year")
            if key in item.get("properties", {})
        },
        "status": "planned",
    }


def build_manifest(
    *,
    year: int,
    county: CountyBoundary,
    stac_items: Iterable[dict[str, Any]],
    asset_key: str,
    source: str,
) -> dict[str, Any]:
    """Build a resumable county inference manifest."""

    shards = [item_shard(item, year, asset_key) for item in stac_items]
    for index, shard in enumerate(shards):
        shard["shard_id"] = index

    return {
        "schema_version": 1,
        "created_at_unix": int(time.time()),
        "pipeline": "county-inference",
        "year": year,
        "county": {
            "path": county.path,
            "bbox_wgs84": county.bbox_wgs84,
            "coordinate_count": county.coordinate_count,
        },
        "stac": {
            "collection": "naip",
            "asset_key": asset_key,
            "source": source,
            "item_count": len(shards),
        },
        "planning_notes": [
            "County bbox is used only for STAC discovery.",
            "Workers must use the county polygon for raster window inclusion.",
            "This v1 manifest plans one shard per NAIP item; window shards come next.",
        ],
        "shards": shards,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically enough for local planning artifacts."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def default_asset_filename(shard: dict[str, Any]) -> str:
    """Choose a deterministic local filename for a STAC asset."""

    href_path = urllib.parse.urlparse(shard["asset_href"]).path
    suffix = Path(href_path).suffix or ".tif"
    return f"{shard['year']}_{shard['naip_item_id']}{suffix}"


def download_asset(
    *,
    url: str,
    destination: Path,
    overwrite: bool = False,
    timeout: int = 120,
) -> str:
    """Download a remote asset with skip/resume-friendly semantics."""

    if destination.exists() and not overwrite:
        return "skipped"

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                shutil.copyfileobj(response, tmp)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    os.replace(temp_path, destination)
    return "downloaded"


def command_plan_county(args: argparse.Namespace) -> int:
    county = county_boundary_from_kml(args.county)
    payload = stac_search_payload(args.year, county.bbox_wgs84, limit=args.limit)
    stac_items = load_stac_items(args.stac_items_json, payload)
    if args.max_items is not None:
        stac_items = stac_items[: args.max_items]
    manifest = build_manifest(
        year=args.year,
        county=county,
        stac_items=stac_items,
        asset_key=args.asset_key,
        source=(
            str(args.stac_items_json)
            if args.stac_items_json
            else PLANETARY_COMPUTER_SEARCH_URL
        ),
    )
    write_json(args.out, manifest)
    print(f"Wrote {len(manifest['shards'])} shard(s) to {args.out}")
    return 0


def command_download_assets(args: argparse.Namespace) -> int:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    shards = manifest.get("shards", [])
    selected = shards if args.shard_id is None else [shards[args.shard_id]]

    for shard in selected:
        destination = args.out_dir / str(shard["year"]) / default_asset_filename(shard)
        if args.dry_run:
            print(f"DRY RUN {shard['naip_item_id']} -> {destination}")
            continue
        try:
            status = download_asset(
                url=shard["asset_href"],
                destination=destination,
                overwrite=args.overwrite,
            )
        except urllib.error.HTTPError as exc:
            print(
                f"ERROR {shard['naip_item_id']}: HTTP {exc.code} while downloading",
                file=sys.stderr,
            )
            return 1
        print(f"{status.upper()} {shard['naip_item_id']} -> {destination}")
    return 0


def command_run_shard(args: argparse.Namespace) -> int:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    shard = manifest["shards"][args.shard_id]
    args.out.mkdir(parents=True, exist_ok=True)

    status = {
        "schema_version": 1,
        "shard_id": shard["shard_id"],
        "year": shard["year"],
        "naip_item_id": shard["naip_item_id"],
        "asset_key": shard["asset_key"],
        "asset_href": shard["asset_href"],
        "weights": str(args.weights) if args.weights else None,
        "status": "dry_run" if args.dry_run else "not_implemented",
        "message": (
            "Shard metadata smoke test only. Model/window inference is the next layer."
            if args.dry_run
            else "Real model inference is not implemented yet."
        ),
    }
    write_json(args.out / "status.json", status)

    detections = {
        "type": "FeatureCollection",
        "features": [],
        "properties": {
            "shard_id": shard["shard_id"],
            "naip_item_id": shard["naip_item_id"],
            "status": status["status"],
        },
    }
    write_json(args.out / "detections.geojson", detections)
    print(f"Wrote shard smoke outputs to {args.out}")
    return 0 if args.dry_run else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="county-infer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser(
        "plan-county", help="Plan county NAIP inference shards"
    )
    plan.add_argument("--year", type=int, required=True)
    plan.add_argument("--county", type=Path, required=True)
    plan.add_argument("--out", type=Path, required=True)
    plan.add_argument("--asset-key", default="image")
    plan.add_argument("--limit", type=int, default=100)
    plan.add_argument("--max-items", type=int)
    plan.add_argument("--stac-items-json", type=Path)
    plan.set_defaults(func=command_plan_county)

    download = subparsers.add_parser(
        "download-assets", help="Download manifest NAIP assets to local storage"
    )
    download.add_argument("--manifest", type=Path, required=True)
    download.add_argument("--out-dir", type=Path, required=True)
    download.add_argument("--shard-id", type=int)
    download.add_argument("--overwrite", action="store_true")
    download.add_argument("--dry-run", action="store_true")
    download.set_defaults(func=command_download_assets)

    run = subparsers.add_parser("run-shard", help="Run or smoke-test one planned shard")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--shard-id", type=int, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--weights", type=Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run_shard)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
