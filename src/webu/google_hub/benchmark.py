from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

from dataclasses import asdict, dataclass
from typing import Any

import aiohttp


@dataclass(frozen=True)
class BenchmarkSample:
    index: int
    query: str
    success: bool
    latency_ms: float
    backend: str = ""
    error: str = ""
    result_count: int = 0
    status_code: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass(frozen=True)
class BenchmarkSummary:
    total_requests: int
    concurrency: int
    success_count: int
    failure_count: int
    success_rate: float
    wall_time_ms: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    requests_per_second: float
    backend_counts: dict[str, int]
    samples: list[dict[str, Any]]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "success_rate": round(self.success_rate, 2),
            "wall_time_ms": round(self.wall_time_ms, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p50_latency_ms": round(self.p50_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "min_latency_ms": round(self.min_latency_ms, 1),
            "max_latency_ms": round(self.max_latency_ms, 1),
            "requests_per_second": round(self.requests_per_second, 2),
        }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(value) for value in values)
    rank = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    low = int(rank)
    high = min(len(ordered) - 1, low + 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def summarize_benchmark(
    samples: list[BenchmarkSample],
    *,
    concurrency: int,
    wall_time_ms: float,
) -> BenchmarkSummary:
    latencies = [sample.latency_ms for sample in samples]
    success_count = sum(1 for sample in samples if sample.success)
    failure_count = len(samples) - success_count
    backend_counts: dict[str, int] = {}
    for sample in samples:
        backend = sample.backend or "unknown"
        backend_counts[backend] = backend_counts.get(backend, 0) + 1

    errors = sorted({sample.error for sample in samples if sample.error})
    success_rate = (success_count / len(samples) * 100.0) if samples else 0.0
    requests_per_second = (
        (len(samples) / (wall_time_ms / 1000.0)) if wall_time_ms > 0 else 0.0
    )
    return BenchmarkSummary(
        total_requests=len(samples),
        concurrency=max(1, int(concurrency)),
        success_count=success_count,
        failure_count=failure_count,
        success_rate=success_rate,
        wall_time_ms=wall_time_ms,
        avg_latency_ms=(statistics.fmean(latencies) if latencies else 0.0),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        min_latency_ms=min(latencies) if latencies else 0.0,
        max_latency_ms=max(latencies) if latencies else 0.0,
        requests_per_second=requests_per_second,
        backend_counts=backend_counts,
        samples=[sample.to_dict() for sample in samples],
        errors=errors,
    )


async def run_manager_benchmark(
    manager,
    *,
    query: str,
    total_requests: int,
    concurrency: int,
    num: int = 10,
    lang: str = "en",
) -> BenchmarkSummary:
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    samples: list[BenchmarkSample] = []

    async def _run_once(index: int):
        async with semaphore:
            started = time.perf_counter()
            try:
                payload = await manager.search(query=query, num=num, lang=lang)
                samples.append(
                    BenchmarkSample(
                        index=index,
                        query=query,
                        success=bool(payload.get("success", True)),
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        backend=str(payload.get("backend", "")),
                        error=str(payload.get("error", "")),
                        result_count=int(payload.get("result_count", 0)),
                        status_code=200,
                    )
                )
            except Exception as exc:
                samples.append(
                    BenchmarkSample(
                        index=index,
                        query=query,
                        success=False,
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        error=str(exc),
                        status_code=500,
                    )
                )

    started = time.perf_counter()
    await asyncio.gather(*[_run_once(index) for index in range(total_requests)])
    return summarize_benchmark(
        sorted(samples, key=lambda item: item.index),
        concurrency=concurrency,
        wall_time_ms=(time.perf_counter() - started) * 1000.0,
    )


async def run_http_benchmark(
    *,
    base_url: str,
    query: str,
    total_requests: int,
    concurrency: int,
    num: int = 10,
    lang: str = "en",
    api_token: str = "",
    timeout_sec: int = 90,
) -> BenchmarkSummary:
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    samples: list[BenchmarkSample] = []
    timeout = aiohttp.ClientTimeout(total=max(1, int(timeout_sec)))
    headers = {"X-Api-Token": api_token} if api_token else {}
    normalized_base_url = base_url.rstrip("/")

    async with aiohttp.ClientSession(timeout=timeout) as session:

        async def _run_once(index: int):
            async with semaphore:
                started = time.perf_counter()
                try:
                    async with session.get(
                        f"{normalized_base_url}/search",
                        params={"q": query, "num": num, "lang": lang},
                        headers=headers or None,
                    ) as response:
                        payload: dict[str, Any] = {}
                        try:
                            payload = await response.json(content_type=None)
                        except Exception:
                            text = await response.text()
                            payload = {"error": text.strip()}

                        samples.append(
                            BenchmarkSample(
                                index=index,
                                query=query,
                                success=response.status < 400
                                and bool(payload.get("success", True)),
                                latency_ms=(time.perf_counter() - started) * 1000.0,
                                backend=str(payload.get("backend", "")),
                                error=str(payload.get("error", "")),
                                result_count=int(payload.get("result_count", 0)),
                                status_code=int(response.status),
                            )
                        )
                except Exception as exc:
                    samples.append(
                        BenchmarkSample(
                            index=index,
                            query=query,
                            success=False,
                            latency_ms=(time.perf_counter() - started) * 1000.0,
                            error=str(exc),
                            status_code=0,
                        )
                    )

        started = time.perf_counter()
        await asyncio.gather(*[_run_once(index) for index in range(total_requests)])

    return summarize_benchmark(
        sorted(samples, key=lambda item: item.index),
        concurrency=concurrency,
        wall_time_ms=(time.perf_counter() - started) * 1000.0,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark google_hub or compatible /search endpoints"
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--query", default="test")
    parser.add_argument("--requests", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--num", type=int, default=5)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--api-token", default="")
    parser.add_argument("--timeout-sec", type=int, default=90)
    args = parser.parse_args()

    summary = asyncio.run(
        run_http_benchmark(
            base_url=args.base_url,
            query=args.query,
            total_requests=max(1, int(args.requests)),
            concurrency=max(1, int(args.concurrency)),
            num=max(1, int(args.num)),
            lang=args.lang,
            api_token=str(args.api_token).strip(),
            timeout_sec=max(1, int(args.timeout_sec)),
        )
    )
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
