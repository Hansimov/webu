from DrissionPage import Chromium, ChromiumOptions
from pyvirtualdisplay import Display
from tclogger import logger, dict_to_str, PathType, norm_path, strf_path
from typing import Union, TypedDict, Optional

CHROME_USER_DATA_DIR = norm_path("~/.config/google-chrome")


class ChromeClientConfigType(TypedDict):
    uid: Optional[Union[int, str]]
    port: Optional[Union[int, str]]
    proxy: Optional[str]
    user_data_dir: Optional[PathType]
    use_vdisp: Optional[bool]


class ChromeClient:
    def __init__(
        self,
        uid: Union[int, str] = None,
        port: Union[int, str] = None,
        proxy: str = None,
        user_data_dir: PathType = None,
        use_vdisp: bool = False,
    ):
        self.uid = uid
        self.port = port
        self.proxy = proxy
        self.user_data_dir = user_data_dir or CHROME_USER_DATA_DIR
        self.is_browser_opened = False
        self.use_vdisp = use_vdisp
        self.is_using_vdisp = False

    def open_vdisp(self):
        if self.use_vdisp and not self.is_using_vdisp:
            self.display = Display()
            self.display.start()
            self.is_using_vdisp = True

    def close_vdisp(self):
        if self.is_using_vdisp and hasattr(self, "display"):
            self.display.stop()
        self.is_using_vdisp = False

    def init_options(self):
        info_dict = {}
        chrome_options = ChromiumOptions()
        if self.uid:
            self.user_data_path = norm_path(self.user_data_dir) / str(self.uid)
            chrome_options.set_user_data_path(self.user_data_path)
            info_dict["uid"] = self.uid
            info_dict["user_data_path"] = strf_path(self.user_data_path)
        if self.port:
            chrome_options.set_local_port(self.port)
            info_dict["port"] = self.port
        if self.proxy:
            chrome_options.set_proxy(self.proxy)
            info_dict["proxy"] = self.proxy
        if info_dict:
            logger.mesg(dict_to_str(info_dict), indent=2)
        self.chrome_options = chrome_options

    def open_browser(self):
        if self.is_browser_opened:
            return
        logger.note("> Opening browser ...")
        self.init_options()
        self.browser = Chromium(addr_or_opts=self.chrome_options)
        self.is_browser_opened = True

    def close_browser(self):
        if hasattr(self, "browser") and self.is_browser_opened:
            logger.note(f"> Closing browser ...")
            try:
                self.browser.quit()
            except Exception as e:
                logger.warn(f"× BrowserClient.close_browser: {e}")
            self.is_browser_opened = False

    def start_client(self):
        self.open_vdisp()
        self.open_browser()

    def stop_client(self, close_browser: bool = False):
        if close_browser:
            self.close_browser()
        self.close_vdisp()

    def close_other_tabs(self, create_new_tab: bool = True):
        if hasattr(self, "browser") and isinstance(self.browser, Chromium):
            if create_new_tab:
                self.browser.new_tab()
            self.browser.latest_tab.close(others=True)


def test_chrome_client():
    from time import sleep

    client = ChromeClient(
        uid="1000",
        port=29001,
        proxy="http://127.0.0.1:11111",
        user_data_dir="./data/chrome",
        use_vdisp=False,
    )
    client.start_client()
    tab = client.browser.latest_tab
    sleep(2)
    client.stop_client(close_browser=False)


if __name__ == "__main__":
    test_chrome_client()

    # python -m webu.chrome
