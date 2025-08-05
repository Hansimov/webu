"""
This module is evolved from my previous projects:
- https://github.com/Hansimov/purehtml/blob/main/src/purehtml/purehtml.py
- https://github.com/Hansimov/purepage/blob/main/purepage.user.js
"""

import concurrent.futures
import re

from bs4 import BeautifulSoup, Comment, NavigableString
from pathlib import Path
from tclogger import logger, logstr, PathType, PathsType, norm_path
from typing import Union, Literal

from .math import MathPurifier

from .constants import (
    REMOVE_TAGS,
    REMOVE_CLASSES,
    ENV_TAGS,
    GROUP_TAGS,
    FORMAT_TAGS,
    PROTECT_TAGS,
    PROTECT_ATTRS,
)
from .html2md import html2md


class HTMLPurifier:
    def __init__(
        self,
        output_format: Literal["markdown", "html"] = "html",
        keep_href: bool = False,
        keep_format_tags: bool = True,
        keep_group_tags: bool = True,
        math_style: Literal["latex", "latex_in_tag", "html"] = "latex",
        verbose: bool = False,
    ):
        self.output_format = output_format
        self.keep_href = keep_href
        self.keep_format_tags = keep_format_tags
        self.keep_group_tags = keep_group_tags
        self.math_style = math_style
        self.verbose = verbose
        self.init_extra_purifiers()

    def init_extra_purifiers(self):
        self.extra_purifiers = [
            MathPurifier(),
        ]

    def is_element_protected(self, element: BeautifulSoup):
        return (element.name in PROTECT_TAGS) or any(
            parent.name in PROTECT_TAGS for parent in element.parents
        )

    def filter_elements(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Filter elements by patterns of tags, classes and ids."""
        # Remove comments
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        comment: BeautifulSoup
        for comment in comments:
            comment.extract()

        # Remove elements with patterns of classes and ids
        removed_element_count = 0
        unwrapped_element_count = 0
        element: BeautifulSoup
        for element in soup.find_all():
            try:
                class_attr = element.get("class", [])
                class_str = " ".join(list(class_attr))
            except:
                class_str = ""

            try:
                id_str = element.get("id", "")
            except:
                id_str = ""

            class_id_str = f"{class_str} {id_str}"

            is_in_remove_classes = any(
                re.search(remove_class, class_id_str, flags=re.IGNORECASE)
                for remove_class in REMOVE_CLASSES
            )
            is_in_remove_tags = element.name in REMOVE_TAGS
            is_in_protect_tags = self.is_element_protected(element)

            if (not is_in_protect_tags) and (is_in_remove_tags or is_in_remove_classes):
                element.extract()
                removed_element_count += 1

        # Unwrap tags by [env, group, format], and remove empty elements
        KEEP_TAGS = ENV_TAGS
        if self.keep_group_tags:
            KEEP_TAGS.extend(GROUP_TAGS)
        if self.keep_format_tags:
            KEEP_TAGS.extend(FORMAT_TAGS)

        for element in soup.find_all():
            if self.is_element_protected(element):
                continue

            is_in_keep_tags = element.name in KEEP_TAGS
            if is_in_protect_tags:
                continue

            if not is_in_keep_tags:
                element.unwrap()
                unwrapped_element_count += 1
            elif not element.get_text().strip():
                element.extract()
                removed_element_count += 1
            else:
                pass
        remained_element_count = len(soup.find_all())

        logger.mesg(
            f"  - Elements: "
            f"{logstr.okay(remained_element_count)} (Remained) "
            f"/ {logstr.warn(removed_element_count)} (Removed)"
            f"/ {logstr.mesg(unwrapped_element_count)} (Unwrapped)"
        )

        return soup

    def filter_attrs(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Filter attrs of elements."""
        element: BeautifulSoup
        for element in soup.find_all():
            if self.is_element_protected(element):
                continue
            protected_attrs = {
                attr_key: element.get(attr_key)
                for attr_key in PROTECT_ATTRS
                if element.get(attr_key)
            }
            if element.name == "a":
                if self.keep_href:
                    element.attrs = {"href": element.get("href")}
                else:
                    element.attrs = {}
            elif element.name == "img":
                element.attrs = {"alt": element.get("alt") or None}
                if self.keep_href:
                    element["src"] = element.get("src")
                else:
                    element.attrs = {}
            else:
                element.attrs = {}
            if protected_attrs:
                element.attrs.update(protected_attrs)
        return soup

    def apply_extra_purifiers(self, soup: BeautifulSoup) -> BeautifulSoup:
        for purifier in self.extra_purifiers:
            for element in soup.find_all():
                if purifier.match(element):
                    purifier.purify(element)
        return soup

    def flatten_elements(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Flatten nested div elements
        If a div only contains one child, and which is also a div, then unwrap the parent div.
        """
        element: BeautifulSoup
        for element in soup.find_all("div"):
            parent: BeautifulSoup = element.parent
            if (
                not parent
                or self.is_element_protected(parent)
                or parent.attrs.get("id")
            ):
                continue
            if parent.name == "div" and len(parent.find_all(recursive=False)) == 1:
                parent.unwrap()
        return soup

    def strip_elements(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Strip whitespaces among tags."""
        element: BeautifulSoup
        for element in soup.find_all(string=True):
            if isinstance(element, NavigableString):
                stripped_text = element.strip()
                if stripped_text:
                    element.replace_with(stripped_text)
                else:
                    element.extract()

        return soup

    def read_html_file(self, html_path: PathType) -> str:
        logger.note(f"> Purifying content in: {html_path}")

        html_path = norm_path(html_path)

        if not html_path.exists():
            warn_msg = f"File not found: {html_path}"
            logger.warn(warn_msg)
            raise FileNotFoundError(warn_msg)

        encodings = ["utf-8", "latin-1"]
        for encoding in encodings:
            try:
                with open(html_path, "r", encoding=encoding, errors="ignore") as rf:
                    html_str = rf.read()
                    return html_str
            except UnicodeDecodeError:
                pass
        else:
            warn_msg = f"No matching encodings: {html_path}"
            logger.warn(warn_msg)
            raise UnicodeDecodeError(warn_msg)

    def purify_str(self, html_str: str) -> str:
        logger.enter_quiet(not self.verbose)
        if not html_str:
            return ""

        soup = BeautifulSoup(html_str, "html.parser")

        soup = self.filter_elements(soup)
        soup = self.filter_attrs(soup)
        soup = self.apply_extra_purifiers(soup)
        soup = self.flatten_elements(soup)
        soup = self.strip_elements(soup)

        html_str = str(soup)
        if self.output_format == "markdown":
            html_str = html2md(html_str).strip()

        html_str = html_str.strip()

        logger.exit_quiet(not self.verbose)
        return html_str

    def purify_file(
        self,
        html_path: PathType,
        save: bool = True,
        output_path: Path = None,
    ) -> dict:
        logger.enter_quiet(not self.verbose)
        html_path = norm_path(html_path)
        html_str = self.read_html_file(html_path)
        if not html_str:
            return {"path": html_path, "output_path": None, "output": ""}
        else:
            result = self.purify_str(html_str)
        if save:
            if not output_path:
                if self.output_format == "html":
                    output_path = norm_path(str(html_path) + ".pure")
                else:
                    output_path = norm_path(str(html_path) + ".md")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as wf:
                wf.write(result)
            logger.success(f"  > Saved to: {output_path}")
        logger.exit_quiet(not self.verbose)
        return {
            "path": html_path,
            "output_path": output_path,
            "output": result,
        }


class BatchHTMLPurifier:
    def __init__(self, purifier: HTMLPurifier):
        self.html_path_and_purified_content_list = []
        self.done_count = 0
        self.purifier = purifier

    def purify_single_html_file(self, html_path: PathType):
        result = self.purifier.purify_file(html_path)
        self.html_path_and_purified_content_list.append(
            {
                "path": html_path,
                "output": result["output"],
                "output_path": result["output_path"],
                "format": self.purifier.output_format,
            }
        )
        self.done_count += 1

        if self.purifier.verbose:
            logger.success(
                f"> Purified [{self.done_count}/{self.total_count}]: [{html_path}]"
            )

    def purify_files(self, html_paths: PathsType):
        self.html_path = html_paths
        self.total_count = len(self.html_path)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(self.purify_single_html_file, html_path)
                for html_path in self.html_path
            ]
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                result = future.result()

        return self.html_path_and_purified_content_list


def purify_html_str(
    html_str: str,
    output_format: Literal["markdown", "html"] = "html",
    keep_href: bool = False,
    keep_format_tags: bool = True,
    keep_group_tags: bool = True,
    math_style: Literal["latex", "latex_in_tag", "html"] = "latex",
    verbose: bool = False,
):
    purifier = HTMLPurifier(
        output_format=output_format,
        keep_href=keep_href,
        keep_format_tags=keep_format_tags,
        keep_group_tags=keep_group_tags,
        math_style=math_style,
        verbose=verbose,
    )
    return purifier.purify_str(html_str)


def purify_html_file(
    html_path: Union[Path, str],
    output_format: Literal["markdown", "html"] = "html",
    keep_href: bool = False,
    keep_format_tags: bool = True,
    keep_group_tags: bool = True,
    math_style: Literal["latex", "latex_in_tag", "html"] = "latex",
    verbose: bool = False,
):
    purifier = HTMLPurifier(
        output_format=output_format,
        keep_href=keep_href,
        keep_format_tags=keep_format_tags,
        keep_group_tags=keep_group_tags,
        math_style=math_style,
        verbose=verbose,
    )
    return purifier.purify_file(html_path)


def purify_html_files(
    html_paths: list[Union[Path, str]],
    output_format: Literal["markdown", "html"] = "html",
    keep_href: bool = False,
    keep_format_tags: bool = True,
    keep_group_tags: bool = True,
    math_style: Literal["latex", "latex_in_tag", "html"] = "latex",
    verbose: bool = False,
):
    purifier = HTMLPurifier(
        output_format=output_format,
        keep_href=keep_href,
        keep_format_tags=keep_format_tags,
        keep_group_tags=keep_group_tags,
        math_style=math_style,
        verbose=verbose,
    )
    batch_purifier = BatchHTMLPurifier(purifier=purifier)
    return batch_purifier.purify_files(html_paths)


def test_purify_html_files():
    from ..constants import WEBU_DATA_ROOT

    html_root = WEBU_DATA_ROOT / "htmls" / "google"
    html_paths = sorted(list(html_root.glob("*.html")), key=lambda x: x.name)
    html_path_and_purified_content_list = purify_html_files(
        html_paths,
        output_format="html",
        keep_href=True,
        keep_format_tags=True,
        keep_group_tags=True,
        math_style="html",
        verbose=False,
    )
    for item in html_path_and_purified_content_list:
        html_path = item["path"]
        purified_content = item["output"]
        output_path = item["output_path"]
        # logger.line(purified_content)
        # logger.file(html_path)
        logger.okay(f"* {output_path.name}")


if __name__ == "__main__":
    test_purify_html_files()

    # python -m webu.pures.purehtml
