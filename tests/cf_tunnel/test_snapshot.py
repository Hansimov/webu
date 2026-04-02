import json

from pathlib import Path

from webu.cf_tunnel.snapshot import capture_canary_snapshot
from webu.cf_tunnel.paths import default_snapshot_output_dir


DOC_EDGE_IPV4_PRIMARY = "198.51.100.10"
DOC_EDGE_IPV4_SECONDARY = "203.0.113.20"
DOC_EDGE_IPV6_PRIMARY = "2001:db8::10"


def test_capture_canary_snapshot_writes_summary_and_snapshot_files(
    monkeypatch, tmp_path
):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(
            {
                "cf_account_id": "account-1",
                "cf_api_token": "existing-token",
                "domains": [{"domain_name": "blbl.top"}],
                "cf_tunnels": [
                    {
                        "tunnel_name": "dev.blbl.top",
                        "domain_name": "dev.blbl.top",
                        "local_url": "http://127.0.0.1:21012",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    monkeypatch.setattr(
        "webu.cf_tunnel.snapshot.edge_trace",
        lambda tunnel_name=None, hostname=None: {
            "hostname": "dev.blbl.top",
            "tunnel_name": tunnel_name,
            "unique_edge_results": [
                {
                    "ip": DOC_EDGE_IPV4_PRIMARY,
                    "success": True,
                    "colo": "HKG",
                    "cf_ray": "abc-HKG",
                },
                {
                    "ip": DOC_EDGE_IPV4_SECONDARY,
                    "success": True,
                    "colo": "NRT",
                    "cf_ray": "def-NRT",
                },
            ],
        },
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.snapshot.client_override_plan",
        lambda tunnel_name=None, hostname=None, prefer_family="any", max_candidates=2: {
            "hostname": "dev.blbl.top",
            "tunnel_name": tunnel_name,
            "recommended_prefer_family": "ipv4",
            "family_assessment": {
                "summary": "Resolver drift makes IPv4 the safer first canary.",
                "reason_codes": ["dns_mismatch"],
            },
            "candidates": [
                {
                    "ip": DOC_EDGE_IPV4_PRIMARY,
                    "family": "ipv4",
                    "colo": "HKG",
                },
                {
                    "ip": DOC_EDGE_IPV6_PRIMARY,
                    "family": "ipv6",
                    "colo": "NRT",
                },
            ],
        },
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.snapshot.client_canary_bundle",
        lambda tunnel_name=None, hostname=None, prefer_family="any", max_candidates=2: {
            "hostname": "dev.blbl.top",
            "recommended_prefer_family": "ipv4",
            "recommendations": ["Current probes recommend ipv4-first canaries."],
        },
    )

    result = capture_canary_snapshot(
        names=["dev.blbl.top"],
        prefer_family="any",
        max_candidates=2,
        output_dir=Path("debugs/cf-tunnel-snapshots"),
        stamp="20260401T010203Z",
    )

    snapshot_root = tmp_path / "debugs" / "cf-tunnel-snapshots" / "20260401T010203Z"
    assert result["snapshot_label"] == "20260401T010203Z"
    assert result["config_path"] == str((config_dir / "cf_tunnel.json").resolve())
    assert result["snapshots"][0]["recommended_prefer_family"] == "ipv4"
    assert result["snapshots"][0]["observed_colos"] == ["HKG", "NRT"]
    assert (
        result["snapshots"][0]["rollout_template"]["primary_candidate_ip"]
        == DOC_EDGE_IPV4_PRIMARY
    )
    assert (
        result["snapshots"][0]["operator_shortcuts"]["first_round_strategy"]
        == "ipv4-first"
    )
    assert (snapshot_root / "summary.json").exists()
    assert (snapshot_root / "SUMMARY.md").exists()
    assert (snapshot_root / "dev.blbl.top" / "edge-trace.json").exists()
    assert (snapshot_root / "dev.blbl.top" / "client-override-plan.json").exists()
    summary_text = (snapshot_root / "SUMMARY.md").read_text(encoding="utf-8")
    assert "operator_shortcuts" in summary_text
    assert "Chinaz Domestic Speed" in summary_text
    assert "CloudflareST repo" in summary_text


def test_default_snapshot_output_dir_prefers_sibling_blbl_dash_repo(
    monkeypatch, tmp_path
):
    webu_root = tmp_path / "webu"
    blbl_dash_root = tmp_path / "blbl-dash"
    (webu_root / "configs").mkdir(parents=True)
    (blbl_dash_root / "configs" / "services").mkdir(parents=True)
    (webu_root / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    (blbl_dash_root / "configs" / "services" / "dash.api.yaml").write_text(
        "metadata:\n  id: dash.api\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(webu_root))

    resolved = default_snapshot_output_dir()

    assert resolved == (blbl_dash_root / "debugs" / "cf-tunnel-snapshots").resolve()
