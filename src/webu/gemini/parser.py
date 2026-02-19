import base64
import re

from bs4 import BeautifulSoup, NavigableString, Tag
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
    """将 Gemini 页面响应解析为结构化数据。

    使用 BeautifulSoup 进行 HTML 解析，比纯正则更可靠。
    """

    def __init__(self):
        pass

    def _make_soup(self, html_content: str) -> BeautifulSoup:
        """创建 BeautifulSoup 实例。"""
        return BeautifulSoup(html_content, "html.parser")

    def parse_text(self, html_content: str) -> str:
        """从响应 HTML 中提取纯文本。

        使用 BeautifulSoup 的 get_text() 方法，比正则更可靠地处理嵌套标签。
        """
        if not html_content or not html_content.strip():
            return ""
        soup = self._make_soup(html_content)
        # get_text 以空格分隔相邻元素
        text = soup.get_text(separator=" ", strip=True)
        # 规范化空白字符
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _element_to_markdown(self, element, depth: int = 0) -> str:
        """递归将 HTML 元素转换为 Markdown 格式。

        使用 BeautifulSoup 的 DOM 树遍历，比正则更可靠地处理嵌套结构。
        """
        if isinstance(element, NavigableString):
            text = str(element)
            # 保留换行但规范化多余空白
            text = re.sub(r"[ \t]+", " ", text)
            return text

        if not isinstance(element, Tag):
            return ""

        tag = element.name
        children_md = ""
        for child in element.children:
            children_md += self._element_to_markdown(child, depth + 1)

        # 标题 h1-h6
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            content = children_md.strip()
            return f"\n\n{'#' * level} {content}\n\n"

        # 粗体
        if tag in ("b", "strong"):
            content = children_md.strip()
            return f"**{content}**" if content else ""

        # 斜体
        if tag in ("i", "em"):
            content = children_md.strip()
            return f"*{content}*" if content else ""

        # 删除线
        if tag in ("s", "del", "strike"):
            content = children_md.strip()
            return f"~~{content}~~" if content else ""

        # 代码块 <pre><code>
        if tag == "pre":
            code_el = element.find("code")
            if code_el:
                lang = ""
                for cls in code_el.get("class", []):
                    if cls.startswith("language-"):
                        lang = cls[len("language-") :]
                        break
                code_text = code_el.get_text()
                return f"\n```{lang}\n{code_text}\n```\n"
            else:
                pre_text = element.get_text()
                return f"\n```\n{pre_text}\n```\n"

        # 行内代码
        if tag == "code":
            # 如果已在 <pre> 中，不重复处理
            if element.parent and element.parent.name == "pre":
                return children_md
            content = element.get_text()
            return f"`{content}`"

        # 链接
        if tag == "a":
            href = element.get("href", "")
            content = children_md.strip()
            if href and content:
                return f"[{content}]({href})"
            return content

        # 图片
        if tag == "img":
            src = element.get("src", "")
            alt = element.get("alt", "")
            if src:
                return f"![{alt}]({src})"
            return ""

        # 列表项
        if tag == "li":
            content = children_md.strip()
            return f"- {content}\n"

        # 列表容器
        if tag in ("ul", "ol"):
            return f"\n{children_md}\n"

        # 段落
        if tag == "p":
            content = children_md.strip()
            return f"\n{content}\n\n" if content else ""

        # 换行
        if tag == "br":
            return "\n"

        # 水平线
        if tag == "hr":
            return "\n---\n"

        # 引用块
        if tag == "blockquote":
            content = children_md.strip()
            quoted_lines = "\n".join(
                f"> {line}" for line in content.split("\n") if line.strip()
            )
            return f"\n{quoted_lines}\n"

        # 表格
        if tag == "table":
            return self._table_to_markdown(element)

        # div, span 和其他容器 - 传递子内容
        return children_md

    def _table_to_markdown(self, table_el: Tag) -> str:
        """将 HTML 表格转换为 Markdown 表格。"""
        rows = []
        for tr in table_el.find_all("tr"):
            cells = []
            for td in tr.find_all(["th", "td"]):
                cell_text = td.get_text(strip=True)
                cells.append(cell_text)
            if cells:
                rows.append(cells)

        if not rows:
            return ""

        # 构建 Markdown 表格
        lines = []
        # 表头
        lines.append("| " + " | ".join(rows[0]) + " |")
        lines.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
        # 数据行
        for row in rows[1:]:
            # 确保列数一致
            while len(row) < len(rows[0]):
                row.append("")
            lines.append("| " + " | ".join(row[: len(rows[0])]) + " |")

        return "\n" + "\n".join(lines) + "\n"

    def parse_markdown(self, html_content: str) -> str:
        """将响应 HTML 转换为 Markdown 格式。

        使用 BeautifulSoup DOM 树递归遍历，处理嵌套标签更可靠。
        """
        if not html_content or not html_content.strip():
            return ""

        soup = self._make_soup(html_content)
        md = ""
        for child in soup.children:
            md += self._element_to_markdown(child)

        # 清理多余空行
        md = re.sub(r"\n{3,}", "\n\n", md)
        md = md.strip()
        return md

    def parse_code_blocks(self, html_content: str) -> list[GeminiCodeBlock]:
        """从响应 HTML 中提取代码块。

        使用 BeautifulSoup 查找 <pre><code> 结构，提取语言和代码内容。
        """
        if not html_content:
            return []

        blocks = []
        soup = self._make_soup(html_content)

        for pre in soup.find_all("pre"):
            code_el = pre.find("code")
            if code_el:
                # 提取语言
                language = ""
                for cls in code_el.get("class", []):
                    if cls.startswith("language-"):
                        language = cls[len("language-") :]
                        break
                code_text = code_el.get_text()
                blocks.append(GeminiCodeBlock(language=language, code=code_text))
            else:
                # <pre> 内没有 <code>，使用 pre 内容
                code_text = pre.get_text()
                if code_text.strip():
                    blocks.append(GeminiCodeBlock(language="", code=code_text))

        return blocks

    def parse_images_from_elements(
        self, image_data_list: list[dict]
    ) -> list[GeminiImage]:
        """从页面元素属性中解析图片数据。

        过滤掉小图标（<50px），处理 base64 嵌入图片。
        """
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

    def parse_images_from_html(self, html_content: str) -> list[GeminiImage]:
        """从 HTML 内容中直接提取图片。

        补充 parse_images_from_elements，从 HTML 中直接收集图片标签信息。
        """
        if not html_content:
            return []

        images = []
        soup = self._make_soup(html_content)

        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src:
                continue

            # 跳过小图标
            width = img.get("width", 0)
            height = img.get("height", 0)
            try:
                width = int(width) if width else 0
                height = int(height) if height else 0
            except (ValueError, TypeError):
                width, height = 0, 0

            if width and height and (width < 50 or height < 50):
                continue

            image = GeminiImage(
                url=src,
                alt=img.get("alt", ""),
                width=width,
                height=height,
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
        """解析完整的 Gemini 响应。

        整合文本提取、Markdown 转换、代码块提取和图片解析。
        """
        response = GeminiResponse(raw_html=html_content)

        try:
            response.text = self.parse_text(html_content)
            response.markdown = self.parse_markdown(html_content)
            response.code_blocks = self.parse_code_blocks(html_content)

            if image_data_list:
                response.images = self.parse_images_from_elements(image_data_list)
            else:
                # 从 HTML 中提取图片作为回退
                response.images = self.parse_images_from_html(html_content)

        except Exception as e:
            logger.warn(f"  × 响应解析警告: {e}")
            response.is_error = True
            response.error_message = f"解析错误: {e}"
            # 仍然返回部分结果
            if not response.text:
                try:
                    response.text = self.parse_text(html_content)
                except Exception:
                    response.text = html_content or ""

        return response
