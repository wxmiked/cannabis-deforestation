# Planetary Computer Signed URL Read Benchmark

## Question

Can a GCP worker read NAIP windows directly from signed Planetary Computer URLs fast enough that GPU inference is likely to remain the bottleneck?

## Run

```bash
.venv/bin/python .tmp/openclaw-spikes/pc-signed-url-read-benchmark/pc_signed_url_read_benchmark.py \
  --year 2016 \
  --items 1 \
  --window-size 256 \
  --reads-per-item 25 \
  --warmup-reads 3 \
  --gpu-ms-per-window 25 \
  --allow-unsigned-fallback
```

Increase stress with more items or larger windows:

```bash
.venv/bin/python .tmp/openclaw-spikes/pc-signed-url-read-benchmark/pc_signed_url_read_benchmark.py \
  --year 2016 \
  --items 3 \
  --window-size 512 \
  --reads-per-item 50 \
  --warmup-reads 5 \
  --gpu-ms-per-window 25 \
  --allow-unsigned-fallback
```

Use scan mode to approximate normal tiled inference locality:

```bash
.venv/bin/python .tmp/openclaw-spikes/pc-signed-url-read-benchmark/pc_signed_url_read_benchmark.py \
  --item-id ca_m_3812040_nw_10_.6_20160802_20161004 \
  --window-size 256 \
  --pattern scan \
  --reads-per-item 100 \
  --warmup-reads 5 \
  --gpu-ms-per-window 25
```

If STAC search is rate-limited, use known item IDs from a prior planner run:

```bash
.venv/bin/python .tmp/openclaw-spikes/pc-signed-url-read-benchmark/pc_signed_url_read_benchmark.py \
  --item-id ca_m_3812040_nw_10_.6_20160802_20161004 \
  --window-size 256 \
  --reads-per-item 25 \
  --warmup-reads 3 \
  --gpu-ms-per-window 25 \
  --allow-unsigned-fallback
```

## Notes

- This measures Rasterio/GDAL HTTP range reads against signed NAIP COG assets.
- It does not run the actual segmentation model.
- `--gpu-ms-per-window` is a comparison knob. If mean remote read latency is above the assumed GPU time, direct remote reads are likely to starve the GPU.
- Benchmark results depend heavily on where the worker runs. Results from this OpenClaw host are useful for feasibility, but the production decision should be repeated from the target GCP region.
