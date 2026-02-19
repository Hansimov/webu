import base64
import re

from dataclasses import dataclass, field
from tclogger import logger
from typing import Optional


@dataclass
class GeminiImage:
    """Gemini 响应中的图片。"""

    url: str = ""
    alt: str = ""
    base64_data: str = ""
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict:
        d = {
            "url": self.url,
            "alt": self.alt,
            "mime_type": self.mime_type,
        }
        if self.width:
            d["width"] = self.width
        if self.height:
            d["height"] = self.height
        if self.base64_data:
            d["base64_data"] = self.base64_data
        return d


@dataclass
class GeminiCodeBlock:
    """Gemini 响应中的代码块。"""

    language: str = ""
    code: str = ""

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "code": self.code,
        }


@dataclass
class GeminiResponse:
    """解析后的 Gemini 响应。"""

    text: str = ""
    markdown: str = ""
    images: list[GeminiImage] = field(default_factory=list)
    code_blocks: list[GeminiCodeBlock] = field(default_factory=list)
    is_error: bool = False
    error_message: str = ""
    raw_html: str = ""

    def to_dict(self) -> dict:
        d = {
            "text": self.text,
            "markdown": self.markdown,
            "images": [img.to_dict() for img in self.images],
            "code_blocks": [cb.to_dict() for cb in self.code_blocks],
            "is_error": self.is_error,
        }
        if self.error_message:
            d["error_message"] = self.error_message
        return d


class GeminiResponseParser:
    """将 Gemini 页面响应解析为结构化数据。"""

    def __init__(self):
        pass

    def parse_text(self, html_content: str) -> str:
        """从响应 HTML 中提取纯文本。"""
        # 去除 HTML 标签，获取纯文本
        text = re.sub(r"<[^>]+>", "", html_content)
        # 规范化空白字符
        text = re.sub(r"\s+", " ", text).strip()
        # 反转义 HTML 实体
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&amp;", "&").replace("&quot;", '"')
        text = text.replace("&#39;", "'").replace("&nbsp;", " ")
        return text

    def parse_markdown(self, html_content: str) -> str:
        """将响应 HTML 转换为 Markdown 格式。"""
        md = html_content

        # 标题
        for i in range(6, 0, -1):
            md = re.sub(
                rf"<h{i}[^>]*>(.*?)</h{i}>",
                rf"{'#' * i} \1\n\n",
                md,
                flags=re.DOTALL,
            )

        # 粗体
        md = re.sub(
            r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>", r"**\1**", md, flags=re.DOTALL
        )
        # 斜体
        md = re.sub(r"<(?:i|em)[^>]*>(.*?)</(?:i|em)>", r"*\1*", md, flags=re.DOTALL)
        # 删除线
        md = re.sub(
            r"<(?:s|del|strike)[^>]*>(.*?)</(?:s|del|strike)>",
            r"~~\1~~",
            md,
            flags=re.DOTALL,
        )

        # 代码块
        md = re.sub(
            r'<pre[^>]*>\s*<code(?:\s+[^>]*?class="[^"]*?language-(\w+)[^"]*"[^>]*?|[^>]*)>(.*?)</code>\s*</pre>',
            lambda m: f"\n```{m.group(1) or ''}\n{self.parse_text(m.group(2))}\n```\n",
            md,
            flags=re.DOTALL,
        )
        # 行内代码
        md = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", md, flags=re.DOTALL)

        # 链接
        md = re.sub(
            r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", md, flags=re.DOTALL
        )

        # 图片
        md = re.sub(
            r'<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*/?>', r"![\2](\1)", md
        )
        md = re.sub(r'<img[^>]*src="([^"]*)"[^>]*/?>', r"![](\1)", md)

        # 列表
        md = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", md, flags=re.DOTALL)
        md = re.sub(r"</?[uo]l[^>]*>", "\n", md)

        # 段落和换行
        md = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", md, flags=re.DOTALL)
        md = re.sub(r"<br\s*/?>", "\n", md)
        md = re.sub(r"<hr\s*/?>", "\n---\n", md)

        # 引用块
        md = re.sub(
            r"<blockquote[^>]*>(.*?)</blockquote>",
            lambda m: "\n".join(f"> {line}" for line in m.group(1).strip().split("\n"))
            + "\n",
            md,
            flags=re.DOTALL,
        )

        # 移除剩余 HTML 标签
        md = re.sub(r"<[^>]+>", "", md)

        # 反转义 HTML 实体
        md = md.replace("&lt;", "<").replace("&gt;", ">")
        md = md.replace("&amp;", "&").replace("&quot;", '"')
        md = md.replace("&#39;", "'").replace("&nbsp;", " ")

        # 清理多余空行
        md = re.sub(r"\n{3,}", "\n\n", md)
        md = md.strip()

        return md

    def parse_code_blocks(self, html_content: str) -> list[GeminiCodeBlock]:
        """从响应 HTML 中提取代码块。"""
        blocks = []
        pattern = r'<pre[^>]*>\s*<code(?:\s+[^>]*?class="[^"]*?language-(\w+)[^"]*"[^>]*?|[^>]*)>(.*?)</code>\s*</pre>'
        for match in re.finditer(pattern, html_content, re.DOTALL):
            language = match.group(1) or ""
            code = self.parse_text(match.group(2))
            blocks.append(GeminiCodeBlock(language=language, code=code))
        return blocks

    def parse_images_from_elements(
        self, image_data_list: list[dict]
    ) -> list[GeminiImage]:
        """从页面元素属性中解析图片数据。"""
        images = []
        for img_data in image_data_list:
            src = img_data.get("src", "")
            if not src:
                continue
            # 跳过小图标和 UI 元素
            width = img_data.get("naturalWidth", 0) or img_data.get("width", 0)
            height = img_data.get("naturalHeight", 0) or img_data.get("height", 0)
            if width and height and (int(width) < 50 or int(height) < 50):
                continue

            image = GeminiImage(
                url=src,
                alt=img_data.get("alt", ""),
                width=int(width) if width else 0,
                height=int(height) if height else 0,
            )

            # 处理 base64 嵌入图片
            if src.startswith("data:"):
                parts = src.split(",", 1)
                if len(parts) == 2:
                    mime_match = re.match(r"data:([^;]+)", parts[0])
                    if mime_match:
                        image.mime_type = mime_match.group(1)
                    image.base64_data = parts[1]
                    image.url = ""

            images.append(image)
        return images

    def parse(
        self, html_content: str, image_data_list: list[dict] = None
    ) -> GeminiResponse:
        """解析完整的 Gemini 响应。"""
        response = GeminiResponse(raw_html=html_content)

        try:
            response.text = self.parse_text(html_content)
            response.markdown = self.parse_markdown(html_content)
            response.code_blocks = self.parse_code_blocks(html_content)

            if image_data_list:
                response.images = self.parse_images_from_elements(image_data_list)

        except Exception as e:
            logger.warn(f"  × 响应解析警告: {e}")
            response.is_error = True
            response.error_message = f"解析错误: {e}"
            # 仍然返回部分结果
            if not response.text:
                response.text = self.parse_text(html_content)

        return response
