"""
inference_mask.py

Utility module for applying the DWR Statewide Crop Mapping false-positive
suppression mask during inference.

The mask covers crop categories whose spectral/structural signatures are known
to trigger false positives in the cannabis segmentation model (NIR similarity
to cannabis canopy, or mowing row patterns). See data-to-import/dwr-crop-mapping-2016/
SOURCE.md for full documentation.

Typical usage in the inference notebook:

    from scripts.inference_mask import load_crop_mask, suppress_with_crop_mask

    crop_mask = load_crop_mask(
        '../data-to-import/dwr-crop-mapping-2016/calaveras_crop_mask_2016.geojson'
    )

    # In stream_inference, after model forward pass:
    pred_np = suppress_with_crop_mask(pred_np, tile_bbox, tile_crs, crop_mask)

    # In KML export, same call before mask_to_polygons:
    mask = suppress_with_crop_mask(mask, tile_bbox, dst_crs, crop_mask)
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Union

import numpy as np


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_crop_mask(geojson_path: Union[str, Path]):
    """
    Load a crop mask GeoJSON and return a unified Shapely geometry (EPSG:4326).

    The returned geometry is the union of all features in the file. It is
    cached by resolved path so repeated calls in a notebook session are free.

    Args:
        geojson_path: Path to the crop mask GeoJSON file.

    Returns:
        Shapely geometry representing the union of all mask polygons.
    """
    from shapely.geometry import shape
    from shapely.ops import unary_union

    path = str(Path(geojson_path).resolve())
    return _load_mask_cached(path)


@lru_cache(maxsize=8)
def _load_mask_cached(resolved_path: str):
    from shapely.geometry import shape
    from shapely.ops import unary_union

    with open(resolved_path) as f:
        gj = json.load(f)

    geoms = [shape(feat["geometry"]) for feat in gj["features"]]
    union = unary_union(geoms)

    if not union.is_valid:
        union = union.buffer(0)

    print(f"[inference_mask] Loaded {len(geoms)} mask features from {resolved_path}")
    print(f"[inference_mask] Union valid: {union.is_valid}, bounds: {union.bounds}")
    return union


# ---------------------------------------------------------------------------
# Per-tile suppression
# ---------------------------------------------------------------------------

def suppress_with_crop_mask(
    pred_mask: np.ndarray,
    tile_bbox,
    tile_crs,
    crop_mask_geom,
    tile_size: int = 256,
) -> np.ndarray:
    """
    Zero out predicted-positive pixels that fall within the DWR crop mask.

    The crop mask geometry is in EPSG:4326. If the tile CRS differs, the mask
    is reprojected to the tile CRS before rasterization.

    An early-exit check is performed: if the tile bbox does not intersect the
    mask at all, the prediction is returned unchanged with no rasterization cost.

    Args:
        pred_mask:     Numpy array of shape (1, H, W) or (H, W), binary float.
        tile_bbox:     TorchGeo BoundingBox (minx, miny, maxx, maxy) in tile_crs.
        tile_crs:      CRS of the tile (pyproj CRS, rasterio CRS, or EPSG int/str).
        crop_mask_geom: Shapely geometry in EPSG:4326 (from load_crop_mask).
        tile_size:     Pixel dimensions of the tile (assumed square).

    Returns:
        Suppressed mask as numpy array, same shape and dtype as pred_mask.
        Original array is not modified; a copy is returned only when suppression
        actually removes pixels.
    """
    from shapely.geometry import box as shapely_box
    from pyproj import CRS, Transformer
    from shapely.ops import transform as shp_transform
    from rasterio.features import rasterize as rio_rasterize
    import rasterio.transform

    # --- Normalize tile CRS ---
    wgs84 = CRS.from_epsg(4326)
    if isinstance(tile_crs, int):
        tile_crs_obj = CRS.from_epsg(tile_crs)
    elif isinstance(tile_crs, str):
        tile_crs_obj = CRS.from_string(tile_crs)
    else:
        try:
            tile_crs_obj = CRS.from_user_input(tile_crs)
        except Exception:
            tile_crs_obj = CRS.from_user_input(str(tile_crs))

    # --- Reproject mask to tile CRS (cached per CRS) ---
    mask_in_tile_crs = _reproject_mask(crop_mask_geom, wgs84, tile_crs_obj)

    # --- Early exit: bbox does not intersect mask ---
    tile_box = shapely_box(tile_bbox.minx, tile_bbox.miny, tile_bbox.maxx, tile_bbox.maxy)
    if not mask_in_tile_crs.intersects(tile_box):
        return pred_mask

    # --- Clip mask to tile extent ---
    mask_clipped = mask_in_tile_crs.intersection(tile_box)
    if mask_clipped.is_empty:
        return pred_mask

    # --- Rasterize to tile pixel grid ---
    affine = rasterio.transform.from_bounds(
        tile_bbox.minx, tile_bbox.miny,
        tile_bbox.maxx, tile_bbox.maxy,
        tile_size, tile_size,
    )

    raster_mask = rio_rasterize(
        [(mask_clipped, 1)],
        out_shape=(tile_size, tile_size),
        transform=affine,
        fill=0,
        dtype="uint8",
    )

    if not np.any(raster_mask):
        return pred_mask

    # --- Suppress pixels within the crop mask ---
    suppressed = pred_mask.copy()
    if suppressed.ndim == 3:
        suppressed[0][raster_mask == 1] = 0
    else:
        suppressed[raster_mask == 1] = 0

    return suppressed


@lru_cache(maxsize=16)
def _reproject_mask(mask_geom, src_crs, dst_crs):
    """
    Reproject a Shapely geometry from src_crs to dst_crs.
    Cached so the reprojection is only computed once per CRS pair per session.
    """
    from pyproj import Transformer
    from shapely.ops import transform as shp_transform

    if src_crs == dst_crs:
        return mask_geom

    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return shp_transform(transformer.transform, mask_geom)
