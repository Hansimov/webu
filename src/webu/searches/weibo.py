from DrissionPage._pages.chromium_tab import ChromiumTab
from typing import TypedDict, Optional, Literal
from tclogger import logger, logstr, brk, PathType, norm_path
from urllib.parse import urlencode

from ..browsers.chrome import ChromeClient
from ..files.paths import xquote
from .constants import CHROME_CONFIGS


WEIBO_SEARCH_GENERAL_URL = "https://s.weibo.com/weibo"
WEIBO_SEARCH_AI_URL = "https://s.weibo.com/aisearch"
WEIBO_SEARCH_REALTIME_URL = "https://s.weibo.com/realtime"
WEIBO_SEARCH_PIC_URL = "https://s.weibo.com/pic"
WEIBO_HTMLS_DIR = norm_path("./data/htmls/weibo")

CHANNEL_URLS = {
    "general": WEIBO_SEARCH_GENERAL_URL,
    "ai": WEIBO_SEARCH_AI_URL,
    "realtime": WEIBO_SEARCH_REALTIME_URL,
    "pic": WEIBO_SEARCH_PIC_URL,
}
CHANNEL_PARAMS = {
    "general": {"Referer": "weibo"},
    "realtime": {"rd": "realtime", "tw": "realtime", "Refer": "realtime"},
    "ai": {"Referer": "aisearch"},
    "pic": {"Referer": "pic"},
}

CHANNEL_TYPE = Literal["general", "ai", "realtime", "pic"]
CHANNEL_DEFAULT = "realtime"


class WeiboSearchConfigType(TypedDict):
    proxy: Optional[str]
    chrome_port: Optional[int]
    htmls_dir: Optional[PathType]


class WeiboSearcher:
    def __init__(self, proxy: str = None, htmls_dir: PathType = None):
        self.proxy = proxy
        self.htmls_dir = norm_path(htmls_dir or WEIBO_HTMLS_DIR)
        self.chrome_client = None

    def init_chrome_client(self):
        if not self.chrome_client:
            self.chrome_client = ChromeClient(**CHROME_CONFIGS, proxy=self.proxy)
            self.chrome_client.start_client()

    def send_request(self, query: str, channel: CHANNEL_TYPE) -> ChromiumTab:
        logger.note(f"> Query: {logstr.mesg(brk(query))}")
        url_head = CHANNEL_URLS.get(channel, WEIBO_SEARCH_GENERAL_URL)
        channel_params = CHANNEL_PARAMS.get(channel, {})
        url_params = {"q": query, **channel_params}
        encoded_url_params = urlencode(url_params)
        url = f"{url_head}?{encoded_url_params}"
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
        channel: CHANNEL_TYPE = CHANNEL_DEFAULT,
        overwrite: bool = False,
    ):
        logger.note(f"> Searching weibo: [{query}] ({channel})")
        html_name = f"{xquote(query)}.html"
        html_path = self.htmls_dir / channel / html_name
        if html_path.exists() and not overwrite:
            logger.okay(f"> Existed html: {logstr.okay(brk(html_path))}")
        else:
            tab = self.send_request(query, channel=channel)
            self.save_response(tab=tab, save_path=html_path)
        return html_path


def test_weibo_searcher():
    searcher = WeiboSearcher()
    query = "OpenAI 的开源模型"
    channel = "realtime"
    searcher.search(query, channel=channel, overwrite=True)


if __name__ == "__main__":
    test_weibo_searcher()

    # python -m webu.sites.weibo
