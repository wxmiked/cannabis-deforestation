#!/usr/bin/env python3
"""
build_dwr_crop_mask.py

Extracts a false-positive suppression mask from the California DWR Statewide
Crop Mapping GDB for a given year and county, and saves it as GeoJSON in
EPSG:4326.

The mask covers crop types whose spectral/structural signatures trigger false
positives in the cannabis segmentation model: NIR similarity to cannabis
canopy (vineyards, orchards), or mowing/tilling row patterns (pasture, grain).

Usage:
    python scripts/build_dwr_crop_mask.py \
        --gdb data-to-import/dwr-crop-mapping-2016/i15_crop_mapping_2016_gdb.zip \
        --county Calaveras \
        --out data-to-import/dwr-crop-mapping-2016/calaveras_crop_mask_2016.geojson

The GDB is read directly from the zip file via GDAL's /vsizip/ virtual
filesystem — no extraction needed. The zip path is auto-wrapped.

Pass --boundary to a KML or GeoJSON file to clip the output to a county
boundary polygon. Shapely intersection is used; empty geometries are dropped.

Dependencies: fiona, shapely, pyproj
    pip install fiona shapely pyproj

Schema notes (confirmed via fiona on i15_crop_mapping_2016_gdb.zip):
    Layer:       i15_Crop_Mapping_2016
    Source CRS:  EPSG:3857 (Web Mercator)
    Class field: Symb_class (str:4) — preferred over CLASS2 which has leading spaces
    County:      County (str:50) — full county name, e.g. "Calaveras"
    Crop label:  Crop2016 (str:50) — human-readable crop type (useful for verification)
"""

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Mask category definitions
# Source: 2022 DWR Standard Land Use Legend
# https://water.ca.gov/-/media/DWR-Website/Web-Pages/Programs/Water-Use-And-Efficiency/
#         Land-And-Water-Use/Land-Use-Surveys/Files/
#         2022-standard-land-use-legend-remote-sensing_ADA-compliant.pdf
#
# Symb_class values confirmed in the 2016 GDB via fiona inspection.
#
# MASK (suppress these as false positives):
#   V   Vineyards            — NIR spectral similarity to cannabis; primary FP source
#   D   Deciduous Fruits and Nuts  — orchards (walnuts, almonds, cherries, plums, etc.)
#   C   Citrus and Subtropical     — olives, citrus groves, avocados
#   YP  Young Perennial Fruits and Nuts  — young orchards/vineyards
#   P   Pasture              — alfalfa, mixed pasture, turf; mowing patterns cause FP
#   G   Grain and Hay Crops  — barley, wheat, misc grain/hay; mowing patterns cause FP
#   R   Rice                 — rice paddies (not present in Calaveras 2016 but included
#                              for completeness; low FP risk)
#   F   Field Crops          — cotton, corn, sugar beets, beans, sunflowers
#                              (agricultural class F = field crops, NOT fallow)
#
# DO NOT MASK:
#   X   Unclassified / Idle  — cannabis grows observed on idle/fallow land in Calaveras
#   I   Idle (if present)    — same concern
#   T   Truck/Nursery        — T16 subclass explicitly groups cannabis; masking would
#                              suppress real detections
#   T16 (subclass of T)      — DWR groups cannabis with Christmas trees and ornamentals
# ---------------------------------------------------------------------------

MASK_CLASSES = {"V", "D", "C", "YP", "P", "G", "R", "F"}
NO_MASK_CLASSES = {"X", "I", "T"}  # T covers T16 subclass


def parse_args():
    p = argparse.ArgumentParser(description="Build DWR crop false-positive suppression mask")
    p.add_argument(
        "--gdb",
        required=True,
        help="Path to the DWR Statewide Crop Mapping .gdb directory or .zip file",
    )
    p.add_argument(
        "--county",
        default="Calaveras",
        help="County name to filter (must match 'County' field in GDB, default: Calaveras)",
    )
    p.add_argument(
        "--layer",
        default=None,
        help="GDB layer name. Auto-detected if omitted.",
    )
    p.add_argument(
        "--boundary",
        default=None,
        help="Optional path to a KML or GeoJSON boundary file (EPSG:4326) to clip output",
    )
    p.add_argument(
        "--class-field",
        default="Symb_class",
        help="Field containing land use class (default: Symb_class)",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output path for the mask GeoJSON (EPSG:4326)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats without writing output",
    )
    return p.parse_args()


def should_mask(symb_class: str) -> bool:
    """Return True if this Symb_class value should be included in the mask."""
    s = symb_class.strip()
    # Explicit no-mask check first
    if s in NO_MASK_CLASSES or s.startswith("T"):
        return False
    return s in MASK_CLASSES


def main():
    args = parse_args()
    raw_path = str(Path(args.gdb).resolve())
    out_path = str(Path(args.out).resolve())

    try:
        import fiona
        from pyproj import Transformer
        from shapely.geometry import mapping, shape, Polygon
        from shapely.ops import transform as shp_transform
    except ImportError as e:
        print(f"ERROR: Missing dependency: {e}", file=sys.stderr)
        print("Install with: pip install fiona shapely pyproj", file=sys.stderr)
        sys.exit(1)

    # --- Load optional boundary polygon for clipping ---
    boundary_poly = None
    if args.boundary:
        boundary_path = str(Path(args.boundary).resolve())
        print(f"Loading boundary: {boundary_path}")
        if boundary_path.endswith(".kml"):
            # Parse KML with stdlib xml — avoids GDAL KML driver requirement
            import xml.etree.ElementTree as ET
            tree = ET.parse(boundary_path)
            coords_text = None
            for elem in tree.getroot().iter():
                if elem.tag.endswith("coordinates"):
                    coords_text = elem.text.strip()
                    break
            if not coords_text:
                print("ERROR: No <coordinates> found in KML", file=sys.stderr)
                sys.exit(1)
            pairs = []
            for token in coords_text.split():
                parts = token.split(",")
                pairs.append((float(parts[0]), float(parts[1])))
            boundary_poly = Polygon(pairs)
        else:
            # GeoJSON
            with open(boundary_path) as f:
                import json as _json
                gj = _json.load(f)
            if gj["type"] == "FeatureCollection":
                boundary_poly = shape(gj["features"][0]["geometry"])
            elif gj["type"] == "Feature":
                boundary_poly = shape(gj["geometry"])
            else:
                boundary_poly = shape(gj)
        if not boundary_poly.is_valid:
            boundary_poly = boundary_poly.buffer(0)
        print(f"Boundary loaded: {len(list(boundary_poly.exterior.coords))} vertices, bounds={boundary_poly.bounds}")

    # If given a zip, wrap with GDAL's vsizip virtual filesystem.
    # The zip contains a single .gdb inside a subdirectory; fiona/GDAL
    # can list and open it directly without extraction.
    if raw_path.endswith(".zip"):
        # List what's inside to find the .gdb path
        import zipfile
        with zipfile.ZipFile(raw_path) as zf:
            gdb_entries = [n for n in zf.namelist() if n.endswith(".gdb/") or ".gdb/" in n]
            # Extract the .gdb directory name (e.g. "i15_Crop_Mapping_2016_GDB/i15_Crop_Mapping_2016.gdb")
            gdb_dirs = sorted({n.split(".gdb/")[0] + ".gdb" for n in gdb_entries if ".gdb/" in n})
        if not gdb_dirs:
            print("ERROR: No .gdb found inside zip", file=sys.stderr)
            sys.exit(1)
        gdb_path = f"/vsizip/{raw_path}/{gdb_dirs[0]}"
        print(f"Reading GDB from zip: {gdb_dirs[0]}")
    else:
        gdb_path = raw_path

    # Detect layer
    layer = args.layer
    if not layer:
        layers = fiona.listlayers(gdb_path)
        print(f"Layers in GDB: {layers}")
        if not layers:
            print("ERROR: No layers found in GDB", file=sys.stderr)
            sys.exit(1)
        layer = layers[0]
        print(f"Using layer: {layer}")

    print(f"Opening {gdb_path} / {layer}")
    print(f"County filter: {args.county}")
    print(f"Class field: {args.class_field}")

    # Build transformer from source CRS to EPSG:4326
    # (source CRS confirmed as EPSG:3857 in 2016 GDB)
    transformer = None

    total = 0
    kept = 0
    skipped_county = 0
    skipped_class = 0
    class_counts: dict[str, int] = {}
    crop_counts: dict[str, int] = {}
    features_out = []

    with fiona.open(gdb_path, layer=layer) as src:
        src_crs = src.crs
        print(f"Source CRS: {src_crs}")

        # Set up reprojection
        from pyproj import CRS
        src_crs_obj = CRS.from_user_input(src_crs)
        dst_crs_obj = CRS.from_epsg(4326)

        if src_crs_obj != dst_crs_obj:
            transformer = Transformer.from_crs(src_crs_obj, dst_crs_obj, always_xy=True)
            print("Reprojecting to EPSG:4326")
        else:
            print("Source is already EPSG:4326, no reprojection needed")

        for feat in src:
            total += 1
            props = feat["properties"]
            county = (props.get("County") or "").strip()
            symb = (props.get(args.class_field) or "").strip()

            if county != args.county:
                skipped_county += 1
                continue

            if not should_mask(symb):
                skipped_class += 1
                continue

            kept += 1
            class_counts[symb] = class_counts.get(symb, 0) + 1
            crop_label = (props.get("Crop2016") or "").strip()
            crop_counts[crop_label] = crop_counts.get(crop_label, 0) + 1

            # Reproject geometry
            geom_shape = shape(feat["geometry"])
            if transformer:
                geom_shape = shp_transform(transformer.transform, geom_shape)

            # Clip to boundary if provided
            if boundary_poly is not None:
                geom_shape = geom_shape.intersection(boundary_poly)
                if geom_shape.is_empty:
                    kept -= 1
                    continue

            geom = mapping(geom_shape)

            features_out.append({
                "type": "Feature",
                "properties": {
                    "Symb_class": symb,
                    "Crop2016": crop_label,
                    "County": county,
                    "Acres": props.get("Acres"),
                    "SUBCLASS2": (props.get("SUBCLASS2") or "").strip(),
                },
                "geometry": geom,
            })

    print(f"\nResults:")
    print(f"  Total features in layer: {total}")
    print(f"  Skipped (other county):  {skipped_county}")
    print(f"  Skipped (no-mask class): {skipped_class}")
    print(f"  Kept (mask candidates):  {kept}")
    print(f"\n  Class breakdown (Symb_class):")
    for k, v in sorted(class_counts.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}")
    print(f"\n  Crop type breakdown (Crop2016):")
    for k, v in sorted(crop_counts.items(), key=lambda x: -x[1]):
        print(f"    {repr(k)}: {v}")

    if args.dry_run:
        print("\n[dry-run] No output written.")
        return

    geojson_out = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": features_out,
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(geojson_out, f)

    print(f"\nOutput: {out_path}")
    print(f"  {kept} features written")

    print("\nNext steps:")
    print("  1. Inspect output in QGIS — verify coverage in Calaveras County")
    print("  2. Cross-check Crop2016 values against known FP locations")
    print("  3. Apply mask in inference: rasterize to NAIP tile CRS/resolution,")
    print("     zero out predicted-positive pixels within mask polygons")
    print("  4. Run with --county Calaveras (default) for inference; adjust for other counties")
    if args.boundary is None:
        print("  5. Consider re-running with --boundary to clip geometries to the county boundary")
        print("     e.g.: --boundary data-to-import/calaveras-county/boundary/COUNTY_BOUNDARY.kml")


if __name__ == "__main__":
    main()
