from __future__ import annotations

from pathlib import Path

from webu.cf_tunnel.operations import guard_tunnel_quality, stabilize_tunnel


def _access_payload(
    hostname: str,
    *,
    system_ok: bool,
    cloudflare_ok: bool,
    authoritative_ok: bool,
    mismatch: bool = False,
    recursive_mismatch: bool = False,
) -> dict:
    def _probe(ip_address: str, success: bool) -> dict:
        payload = {"ip": ip_address, "success": success}
        if success:
            payload["status_code"] = 200
        return payload

    return {
        "hostname": hostname,
        "tunnel_name": hostname,
        "dns": {
            "mismatch": mismatch,
            "recursive_mismatch": recursive_mismatch,
        },
        "https": {
            "system_resolver": [_probe("203.0.113.10", system_ok)],
            "cloudflare_doh": [_probe("198.51.100.10", cloudflare_ok)],
            "cloudflare_authoritative_ns": [_probe("198.51.100.11", authoritative_ok)],
        },
    }


def test_stabilize_tunnel_reapplies_baseline_and_captures_snapshot(monkeypatch):
    status_payloads = iter(
        [
            {"status": "down", "connections": []},
            {"status": "healthy", "connections": [{"id": "conn-1"}]},
        ]
    )
    access_payloads = iter(
        [
            _access_payload(
                "dev.blbl.top",
                system_ok=False,
                cloudflare_ok=False,
                authoritative_ok=False,
            ),
            _access_payload(
                "dev.blbl.top",
                system_ok=True,
                cloudflare_ok=True,
                authoritative_ok=True,
            ),
        ]
    )
    apply_calls: list[dict] = []

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.tunnel_status",
        lambda tunnel_name=None, cf_token_mode="auto": next(status_payloads),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: next(access_payloads),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.apply_tunnel",
        lambda **kwargs: apply_calls.append(kwargs)
        or [{"tunnel_name": kwargs["tunnel_name"], "verification": {}}],
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.snapshot.capture_canary_snapshot",
        lambda **kwargs: {
            "snapshot_label": "snap-1",
            "output_dir": "/tmp/snap-1",
            "snapshots": [
                {
                    "hostname": "dev.blbl.top",
                    "recommended_prefer_family": "ipv4",
                    "reason_codes": ["status_down"],
                    "top_candidates": [{"ip": "198.51.100.10"}],
                    "operator_shortcuts": {"first_round_strategy": "ipv4-first"},
                }
            ],
        },
    )

    result = stabilize_tunnel(
        tunnel_name="dev.blbl.top",
        hostname="dev.blbl.top",
        cf_token_mode="auto",
        prefer_family="any",
        max_candidates=2,
        install_service=True,
        save_config=True,
        capture_snapshot=True,
        snapshot_output_dir=Path("debugs/cf-tunnel-snapshots"),
    )

    assert len(apply_calls) == 1
    assert apply_calls[0]["install_service"] is True
    assert apply_calls[0]["save_config"] is True
    assert result["action_taken"] == "reapply_baseline"
    assert result["repaired"] is True
    assert result["snapshot"]["snapshot_label"] == "snap-1"


def test_stabilize_tunnel_avoids_reapply_for_dns_drift(monkeypatch):
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.tunnel_status",
        lambda tunnel_name=None, cf_token_mode="auto": {
            "status": "healthy",
            "connections": [{"id": "conn-1"}],
        },
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: _access_payload(
            "dev.blbl.top",
            system_ok=False,
            cloudflare_ok=True,
            authoritative_ok=True,
            mismatch=True,
            recursive_mismatch=True,
        ),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.apply_tunnel",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected reapply")),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.snapshot.capture_canary_snapshot",
        lambda **kwargs: {
            "snapshot_label": "snap-drift",
            "output_dir": "/tmp/snap-drift",
            "snapshots": [
                {
                    "hostname": "dev.blbl.top",
                    "recommended_prefer_family": "ipv4",
                    "reason_codes": ["dns_mismatch"],
                    "top_candidates": [{"ip": "198.51.100.10"}],
                    "operator_shortcuts": {"first_round_strategy": "ipv4-first"},
                }
            ],
        },
    )

    result = stabilize_tunnel(
        tunnel_name="dev.blbl.top",
        hostname="dev.blbl.top",
        cf_token_mode="auto",
        prefer_family="any",
        max_candidates=2,
        install_service=True,
        save_config=True,
        capture_snapshot=True,
        snapshot_output_dir=Path("debugs/cf-tunnel-snapshots"),
    )

    assert result["action_taken"] == "snapshot_only"
    assert result["repaired"] is False
    assert result["snapshot"]["snapshot_label"] == "snap-drift"


def test_stabilize_tunnel_records_snapshot_error_without_raising(monkeypatch):
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.tunnel_status",
        lambda tunnel_name=None, cf_token_mode="auto": {
            "status": "healthy",
            "connections": [{"id": "conn-1"}],
        },
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: _access_payload(
            "dev.blbl.top",
            system_ok=False,
            cloudflare_ok=True,
            authoritative_ok=True,
            mismatch=True,
        ),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.snapshot.capture_canary_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("snapshot failed")),
    )

    result = stabilize_tunnel(
        tunnel_name="dev.blbl.top",
        hostname="dev.blbl.top",
        cf_token_mode="auto",
        prefer_family="any",
        max_candidates=2,
        install_service=True,
        save_config=True,
        capture_snapshot=True,
        snapshot_output_dir=Path("debugs/cf-tunnel-snapshots"),
    )

    assert result["action_taken"] == "snapshot_only"
    assert result["snapshot"] == {}
    assert result["snapshot_error"] == "RuntimeError: snapshot failed"


def test_guard_tunnel_quality_triggers_stabilize_after_threshold(monkeypatch):
    status_payloads = iter(
        [
            {"status": "down", "connections": []},
            {"status": "down", "connections": []},
        ]
    )
    time_values = iter([0.0, 60.0])
    stabilize_calls: list[dict] = []
    events: list[dict] = []

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.tunnel_status",
        lambda tunnel_name=None, cf_token_mode="auto": next(status_payloads),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: _access_payload(
            "dev.blbl.top",
            system_ok=False,
            cloudflare_ok=False,
            authoritative_ok=False,
        ),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.stabilize_tunnel",
        lambda **kwargs: stabilize_calls.append(kwargs)
        or {
            "action_taken": "reapply_baseline",
            "healthy_now": True,
            "snapshot": {},
            "post_decision": {"action": "observe"},
            "post_status": {
                "status": "healthy",
                "active_connections": 1,
                "healthy": True,
                "reason_codes": ["healthy"],
            },
        },
    )

    result = guard_tunnel_quality(
        tunnel_name="dev.blbl.top",
        hostname="dev.blbl.top",
        cf_token_mode="auto",
        interval_seconds=1,
        failure_threshold=2,
        cooldown_seconds=300,
        snapshot_interval_seconds=0,
        prefer_family="any",
        max_candidates=2,
        install_service=True,
        save_config=True,
        snapshot_output_dir=Path("debugs/cf-tunnel-snapshots"),
        iterations=2,
        history_limit=10,
        emit_event=events.append,
        sleep_fn=lambda _seconds: None,
        time_fn=lambda: next(time_values),
    )

    assert len(stabilize_calls) == 1
    assert events[-1]["action"] == "stabilize"
    assert result["iterations_run"] == 2


def test_guard_tunnel_quality_counts_observation_errors_toward_stabilize_threshold(
    monkeypatch,
):
    status_values = iter(
        [
            RuntimeError("temporary cloudflare reset"),
            RuntimeError("temporary cloudflare reset"),
        ]
    )
    time_values = iter([0.0, 60.0])
    stabilize_calls: list[dict] = []
    events: list[dict] = []

    def fake_tunnel_status(tunnel_name=None, cf_token_mode="auto"):
        value = next(status_values)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr("webu.cf_tunnel.operations.tunnel_status", fake_tunnel_status)
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: _access_payload(
            "dev.blbl.top",
            system_ok=True,
            cloudflare_ok=True,
            authoritative_ok=True,
        ),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.stabilize_tunnel",
        lambda **kwargs: stabilize_calls.append(kwargs)
        or {
            "action_taken": "reapply_baseline",
            "healthy_now": True,
            "snapshot": {},
            "post_decision": {"action": "observe"},
        },
    )

    result = guard_tunnel_quality(
        tunnel_name="dev.blbl.top",
        hostname="dev.blbl.top",
        cf_token_mode="auto",
        interval_seconds=1,
        failure_threshold=2,
        cooldown_seconds=300,
        snapshot_interval_seconds=0,
        prefer_family="any",
        max_candidates=2,
        install_service=True,
        save_config=True,
        snapshot_output_dir=Path("debugs/cf-tunnel-snapshots"),
        iterations=2,
        history_limit=10,
        emit_event=events.append,
        sleep_fn=lambda _seconds: None,
        time_fn=lambda: next(time_values),
    )

    assert result["iterations_run"] == 2
    assert events[0]["action"] == "observe-error"
    assert events[0]["error"] == "RuntimeError: temporary cloudflare reset"
    assert events[0]["decision"]["action"] == "observation_error"
    assert events[1]["action"] == "stabilize"
    assert len(stabilize_calls) == 1


def test_guard_tunnel_quality_snapshots_drift_before_threshold(monkeypatch):
    events: list[dict] = []

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.tunnel_status",
        lambda tunnel_name=None, cf_token_mode="auto": {
            "status": "healthy",
            "connections": [{"id": "conn-1"}],
        },
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: _access_payload(
            "dev.blbl.top",
            system_ok=False,
            cloudflare_ok=True,
            authoritative_ok=True,
            mismatch=True,
            recursive_mismatch=True,
        ),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.stabilize_tunnel",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected stabilize")),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations._capture_snapshot_overview",
        lambda **kwargs: {
            "snapshot_label": "snap-drift",
            "output_dir": "/tmp/snap-drift",
            "hostname": "dev.blbl.top",
            "recommended_prefer_family": "ipv4",
            "reason_codes": ["dns_mismatch", "recursive_dns_mismatch"],
            "first_round_strategy": "ipv4-first",
            "top_candidates": [{"ip": "198.51.100.10"}],
        },
    )

    result = guard_tunnel_quality(
        tunnel_name="dev.blbl.top",
        hostname="dev.blbl.top",
        cf_token_mode="auto",
        interval_seconds=1,
        failure_threshold=2,
        cooldown_seconds=300,
        snapshot_interval_seconds=0,
        prefer_family="any",
        max_candidates=2,
        install_service=True,
        save_config=True,
        snapshot_output_dir=Path("debugs/cf-tunnel-snapshots"),
        iterations=1,
        history_limit=10,
        emit_event=events.append,
        sleep_fn=lambda _seconds: None,
        time_fn=lambda: 0.0,
    )

    assert result["iterations_run"] == 1
    assert events[0]["decision"]["action"] == "snapshot_only"
    assert events[0]["action"] == "snapshot-degraded"
    assert events[0]["snapshot"]["snapshot_label"] == "snap-drift"


def test_guard_tunnel_quality_records_snapshot_errors_without_crashing(monkeypatch):
    events: list[dict] = []

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.tunnel_status",
        lambda tunnel_name=None, cf_token_mode="auto": {
            "status": "healthy",
            "connections": [{"id": "conn-1"}],
        },
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: _access_payload(
            "dev.blbl.top",
            system_ok=True,
            cloudflare_ok=True,
            authoritative_ok=True,
        ),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations._capture_snapshot_overview",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("snapshot crash")),
    )

    result = guard_tunnel_quality(
        tunnel_name="dev.blbl.top",
        hostname="dev.blbl.top",
        cf_token_mode="auto",
        interval_seconds=1,
        failure_threshold=2,
        cooldown_seconds=300,
        snapshot_interval_seconds=60,
        prefer_family="any",
        max_candidates=2,
        install_service=True,
        save_config=True,
        snapshot_output_dir=Path("debugs/cf-tunnel-snapshots"),
        iterations=1,
        history_limit=10,
        emit_event=events.append,
        sleep_fn=lambda _seconds: None,
        time_fn=lambda: 0.0,
    )

    assert result["iterations_run"] == 1
    assert events[0]["action"] == "snapshot-error"
    assert events[0]["error"] == "RuntimeError: snapshot crash"
