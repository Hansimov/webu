"""Gemini 模块测试。

测试分为：
- 单元测试：测试解析、配置、错误处理（无需浏览器）
- 集成测试：测试浏览器交互（需要浏览器，标记为 @pytest.mark.integration）
"""

import asyncio
import json
import pytest
import tempfile

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from webu.gemini.config import GeminiConfig, DEFAULT_GEMINI_CONFIG
from webu.gemini.constants import (
    GEMINI_URL,
    GEMINI_BROWSER_PORT,
    GEMINI_API_PORT,
    GEMINI_VNC_PORT,
    GEMINI_NOVNC_PORT,
    GEMINI_DEFAULT_PROXY,
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_DELAY,
)
from webu.gemini.errors import (
    GeminiError,
    GeminiLoginRequiredError,
    GeminiNetworkError,
    GeminiTimeoutError,
    GeminiResponseParseError,
    GeminiImageGenerationError,
    GeminiBrowserError,
    GeminiPageError,
    GeminiRateLimitError,
    GeminiImageDownloadError,
)
from webu.gemini.parser import (
    GeminiImage,
    GeminiCodeBlock,
    GeminiResponse,
    GeminiResponseParser,
)


# ═══════════════════════════════════════════════════════════════════
# 单元测试：错误
# ═══════════════════════════════════════════════════════════════════


class TestErrors:
    def test_base_error(self):
        err = GeminiError("test error", details={"key": "value"})
        assert "test error" in str(err)
        assert err.details == {"key": "value"}

    def test_base_error_no_details(self):
        err = GeminiError("test error")
        assert str(err) == "test error"
        assert err.details == {}

    def test_login_required_error(self):
        err = GeminiLoginRequiredError()
        assert "未登录" in str(err)

    def test_login_required_custom_message(self):
        err = GeminiLoginRequiredError("Custom login message")
        assert str(err) == "Custom login message"

    def test_network_error(self):
        err = GeminiNetworkError(details={"proxy": "http://localhost:1234"})
        assert err.details["proxy"] == "http://localhost:1234"

    def test_timeout_error(self):
        err = GeminiTimeoutError(timeout_ms=5000)
        assert err.details["timeout_ms"] == 5000

    def test_response_parse_error(self):
        err = GeminiResponseParseError(raw_content="<div>test</div>")
        assert err.details["raw_content"] == "<div>test</div>"

    def test_response_parse_error_truncation(self):
        long_content = "x" * 1000
        err = GeminiResponseParseError(raw_content=long_content)
        assert len(err.details["raw_content"]) == 500

    def test_image_generation_error(self):
        err = GeminiImageGenerationError()
        assert "图片生成" in str(err)

    def test_browser_error(self):
        err = GeminiBrowserError("browser crash")
        assert "browser crash" in str(err)

    def test_page_error(self):
        err = GeminiPageError("element not found")
        assert "element not found" in str(err)

    def test_rate_limit_error(self):
        err = GeminiRateLimitError()
        assert "速率限制" in str(err)

    def test_rate_limit_error_custom(self):
        err = GeminiRateLimitError("Too many requests", details={"retry_after": 60})
        assert err.details["retry_after"] == 60

    def test_image_download_error(self):
        err = GeminiImageDownloadError()
        assert "图片下载" in str(err)

    def test_image_download_error_with_url(self):
        err = GeminiImageDownloadError(
            "Failed", details={"url": "https://example.com/img.png"}
        )
        assert err.details["url"] == "https://example.com/img.png"

    def test_error_inheritance(self):
        """所有错误都应继承自 GeminiError。"""
        assert issubclass(GeminiLoginRequiredError, GeminiError)
        assert issubclass(GeminiNetworkError, GeminiError)
        assert issubclass(GeminiTimeoutError, GeminiError)
        assert issubclass(GeminiResponseParseError, GeminiError)
        assert issubclass(GeminiImageGenerationError, GeminiError)
        assert issubclass(GeminiBrowserError, GeminiError)
        assert issubclass(GeminiPageError, GeminiError)
        assert issubclass(GeminiRateLimitError, GeminiError)
        assert issubclass(GeminiImageDownloadError, GeminiError)

    def test_error_with_details_str(self):
        """带 details 的错误应包含详情信息。"""
        err = GeminiError("test", details={"key": "val"})
        s = str(err)
        assert "test" in s
        assert "Details" in s


# ═══════════════════════════════════════════════════════════════════
# 单元测试：配置
# ═══════════════════════════════════════════════════════════════════


class TestConfig:
    def test_default_config(self):
        config = GeminiConfig()
        assert config.proxy == GEMINI_DEFAULT_PROXY
        assert config.browser_port == GEMINI_BROWSER_PORT
        assert config.api_port == GEMINI_API_PORT
        assert config.vnc_port == GEMINI_VNC_PORT
        assert config.novnc_port == GEMINI_NOVNC_PORT
        assert config.headless is False
        assert config.verbose is False

    def test_config_override(self):
        config = GeminiConfig(
            config={
                "proxy": "http://127.0.0.1:9999",
                "browser_port": 30099,
                "headless": True,
            }
        )
        assert config.proxy == "http://127.0.0.1:9999"
        assert config.browser_port == 30099
        assert config.headless is True
        # Other defaults should remain
        assert config.api_port == GEMINI_API_PORT
        assert config.vnc_port == GEMINI_VNC_PORT

    def test_config_vnc_override(self):
        config = GeminiConfig(
            config={
                "vnc_port": 5999,
                "novnc_port": 6080,
            }
        )
        assert config.vnc_port == 5999
        assert config.novnc_port == 6080

    def test_config_none_values_ignored(self):
        config = GeminiConfig(
            config={
                "proxy": None,
                "browser_port": 30050,
            }
        )
        # None 值不应覆盖默认值
        assert config.proxy == GEMINI_DEFAULT_PROXY
        assert config.browser_port == 30050

    def test_config_file_save_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "test_config.json")

            # Save
            config = GeminiConfig(
                config={"proxy": "http://test:1234", "browser_port": 31000},
                config_path=config_path,
            )
            config.save_to_file()
            assert Path(config_path).exists()

            # Load
            loaded = GeminiConfig(config_path=config_path)
            assert loaded.proxy == "http://test:1234"
            assert loaded.browser_port == 31000

    def test_config_file_not_exist(self):
        config = GeminiConfig(config_path="/nonexistent/path/config.json")
        # Should use defaults without error
        assert config.proxy == GEMINI_DEFAULT_PROXY

    def test_config_priority(self):
        """输入配置应覆盖文件配置。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "test_config.json")

            # Write a config file
            with open(config_path, "w") as f:
                json.dump({"proxy": "http://file:1111", "browser_port": 30011}, f)

            # Create config with both file and input
            config = GeminiConfig(
                config={"proxy": "http://input:2222"},
                config_path=config_path,
            )
            assert config.proxy == "http://input:2222"  # 输入优先
            assert config.browser_port == 30011  # 保留文件值

    def test_create_default_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "default_config.json")
            config = GeminiConfig.create_default_config(config_path=config_path)
            assert Path(config_path).exists()

            with open(config_path) as f:
                data = json.load(f)
            assert data["proxy"] == GEMINI_DEFAULT_PROXY

    def test_config_repr(self):
        config = GeminiConfig()
        repr_str = repr(config)
        assert "GeminiConfig" in repr_str

    def test_config_log(self, capsys):
        config = GeminiConfig()
        config.log_config()
        # 不应报错

    def test_config_timeout_properties(self):
        config = GeminiConfig(
            config={
                "page_load_timeout": 30000,
                "response_timeout": 60000,
                "image_generation_timeout": 90000,
            }
        )
        assert config.page_load_timeout == 30000
        assert config.response_timeout == 60000
        assert config.image_generation_timeout == 90000

    def test_config_corrupt_file(self):
        """损坏的配置文件不应导致崩溃。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "corrupt.json")
            with open(config_path, "w") as f:
                f.write("not valid json {{{")

            config = GeminiConfig(config_path=config_path)
            # Should fall back to defaults
            assert config.proxy == GEMINI_DEFAULT_PROXY


# ═══════════════════════════════════════════════════════════════
# 单元测试：解析器
# ═══════════════════════════════════════════════════════════════════


class TestParser:
    def setup_method(self):
        self.parser = GeminiResponseParser()

    # ── 文本解析 ─────────────────────────────────────────────────

    def test_parse_text_simple(self):
        html = "<p>Hello world</p>"
        text = self.parser.parse_text(html)
        assert text == "Hello world"

    def test_parse_text_nested(self):
        html = "<div><p>Line 1</p><p>Line 2</p></div>"
        text = self.parser.parse_text(html)
        assert "Line 1" in text
        assert "Line 2" in text

    def test_parse_text_entities(self):
        html = "&lt;code&gt; &amp; &quot;test&quot;"
        text = self.parser.parse_text(html)
        assert '<code> & "test"' == text

    def test_parse_text_empty(self):
        text = self.parser.parse_text("")
        assert text == ""

    def test_parse_text_whitespace(self):
        html = "  <p>  spaced   text  </p>  "
        text = self.parser.parse_text(html)
        assert text == "spaced text"

    def test_parse_text_deeply_nested(self):
        html = "<div><span><b><i>deep text</i></b></span></div>"
        text = self.parser.parse_text(html)
        assert "deep text" in text

    def test_parse_text_with_br(self):
        html = "line 1<br/>line 2<br>line 3"
        text = self.parser.parse_text(html)
        assert "line 1" in text
        assert "line 2" in text

    def test_parse_text_none_handling(self):
        text = self.parser.parse_text(None)
        assert text == ""

    # ── Markdown 转换 ────────────────────────────────────────────

    def test_parse_markdown_headers(self):
        html = "<h1>Title</h1><h2>Subtitle</h2><h3>Section</h3>"
        md = self.parser.parse_markdown(html)
        assert "# Title" in md
        assert "## Subtitle" in md
        assert "### Section" in md

    def test_parse_markdown_all_header_levels(self):
        html = "<h1>H1</h1><h2>H2</h2><h3>H3</h3><h4>H4</h4><h5>H5</h5><h6>H6</h6>"
        md = self.parser.parse_markdown(html)
        assert "# H1" in md
        assert "## H2" in md
        assert "### H3" in md
        assert "#### H4" in md
        assert "##### H5" in md
        assert "###### H6" in md

    def test_parse_markdown_bold(self):
        html = "<b>bold text</b> and <strong>strong text</strong>"
        md = self.parser.parse_markdown(html)
        assert "**bold text**" in md
        assert "**strong text**" in md

    def test_parse_markdown_italic(self):
        html = "<i>italic</i> and <em>emphasis</em>"
        md = self.parser.parse_markdown(html)
        assert "*italic*" in md
        assert "*emphasis*" in md

    def test_parse_markdown_strikethrough(self):
        html = "<s>deleted</s> and <del>removed</del>"
        md = self.parser.parse_markdown(html)
        assert "~~deleted~~" in md
        assert "~~removed~~" in md

    def test_parse_markdown_code_inline(self):
        html = "Use <code>print()</code> function"
        md = self.parser.parse_markdown(html)
        assert "`print()`" in md

    def test_parse_markdown_code_block(self):
        html = '<pre><code class="language-python">x = 1\nprint(x)</code></pre>'
        md = self.parser.parse_markdown(html)
        assert "```python" in md
        assert "x = 1" in md

    def test_parse_markdown_code_block_no_language(self):
        html = "<pre><code>some code</code></pre>"
        md = self.parser.parse_markdown(html)
        assert "```" in md
        assert "some code" in md

    def test_parse_markdown_pre_without_code(self):
        html = "<pre>plain preformatted</pre>"
        md = self.parser.parse_markdown(html)
        assert "```" in md
        assert "plain preformatted" in md

    def test_parse_markdown_links(self):
        html = '<a href="https://example.com">Example</a>'
        md = self.parser.parse_markdown(html)
        assert "[Example](https://example.com)" in md

    def test_parse_markdown_images(self):
        html = '<img src="https://example.com/img.png" alt="photo"/>'
        md = self.parser.parse_markdown(html)
        assert "![photo](https://example.com/img.png)" in md

    def test_parse_markdown_image_no_alt(self):
        html = '<img src="https://example.com/img.png"/>'
        md = self.parser.parse_markdown(html)
        assert "![](https://example.com/img.png)" in md

    def test_parse_markdown_list(self):
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        md = self.parser.parse_markdown(html)
        assert "- Item 1" in md
        assert "- Item 2" in md

    def test_parse_markdown_paragraph(self):
        html = "<p>Paragraph one</p><p>Paragraph two</p>"
        md = self.parser.parse_markdown(html)
        assert "Paragraph one" in md
        assert "Paragraph two" in md

    def test_parse_markdown_blockquote(self):
        html = "<blockquote>Quoted text</blockquote>"
        md = self.parser.parse_markdown(html)
        assert "> Quoted text" in md

    def test_parse_markdown_hr(self):
        html = "<p>Before</p><hr/><p>After</p>"
        md = self.parser.parse_markdown(html)
        assert "---" in md

    def test_parse_markdown_br(self):
        html = "line one<br/>line two"
        md = self.parser.parse_markdown(html)
        assert "line one" in md
        assert "line two" in md

    def test_parse_markdown_table(self):
        html = """
        <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>A</td><td>1</td></tr>
            <tr><td>B</td><td>2</td></tr>
        </table>
        """
        md = self.parser.parse_markdown(html)
        assert "| Name | Value |" in md
        assert "| --- | --- |" in md
        assert "| A | 1 |" in md
        assert "| B | 2 |" in md

    def test_parse_markdown_nested_formatting(self):
        """嵌套格式化应正确处理。"""
        html = "<p>This is <b>bold with <i>italic</i> inside</b></p>"
        md = self.parser.parse_markdown(html)
        assert "**bold with *italic* inside**" in md

    def test_parse_markdown_complex(self):
        html = """
        <h2>Welcome</h2>
        <p>This is a <b>bold</b> and <i>italic</i> text.</p>
        <pre><code class="language-python">def hello():
    print("hello")</code></pre>
        <ul>
            <li>Item A</li>
            <li>Item B</li>
        </ul>
        """
        md = self.parser.parse_markdown(html)
        assert "## Welcome" in md
        assert "**bold**" in md
        assert "*italic*" in md
        assert "```python" in md
        assert "- Item A" in md

    def test_parse_markdown_empty(self):
        md = self.parser.parse_markdown("")
        assert md == ""

    def test_parse_markdown_none(self):
        md = self.parser.parse_markdown(None)
        assert md == ""

    # ── 代码块提取 ────────────────────────────────────────────

    def test_parse_code_blocks(self):
        html = '<pre><code class="language-javascript">const x = 1;</code></pre>'
        blocks = self.parser.parse_code_blocks(html)
        assert len(blocks) == 1
        assert blocks[0].language == "javascript"
        assert "const x = 1" in blocks[0].code

    def test_parse_code_blocks_no_language(self):
        html = "<pre><code>plain code</code></pre>"
        blocks = self.parser.parse_code_blocks(html)
        assert len(blocks) == 1
        assert blocks[0].language == ""
        assert "plain code" in blocks[0].code

    def test_parse_code_blocks_multiple(self):
        html = """
        <pre><code class="language-python">x = 1</code></pre>
        <p>Some text</p>
        <pre><code class="language-bash">echo hello</code></pre>
        """
        blocks = self.parser.parse_code_blocks(html)
        assert len(blocks) == 2
        assert blocks[0].language == "python"
        assert blocks[1].language == "bash"

    def test_parse_code_blocks_empty(self):
        html = "<p>No code here</p>"
        blocks = self.parser.parse_code_blocks(html)
        assert len(blocks) == 0

    def test_parse_code_blocks_empty_input(self):
        blocks = self.parser.parse_code_blocks("")
        assert len(blocks) == 0

    def test_parse_code_blocks_none(self):
        blocks = self.parser.parse_code_blocks(None)
        assert len(blocks) == 0

    def test_parse_code_blocks_pre_without_code(self):
        html = "<pre>just preformatted text</pre>"
        blocks = self.parser.parse_code_blocks(html)
        assert len(blocks) == 1
        assert "just preformatted text" in blocks[0].code

    def test_parse_code_blocks_multiline(self):
        html = '<pre><code class="language-python">def foo():\n    return 42\n\nprint(foo())</code></pre>'
        blocks = self.parser.parse_code_blocks(html)
        assert len(blocks) == 1
        assert "def foo():" in blocks[0].code
        assert "return 42" in blocks[0].code

    # ── 图片解析 ──────────────────────────────────────────────

    def test_parse_images(self):
        images_data = [
            {
                "src": "https://example.com/img1.png",
                "alt": "Image 1",
                "naturalWidth": 100,
                "naturalHeight": 100,
            },
            {
                "src": "https://example.com/img2.jpg",
                "alt": "Image 2",
                "naturalWidth": 200,
                "naturalHeight": 150,
            },
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 2
        assert images[0].url == "https://example.com/img1.png"
        assert images[0].alt == "Image 1"
        assert images[1].width == 200

    def test_parse_images_skip_small(self):
        """小图片 (< 50px) 应被跳过，因为它们可能是图标。"""
        images_data = [
            {
                "src": "https://example.com/icon.png",
                "alt": "",
                "naturalWidth": 16,
                "naturalHeight": 16,
            },
            {
                "src": "https://example.com/photo.png",
                "alt": "Photo",
                "naturalWidth": 400,
                "naturalHeight": 300,
            },
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].alt == "Photo"

    def test_parse_images_base64(self):
        images_data = [
            {
                "src": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==",
                "alt": "Embedded",
                "naturalWidth": 100,
                "naturalHeight": 100,
            }
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].base64_data == "iVBORw0KGgoAAAANSUhEUg=="
        assert images[0].mime_type == "image/png"
        assert images[0].url == ""

    def test_parse_images_base64_jpeg(self):
        images_data = [
            {
                "src": "data:image/jpeg;base64,/9j/4AAQSkZJRgAB",
                "alt": "JPEG",
                "naturalWidth": 200,
                "naturalHeight": 200,
            }
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].mime_type == "image/jpeg"

    def test_parse_images_no_src(self):
        images_data = [{"src": "", "alt": "No source"}]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 0

    def test_parse_images_empty(self):
        images = self.parser.parse_images_from_elements([])
        assert len(images) == 0

    def test_parse_images_width_fallback(self):
        """使用 width 字段作为 naturalWidth 的回退。"""
        images_data = [
            {
                "src": "https://example.com/img.png",
                "alt": "test",
                "width": 200,
                "height": 150,
            }
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].width == 200
        assert images[0].height == 150

    # ── HTML 图片提取 ────────────────────────────────────────────

    def test_parse_images_from_html(self):
        html = '<img src="https://example.com/photo.jpg" alt="Photo" width="300" height="200"/>'
        images = self.parser.parse_images_from_html(html)
        assert len(images) == 1
        assert images[0].url == "https://example.com/photo.jpg"
        assert images[0].alt == "Photo"

    def test_parse_images_from_html_base64(self):
        html = '<img src="data:image/png;base64,ABC123==" alt="Embedded" width="100" height="100"/>'
        images = self.parser.parse_images_from_html(html)
        assert len(images) == 1
        assert images[0].base64_data == "ABC123=="
        assert images[0].mime_type == "image/png"
        assert images[0].url == ""

    def test_parse_images_from_html_skip_small(self):
        html = '<img src="icon.png" width="16" height="16"/><img src="photo.png" width="300" height="200"/>'
        images = self.parser.parse_images_from_html(html)
        assert len(images) == 1
        assert images[0].url == "photo.png"

    def test_parse_images_from_html_empty(self):
        images = self.parser.parse_images_from_html("")
        assert len(images) == 0

    def test_parse_images_from_html_none(self):
        images = self.parser.parse_images_from_html(None)
        assert len(images) == 0

    def test_parse_images_from_html_no_size(self):
        """没有尺寸的图片不应被过滤。"""
        html = '<img src="https://example.com/photo.jpg" alt="Photo"/>'
        images = self.parser.parse_images_from_html(html)
        assert len(images) == 1

    # ── 完整解析 ─────────────────────────────────────────────────

    def test_full_parse(self):
        html = """
        <h2>Answer</h2>
        <p>Here is the response with <b>formatting</b>.</p>
        <pre><code class="language-python">print("hello")</code></pre>
        """
        images_data = [
            {
                "src": "https://example.com/img.png",
                "alt": "Result",
                "naturalWidth": 300,
                "naturalHeight": 200,
            }
        ]
        response = self.parser.parse(html, images_data)

        assert not response.is_error
        assert "Answer" in response.text
        assert "## Answer" in response.markdown
        assert len(response.code_blocks) == 1
        assert len(response.images) == 1
        assert response.images[0].alt == "Result"

    def test_full_parse_empty(self):
        response = self.parser.parse("")
        assert response.text == ""
        assert response.markdown == ""
        assert len(response.images) == 0
        assert len(response.code_blocks) == 0

    def test_full_parse_no_images(self):
        html = "<p>Text only</p>"
        response = self.parser.parse(html)
        assert response.text == "Text only"

    def test_full_parse_html_images_fallback(self):
        """无 image_data_list 时，应从 HTML 中提取图片。"""
        html = '<p>Text</p><img src="https://example.com/img.png" alt="Photo" width="300" height="200"/>'
        response = self.parser.parse(html)
        assert len(response.images) == 1
        assert response.images[0].alt == "Photo"

    def test_full_parse_preserves_raw_html(self):
        html = "<p>Test</p>"
        response = self.parser.parse(html)
        assert response.raw_html == html

    def test_full_parse_to_dict_complete(self):
        """to_dict 应包含所有字段。"""
        html = "<p>Hello</p>"
        response = self.parser.parse(html)
        d = response.to_dict()
        assert "text" in d
        assert "markdown" in d
        assert "images" in d
        assert "code_blocks" in d
        assert "is_error" in d


# ═══════════════════════════════════════════════════════════════════
# 单元测试：数据类
# ═══════════════════════════════════════════════════════════════════


class TestDataClasses:
    def test_gemini_image_to_dict(self):
        img = GeminiImage(
            url="https://example.com/img.png", alt="test", width=100, height=50
        )
        d = img.to_dict()
        assert d["url"] == "https://example.com/img.png"
        assert d["alt"] == "test"
        assert d["width"] == 100
        assert d["height"] == 50

    def test_gemini_image_to_dict_no_optional(self):
        img = GeminiImage(url="https://example.com/img.png")
        d = img.to_dict()
        assert "width" not in d  # 0 是假值，被排除
        assert "base64_data" not in d

    def test_gemini_image_to_dict_with_base64(self):
        img = GeminiImage(
            url="", base64_data="ABC123==", mime_type="image/png", width=100, height=100
        )
        d = img.to_dict()
        assert d["base64_data"] == "ABC123=="
        assert d["mime_type"] == "image/png"
        assert d["width"] == 100

    def test_gemini_code_block_to_dict(self):
        cb = GeminiCodeBlock(language="python", code="x = 1")
        d = cb.to_dict()
        assert d["language"] == "python"
        assert d["code"] == "x = 1"

    def test_gemini_response_to_dict(self):
        resp = GeminiResponse(
            text="Hello",
            markdown="**Hello**",
            images=[GeminiImage(url="https://img.png", width=100, height=100)],
            code_blocks=[GeminiCodeBlock(language="py", code="x=1")],
        )
        d = resp.to_dict()
        assert d["text"] == "Hello"
        assert d["markdown"] == "**Hello**"
        assert len(d["images"]) == 1
        assert len(d["code_blocks"]) == 1
        assert d["is_error"] is False

    def test_gemini_response_error_to_dict(self):
        resp = GeminiResponse(is_error=True, error_message="Something went wrong")
        d = resp.to_dict()
        assert d["is_error"] is True
        assert d["error_message"] == "Something went wrong"

    def test_gemini_response_defaults(self):
        resp = GeminiResponse()
        assert resp.text == ""
        assert resp.markdown == ""
        assert resp.images == []
        assert resp.code_blocks == []
        assert resp.is_error is False
        assert resp.error_message == ""
        assert resp.raw_html == ""


# ═══════════════════════════════════════════════════════════════════
# 单元测试：重试装饰器
# ═══════════════════════════════════════════════════════════════════


class TestRetryDecorator:
    @pytest.mark.asyncio
    async def test_retry_on_page_error(self):
        """GeminiPageError 应触发重试。"""
        from webu.gemini.client import with_retry

        call_count = 0

        @with_retry(max_retries=3, delay=0.01)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise GeminiPageError("intermittent error")
            return "success"

        result = await flaky_func()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_no_retry_on_login_error(self):
        """GeminiLoginRequiredError 不应重试。"""
        from webu.gemini.client import with_retry

        call_count = 0

        @with_retry(max_retries=3, delay=0.01)
        async def login_check():
            nonlocal call_count
            call_count += 1
            raise GeminiLoginRequiredError("not logged in")

        with pytest.raises(GeminiLoginRequiredError):
            await login_check()

        assert call_count == 1  # 不应重试

    @pytest.mark.asyncio
    async def test_retry_no_retry_on_rate_limit(self):
        """GeminiRateLimitError 不应重试。"""
        from webu.gemini.client import with_retry

        call_count = 0

        @with_retry(max_retries=3, delay=0.01)
        async def rate_limited():
            nonlocal call_count
            call_count += 1
            raise GeminiRateLimitError("quota exceeded")

        with pytest.raises(GeminiRateLimitError):
            await rate_limited()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """超过最大重试次数应抛出最后的错误。"""
        from webu.gemini.client import with_retry

        call_count = 0

        @with_retry(max_retries=2, delay=0.01)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise GeminiPageError("persistent error")

        with pytest.raises(GeminiPageError):
            await always_fails()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_success_on_first_try(self):
        """首次成功不应触发重试。"""
        from webu.gemini.client import with_retry

        call_count = 0

        @with_retry(max_retries=3, delay=0.01)
        async def always_works():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await always_works()
        assert result == "ok"
        assert call_count == 1


# ═══════════════════════════════════════════════════════════════════
# 单元测试：常量
# ═══════════════════════════════════════════════════════════════════


class TestConstants:
    def test_gemini_url(self):
        from webu.gemini.constants import GEMINI_URL

        assert "gemini.google.com" in GEMINI_URL

    def test_selectors_not_empty(self):
        """所有选择器常量都不为空。"""
        from webu.gemini import constants

        for name in dir(constants):
            if name.startswith("SEL_"):
                value = getattr(constants, name)
                assert value, f"{name} 不应为空"
                assert isinstance(value, str), f"{name} 应为字符串"

    def test_ports_in_range(self):
        """端口号应在合理范围内。"""
        assert 30000 <= GEMINI_BROWSER_PORT <= 40000
        assert 30000 <= GEMINI_API_PORT <= 40000
        assert 30000 <= GEMINI_VNC_PORT <= 40000
        assert 30000 <= GEMINI_NOVNC_PORT <= 40000

    def test_retry_defaults(self):
        assert GEMINI_MAX_RETRIES >= 1
        assert GEMINI_RETRY_DELAY > 0


# ═══════════════════════════════════════════════════════════════════
# 单元测试：API 模型
# ═══════════════════════════════════════════════════════════════════


class TestAPIModels:
    def test_chat_request_model(self):
        from webu.gemini.api import ChatRequest

        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.new_chat is False
        assert req.image_mode is False
        assert req.download_images is True

    def test_chat_request_all_fields(self):
        from webu.gemini.api import ChatRequest

        req = ChatRequest(
            message="test", new_chat=True, image_mode=True, download_images=False
        )
        assert req.new_chat is True
        assert req.image_mode is True
        assert req.download_images is False

    def test_image_request_model(self):
        from webu.gemini.api import ImageRequest

        req = ImageRequest(prompt="a cat")
        assert req.prompt == "a cat"
        assert req.new_chat is True

    def test_chat_response_model(self):
        from webu.gemini.api import ChatResponse

        resp = ChatResponse(success=True, text="Hello", markdown="Hello")
        assert resp.success is True
        assert resp.text == "Hello"
        assert resp.images == []

    def test_status_response_model(self):
        from webu.gemini.api import StatusResponse

        resp = StatusResponse(
            status="ok", is_ready=True, is_logged_in=True, message_count=5
        )
        assert resp.message_count == 5

    def test_health_response_model(self):
        from webu.gemini.api import HealthResponse

        resp = HealthResponse()
        assert resp.status == "ok"
        assert resp.version == "1.0.0"


# ═══════════════════════════════════════════════════════════════════
# 单元测试：图片保存
# ═══════════════════════════════════════════════════════════════════


class TestImageSaving:
    def test_get_extension_png(self):
        img = GeminiImage(mime_type="image/png")
        assert img.get_extension() == "png"

    def test_get_extension_jpeg(self):
        img = GeminiImage(mime_type="image/jpeg")
        assert img.get_extension() == "jpg"

    def test_get_extension_webp(self):
        img = GeminiImage(mime_type="image/webp")
        assert img.get_extension() == "webp"

    def test_get_extension_gif(self):
        img = GeminiImage(mime_type="image/gif")
        assert img.get_extension() == "gif"

    def test_get_extension_svg(self):
        img = GeminiImage(mime_type="image/svg+xml")
        assert img.get_extension() == "svg"

    def test_get_extension_unknown(self):
        img = GeminiImage(mime_type="image/tiff")
        assert img.get_extension() == "png"  # 默认 png

    def test_save_to_file_success(self):
        import base64

        # 创建一个简单的 1x1 PNG (最小有效 PNG)
        png_data = base64.b64encode(
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            + b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            + b"\x00\x00\x00\x0cIDATx"
            + b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
            + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ).decode()

        img = GeminiImage(base64_data=png_data, mime_type="image/png")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "test_img.png")
            result = img.save_to_file(filepath)
            assert result is True
            assert Path(filepath).exists()
            assert Path(filepath).stat().st_size > 0

    def test_save_to_file_no_data(self):
        img = GeminiImage(url="https://example.com/img.png")
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "test_img.png")
            result = img.save_to_file(filepath)
            assert result is False
            assert not Path(filepath).exists()

    def test_save_to_file_creates_dirs(self):
        import base64

        data = base64.b64encode(b"fake image data").decode()
        img = GeminiImage(base64_data=data, mime_type="image/png")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "subdir" / "deep" / "test_img.png")
            result = img.save_to_file(filepath)
            assert result is True
            assert Path(filepath).exists()


# ═══════════════════════════════════════════════════════════════════
# 单元测试：解析器 - 预提取 base64 数据处理
# ═══════════════════════════════════════════════════════════════════


class TestParserBase64Handling:
    def setup_method(self):
        self.parser = GeminiResponseParser()

    def test_parse_images_with_pre_extracted_base64(self):
        """预提取的 base64 数据应正确传递到 GeminiImage。"""
        images_data = [
            {
                "src": "https://example.com/img.png",
                "alt": "Generated",
                "width": 512,
                "height": 512,
                "base64_data": "iVBORw0KGgoAAAANSUhEUg==",
                "mime_type": "image/png",
            }
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].base64_data == "iVBORw0KGgoAAAANSUhEUg=="
        assert images[0].mime_type == "image/png"
        assert images[0].url == "https://example.com/img.png"

    def test_parse_images_canvas_no_src(self):
        """来自 canvas 的图片没有 src，但有 base64 数据，应被正确处理。"""
        images_data = [
            {
                "src": "",
                "alt": "canvas-image",
                "width": 256,
                "height": 256,
                "base64_data": "CANVAS_BASE64_DATA==",
                "mime_type": "image/png",
                "type": "canvas",
            }
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].base64_data == "CANVAS_BASE64_DATA=="
        assert images[0].mime_type == "image/png"
        assert images[0].url == ""

    def test_parse_images_blob_converted(self):
        """blob URL 转换后应只保留 base64 数据。"""
        images_data = [
            {
                "src": "blob:https://gemini.google.com/abc123",
                "alt": "Generated Image",
                "width": 1024,
                "height": 1024,
                "base64_data": "BLOB_CONVERTED_BASE64==",
                "mime_type": "image/png",
            }
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].base64_data == "BLOB_CONVERTED_BASE64=="
        # blob URL 不是 data: URL，所以保留在 url 字段
        assert "blob:" in images[0].url

    def test_parse_images_mixed_sources(self):
        """混合来源的图片（URL、data、canvas）应全部正确处理。"""
        images_data = [
            {
                "src": "https://example.com/photo.jpg",
                "alt": "Photo",
                "width": 200,
                "height": 200,
                "base64_data": "DOWNLOADED_B64==",
                "mime_type": "image/jpeg",
            },
            {
                "src": "data:image/png;base64,INLINE_DATA==",
                "alt": "Inline",
                "width": 100,
                "height": 100,
            },
            {
                "src": "",
                "alt": "Canvas",
                "width": 300,
                "height": 300,
                "base64_data": "CANVAS_B64==",
                "mime_type": "image/png",
            },
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 3

        # URL 图片 with downloaded base64
        assert images[0].url == "https://example.com/photo.jpg"
        assert images[0].base64_data == "DOWNLOADED_B64=="
        assert images[0].mime_type == "image/jpeg"

        # data: URL 图片
        assert images[1].url == ""
        assert images[1].base64_data == "INLINE_DATA=="
        assert images[1].mime_type == "image/png"

        # Canvas 图片
        assert images[2].url == ""
        assert images[2].base64_data == "CANVAS_B64=="

    def test_parse_images_data_url_takes_priority(self):
        """data: URL 的 base64 应优先于预提取的 base64_data。"""
        images_data = [
            {
                "src": "data:image/jpeg;base64,DATA_URL_B64==",
                "alt": "test",
                "width": 100,
                "height": 100,
                "base64_data": "PRE_EXTRACTED_B64==",
                "mime_type": "image/png",
            }
        ]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        # data: URL 的数据应优先
        assert images[0].base64_data == "DATA_URL_B64=="
        assert images[0].mime_type == "image/jpeg"

    def test_full_parse_with_base64_data(self):
        """完整解析应正确处理带 base64 的 image_data_list。"""
        html = "<p>Here is your image</p>"
        images_data = [
            {
                "src": "",
                "alt": "Generated",
                "width": 512,
                "height": 512,
                "base64_data": "GENERATED_IMAGE_DATA==",
                "mime_type": "image/png",
                "type": "canvas",
            }
        ]
        response = self.parser.parse(html, images_data)
        assert len(response.images) == 1
        assert response.images[0].base64_data == "GENERATED_IMAGE_DATA=="
        assert "image" in response.text.lower() or "here" in response.text.lower()


# ═══════════════════════════════════════════════════════════════════
# 单元测试：客户端 save_images
# ═══════════════════════════════════════════════════════════════════


class TestSaveImages:
    def test_save_images_empty_response(self):
        """无图片时应返回空列表。"""
        import base64

        from webu.gemini.client import GeminiClient

        client = GeminiClient.__new__(GeminiClient)
        response = GeminiResponse()
        paths = client.save_images(response, output_dir="/tmp/test_empty")
        assert paths == []

    def test_save_images_with_data(self):
        """有 base64 数据的图片应被保存。"""
        import base64

        from webu.gemini.client import GeminiClient

        client = GeminiClient.__new__(GeminiClient)

        b64 = base64.b64encode(b"fake png data").decode()
        response = GeminiResponse(
            text="test",
            images=[
                GeminiImage(
                    base64_data=b64, mime_type="image/png", width=100, height=100
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = client.save_images(response, output_dir=tmpdir, prefix="test")
            assert len(paths) == 1
            assert Path(paths[0]).exists()
            assert "test_" in Path(paths[0]).name

    def test_save_images_skip_no_base64(self):
        """无 base64 数据的图片应被跳过。"""
        from webu.gemini.client import GeminiClient

        client = GeminiClient.__new__(GeminiClient)

        response = GeminiResponse(
            text="test",
            images=[
                GeminiImage(url="https://example.com/img.png", width=100, height=100),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = client.save_images(response, output_dir=tmpdir)
            assert len(paths) == 0

    def test_save_images_multiple(self):
        """多张图片应全部保存。"""
        import base64

        from webu.gemini.client import GeminiClient

        client = GeminiClient.__new__(GeminiClient)

        b64 = base64.b64encode(b"image data").decode()
        response = GeminiResponse(
            images=[
                GeminiImage(
                    base64_data=b64, mime_type="image/png", width=100, height=100
                ),
                GeminiImage(
                    base64_data=b64, mime_type="image/jpeg", width=200, height=200
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = client.save_images(response, output_dir=tmpdir, prefix="multi")
            assert len(paths) == 2
            assert paths[0].endswith(".png")
            assert paths[1].endswith(".jpg")


# ═══════════════════════════════════════════════════════════════════
# 集成测试（需要浏览器）— 使用 module 级别共享 fixture
# ═══════════════════════════════════════════════════════════════════

# 使用 module 级别的 fixture 避免每个测试创建/销毁浏览器实例
_shared_client = None


@pytest.fixture(scope="module")
async def shared_client():
    """模块级别共享的 GeminiClient，所有集成测试复用同一个浏览器实例。"""
    from webu.gemini.client import GeminiClient

    client = GeminiClient(config={"headless": False})
    await client.start()
    yield client
    await client.stop()


@pytest.mark.integration
class TestBrowserIntegration:
    """这些测试需要运行中的浏览器和网络访问。
    运行方式: pytest -m integration

    所有测试共享同一个浏览器实例，避免创建多余标签页。
    """

    @pytest.mark.asyncio
    async def test_browser_launch(self, shared_client):
        assert shared_client.is_ready
        assert shared_client.page is not None

    @pytest.mark.asyncio
    async def test_login_check(self, shared_client):
        status = await shared_client.check_login_status()
        assert "logged_in" in status
        assert "message" in status

    @pytest.mark.asyncio
    async def test_screenshot(self, shared_client):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test_screenshot.png")
            data = await shared_client.screenshot(path=path)
            assert data is not None
            assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_get_status(self, shared_client):
        status = await shared_client.get_status()
        assert "is_ready" in status
        assert status["is_ready"] is True

    @pytest.mark.asyncio
    async def test_page_info(self, shared_client):
        info = await shared_client.browser.get_page_info()
        assert "url" in info
        assert "title" in info

    @pytest.mark.asyncio
    async def test_new_chat_no_extra_tabs(self, shared_client):
        """新会话不应创建多余标签页。"""
        pages_before = len(shared_client.browser.context.pages)
        await shared_client.new_chat()
        # 清理后应只有一个标签页
        pages_after = len(shared_client.browser.context.pages)
        assert pages_after <= pages_before
        assert pages_after == 1

    @pytest.mark.asyncio
    async def test_close_extra_pages(self, shared_client):
        """close_extra_pages 应正确清理多余标签页。"""
        await shared_client.browser.close_extra_pages()
        assert len(shared_client.browser.context.pages) == 1


@pytest.mark.integration
class TestChatIntegration:
    """聊天功能集成测试。运行方式: pytest -m integration

    这些测试需要已登录的 Gemini 账号。
    """

    @pytest.mark.asyncio
    async def test_send_text_message(self, shared_client):
        """发送简单文本消息并获取响应。"""
        await shared_client.new_chat()
        response = await shared_client.send_message("Hello, say 'Hi' back briefly.")
        assert response is not None
        assert len(response.text) > 0
        assert not response.is_error

    @pytest.mark.asyncio
    async def test_send_message_with_code(self, shared_client):
        """发送需要代码回复的消息。"""
        await shared_client.new_chat()
        response = await shared_client.send_message(
            "Write a Python function that returns 42. Keep it short."
        )
        assert response is not None
        assert len(response.text) > 0
        # 可能包含代码块
        if response.code_blocks:
            assert "42" in response.code_blocks[0].code

    @pytest.mark.asyncio
    async def test_send_message_preserves_single_tab(self, shared_client):
        """发送消息后应保持单标签页。"""
        await shared_client.new_chat()
        await shared_client.send_message("Say hello")
        pages = len(shared_client.browser.context.pages)
        assert pages == 1


@pytest.mark.integration
class TestImageIntegration:
    """图片生成集成测试。运行方式: pytest -m integration"""

    @pytest.mark.asyncio
    async def test_generate_and_save_image(self, shared_client):
        """生成图片并保存到磁盘。"""
        await shared_client.new_chat()
        response = await shared_client.generate_image(
            "Draw a simple red circle on white background"
        )
        assert response is not None

        if response.images:
            with tempfile.TemporaryDirectory() as tmpdir:
                paths = shared_client.save_images(
                    response, output_dir=tmpdir, prefix="test_gen"
                )
                # 如果有 base64 数据，应该能保存
                for path in paths:
                    assert Path(path).exists()
                    assert Path(path).stat().st_size > 0


@pytest.mark.integration
class TestAPIIntegration:
    """API 集成测试。运行方式: pytest -m integration"""

    @pytest.fixture
    def app(self):
        from webu.gemini.api import create_gemini_app

        return create_gemini_app(config={"headless": False})

    @pytest.mark.asyncio
    async def test_app_creation(self, app):
        assert app is not None
        assert app.title == "Gemini 自动化 API"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "not integration"])
