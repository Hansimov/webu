from webu.fastapis.request_metrics import (
    RequestMetrics,
    format_dashboard_timestamp,
    format_dashboard_timezone,
)


def test_request_metrics_snapshot_keeps_history():
    metrics = RequestMetrics(history_limit=4)

    metrics.record(120.0, True)
    metrics.record(240.0, False)

    snapshot = metrics.snapshot()

    assert snapshot.accepted_requests == 2
    assert snapshot.successful_requests == 1
    assert snapshot.failed_requests == 1
    assert snapshot.history
    assert snapshot.history[-1]["accepted_requests"] == 2
    assert snapshot.history[-1]["successful_requests"] == 1
    assert snapshot.history[-1]["last_latency_ms"] == 240.0


def test_dashboard_timestamp_uses_shanghai_timezone():
    assert format_dashboard_timestamp(0) == "1970-01-01 08:00:00"
    assert format_dashboard_timezone() == "UTC+08 Shanghai"
