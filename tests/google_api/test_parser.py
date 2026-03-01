"""HTML 解析器测试。

运行: pytest tests/google_api/test_parser.py -xvs
"""

import pytest

from webu.google_api.parser import GoogleResultParser, GoogleSearchResult


# ═══════════════════════════════════════════════════════════════
# 模拟的 Google 搜索结果 HTML
# ═══════════════════════════════════════════════════════════════

SAMPLE_GOOGLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>test - Google Search</title></head>
<body>
<div id="search">
  <div id="rso">
    <div class="g">
      <div>
        <a href="https://example.com/page1">
          <h3>Example Page One - Test Result</h3>
        </a>
        <div><cite>https://example.com/page1</cite></div>
        <div>
          <span>This is the snippet for the first search result. It contains a description of the page content that is long enough to be considered a real snippet.</span>
        </div>
      </div>
    </div>
    <div class="g">
      <div>
        <a href="https://example.org/page2">
          <h3>Another Example Page - Second Result</h3>
        </a>
        <div><cite>https://example.org/page2</cite></div>
        <div>
          <span>This is the snippet for the second search result. Another description of a page that covers a different topic entirely.</span>
        </div>
      </div>
    </div>
    <div class="g">
      <div>
        <a href="https://test.dev/article">
          <h3>Test Dev Article - Technical Documentation</h3>
        </a>
        <div><cite>https://test.dev/article</cite></div>
        <div>
          <span>Technical documentation snippet explaining how certain features work in detail and providing comprehensive guidance for developers.</span>
        </div>
      </div>
    </div>
  </div>
</div>
<div id="result-stats">About 1,000,000 results (0.42 seconds)</div>
<script>var x = 123;</script>
<style>.foo { color: red; }</style>
</body>
</html>
"""

CAPTCHA_HTML = """
<!DOCTYPE html>
<html>
<head><title>Sorry...</title></head>
<body>
<div>
  <p>Our systems have detected unusual traffic from your computer network.</p>
  <p>This page checks to see if it's really you sending the requests, and not a robot.</p>
  <div class="captcha-container">
    <div class="recaptcha"></div>
  </div>
</div>
</body>
</html>
"""

EMPTY_HTML = """
<!DOCTYPE html>
<html><head><title>Google</title></head><body></body></html>
"""

# Google 重定向链接格式
REDIRECT_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="g">
      <a href="/url?q=https://redirected.example.com/page&sa=U">
        <h3>Redirected Result Title</h3>
      </a>
      <div><cite>redirected.example.com</cite></div>
      <div><span>This result uses Google redirect URL format which needs to be decoded properly for the final destination URL.</span></div>
    </div>
  </div>
</div>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════════


class TestGoogleResultParser:
    """Google 搜索结果解析器测试。"""

    def setup_method(self):
        self.parser = GoogleResultParser(verbose=False)

    def test_parse_standard_results(self):
        """测试标准搜索结果解析。"""
        response = self.parser.parse(SAMPLE_GOOGLE_HTML, query="test")

        assert response.query == "test"
        assert not response.has_captcha
        assert len(response.results) == 3
        assert response.total_results_text  # 应该有搜索结果统计

        # 验证第一个结果
        r1 = response.results[0]
        assert r1.title == "Example Page One - Test Result"
        assert r1.url == "https://example.com/page1"
        assert r1.displayed_url == "https://example.com/page1"
        assert r1.position == 1
        assert len(r1.snippet) > 0

        # 验证第二个结果
        r2 = response.results[1]
        assert r2.title == "Another Example Page - Second Result"
        assert r2.url == "https://example.org/page2"
        assert r2.position == 2

    def test_detect_captcha(self):
        """测试 CAPTCHA 检测。"""
        response = self.parser.parse(CAPTCHA_HTML, query="test")
        assert response.has_captcha
        assert response.error == "CAPTCHA detected"
        assert len(response.results) == 0

    def test_empty_html(self):
        """测试空页面。"""
        response = self.parser.parse(EMPTY_HTML, query="test")
        assert len(response.results) == 0
        assert not response.has_captcha

    def test_redirect_url_parsing(self):
        """测试 Google 重定向 URL 解码。"""
        response = self.parser.parse(REDIRECT_HTML, query="test")
        assert len(response.results) >= 1

        r1 = response.results[0]
        assert r1.title == "Redirected Result Title"
        assert r1.url == "https://redirected.example.com/page"
        assert r1.displayed_url == "redirected.example.com"

    def test_clean_html_removes_scripts(self):
        """测试 HTML 纯化：移除 script 标签。"""
        clean = self.parser.clean_html(SAMPLE_GOOGLE_HTML)
        assert "<script>" not in clean
        assert "var x = 123" not in clean

    def test_clean_html_removes_styles(self):
        """测试 HTML 纯化：移除 style 标签。"""
        clean = self.parser.clean_html(SAMPLE_GOOGLE_HTML)
        assert "<style>" not in clean
        assert ".foo" not in clean

    def test_captcha_detection_various(self):
        """测试各种 CAPTCHA 检测模式。"""
        assert self.parser.detect_captcha("unusual traffic from your computer")
        assert self.parser.detect_captcha("please solve the CAPTCHA")
        assert self.parser.detect_captcha("recaptcha verification required")
        assert not self.parser.detect_captcha("normal search results page")

    def test_result_to_dict(self):
        """测试结果转字典。"""
        result = GoogleSearchResult(
            title="Test",
            url="https://example.com",
            snippet="A snippet",
            position=1,
        )
        d = result.to_dict()
        assert d["title"] == "Test"
        assert d["url"] == "https://example.com"
        assert d["position"] == 1

    def test_response_to_dict(self):
        """测试响应转字典。"""
        response = self.parser.parse(SAMPLE_GOOGLE_HTML, query="test")
        d = response.to_dict()
        assert d["query"] == "test"
        assert d["result_count"] == 3
        assert isinstance(d["results"], list)
        assert d["results"][0]["title"] == "Example Page One - Test Result"
