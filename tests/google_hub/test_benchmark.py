import asyncio

from webu.google_hub.benchmark import (
    BenchmarkSample,
    run_manager_benchmark,
    summarize_benchmark,
)


class _FakeManager:
    def __init__(self):
        self._counter = 0

    async def search(self, *, query: str, num: int, lang: str):
        self._counter += 1
        current = self._counter
        await asyncio.sleep(0.005 if current % 2 else 0.01)
        backend = "fast-a" if current % 2 else "fast-b"
        return {
            "success": True,
            "backend": backend,
            "query": query,
            "result_count": num,
            "results": [{"title": query, "url": "https://example.com"}],
        }


def test_summarize_benchmark_calculates_distribution_and_percentiles():
    summary = summarize_benchmark(
        [
            BenchmarkSample(
                index=0,
                query="q",
                success=True,
                latency_ms=100.0,
                backend="a",
                result_count=2,
                status_code=200,
            ),
            BenchmarkSample(
                index=1,
                query="q",
                success=False,
                latency_ms=250.0,
                backend="b",
                error="timeout",
                status_code=502,
            ),
            BenchmarkSample(
                index=2,
                query="q",
                success=True,
                latency_ms=140.0,
                backend="a",
                result_count=2,
                status_code=200,
            ),
        ],
        concurrency=3,
        wall_time_ms=400.0,
    )

    data = summary.to_dict()
    assert data["total_requests"] == 3
    assert data["success_count"] == 2
    assert data["failure_count"] == 1
    assert data["backend_counts"] == {"a": 2, "b": 1}
    assert data["p95_latency_ms"] >= data["p50_latency_ms"]
    assert data["requests_per_second"] == 7.5


def test_run_manager_benchmark_supports_concurrency():
    summary = asyncio.run(
        run_manager_benchmark(
            _FakeManager(),
            query="openai",
            total_requests=6,
            concurrency=3,
            num=3,
            lang="en",
        )
    )

    data = summary.to_dict()
    assert data["total_requests"] == 6
    assert data["success_count"] == 6
    assert data["concurrency"] == 3
    assert set(data["backend_counts"]) == {"fast-a", "fast-b"}
    assert len(data["samples"]) == 6
