#!/usr/bin/env python3
"""Stress-test direct raster window reads from signed Planetary Computer URLs.

This is intentionally a spike artifact. It benchmarks the I/O side of a future
GPU inference worker by reading random fixed-size windows from signed NAIP COG
assets through Rasterio/GDAL HTTP range requests.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import planetary_computer
import pystac
import rasterio
from pystac_client import Client
from rasterio.windows import Window


REPO = Path(__file__).resolve().parents[3]
COUNTY_KML = REPO / "data-to-import/calaveras-county/boundary/COUNTY_BOUNDARY.kml"
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


@dataclass(frozen=True)
class TimedRead:
    item_id: str
    window: tuple[int, int, int, int]
    seconds: float
    payload_mb: float

    @property
    def mbps(self) -> float:
        return self.payload_mb / self.seconds if self.seconds else math.inf


def read_kml_bbox(path: Path) -> list[float]:
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
    return [min(xs), min(ys), max(xs), max(ys)]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((pct / 100) * len(ordered)) - 1))
    return ordered[idx]


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {
        "min": min(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "max": max(values),
    }


def search_naip_items(year: int, bbox: list[float], limit: int) -> list[Any]:
    client = Client.open(PC_STAC)
    search = client.search(
        collections=["naip"],
        bbox=bbox,
        datetime=f"{year}-01-01/{year}-12-31",
        limit=limit,
    )
    return list(search.items())


def fetch_naip_item(item_id: str) -> Any:
    url = f"{PC_STAC}/collections/naip/items/{item_id}"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.load(response)
    return pystac.Item.from_dict(data)


def content_length_mb(url: str, timeout: int = 30) -> float | None:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
    except Exception:
        return None
    if not length:
        return None
    return int(length) / 1024 / 1024


def random_window(width: int, height: int, size: int, rng: random.Random) -> Window:
    if width < size or height < size:
        raise ValueError(f"raster is smaller than requested window size {size}")
    col = rng.randint(0, width - size)
    row = rng.randint(0, height - size)
    return Window(col, row, size, size)


def scan_windows(width: int, height: int, size: int, stride: int) -> list[Window]:
    windows: list[Window] = []
    for row in range(0, max(1, height - size + 1), stride):
        for col in range(0, max(1, width - size + 1), stride):
            windows.append(Window(col, row, size, size))
    return windows


def benchmark_windows(
    width: int,
    height: int,
    size: int,
    reads: int,
    pattern: str,
    stride: int,
    rng: random.Random,
) -> list[Window]:
    if pattern == "random":
        return [random_window(width, height, size, rng) for _ in range(reads)]
    windows = scan_windows(width, height, size, stride)
    if len(windows) < reads:
        repeats = math.ceil(reads / len(windows))
        windows = windows * repeats
    return windows[:reads]


def benchmark_item(
    item: Any,
    asset_key: str,
    window_size: int,
    reads: int,
    warmup_reads: int,
    pattern: str,
    stride: int,
    allow_unsigned_fallback: bool,
    rng: random.Random,
) -> dict[str, Any]:
    href = item.assets[asset_key].href
    signed = False
    sign_error = None
    try:
        href = planetary_computer.sign_url(href)
        signed = True
    except Exception as exc:
        sign_error = f"{type(exc).__name__}: {exc}"
        if not allow_unsigned_fallback:
            raise

    open_start = time.perf_counter()
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
        VSI_CACHE="TRUE",
        VSI_CACHE_SIZE=50_000_000,
    ):
        with rasterio.open(href) as src:
            open_seconds = time.perf_counter() - open_start
            shape = {
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "dtype": src.dtypes[0],
                "crs": str(src.crs),
            }

            warmup_timings: list[float] = []
            warmups = benchmark_windows(
                src.width, src.height, window_size, warmup_reads, pattern, stride, rng
            )
            windows = benchmark_windows(
                src.width, src.height, window_size, reads, pattern, stride, rng
            )

            for window in warmups:
                start = time.perf_counter()
                _ = src.read(window=window)
                warmup_timings.append(time.perf_counter() - start)

            timed_reads: list[TimedRead] = []
            for window in windows:
                start = time.perf_counter()
                data = src.read(window=window)
                seconds = time.perf_counter() - start
                payload_mb = data.nbytes / 1024 / 1024
                timed_reads.append(
                    TimedRead(
                        item_id=item.id,
                        window=(
                            int(window.col_off),
                            int(window.row_off),
                            int(window.width),
                            int(window.height),
                        ),
                        seconds=seconds,
                        payload_mb=payload_mb,
                    )
                )

    seconds = [read.seconds for read in timed_reads]
    mbps = [read.mbps for read in timed_reads]
    chips_per_second = 1 / statistics.fmean(seconds) if seconds else 0
    return {
        "item_id": item.id,
        "signed": signed,
        "sign_error": sign_error,
        "href_content_length_mb": content_length_mb(href),
        "open_seconds": open_seconds,
        "shape": shape,
        "warmup_seconds": summarize(warmup_timings),
        "read_seconds": summarize(seconds),
        "read_mbps": summarize(mbps),
        "chips_per_second_per_worker": chips_per_second,
        "payload_mb_per_window": timed_reads[0].payload_mb if timed_reads else None,
        "sample_windows": [
            {
                "window": read.window,
                "seconds": read.seconds,
                "mbps": read.mbps,
            }
            for read in timed_reads[:5]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2016)
    parser.add_argument("--items", type=int, default=1)
    parser.add_argument(
        "--item-id",
        action="append",
        default=[],
        help="Known NAIP STAC item ID. May be repeated. Skips STAC search.",
    )
    parser.add_argument("--asset-key", default="image")
    parser.add_argument("--window-size", type=int, default=256)
    parser.add_argument("--stride", type=int, default=None)
    parser.add_argument(
        "--pattern",
        choices=["random", "scan"],
        default="random",
        help="Random windows stress latency; scan windows approximate tiled inference locality.",
    )
    parser.add_argument("--reads-per-item", type=int, default=25)
    parser.add_argument("--warmup-reads", type=int, default=3)
    parser.add_argument(
        "--allow-unsigned-fallback",
        action="store_true",
        help="Continue with the raw asset href if Planetary Computer SAS signing fails.",
    )
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument(
        "--gpu-ms-per-window",
        type=float,
        default=25.0,
        help="Assumed model inference time per chip for starvation comparison.",
    )
    args = parser.parse_args()

    bbox = read_kml_bbox(COUNTY_KML)
    if args.item_id:
        items = [fetch_naip_item(item_id) for item_id in args.item_id]
    else:
        items = search_naip_items(args.year, bbox, args.items)
    if not items:
        raise RuntimeError(f"no NAIP items found for {args.year} and bbox {bbox}")

    rng = random.Random(args.seed)
    stride = args.stride or args.window_size
    started = time.perf_counter()
    item_results = [
        benchmark_item(
            item=item,
            asset_key=args.asset_key,
            window_size=args.window_size,
            reads=args.reads_per_item,
            warmup_reads=args.warmup_reads,
            pattern=args.pattern,
            stride=stride,
            allow_unsigned_fallback=args.allow_unsigned_fallback,
            rng=rng,
        )
        for item in items
    ]
    elapsed = time.perf_counter() - started

    read_means = [
        result["read_seconds"]["mean"]
        for result in item_results
        if result.get("read_seconds")
    ]
    mean_read_seconds = statistics.fmean(read_means) if read_means else 0
    assumed_gpu_seconds = args.gpu_ms_per_window / 1000
    bottleneck = (
        "remote_read"
        if mean_read_seconds > assumed_gpu_seconds
        else "gpu_or_postprocess"
    )

    print(
        json.dumps(
            {
                "benchmark": "pc_signed_url_read_benchmark",
                "year": args.year,
                "county_bbox_wgs84": bbox,
                "items_requested": args.items,
                "items_returned": len(items),
                "window_size": args.window_size,
                "stride": stride,
                "pattern": args.pattern,
                "reads_per_item": args.reads_per_item,
                "warmup_reads": args.warmup_reads,
                "elapsed_seconds": elapsed,
                "assumed_gpu_ms_per_window": args.gpu_ms_per_window,
                "mean_remote_read_ms": mean_read_seconds * 1000,
                "bottleneck_guess": bottleneck,
                "items": item_results,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
