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
        --gdb data-to-import/dwr-crop-mapping-2016/i15_Crop_Mapping_2016_GDB/i15_Crop_Mapping_2016.gdb \
        --county Calaveras \
        --out data-to-import/dwr-crop-mapping-2016/calaveras_crop_mask_2016.geojson

Dependencies: fiona, shapely, pyproj
    pip install fiona shapely pyproj

Schema notes (confirmed via ogrinfo on i15_Crop_Mapping_2016.gdb):
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
        help="Path to the DWR Statewide Crop Mapping .gdb directory",
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
    gdb_path = str(Path(args.gdb).resolve())
    out_path = str(Path(args.out).resolve())

    try:
        import fiona
        from pyproj import Transformer
        from shapely.geometry import mapping, shape
    except ImportError as e:
        print(f"ERROR: Missing dependency: {e}", file=sys.stderr)
        print("Install with: pip install fiona shapely pyproj", file=sys.stderr)
        sys.exit(1)

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

            # Reproject geometry if needed
            geom = feat["geometry"]
            if transformer:
                shp = shape(geom)
                from shapely.ops import transform as shp_transform
                reprojected = shp_transform(transformer.transform, shp)
                geom = mapping(reprojected)

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


if __name__ == "__main__":
    main()
