from tclogger import logger, PathType
from typing import Literal

from ..browsers.chrome import ChromeClient, ChromeClientByConfig
from ..files.paths import WEBU_HTML_ROOT, url_to_domain, url_to_segs_list
from ..pures.purehtml import purify_html_str

DumpPathType = Literal["domain_path", "path_segs"]


class UrlPager:
    def __init__(self, client: ChromeClient = None, root: PathType = None):
        self.client = client or ChromeClientByConfig()
        self.root = root or WEBU_HTML_ROOT

    def fetch_url(self, url: str, output_path: PathType = None):
        self.client.start_client()
        html_str = self.client.get_url_html(url)
        pure_html_str = purify_html_str(html_str, output_format="markdown")
        logger.okay(pure_html_str)
        self.client.stop_client()


def test_url_pager():
    client = ChromeClientByConfig()
    client.verbose = True
    pager = UrlPager(client=client)
    url = "https://developers.weixin.qq.com/miniprogram/dev/framework/server-ability/backend-api.html"
    pager.fetch_url(url)


if __name__ == "__main__":
    test_url_pager()

    # python -m webu.workers.page
