from DrissionPage._pages.chromium_tab import ChromiumTab
from typing import TypedDict, Optional
from tclogger import logger, logstr, brk, PathType, norm_path
from urllib.parse import urlencode

from ..browsers.chrome import ChromeClient
from ..files.paths import xquote
from .constants import PROXY_CHROME_CONFIGS


GOOGLE_URL = "https://www.google.com/search"
GOOGLE_HTMLS_DIR = norm_path("./data/htmls/google")


class GoogleSearchConfigType(TypedDict):
    proxy: Optional[str]
    htmls_dir: Optional[PathType]


class GoogleSearcher:
    def __init__(self, proxy: str = None, htmls_dir: PathType = None):
        self.proxy = proxy
        self.htmls_dir = norm_path(htmls_dir or GOOGLE_HTMLS_DIR)
        self.chrome_client = None

    def init_chrome_client(self):
        if not self.chrome_client:
            chrome_configs = PROXY_CHROME_CONFIGS
            if self.proxy:
                chrome_configs["proxy"] = self.proxy
            self.chrome_client = ChromeClient(**chrome_configs)
            self.chrome_client.start_client()

    def send_request(self, query: str, result_num: int = 10) -> ChromiumTab:
        logger.note(f"> Query: {logstr.mesg(brk(query))}")
        url_params = {"q": query, "num": result_num}
        encoded_url_params = urlencode(url_params)
        url = f"{GOOGLE_URL}?{encoded_url_params}"
        self.init_chrome_client()
        tab = self.chrome_client.browser.latest_tab
        logger.mesg(f"  * {url}")
        tab.get(url)
        return tab

    def save_response(self, tab: ChromiumTab, save_path: PathType):
        logger.note(f"> Save html: {logstr.okay(brk(save_path))}")
        save_path = norm_path(save_path)
        if not save_path.parent.exists():
            save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as wf:
            wf.write(tab.html)

    def search(
        self,
        query: str,
        result_num: int = 10,
        safe: bool = False,
        overwrite: bool = False,
    ):
        logger.note(f"Searching: [{query}]")
        html_name = f"{xquote(query)}.html"
        html_path = self.htmls_dir / html_name
        if html_path.exists() and not overwrite:
            logger.okay(f"> Existed html: {logstr.okay(brk(html_path))}")
        else:
            tab = self.send_request(query, result_num=result_num)
            self.save_response(tab=tab, save_path=html_path)
        return html_path


def test_google_searcher():
    searcher = GoogleSearcher()
    query = "OpenAI latest opensource model"
    searcher.search(query, overwrite=True)


if __name__ == "__main__":
    test_google_searcher()

    # python -m webu.sites.google
