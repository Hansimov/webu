import argparse

from copy import deepcopy
from DrissionPage import Chromium, ChromiumOptions
from pyvirtualdisplay import Display
from tclogger import logger, logstr, dict_to_str, PathType, norm_path, strf_path, brk
from typing import Union, TypedDict, Optional

CHROME_USER_DATA_DIR = norm_path("~/.config/google-chrome")


class ChromeClientConfigType(TypedDict):
    uid: Optional[Union[int, str]]
    port: Optional[Union[int, str]]
    proxy: Optional[str]
    user_data_dir: Optional[PathType]
    use_vdisp: Optional[bool]
    verbose: Optional[bool]


class ChromeClient:
    def __init__(
        self,
        uid: Union[int, str] = None,
        port: Union[int, str] = None,
        proxy: str = None,
        user_data_dir: PathType = None,
        use_vdisp: bool = False,
        verbose: bool = False,
    ):
        self.uid = uid
        self.port = port
        self.proxy = proxy
        self.user_data_dir = user_data_dir or CHROME_USER_DATA_DIR
        self.is_browser_opened = False
        self.use_vdisp = use_vdisp
        self.is_using_vdisp = False
        self.verbose = verbose

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
        if self.verbose:
            info_dict["verbose"] = self.verbose
        if info_dict:
            logger.mesg(dict_to_str(info_dict), indent=2)
        self.chrome_options = chrome_options

    def has_browser_instance(self) -> bool:
        return hasattr(self, "browser") and isinstance(self.browser, Chromium)

    def has_browser_opened(self) -> bool:
        return self.has_browser_instance() and self.is_browser_opened

    def open_browser(self):
        if self.is_browser_opened:
            return
        logger.note("> Opening browser ...")
        self.init_options()
        self.browser = Chromium(addr_or_opts=self.chrome_options)
        self.is_browser_opened = True

    def close_browser(self):
        if self.has_browser_opened():
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

    @property
    def latest_tab(self):
        if self.has_browser_instance():
            return self.browser.latest_tab
        else:
            return None

    def close_other_tabs(self, create_new_tab: bool = True):
        if self.has_browser_instance():
            if create_new_tab:
                self.browser.new_tab()
            self.latest_tab.close(others=True)

    def get_url_html(self, url: str, interval: int = 5, timeout: int = 30) -> str:
        logger.note(f"> URL: {logstr.mesg(url)}")
        tab = self.latest_tab
        tab.set.load_mode.none()
        tab.get(url, interval=interval, timeout=timeout)
        logger.mesg(f"  ✓ Title: {brk(tab.title)}")
        return tab.html


DEFAULT_CHROME_CLIENT_CONFIG = {
    "uid": "1000",
    "port": 29001,
    "proxy": None,
    "user_data_dir": CHROME_USER_DATA_DIR,
    "use_vdisp": False,
    "verbose": False,
}


class ChromeClientArgParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument("-u", "--uid", type=str)
        self.add_argument("-p", "--port", type=int)
        self.add_argument("-x", "--proxy", type=str)
        self.add_argument("-c", "--user-data-dir", type=str)
        self.add_argument("-s", "--use-vdisp", action="store_true")
        self.add_argument("-v", "--verbose", action="store_true")
        self.args, _ = self.parse_known_args()

    def to_dict(self, skip_none: bool = True) -> ChromeClientConfigType:
        arg_keys = ["uid", "port", "proxy", "user_data_dir", "use_vdisp", "verbose"]
        arg_kvs = {}
        for key in arg_keys:
            if skip_none and getattr(self.args, key) is None:
                continue
            arg_kvs[key] = getattr(self.args, key)
        return arg_kvs


class ChromeClientByConfig(ChromeClient):
    """Priority: default config < cli args < input config"""

    def __init__(self, config: ChromeClientConfigType = None):
        self.config = deepcopy(DEFAULT_CHROME_CLIENT_CONFIG)
        arg_parser = ChromeClientArgParser()
        arg_config = arg_parser.to_dict()
        if arg_config:
            self.config.update(arg_config)
        if config:
            self.config.update(config)
        super().__init__(**self.config)


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
    tab = client.latest_tab
    sleep(2)
    client.stop_client(close_browser=False)


def test_chrome_client_by_config():
    from time import sleep

    client = ChromeClientByConfig()
    client.start_client()
    tab = client.latest_tab
    sleep(2)
    client.stop_client(close_browser=False)


if __name__ == "__main__":
    # test_chrome_client()
    test_chrome_client_by_config()

    # python -m webu.browsers.chrome
    # python -m webu.browsers.chrome -u 1001 -p 29002 -x "http://127.0.0.1:11111"
