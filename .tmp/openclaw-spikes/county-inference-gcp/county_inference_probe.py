#!/usr/bin/env python3
"""Throwaway probe for county-scale inference prerequisites.

This intentionally avoids heavyweight geospatial/model dependencies so it can
run in a bare checkout. It validates what can be inferred from repo files and
does a bounded Planetary Computer STAC dry-run without downloading imagery.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
COUNTY_KML = REPO / "data-to-import/calaveras-county/boundary/COUNTY_BOUNDARY.kml"
NOTEBOOK = REPO / "notebooks/04-search-cannabis-in-bbox.ipynb"
WEIGHTS = REPO / "models/cannabis-cultivation-deeplabv3plus-resnet50-naip.pth"


def module_status() -> dict[str, bool]:
    modules = [
        "geopandas",
        "fiona",
        "pyogrio",
        "shapely",
        "rasterio",
        "pystac_client",
        "planetary_computer",
        "torch",
        "torchgeo",
        "segmentation_models_pytorch",
        "simplekml",
    ]
    return {name: importlib.util.find_spec(name) is not None for name in modules}


def read_kml_bbox(path: Path) -> tuple[list[float], int]:
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    root = ET.parse(path).getroot()
    coords: list[tuple[float, float]] = []
    for el in root.findall(".//k:coordinates", ns):
        for token in (el.text or "").split():
            parts = token.split(",")
            if len(parts) >= 2:
                coords.append((float(parts[0]), float(parts[1])))
    if not coords:
        raise ValueError(f"no KML coordinates found in {path}")
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    return [min(xs), min(ys), max(xs), max(ys)], len(coords)


def notebook_summary(path: Path) -> dict[str, object]:
    nb = json.loads(path.read_text())
    code_cells = [
        "".join(cell.get("source", []))
        for cell in nb.get("cells", [])
        if cell.get("cell_type") == "code"
    ]
    text = "\n".join(code_cells)
    needles = [
        "DeepLabV3Plus",
        "resnext50_32x4d",
        "in_channels=5",
        "AppendNDVI",
        "GridGeoSampler",
        "planetary_computer.sign",
        "model.load_state_dict",
        "simplekml",
    ]
    return {
        "code_cells": len(code_cells),
        "contains": {needle: needle in text for needle in needles},
    }


def stac_dry_run(bbox: list[float], year: int, limit: int) -> dict[str, object]:
    payload = {
        "collections": ["naip"],
        "bbox": bbox,
        "datetime": f"{year}-01-01/{year}-12-31",
        "limit": limit,
    }
    req = urllib.request.Request(
        "https://planetarycomputer.microsoft.com/api/stac/v1/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/geo+json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.load(response)
    features = data.get("features", [])
    return {
        "returned": len(features),
        "matched": data.get("context", {}).get("matched"),
        "ids": [feature.get("id") for feature in features[:3]],
        "asset_keys_first": sorted(features[0].get("assets", {}).keys()) if features else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stac", action="store_true", help="run bounded STAC dry-run")
    parser.add_argument("--year", type=int, default=2016)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    bbox, coord_count = read_kml_bbox(COUNTY_KML)
    result = {
        "python": sys.version.split()[0],
        "county_kml": str(COUNTY_KML.relative_to(REPO)),
        "county_coord_count": coord_count,
        "county_bbox_wgs84": bbox,
        "weights_present": WEIGHTS.exists(),
        "notebook": notebook_summary(NOTEBOOK),
        "module_status": module_status(),
    }
    if args.stac:
        result["stac"] = stac_dry_run(bbox, args.year, args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
