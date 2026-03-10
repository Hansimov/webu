"""HTML 解析器测试。

运行: pytest tests/google_api/test_parser.py -xvs
"""

import os
import pytest

from webu.google_api.parser import (
    GoogleResultParser,
    GoogleSearchResult,
    _is_google_internal,
    _normalize_url,
    _clean_url,
    _dedup_key,
)


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

RICH_RESULT_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="MjjYud">
      <div class="A6K0A" data-rpos="0">
        <div class="tF2Cxc asEBEc">
          <div class="N54PNb BToiNc">
            <div class="kb0PBd A9Y9g jGGQ5e">
              <div class="yuRUbf">
                <div class="b8lM7">
                  <a href="https://developers.google.com/edu/python">
                    <h3>Google's Python Class | Python Education</h3>
                    <div class="notranslate ESMNde HGLrXd ojE3Fb">
                      <div class="q0vns">
                        <div class="CA5RN">
                          <div><span class="VuuXrf">Google for Developers</span></div>
                          <div class="byrV5b">
                            <cite>https://developers.google.com<span> › edu › python</span></cite>
                          </div>
                        </div>
                      </div>
                    </div>
                  </a>
                </div>
              </div>
            </div>
            <div class="kb0PBd A9Y9g" data-sncf="1">
              <div class="VwiC3b yXK7lf p4wth r025kc Hdw6tb">
                <span class="YrbPuc"><span>23 Jul 2024</span> — </span>
                <span>Welcome to Google's Python Class -- this is a free class for people with a little bit of programming experience who want to learn Python.</span>
                <a href="https://developers.google.com/edu/python#:~:text=Welcome">Read more</a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

VIDEO_META_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="ULSxyf">
      <div class="MjjYud">
        <div class="A6K0A" data-rpos="18">
          <div class="vtSz8d">
            <div class="KYaZsb">
              <div class="rtvRGe">
                <div class="ObbMBf">
                  <a class="rIRoqf" href="https://www.youtube.com/watch?v=K5KVEU3aaeQ">
                    <div class="V5XKdd" aria-level="3" role="heading">
                      <div class="ZxS7Db">
                        <div class="tNxQIb ynAwRc OSrXXb">
                          <span class="cHaqb QOGdqf">Python Full Course for Beginners</span>
                        </div>
                      </div>
                      <div class="ZtihLe YrbPuc">
                        <div class="Foqdsf">
                          <span class="Sg4azc"><span>YouTube</span><span><span aria-hidden="true"> ·</span> Programming with Mosh</span></span>
                          <div><span>12 Feb 2025</span></div>
                        </div>
                      </div>
                    </div>
                  </a>
                </div>
                <div class="kb0PBd A9Y9g" data-sncf="1">
                  <div class="VwiC3b"><span>A complete beginner-friendly Python course with projects and exercises.</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

METRIC_VIDEO_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="MjjYud">
      <div class="A6K0A" data-rpos="18">
        <div class="wHYlTd Ww4FFb tF2Cxc asEBEc vt6azd">
          <div class="N54PNb BToiNc">
            <div class="kb0PBd A9Y9g jGGQ5e">
              <div class="yuRUbf">
                <div class="b8lM7">
                  <a href="https://www.youtube.com/watch?v=_uQrJ0TkZlc&vl=en">
                    <h3>Python Full Course for Beginners</h3>
                    <div class="notranslate ESMNde HGLrXd ojE3Fb">
                      <div class="q0vns">
                        <div class="CA5RN">
                          <div><span class="VuuXrf">YouTube · Programming with Mosh</span></div>
                          <div class="byrV5b"><cite>47.2M+ views · 7 years ago</cite></div>
                        </div>
                      </div>
                    </div>
                  </a>
                </div>
              </div>
            </div>
            <div class="iHxmLe">
              <a class="rIRoqf" href="https://www.youtube.com/watch?v=_uQrJ0TkZlc&vl=en">
                <div class="fzUZNc">
                  <div class="ITCGwe">
                    <div class="ITZIwc p4wth">Learn Python for AI, machine learning, and web development with this beginner-friendly course.</div>
                  </div>
                </div>
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

DURATION_VIDEO_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="MjjYud">
      <div class="vtSz8d">
        <a href="https://www.youtube.com/watch?v=JT_jySzWEco">
          <div aria-level="3" role="heading">Millions Cancel ChatGPT: Sam Altman \"In Pain\"</div>
          <div>
            <span>25:51</span>
          </div>
          <div>
            <span>YouTube</span>
            <span>5 days ago</span>
          </div>
        </a>
        <div data-sncf="1">
          <span>Big Tech can see your AI data. Don't let them.</span>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

ROOT_HOMEPAGE_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="MjjYud">
      <div class="A6K0A">
        <div class="tF2Cxc asEBEc">
          <div class="N54PNb BToiNc">
            <div class="kb0PBd A9Y9g jGGQ5e">
              <div class="yuRUbf">
                <div class="b8lM7">
                  <a href="https://openai.com/">
                    <h3>OpenAI</h3>
                    <div class="notranslate ESMNde HGLrXd ojE3Fb">
                      <div class="q0vns">
                        <div class="CA5RN">
                          <div><span class="VuuXrf">OpenAI</span></div>
                          <div class="byrV5b"><cite>https://openai.com</cite></div>
                        </div>
                      </div>
                    </div>
                  </a>
                </div>
              </div>
            </div>
            <div class="kb0PBd A9Y9g" data-sncf="1">
              <div class="VwiC3b"><span>Research, products, and stories from OpenAI.</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

CLUSTERED_VIDEO_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="MjjYud">
      <div class="A6K0A">
        <div>What people are saying</div>
        <div class="BRBF4d kno-fb-ctx">
          <a href="https://www.youtube.com/watch?v=FSNexK7syFE">
            <div class="MBOAae">
              <div><span>28:24</span></div>
              <div aria-level="3" role="heading">Anthropic vs. the Pentagon: Inside the Battle Over A.I. Warfare</div>
              <div><span>45K+ views</span><span> · </span><span>1 day ago</span></div>
              <div><span>New York Times Podcasts · YouTube</span></div>
              <div><span>New York Times podcast collection</span></div>
            </div>
          </a>
        </div>
        <div>
          <a href="https://x.com/some-post">
            <div>WHITE HOUSE READIES EXECUTIVE ORDER TO WEED OUT ANTHROPIC - AXIOS</div>
            <div><span>740+ likes</span><span> · </span><span>17 hours ago</span></div>
            <div><span>DeItaone · X</span></div>
          </a>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

NOISY_SNIPPET_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="MjjYud">
      <div class="A6K0A" data-rpos="0">
        <div class="tF2Cxc asEBEc">
          <div class="N54PNb BToiNc">
            <div class="kb0PBd A9Y9g jGGQ5e">
              <div class="yuRUbf">
                <div class="b8lM7">
                  <a href="https://developers.google.com/edu/python">
                    <h3>Google's Python Class | Python Education</h3>
                    <div class="notranslate ESMNde HGLrXd ojE3Fb">
                      <div class="q0vns">
                        <div class="CA5RN">
                          <div><span class="VuuXrf">Google for Developers</span></div>
                          <div class="byrV5b"><cite>https://developers.google.com<span> › edu › python</span></cite></div>
                        </div>
                      </div>
                    </div>
                  </a>
                </div>
              </div>
            </div>
            <div class="kb0PBd A9Y9g" data-sncf="1">
              <div class="VwiC3b yXK7lf p4wth r025kc Hdw6tb">
                <span>Web Result with Site Links Google for Developers Jul 23, 2024 — A free class for people with a little bit of programming experience who want to learn Python.</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

SITELINK_INHERITANCE_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="MjjYud">
      <div class="BYM4Nd">
        <div class="tF2Cxc">
          <div class="yuRUbf">
            <div class="b8lM7">
              <a href="https://developers.google.com/edu/python">
                <h3>Google's Python Class | Python Education</h3>
                <div>
                  <span class="VuuXrf">Google for Developers</span>
                </div>
                <div>
                  <cite>https://developers.google.com<span> › edu › python</span></cite>
                </div>
              </a>
            </div>
          </div>
          <div data-sncf="1">
            <span>A free class for people with a little bit of programming experience who want to learn Python.</span>
          </div>
        </div>
        <div class="usJj9c">
          <div>
            <div class="VttTV">
              <a href="https://developers.google.com/edu/python/set-up">
                <h3>Python Set Up</h3>
              </a>
              <div><span>The Google Python Class uses a simple, standard Python environment.</span></div>
            </div>
          </div>
          <div>
            <div class="VttTV">
              <a href="https://developers.google.com/edu/python/exercises/basic">
                <h3>Basic Exercises</h3>
              </a>
              <div><span>There are 3 exercises that go with the first sections of Google's Python class.</span></div>
            </div>
          </div>
          <div>
            <div class="VttTV">
              <a href="https://developers.google.com/edu/python/introduction">
                <h3>Python Introduction</h3>
              </a>
              <div><span>Welcome to Google's Python online tutorial.</span></div>
            </div>
          </div>
        </div>
      </div>
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

    def test_extract_site_title_and_time_info(self):
        response = self.parser.parse(RICH_RESULT_HTML, query="python class")
        assert len(response.results) == 1
        result = response.results[0]
        assert result.site_title == "Google for Developers"
        assert result.displayed_url == "https://developers.google.com > edu > python"
        assert result.time_info == "23 Jul 2024"
        assert result.snippet.startswith("Welcome to Google's Python Class")
        assert "Read more" not in result.snippet


# ═══════════════════════════════════════════════════════════════
# 新版 Google HTML 结构测试（使用 MjjYud 等 class，无 div.g）
# ═══════════════════════════════════════════════════════════════

# 模拟 2025 年 Google 搜索结果 HTML（无 div.g，使用 MjjYud 容器）
MODERN_GOOGLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>python - Google Search</title></head>
<body>
<div id="search">
  <div id="rso" class="dURPMd">
    <div class="MjjYud">
      <div class="A6K0A">
        <div class="wHYlTd">
          <div class="N54PNb BToiNc">
            <div class="kb0PBd A9Y9g">
              <div class="yuRUbf">
                <a href="https://www.python.org/">
                  <h3>Welcome to Python.org</h3>
                </a>
              </div>
            </div>
            <div><cite>www.python.org</cite></div>
            <div data-sncf="1">
              <span>The official home of the Python Programming Language. Download Python, read tutorials, and get started.</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="MjjYud">
      <div class="A6K0A">
        <div class="wHYlTd">
          <div class="N54PNb BToiNc">
            <div class="kb0PBd A9Y9g">
              <div class="yuRUbf">
                <a href="https://docs.python.org/3/">
                  <h3>Python 3 Documentation</h3>
                </a>
              </div>
            </div>
            <div><cite>docs.python.org</cite></div>
            <div><span>Complete Python 3 documentation including library reference and language specification for developers.</span></div>
          </div>
        </div>
      </div>
    </div>
    <div class="MjjYud">
      <div class="A6K0A">
        <div class="wHYlTd">
          <div class="N54PNb BToiNc">
            <div class="kb0PBd A9Y9g">
              <div class="yuRUbf">
                <a href="https://www.w3schools.com/python/">
                  <h3>Python Tutorial - W3Schools</h3>
                </a>
              </div>
            </div>
            <div><cite>www.w3schools.com</cite></div>
            <div><span>Learn Python with our comprehensive tutorial covering basic to advanced Python concepts and real world examples.</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
<div id="result-stats">About 5,000,000 results (0.35 seconds)</div>
</body>
</html>
"""

# 包含视频结果的 HTML
VIDEO_RESULTS_HTML = """
<!DOCTYPE html>
<html>
<body>
<div id="search">
  <div id="rso">
    <div class="MjjYud">
      <a href="https://example.com/article">
        <h3>Python Article</h3>
      </a>
      <div><cite>example.com</cite></div>
      <div><span>A comprehensive article about Python programming covering all the basics and more for beginners.</span></div>
    </div>
    <div class="MjjYud">
      <a href="https://www.youtube.com/watch?v=ABC123">
        <h3>Python Full Course</h3>
      </a>
    </div>
    <div>
      <a href="https://www.youtube.com/watch?v=DEF456">
        <span>Python for Beginners</span>
      </a>
    </div>
    <div>
      <a href="https://www.youtube.com/watch?v=DEF456&t=120">
        <span>From 02:00 Variables</span>
      </a>
    </div>
    <div>
      <a href="https://www.youtube.com/watch?v=GHI789">
        <span>Advanced Python Tutorial</span>
      </a>
    </div>
  </div>
</div>
</body>
</html>
"""


class TestModernGoogleHTML:
    """测试新版 Google HTML 结构解析（无 div.g）。"""

    def setup_method(self):
        self.parser = GoogleResultParser(verbose=False)

    def test_parse_modern_html(self):
        """测试解析 MjjYud 容器结构。"""
        response = self.parser.parse(MODERN_GOOGLE_HTML, query="python")
        assert len(response.results) == 3
        assert response.results[0].title == "Welcome to Python.org"
        assert response.results[0].url == "https://www.python.org/"
        assert response.results[1].title == "Python 3 Documentation"
        assert response.results[2].title == "Python Tutorial - W3Schools"

    def test_modern_html_displayed_url(self):
        """测试从 cite 提取显示 URL。"""
        response = self.parser.parse(MODERN_GOOGLE_HTML, query="python")
        assert response.results[0].displayed_url == "www.python.org"
        assert response.results[1].displayed_url == "docs.python.org"

    def test_modern_html_snippet(self):
        """测试从 data-sncf 或 span 提取摘要。"""
        response = self.parser.parse(MODERN_GOOGLE_HTML, query="python")
        # 第一个结果有 data-sncf 属性的摘要
        assert "official home" in response.results[0].snippet.lower()

    def test_modern_html_total_results(self):
        """测试结果统计文本。"""
        response = self.parser.parse(MODERN_GOOGLE_HTML, query="python")
        assert "5,000,000" in response.total_results_text

    def test_positions_are_sequential(self):
        """测试位置编号连续。"""
        response = self.parser.parse(MODERN_GOOGLE_HTML, query="python")
        for i, r in enumerate(response.results):
            assert r.position == i + 1


class TestVideoResults:
    """测试视频结果解析。"""

    def setup_method(self):
        self.parser = GoogleResultParser(verbose=False)

    def test_video_results_extracted(self):
        """测试视频结果被正确提取。"""
        response = self.parser.parse(VIDEO_RESULTS_HTML, query="python")
        urls = [r.url for r in response.results]
        # 有机结果
        assert "https://example.com/article" in urls
        # YouTube 视频
        assert "https://www.youtube.com/watch?v=ABC123" in urls

    def test_video_timeline_excluded(self):
        """测试视频时间线链接（&t=120）被排除。"""
        response = self.parser.parse(VIDEO_RESULTS_HTML, query="python")
        urls = [r.url for r in response.results]
        # 带 &t= 的时间线链接不应出现
        assert not any("&t=" in u for u in urls)

    def test_video_dedup(self):
        """测试不同 video ID 不会互相去重。"""
        response = self.parser.parse(VIDEO_RESULTS_HTML, query="python")
        yt_urls = [r.url for r in response.results if "youtube.com" in r.url]
        # ABC123（有机 h3）+ DEF456 + GHI789（视频策略）
        assert len(yt_urls) >= 3

    def test_video_result_type(self):
        """测试视频结果的 result_type。"""
        response = self.parser.parse(VIDEO_RESULTS_HTML, query="python")
        for r in response.results:
            if "youtube.com" in r.url and r.title != "Python Full Course":
                # 没有 h3 的 YouTube 链接由视频策略提取
                assert r.result_type == "video"

    def test_video_extracts_site_title_and_time(self):
        response = self.parser.parse(VIDEO_META_HTML, query="python full course")
        assert len(response.results) == 1
        result = response.results[0]
        assert result.result_type == "video"
        assert result.title == "Python Full Course for Beginners"
        assert result.site_title == "YouTube · Programming with Mosh"
        assert result.time_info == "12 Feb 2025"
        assert "beginner-friendly" in result.snippet

    def test_metric_cite_falls_back_to_formatted_url(self):
        response = self.parser.parse(METRIC_VIDEO_HTML, query="python full course")
        assert len(response.results) == 1
        result = response.results[0]
        assert result.displayed_url == "https://www.youtube.com > watch"
        assert result.time_info == "7 years ago"
        assert result.site_title == "YouTube · Programming with Mosh"
        assert "beginner-friendly" in result.snippet

    def test_snippet_removes_site_links_noise(self):
        response = self.parser.parse(NOISY_SNIPPET_HTML, query="python class")
        assert len(response.results) == 1
        result = response.results[0]
        assert "Web Result with Site Links" not in result.snippet
        assert result.snippet.startswith("A free class")

    def test_video_duration_is_not_used_as_site_title(self):
        response = self.parser.parse(DURATION_VIDEO_HTML, query="openai news")
        assert len(response.results) == 1
        result = response.results[0]
        assert result.title == 'Millions Cancel ChatGPT: Sam Altman "In Pain"'
        assert result.site_title == "YouTube"
        assert result.time_info == "5 days ago"
        assert result.displayed_url == "https://www.youtube.com > watch"

    def test_root_homepage_can_keep_title_as_site_title(self):
        response = self.parser.parse(ROOT_HOMEPAGE_HTML, query="openai")
        assert len(response.results) == 1
        result = response.results[0]
        assert result.title == "OpenAI"
        assert result.site_title == "OpenAI"
        assert result.displayed_url == "https://openai.com"

    def test_clustered_video_uses_local_container(self):
        response = self.parser.parse(CLUSTERED_VIDEO_HTML, query="anthropic news")
        assert len(response.results) == 1
        result = response.results[0]
        assert (
            result.title
            == "Anthropic vs. the Pentagon: Inside the Battle Over A.I. Warfare"
        )
        assert result.site_title == "New York Times Podcasts · YouTube"
        assert result.time_info == "1 day ago"
        assert result.snippet == "New York Times podcast collection"

    def test_sitelinks_inherit_parent_site_title(self):
        response = self.parser.parse(
            SITELINK_INHERITANCE_HTML, query="google python class"
        )
        assert len(response.results) == 4
        parent, child1, child2, child3 = response.results
        assert parent.site_title == "Google for Developers"
        assert child1.title == "Python Set Up"
        assert child2.title == "Basic Exercises"
        assert child3.title == "Python Introduction"
        assert child1.site_title == "Google for Developers"
        assert child2.site_title == "Google for Developers"
        assert child3.site_title == "Google for Developers"


class TestHelperFunctions:
    """测试辅助函数。"""

    def test_is_google_internal(self):
        """测试 Google 内部链接判断。"""
        assert _is_google_internal("https://www.google.com/search?q=test")
        assert _is_google_internal("https://accounts.google.com/login")
        assert _is_google_internal("https://support.google.com/help")
        assert _is_google_internal("https://policies.google.com/privacy")
        assert _is_google_internal("https://www.gstatic.com/image.png")

    def test_google_allowed_subdomains(self):
        """测试允许的 Google 子域（有实际内容的）。"""
        assert not _is_google_internal("https://developers.google.com/edu/python")
        assert not _is_google_internal("https://cloud.google.com/products")

    def test_external_urls_not_internal(self):
        """测试外部 URL 不被判定为 Google 内部。"""
        assert not _is_google_internal("https://www.python.org/")
        assert not _is_google_internal("https://github.com/python/cpython")
        assert not _is_google_internal("https://www.youtube.com/watch?v=123")
        assert not _is_google_internal("https://stackoverflow.com/questions")

    def test_normalize_url_redirect(self):
        """测试 /url?q= 重定向链接解码。"""
        url = _normalize_url("/url?q=https://example.com/page&sa=U")
        assert url == "https://example.com/page"

    def test_normalize_url_direct(self):
        """测试直接链接不变。"""
        url = _normalize_url("https://example.com/page")
        assert url == "https://example.com/page"

    def test_clean_url_removes_text_fragment(self):
        """测试去除 #:~:text= fragment。"""
        url = _clean_url("https://example.com/page#:~:text=some%20highlight")
        assert url == "https://example.com/page"

    def test_clean_url_preserves_normal_fragment(self):
        """测试保留正常 fragment。"""
        url = _clean_url("https://example.com/page#section1")
        assert url == "https://example.com/page#section1"

    def test_dedup_key_strips_tracking(self):
        """测试 dedup_key 去除 tracking 参数。"""
        key = _dedup_key("https://example.com/page?ved=abc&sa=U&q=test")
        assert "ved" not in key
        assert "sa=" not in key

    def test_dedup_key_preserves_youtube_vid(self):
        """测试 dedup_key 保留 YouTube 视频 ID。"""
        k1 = _dedup_key("https://www.youtube.com/watch?v=ABC123")
        k2 = _dedup_key("https://www.youtube.com/watch?v=DEF456")
        assert k1 != k2
        assert "ABC123" in k1
        assert "DEF456" in k2


class TestRealHTMLFile:
    """使用真实 HTML 文件测试解析器。"""

    HTML_PATH = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "data",
        "google_api_screenshots",
        "20260305_085929",
        "20260305_085958_captcha_bypassed_python_tutorials_http_127.0.0.1_11119.html",
    )

    def setup_method(self):
        self.parser = GoogleResultParser(verbose=False)

    @pytest.mark.skipif(
        not os.path.exists(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "data",
                "google_api_screenshots",
                "20260305_085929",
                "20260305_085958_captcha_bypassed_python_tutorials_http_127.0.0.1_11119.html",
            )
        ),
        reason="Real HTML file not available",
    )
    def test_real_html_result_count(self):
        """测试真实 HTML 文件提取足够多的结果。"""
        with open(self.HTML_PATH) as f:
            html = f.read()
        response = self.parser.parse(html, query="python tutorials")
        # 应至少提取 8 个有机结果 + 视频结果
        assert len(response.results) >= 10
        assert not response.has_captcha

    @pytest.mark.skipif(
        not os.path.exists(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "data",
                "google_api_screenshots",
                "20260305_085929",
                "20260305_085958_captcha_bypassed_python_tutorials_http_127.0.0.1_11119.html",
            )
        ),
        reason="Real HTML file not available",
    )
    def test_real_html_expected_urls(self):
        """测试真实 HTML 文件包含预期的搜索结果 URL。"""
        with open(self.HTML_PATH) as f:
            html = f.read()
        response = self.parser.parse(html, query="python tutorials")
        urls = [r.url for r in response.results]

        # 应包含这些已知的有机结果
        expected_domains = [
            "w3schools.com",
            "python.org",
            "learnpython.org",
            "codecademy.com",
            "realpython.com",
        ]
        for domain in expected_domains:
            assert any(domain in u for u in urls), f"Missing: {domain}"

    @pytest.mark.skipif(
        not os.path.exists(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "data",
                "google_api_screenshots",
                "20260305_085929",
                "20260305_085958_captcha_bypassed_python_tutorials_http_127.0.0.1_11119.html",
            )
        ),
        reason="Real HTML file not available",
    )
    def test_real_html_has_video_results(self):
        """测试真实 HTML 文件包含 YouTube 视频结果。"""
        with open(self.HTML_PATH) as f:
            html = f.read()
        response = self.parser.parse(html, query="python tutorials")
        video_results = [r for r in response.results if r.result_type == "video"]
        assert len(video_results) >= 1

    @pytest.mark.skipif(
        not os.path.exists(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "data",
                "google_api_screenshots",
                "20260305_085929",
                "20260305_085958_captcha_bypassed_python_tutorials_http_127.0.0.1_11119.html",
            )
        ),
        reason="Real HTML file not available",
    )
    def test_real_html_result_stats(self):
        """测试真实 HTML 文件的结果统计文本。"""
        with open(self.HTML_PATH) as f:
            html = f.read()
        response = self.parser.parse(html, query="python tutorials")
        assert "238,000,000" in response.total_results_text
