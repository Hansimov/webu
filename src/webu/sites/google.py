import requests

from typing import TypedDict, Optional
from tclogger import logger, logstr, brk, PathType, norm_path

from ..urls import url_to_name


REQUESTS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36 Edg/111.0.1661.62",
}

GOOGLE_URL = "https://www.google.com/search"
GOOGLE_HTMLS_DIR = norm_path("./data/htmls/google")


class GoogleSearchConfigType(TypedDict):
    proxy: Optional[str]
    htmls_dir: Optional[PathType]


class GoogleSearcher:
    def __init__(self, proxy: str = None, htmls_dir: PathType = None):
        self.proxy = proxy
        self.htmls_dir = norm_path(htmls_dir or GOOGLE_HTMLS_DIR)
        self.init_request_params()

    def init_request_params(self):
        req_params = {
            "url": GOOGLE_URL,
            "headers": REQUESTS_HEADERS,
        }
        if self.proxy:
            req_params["proxies"] = {"http": self.proxy, "https": self.proxy}
        self.req_params = req_params

    def send_request(self, query: str, result_num=10) -> requests.Response:
        logger.note(f"> Query: {logstr.mesg(brk(query))}")
        req = requests.get(
            **self.req_params,
            params={"q": query, "num": result_num},
        )
        return req

    def save_response(self, resp: requests.Response, save_path: PathType):
        logger.note(f"> Save html: {logstr.okay(brk(save_path))}")
        save_path = norm_path(save_path)
        if not save_path.parent.exists():
            save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as wf:
            wf.write(resp.content)

    def search(
        self,
        query: str,
        result_num: int = 10,
        safe: bool = False,
        overwrite: bool = False,
    ):
        logger.note(f"Searching: [{query}]")
        html_name = f"{url_to_name(query)}.html"
        html_path = self.htmls_dir / html_name
        if html_path.exists() and not overwrite:
            logger.okay(f"> Existed html: {logstr.okay(brk(html_path))}")
        else:
            resp = self.send_request(query, result_num=result_num)
            self.save_response(resp=resp, save_path=html_path)
        return html_path


def test_google_searcher():
    searcher = GoogleSearcher(proxy="http://127.0.0.1:11111")
    query = "python tutorial"
    searcher.search(query, overwrite=True)


if __name__ == "__main__":
    test_google_searcher()

    # python -m webu.sites.google
