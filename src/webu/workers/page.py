import argparse

from pathlib import Path
from tclogger import PathType, logger
from typing import Literal

from ..browsers.chrome import ChromeClient, ChromeClientByConfig
from ..files.paths import url_to_path
from ..pures.purehtml import purify_html_str


class UrlPager:
    def __init__(self, client: ChromeClient = None, verbose: bool = False):
        self.client = client or ChromeClientByConfig()
        self.verbose = verbose

    def fetch_url(
        self,
        url: str,
        output_path: PathType,
        output_format: Literal["markdown", "html"] = "html",
    ):
        self.client.start_client()
        html_str = self.client.get_url_html(url)
        pure_html_str = purify_html_str(
            html_str, keep_href=True, output_format=output_format
        )
        if not output_path:
            output_path = url_to_path(url=url)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.note(f"> Save fetched content to:", verbose=self.verbose)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(pure_html_str)
        logger.okay(f"  * {output_path}", verbose=self.verbose)
        self.client.stop_client()


class UrlPagerArgParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument("-i", "--url", type=str, required=True)
        self.add_argument("-r", "--output-root", type=str)
        self.add_argument("-d", "--output-dir", type=str)
        self.add_argument("-o", "--output-path", type=str)
        self.add_argument("-n", "--output-name", type=str)
        self.add_argument("-e", "--output-ext", type=str)
        self.add_argument("-m", "--output-format", type=str, default="html")
        self.args, _ = self.parse_known_args()


def unify_output_format_ext(output_format: str, output_ext: str) -> tuple[str, str]:
    """Priority: ext < format"""
    if not output_ext and not output_format:
        return "html", None

    if output_ext and not output_format:
        ext = output_ext.lstrip(".").lower()
        if ext in ["md", "markdown"]:
            output_format = "markdown"
        else:
            output_format = "html"
        # keep `ext` as is
        return output_ext, output_format

    if output_format and not output_ext:
        fmt = output_format.lstrip(".").lower()
        if fmt in ["md", "markdown"]:
            output_format = "markdown"
            # make `ext` to ".md" only if `format` is "markdown"
            output_ext = ".md"
        else:
            output_format = "html"
            # keep `ext` as is
        return output_ext, output_format

    if output_format and output_ext:
        fmt = output_ext.lstrip(".").lower()
        # norm `format` to Literal
        if fmt in ["md", "markdown"]:
            output_format = "markdown"
        else:
            output_format = "html"
        # keep `ext` as is

    return output_ext, output_format


def cli_args_to_output_path_format(args: argparse.Namespace) -> tuple[Path, str]:
    output_format, output_ext = unify_output_format_ext(
        output_format=args.output_format, output_ext=args.output_ext
    )
    path = url_to_path(
        url=args.url,
        output_root=args.output_root,
        output_dir=args.output_dir,
        output_name=args.output_name,
        output_path=args.output_path,
        output_ext=output_ext,
    )
    return output_format, path


def test_url_pager():
    client = ChromeClientByConfig()
    client.verbose = True
    pager = UrlPager(client=client)
    url = "https://developers.weixin.qq.com/miniprogram/dev/framework/server-ability/message-push.html"
    pager.fetch_url(url)


def run_url_pager():
    arg_parser = UrlPagerArgParser()
    args = arg_parser.args
    client = ChromeClientByConfig()
    pager = UrlPager(client=client, verbose=True)
    output_path, output_format = cli_args_to_output_path_format(args)
    pager.fetch_url(url=args.url, output_path=output_path, output_format=output_format)


if __name__ == "__main__":
    run_url_pager()

    # python -m webu.workers.page -x "http://127.0.0.1:11111" -i "https://arxiv.org/abs/1810.04805"
