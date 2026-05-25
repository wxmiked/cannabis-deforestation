# County Inference CLI

Issue #37 turns the bounding-box inference notebook into a county-scale,
resumable pipeline for Calaveras County NAIP imagery.

The first implementation slice is deliberately small:

1. Plan the 2016 NAIP source items that intersect the Calaveras County bbox.
2. Persist those STAC item asset URLs in a manifest.
3. Download source assets from the manifest with skip/resume behavior.
4. Smoke-test one shard output directory before model/window inference exists.

## Plan 2016 NAIP Items

```bash
county-infer plan-county \
  --year 2016 \
  --county data-to-import/calaveras-county/boundary/COUNTY_BOUNDARY.kml \
  --out results/inference/calaveras-county/2016/manifest.json
```

The county bbox is only for Planetary Computer STAC discovery. Worker code must
still use the actual county polygon when deciding which raster windows to run.
Otherwise the pipeline processes non-county bbox area, which is how innocent
GPUs end up doing busywork. Tragic, preventable busywork.

## Download NAIP Assets

Dry-run all planned downloads first:

```bash
county-infer download-assets \
  --manifest results/inference/calaveras-county/2016/manifest.json \
  --out-dir data-to-import/microsoft/naip/calaveras-county \
  --dry-run
```

Download all planned 2016 source assets:

```bash
county-infer download-assets \
  --manifest results/inference/calaveras-county/2016/manifest.json \
  --out-dir data-to-import/microsoft/naip/calaveras-county
```

Existing files are skipped unless `--overwrite` is supplied.

## Smoke-Test One Shard

```bash
county-infer run-shard \
  --manifest results/inference/calaveras-county/2016/manifest.json \
  --shard-id 0 \
  --out results/inference/calaveras-county/2016/shards/shard-0000 \
  --dry-run
```

This writes `status.json` and an empty `detections.geojson`. Real model
inference, polygon-window intersection, and partial detection outputs are the
next layer.

## GCP Direction

Terraform should eventually create:

- a Cloud Storage bucket for manifests, staged NAIP assets, model weights,
  partial shard outputs, and merged outputs
- Artifact Registry for the inference container
- Cloud Batch job definitions or IAM/service-account plumbing for the launcher
- enough IAM for workers to read staged assets and write shard outputs

The local CLI is intentionally shaped around paths and manifests that can later
map cleanly to `gs://...` locations.
