# Results

## Verdict: PARTIAL

Question: Can a worker read NAIP inference windows directly from signed Planetary Computer URLs fast enough that GPU compute is likely to be the bottleneck?

Evidence from this OpenClaw host says: not confidently. Spatially local scan reads can be decent after GDAL/VSI cache warms up, but random window reads are much slower than plausible GPU inference time. Production should repeat this benchmark from the target GCP region before choosing direct Planetary Computer reads over staging assets into GCS or local scratch.

## Environment

- Repo venv: `.venv`
- Installed benchmark deps: `rasterio`, `planetary-computer`, `pystac-client`, `requests`, `numpy`
- Test item: `ca_m_3812040_nw_10_.6_20160802_20161004`
- Raster: 9,970 x 12,360, 4 bands, `uint8`, EPSG:26910
- Asset size from `Content-Length`: about 441 MB

## Measurements

Command:

```bash
.venv/bin/python .tmp/openclaw-spikes/pc-signed-url-read-benchmark/pc_signed_url_read_benchmark.py \
  --item-id ca_m_3812040_nw_10_.6_20160802_20161004 \
  --window-size 256 \
  --pattern random \
  --reads-per-item 10 \
  --warmup-reads 2 \
  --gpu-ms-per-window 25
```

Result:

- Mean remote read: 336 ms per 256 px chip
- Median remote read: 366 ms
- Throughput: about 3.0 chips/sec per worker
- Bottleneck guess: remote read

Command:

```bash
.venv/bin/python .tmp/openclaw-spikes/pc-signed-url-read-benchmark/pc_signed_url_read_benchmark.py \
  --item-id ca_m_3812040_nw_10_.6_20160802_20161004 \
  --window-size 256 \
  --pattern scan \
  --reads-per-item 50 \
  --warmup-reads 5 \
  --gpu-ms-per-window 25
```

Result:

- Mean remote read: 50 ms per 256 px chip
- Median remote read: below 1 ms, due to locality/cache
- P95 remote read: 598 ms
- Throughput: about 20 chips/sec per worker
- Bottleneck guess: remote read, if model inference is around 25 ms/chip

Command:

```bash
.venv/bin/python .tmp/openclaw-spikes/pc-signed-url-read-benchmark/pc_signed_url_read_benchmark.py \
  --item-id ca_m_3812040_nw_10_.6_20160802_20161004 \
  --window-size 512 \
  --pattern random \
  --reads-per-item 10 \
  --warmup-reads 2 \
  --gpu-ms-per-window 40 \
  --allow-unsigned-fallback
```

Result:

- Mean remote read: 378 ms per 512 px chip
- Median remote read: 395 ms
- Throughput: about 2.6 chips/sec per worker
- Bottleneck guess: remote read

Command:

```bash
.venv/bin/python .tmp/openclaw-spikes/pc-signed-url-read-benchmark/pc_signed_url_read_benchmark.py \
  --item-id ca_m_3812040_nw_10_.6_20160802_20161004 \
  --window-size 512 \
  --pattern scan \
  --reads-per-item 50 \
  --warmup-reads 5 \
  --gpu-ms-per-window 40 \
  --allow-unsigned-fallback
```

Result:

- Mean remote read: 144 ms per 512 px chip
- Median remote read: 6.5 ms, due to locality/cache
- P95 remote read: 683 ms
- Throughput: about 7.0 chips/sec per worker
- Bottleneck guess: remote read

## Gotchas

- Planetary Computer STAC search returned `rate limit` during the first benchmark attempt.
- Later item metadata fetches also returned HTTP 403 while testing multiple item IDs.
- SAS signing briefly returned HTTP 403 from the Planetary Computer token endpoint, although retrying later succeeded.
- The NAIP blob tested was publicly readable without SAS signing. That is useful, but production should still treat STAC discovery and token signing as shared planner concerns, not per-window worker concerns.
- Scan-mode medians are misleadingly fast because GDAL/VSI cache and COG internal tiling help heavily once adjacent data is fetched. Random reads better expose latency risk.

## Recommendation

For the first production design, do not let every GPU worker independently spam Planetary Computer STAC or SAS endpoints. Have the planner resolve item IDs and asset hrefs once, persist a manifest, and pass workers exact asset URLs.

Direct remote window reads may be acceptable for a CPU-only dry run or a low-parallelism first pass, but for GPU inference I would prefer staging each NAIP asset to GCS or worker-local scratch unless a GCP-region benchmark shows much better read latency. Expensive GPU idle time is a deeply silly way to save a few minutes of staging.
