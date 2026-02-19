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

from webu.gemini.config import GeminiConfig, DEFAULT_GEMINI_CONFIG
from webu.gemini.constants import (
    GEMINI_URL,
    GEMINI_BROWSER_PORT,
    GEMINI_API_PORT,
    GEMINI_VNC_PORT,
    GEMINI_NOVNC_PORT,
    GEMINI_DEFAULT_PROXY,
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

    def test_error_inheritance(self):
        """所有错误都应继承自 GeminiError。"""
        assert issubclass(GeminiLoginRequiredError, GeminiError)
        assert issubclass(GeminiNetworkError, GeminiError)
        assert issubclass(GeminiTimeoutError, GeminiError)
        assert issubclass(GeminiResponseParseError, GeminiError)
        assert issubclass(GeminiImageGenerationError, GeminiError)
        assert issubclass(GeminiBrowserError, GeminiError)
        assert issubclass(GeminiPageError, GeminiError)


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

    # ── Markdown 转换 ────────────────────────────────────────────

    def test_parse_markdown_headers(self):
        html = "<h1>Title</h1><h2>Subtitle</h2><h3>Section</h3>"
        md = self.parser.parse_markdown(html)
        assert "# Title" in md
        assert "## Subtitle" in md
        assert "### Section" in md

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
        html = "<s>deleted</s>"
        md = self.parser.parse_markdown(html)
        assert "~~deleted~~" in md

    def test_parse_markdown_code_inline(self):
        html = "Use <code>print()</code> function"
        md = self.parser.parse_markdown(html)
        assert "`print()`" in md

    def test_parse_markdown_code_block(self):
        html = '<pre><code class="language-python">x = 1\nprint(x)</code></pre>'
        md = self.parser.parse_markdown(html)
        assert "```python" in md
        assert "x = 1" in md

    def test_parse_markdown_links(self):
        html = '<a href="https://example.com">Example</a>'
        md = self.parser.parse_markdown(html)
        assert "[Example](https://example.com)" in md

    def test_parse_markdown_images(self):
        html = '<img src="https://example.com/img.png" alt="photo"/>'
        md = self.parser.parse_markdown(html)
        assert "![photo](https://example.com/img.png)" in md

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

    def test_parse_images_no_src(self):
        images_data = [{"src": "", "alt": "No source"}]
        images = self.parser.parse_images_from_elements(images_data)
        assert len(images) == 0

    def test_parse_images_empty(self):
        images = self.parser.parse_images_from_elements([])
        assert len(images) == 0

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
        assert len(response.images) == 0


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


# ═══════════════════════════════════════════════════════════════════
# 集成测试（需要浏览器）
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestBrowserIntegration:
    """这些测试需要运行中的浏览器和网络访问。
    运行方式: pytest -m integration
    """

    @pytest.fixture
    async def client(self):
        from webu.gemini.client import GeminiClient

        client = GeminiClient(config={"headless": False})
        await client.start()
        yield client
        await client.stop()

    @pytest.mark.asyncio
    async def test_browser_launch(self, client):
        assert client.is_ready
        assert client.page is not None

    @pytest.mark.asyncio
    async def test_login_check(self, client):
        status = await client.check_login_status()
        assert "logged_in" in status
        assert "message" in status

    @pytest.mark.asyncio
    async def test_screenshot(self, client):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test_screenshot.png")
            data = await client.screenshot(path=path)
            assert data is not None
            assert Path(path).exists()


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
