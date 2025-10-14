"""
This module is evolved from my previous projects:
- https://github.com/Hansimov/purehtml/blob/main/src/purehtml/purehtml.py
- https://github.com/Hansimov/purepage/blob/main/purepage.user.js
"""

import concurrent.futures
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Doctype
from copy import deepcopy
from pathlib import Path
from tclogger import logger, logstr, PathType, PathsType, StrsType, norm_path
from typing import Union, Literal

from .constants import (
    REMOVE_TAGS,
    REMOVE_CLASSES,
    HEADER_TAGS,
    ENV_TAGS,
    GROUP_TAGS,
    FORMAT_TAGS,
    IMG_TAGS,
    PROTECT_TAGS,
    PROTECT_ATTRS,
)
from .math import MathPurifier
from .html2md import html2md


def is_element_has_tags(element: BeautifulSoup, tags: StrsType) -> bool:
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        if element.name == tag:
            return True
        for child in element.find_all():
            if child.name == tag:
                return True
    return False


def is_element_under_tags(element: BeautifulSoup, tags: StrsType) -> bool:
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        if element.name == tag:
            return True
        for parent in element.parents:
            if parent.name == tag:
                return True
    return False


def add_url_div(soup: BeautifulSoup, url: str, div_text: str = None) -> BeautifulSoup:
    """Add a div tag with url info at body head.
    <div>Page URL: <a href="{url}">{url}</a></div>
    """
    if not url:
        return soup
    url_div = soup.new_tag("div")
    if not div_text:
        url_div.string = "Page URL: "
    else:
        url_div.string = div_text
    url_a = soup.new_tag(
        "a", attrs={"href": url, "target": "_blank", "rel": "noreferrer"}
    )
    url_a.string = url
    url_div.append(url_a)
    if soup.body:
        soup.body.insert(0, url_div)
    else:
        soup.insert(0, url_div)
    return soup


class HTMLPurifier:
    def __init__(
        self,
        url: str = None,
        output_format: Literal["markdown", "html"] = "html",
        keep_href: bool = False,
        keep_group_tags: bool = True,
        keep_format_tags: bool = True,
        keep_img_tags: bool = False,
        math_style: Literal["latex", "latex_in_tag", "html"] = "latex",
        verbose: bool = False,
    ):
        self.url = url
        self.output_format = output_format or "html"
        self.keep_href = keep_href
        self.keep_group_tags = keep_group_tags
        self.keep_format_tags = keep_format_tags
        self.keep_img_tags = keep_img_tags
        self.math_style = math_style
        self.verbose = verbose
        self.init_extra_purifiers()

    def init_extra_purifiers(self):
        self.extra_purifiers = [
            MathPurifier(),
        ]

    def is_element_protected(self, element: BeautifulSoup):
        protect_tags = PROTECT_TAGS
        if self.keep_img_tags:
            protect_tags.extend(IMG_TAGS)
        return (element.name in protect_tags) or any(
            parent.name in protect_tags for parent in element.parents
        )

    def add_extra_elements(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Add extra informative elements: url div."""
        if self.url:
            soup = add_url_div(soup, self.url)
        return soup

    def filter_elements(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Filter elements by patterns of tags, classes and ids."""
        # Remove <!DOCTYPE ...>
        doctype_element = soup.find(string=lambda text: isinstance(text, Doctype))
        if doctype_element:
            doctype_element.extract()

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
        keep_tags = deepcopy(ENV_TAGS)
        if self.keep_group_tags:
            keep_tags.extend(GROUP_TAGS)
        if self.keep_format_tags:
            keep_tags.extend(FORMAT_TAGS)

        for element in soup.find_all():
            if self.is_element_protected(element):
                continue

            is_in_keep_tags = element.name in keep_tags
            if is_in_protect_tags:
                continue

            if not is_in_keep_tags:
                element.unwrap()
                unwrapped_element_count += 1
            elif not element.get_text().strip():
                if self.keep_img_tags and is_element_has_tags(element, IMG_TAGS):
                    pass
                else:
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
                # if inside <pre> or <code>, skip
                if is_element_under_tags(element, ["pre", "code"]):
                    continue
                ele_str = element.string
                # if all whitespaces, remove element
                if re.match("^\s+$", ele_str):
                    element.extract()
                    continue
                # if header tags, strip all whitespaces
                if is_element_under_tags(element, HEADER_TAGS):
                    ele_str = ele_str.strip()
                # else, convert multiple whitespaces to single
                else:
                    ele_str = re.sub(r"\s+", " ", ele_str)
                element.replace_with(ele_str)

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

        soup = self.add_extra_elements(soup)
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
    url: str = None,
    output_format: Literal["markdown", "html"] = "html",
    keep_href: bool = False,
    keep_group_tags: bool = True,
    keep_format_tags: bool = True,
    keep_img_tags: bool = False,
    math_style: Literal["latex", "latex_in_tag", "html"] = "latex",
    verbose: bool = False,
):
    purifier = HTMLPurifier(
        url=url,
        output_format=output_format,
        keep_href=keep_href,
        keep_group_tags=keep_group_tags,
        keep_format_tags=keep_format_tags,
        keep_img_tags=keep_img_tags,
        math_style=math_style,
        verbose=verbose,
    )
    return purifier.purify_str(html_str)


def purify_html_file(
    html_path: Union[Path, str],
    output_format: Literal["markdown", "html"] = "html",
    keep_href: bool = False,
    keep_group_tags: bool = True,
    keep_format_tags: bool = True,
    keep_img_tags: bool = False,
    math_style: Literal["latex", "latex_in_tag", "html"] = "latex",
    verbose: bool = False,
):
    purifier = HTMLPurifier(
        output_format=output_format,
        keep_href=keep_href,
        keep_group_tags=keep_group_tags,
        keep_format_tags=keep_format_tags,
        keep_img_tags=keep_img_tags,
        math_style=math_style,
        verbose=verbose,
    )
    return purifier.purify_file(html_path)


def purify_html_files(
    html_paths: list[Union[Path, str]],
    output_format: Literal["markdown", "html"] = "html",
    keep_href: bool = False,
    keep_group_tags: bool = True,
    keep_format_tags: bool = True,
    keep_img_tags: bool = False,
    math_style: Literal["latex", "latex_in_tag", "html"] = "latex",
    verbose: bool = False,
):
    purifier = HTMLPurifier(
        output_format=output_format,
        keep_href=keep_href,
        keep_group_tags=keep_group_tags,
        keep_format_tags=keep_format_tags,
        keep_img_tags=keep_img_tags,
        math_style=math_style,
        verbose=verbose,
    )
    batch_purifier = BatchHTMLPurifier(purifier=purifier)
    return batch_purifier.purify_files(html_paths)


def test_purify_html_files():
    from ..files.paths import WEBU_DATA_ROOT

    html_root = WEBU_DATA_ROOT / "htmls" / "weibo"
    html_paths = sorted(list(html_root.rglob("*.html")), key=lambda x: x.name)
    html_path_and_purified_content_list = purify_html_files(
        html_paths,
        output_format="html",
        keep_href=True,
        keep_group_tags=True,
        keep_format_tags=True,
        keep_img_tags=False,
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
