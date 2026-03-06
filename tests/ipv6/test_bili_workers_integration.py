import ipaddress
import os
import sys

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BILI_SCRAPER_ROOT = Path(
    os.environ.get("BILI_SCRAPER_ROOT", REPO_ROOT.parent / "bili-scraper")
)
TEST_BVID = "BV1LMPFzQEeB"


def _ensure_bili_scraper_importable():
    if not BILI_SCRAPER_ROOT.exists():
        pytest.skip("bili-scraper repo not found")
    root_str = str(BILI_SCRAPER_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _assert_session_uses_assigned_ipv6(session):
    assigned_ip = session.ip
    assert assigned_ip, "IPv6 session should be adapted to a random IPv6 address"
    assert ipaddress.IPv6Address(assigned_ip).is_global

    response = session.get("https://test.ipw.cn", timeout=10)
    response.raise_for_status()
    echoed_ip = response.text.strip()

    assert echoed_ip == assigned_ip


@pytest.mark.integration
def test_video_tags_request_uses_random_ipv6_and_returns_tags():
    _ensure_bili_scraper_importable()

    from workers.video_tags.scraper import VideoTagsScraper

    scraper = VideoTagsScraper(generator=None, batcher=None, wid=0)
    scraper.init_session()

    _assert_session_uses_assigned_ipv6(scraper.session)

    result = scraper.fetch_tags(TEST_BVID)

    assert result["code"] == 0
    assert result["data"]
    assert any(tag.get("tag_name") == "GTA" for tag in result["data"])


@pytest.mark.integration
def test_video_checks_request_uses_random_ipv6_and_returns_view_result():
    _ensure_bili_scraper_importable()

    from workers.video_checks.scraper import VideoChecksItem, VideoChecksScraper

    scraper = VideoChecksScraper(generator=None, batcher=None)

    item = VideoChecksItem(
        aid=0,
        bvid=TEST_BVID,
        cid=0,
        pubdate=0,
        fail_count=0,
        check_code=None,
    )

    result = False
    for attempt in range(3):
        _assert_session_uses_assigned_ipv6(scraper.session)
        result = scraper.get_video_view(item)
        if result is not False:
            break
        scraper.session.report_bad()
        assert (
            scraper.session.adapt()
        ), f"failed to adapt IPv6 session on retry {attempt + 1}"

    assert result is not False
    assert result["code"] == 0
    assert result["bvid"] == TEST_BVID
    assert result["data"]["bvid"] == TEST_BVID
    assert result["data"].get("title")
