from bs4 import BeautifulSoup
from typing import Literal

from .constants import MATH_TAGS


class MathPurifier:
    """Purify math elements in HTML."""

    def _set_math_attrs(self, element: BeautifulSoup):
        """Set atts of <math> elements."""
        if element.name == "math":
            element.attrs = {
                "display": element.get("display", ""),
                "title": element.get("alttext", "") or element.get("title", ""),
            }

    def _unwrap_table(self, element: BeautifulSoup):
        """In ar5iv, <math> with block display is wrapped in a table."""
        if (
            element.parent.name == "td"
            and element.parent.parent.name == "tr"
            and element.parent.parent.parent.name == "table"
        ) and (
            len(element.parent.parent.find_all("td")) == 1
            and len(element.parent.parent.parent.find_all("tr")) == 1
        ):
            for i in range(3):
                element.parent.unwrap()

    def match(self, element: BeautifulSoup):
        """Check if the element is a <math> tag.
        Used by `apply_extra_purifiers()` in class `PureHtml`.
        """
        return element.name == "math"

    def purify(
        self,
        element: BeautifulSoup,
        math_style: Literal["html", "latex_in_tag", "latex_block"] = "html",
    ):
        """Used by `apply_extra_purifiers()` in class `PureHtml`."""
        self._set_math_attrs(element)
        for ele in element.find_all():
            self._set_math_attrs(ele)
            if (ele.name not in MATH_TAGS) and (not ele.find_all("math")):
                ele.extract()
            else:
                ele.attrs = {}

        display = element.get("display", "")
        if display == "block":
            self._unwrap_table(element)
            new_tag = BeautifulSoup("<div></div>", "html.parser").div
            new_tag["align"] = "center"
        else:
            new_tag = BeautifulSoup("<span></span>", "html.parser").span

        if math_style == "html":
            new_tag["title"] = element.get("title", "")
            element.attrs = {}
            element.wrap(new_tag)
        else:  # math_style == latex*
            latex_str = element.get("title", "")
            latex_str = latex_str.replace("\\displaystyle", "")

            if display == "block":
                new_tag.string = f"\n$$ {latex_str} $$\n"
            else:
                new_tag.string = f" ${latex_str}$ "

            if math_style == "latex_in_tag":
                element.replace_with(new_tag)
            else:
                element.replace_with(new_tag.string)
