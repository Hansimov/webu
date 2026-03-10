from webu.google_api.audit import (
    HubAudit,
    QueryAudit,
    SpaceAudit,
    audit_has_failures,
    extract_hl,
    format_audit_summary,
    summarize_hub,
    summarize_spaces,
)


def test_extract_hl_reads_google_final_url():
    final_url = "https://www.google.com/search?q=%E7%8E%A9%E6%9C%BA%E5%99%A8%E5%88%87%E7%89%87&num=10&hl=zh-CN"
    assert extract_hl(final_url) == "zh-CN"


def test_summarize_spaces_counts_successes():
    payload = summarize_spaces(
        [
            SpaceAudit(
                space="owner/space1",
                base_url="https://owner-space1.hf.space",
                health_ok=True,
                search_ok=True,
                raw_ok=True,
                play_result_present=True,
                locale_audits=[
                    QueryAudit(query="玩机器切片", expected_hl="zh-CN", success=True),
                    QueryAudit(query="東京の天気予報", expected_hl="ja", success=True),
                    QueryAudit(
                        query="bonjour paris actualites",
                        expected_hl="fr",
                        success=False,
                    ),
                ],
            )
        ]
    )
    assert payload["space_count"] == 1
    assert payload["healthy_count"] == 1
    assert payload["play_result_count"] == 1
    assert payload["locale_ok_counts"] == {"zh-CN": 1, "ja": 1, "fr": 0}


def test_summarize_hub_and_failure_detection():
    hub_payload = summarize_hub(
        HubAudit(
            base_url="http://127.0.0.1:18100",
            health_ok=True,
            healthy_backends=8,
            wikipedia_ok=True,
            wikipedia_result_count=9,
            play_result_present=True,
            locale_audits=[
                QueryAudit(query="玩机器切片", expected_hl="zh", success=True),
                QueryAudit(query="東京の天気予報", expected_hl="ja", success=True),
                QueryAudit(
                    query="bonjour paris actualites", expected_hl="fr", success=True
                ),
            ],
        )
    )
    assert hub_payload["healthy_backends"] == 8
    assert hub_payload["locale_ok_counts"] == {"zh": 1, "ja": 1, "fr": 1}

    assert audit_has_failures({"spaces": [], "hub": {"error": ""}}) is False
    assert (
        audit_has_failures({"spaces": [{"error": "boom"}], "hub": {"error": ""}})
        is True
    )
    assert audit_has_failures({"spaces": [], "hub": {"error": "boom"}}) is True


def test_format_audit_summary_renders_human_readable_output():
    payload = {
        "elapsed_sec": 12.3,
        "summary": {
            "spaces": {
                "space_count": 2,
                "healthy_count": 2,
                "search_ok_count": 2,
                "raw_ok_count": 2,
                "play_result_count": 2,
                "locale_ok_counts": {"zh-CN": 2, "ja": 2, "fr": 1},
            },
            "hub": {
                "health_ok": True,
                "healthy_backends": 8,
                "wikipedia_ok": True,
                "wikipedia_result_count": 9,
                "play_result_present": True,
                "locale_ok_counts": {"zh": 1, "ja": 1, "fr": 1},
            },
        },
        "spaces": [],
        "hub": {"backends_seen": ["space1", "space2"], "error": ""},
    }
    text = format_audit_summary(payload)
    assert "Audit completed in 12.3s" in text
    assert "Spaces: healthy 2/2" in text
    assert "Hub: health ok" in text
    assert "Failures: none" in text
    assert "Hub backends seen: space1, space2" in text
