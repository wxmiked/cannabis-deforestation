# County Inference GCP Spike

## Verdict: PARTIAL

Question: Can the current bbox notebook be reduced to a smallest practical, county-scale, resumable GCP worker path for Calaveras County NAIP inference without building the production pipeline yet?

Short answer: yes for the architecture, but not runnable end-to-end in this checkout. The repo has enough notebook logic to define the production slice, the county KML can be parsed and bounded, and Planetary Computer STAC can be dry-run without downloads. Local execution is blocked by missing geospatial/model dependencies and absent model weights.

## Minimal Production Slice

Build a CLI around one shard:

```text
county-infer shard \
  --year 2016 \
  --county data-to-import/calaveras-county/boundary/COUNTY_BOUNDARY.kml \
  --item-id <planetary-computer-naip-item-id> \
  --asset image \
  --window <pixel-window-or-projected-bounds> \
  --weights models/cannabis-cultivation-deeplabv3plus-resnet50-naip.pth \
  --out gs://.../year=2016/item=<id>/window=<id>/
```

The worker should process one NAIP source asset plus one AOI/window shard, emit resumable outputs, and never assume the entire county or all tiles fit in memory. A separate planner should intersect county polygon with 2016 NAIP STAC items, create projected windows, and enqueue one shard per window.

Core logic to extract from `notebooks/04-search-cannabis-in-bbox.ipynb`:

- STAC search against Microsoft Planetary Computer NAIP.
- Asset signing before reads.
- Model definition: `smp.DeepLabV3Plus(encoder_name="resnext50_32x4d", encoder_weights="imagenet", in_channels=5, classes=1)`.
- RGB+NIR to RGB+NIR+NDVI preprocessing with `AppendNDVI(index_red=0, index_nir=3)`.
- Training normalization: `[0.485, 0.456, 0.406, 0.5, 0.0]` / `[0.229, 0.224, 0.225, 0.2, 1.0]`.
- Windowed inference over 256 px tiles.
- Mask-to-polygons export in georeferenced coordinates.

## Commands Run And Key Outputs

```bash
python3 --version
# Python 3.11.2
```

```bash
python3 - <<'PY'
mods=['geopandas','fiona','pyogrio','shapely','rasterio','pystac_client','planetary_computer','nbformat','torch','segmentation_models_pytorch']
...
PY
# all checked modules failed with ModuleNotFoundError in this environment
```

```bash
find . -maxdepth 2 -type d -name '.venv' -o -name 'venv'
# no repo virtualenv found
```

```bash
python3 .tmp/openclaw-spikes/county-inference-gcp/county_inference_probe.py --stac --year 2016 --limit 5
```

Key output:

```json
{
  "county_bbox_wgs84": [-120.995648855096, 37.8329109673909, -120.017854911053, 38.5098799454128],
  "county_coord_count": 7752,
  "weights_present": false,
  "stac": {
    "returned": 5,
    "ids": [
      "ca_m_3812040_nw_10_.6_20160802_20161004",
      "ca_m_3812040_ne_10_.6_20160802_20161004",
      "ca_m_3812032_sw_10_.6_20160802_20161004"
    ],
    "asset_keys_first": ["image", "metadata", "rendered_preview", "thumbnail", "tilejson"]
  }
}
```

```bash
find cannabis-parcels/cannabis-parcels-masked -maxdepth 1 -type f -name '*.tif' | wc -l
# 215
find cannabis-parcels/cannabis-parcels-masked -maxdepth 1 -type f -name '*.json' | wc -l
# 158
```

```bash
find . -maxdepth 4 -type f \( -name '*.pth' -o -name '*.ckpt' -o -name '*.pt' \)
# no model weight files found
```

## What Worked

- KML boundary can be parsed with Python stdlib, avoiding a hard dependency on local GDAL/KML support for simple bbox derivation.
- County WGS84 bbox derived cleanly from 7,752 KML coordinates.
- Planetary Computer STAC `/search` works with plain HTTP POST and returns 2016 NAIP items for the county bbox without auth or package installs.
- Notebook 04 has all required conceptual pieces for a shard worker: STAC search/download, TorchGeo raster dataset, grid sampler, model load, preprocessing, streaming inference, and KML polygon export.
- Model README identifies the expected weights path and Zenodo source.

## Gotchas / Surprises

- No `.venv` exists and the system Python lacks every required runtime dependency checked: `geopandas`, `fiona`, `pyogrio`, `shapely`, `rasterio`, `pystac_client`, `planetary_computer`, `torch`, `torchgeo`, `segmentation_models_pytorch`, and `simplekml`.
- `ogrinfo`, `ogr2ogr`, and `gdalinfo` are not on PATH, so GDAL-based KML validation is not available locally.
- Model weights are not present at `models/cannabis-cultivation-deeplabv3plus-resnet50-naip.pth`.
- Notebook 04 downloads full NAIP item TIFFs before sampling. That is the wrong production shape for GCP: county-scale should stream/read windows from signed assets or stage assets intentionally.
- The notebook uses bbox as the AOI. County-scale planning needs polygon intersection, otherwise bbox shards include substantial non-county area.
- The notebook currently mixes concerns: model setup, STAC discovery, downloading, sampling, inference, visualization, and KML writing. A worker should only own one shard and write machine-readable output.
- The Zenodo/model README says the training/inference notebook is `notebooks/cannabis-segmentation-torchgeo.ipynb`, but the actual path in this repo is `notebooks/03-cannabis-segmentation-torchgeo.ipynb`.

## Stressed Failure Mode

Failure mode: local geospatial stack and KML support are absent.

Result: production code cannot rely on this checkout's system Python or PATH for `geopandas.read_file(KML)`, `rasterio`, or GDAL CLI tools. The spike worked around only the simplest case, bbox extraction, with `xml.etree.ElementTree`. That is acceptable for planning metadata, but not enough for polygon-window intersection or raster masking.

Implication: the production worker image needs an explicit pinned environment with Rasterio/GDAL/Fiona or Pyogrio/Shapely support, plus a startup self-check that verifies KML/vector reads, raster window reads from signed Planetary Computer assets, model import, and weights presence before accepting shard work.

## Questions For Skipper

- Should outputs be KML/GeoJSON polygons, raster masks/probability tiles, or both?
- Should the GCP worker read signed Planetary Computer URLs directly, or should the planner stage NAIP assets to GCS first for resumability and egress control?
- What threshold/min-area policy should become the default? Notebook values vary between `0.3`, `0.5`, and `0.7`.
- Is 2016 the only first production target, or should the planner schema include `year` from day one for 2014/2018 parity?
- Should model weights be baked into the worker image, fetched at startup from Zenodo/GCS, or mounted as a GCS artifact?

## Recommended Next Production Step

Create a production CLI skeleton with two commands:

- `plan-county`: read county polygon, query NAIP STAC for a year, intersect items with the county polygon, emit a shard manifest.
- `run-shard`: consume one manifest row, load weights, read one signed asset window, append NDVI, normalize, run model, polygonize detections, and write outputs plus a status JSON.

Start with one NAIP item and one 256 px or 512 px window that intersects the county polygon. Add a container/dev environment check before expanding to full county orchestration.

## Files Changed / Created

- `.tmp/openclaw-spikes/county-inference-gcp/README.md`
- `.tmp/openclaw-spikes/county-inference-gcp/county_inference_probe.py`
- `.tmp/openclaw-spikes/county-inference-gcp/notebook-04-code-extract.py`
