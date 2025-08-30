from tclogger import norm_path
from urllib.parse import quote, urlparse


WEBU_LIB_ROOT = norm_path(__file__).parents[1]
WEBU_SRC_ROOT = norm_path(__file__).parents[2]
WEBU_DATA_ROOT = WEBU_SRC_ROOT / "data"
WEBU_HTML_ROOT = WEBU_DATA_ROOT / "htmls"


def xquote(s: str) -> str:
    return quote(s, safe="")


def url_to_name(
    url: str,
    keep_scheme: bool = False,
    keep_domain: bool = False,
    keep_params: bool = False,
    keep_anchor: bool = False,
    keep_slash: bool = False,
    append_html: bool = False,
) -> str:
    """<scheme>://<netloc>/<path>;<params>?<query>#<fragment>"""
    parsed = urlparse(url)
    p = parsed.path
    if keep_params and parsed.params:
        p += "?" + parsed.query
    if keep_anchor and parsed.fragment:
        p += "#" + parsed.fragment
    if not keep_slash and p.endswith("/"):
        p = p.rstrip("/")
    if p.startswith("/"):
        p = p.lstrip("/")
    if p and append_html and not p.endswith(".html") and not p.endswith(".htm"):
        p += ".html"
    if keep_domain:
        p = f"{parsed.netloc}/{p}"
    if keep_scheme:
        p = f"{parsed.scheme}://{p}"

    return xquote(p)


def url_to_name_segs(
    url: str,
    keep_scheme: bool = False,
    keep_domain: bool = False,
    keep_params: bool = False,
    keep_anchor: bool = False,
    keep_slash: bool = False,
    append_html: bool = False,
) -> list[str]:
    """<scheme>://<netloc>/<path>;<params>?<query>#<fragment>"""
    parsed = urlparse(url)
    p = parsed.path
    path_segs = [seg for seg in p.split("/") if seg]
    if path_segs:
        s = path_segs[-1]
        if keep_params and parsed.params:
            s += "?" + parsed.query
        if keep_anchor and parsed.fragment:
            s += "#" + parsed.fragment
        if not keep_slash and p.endswith("/"):
            s = s.rstrip("/")
        if s.startswith("/"):
            s = s.lstrip("/")
        if s and append_html and not s.endswith(".html") and not s.endswith(".htm"):
            s += ".html"
    else:
        s = ""
    if s:
        path_segs[-1] = s
    segs = []
    if keep_scheme and parsed.scheme:
        segs.append(f"{parsed.scheme}://")
    if keep_domain and parsed.netloc:
        segs.append(parsed.netloc)
    if path_segs:
        segs.extend(path_segs)
    return [xquote(seg) for seg in segs if seg]


def url_to_folder(url: str) -> str:
    domain = urlparse(url).netloc
    return xquote(domain)


def url_to_html_name(
    url: str, keep_domain: bool = True, keep_params: bool = True
) -> str:
    return url_to_name(
        url,
        keep_scheme=False,
        keep_domain=keep_domain,
        keep_params=keep_params,
        keep_anchor=False,
        keep_slash=False,
        append_html=True,
    )


def url_to_folder_and_html_name(url: str) -> tuple[str, str]:
    folder_name = url_to_folder(url)
    html_name = url_to_html_name(url, keep_domain=False)
    return folder_name, html_name


def test_url_to_name():
    url = "https://example.com/path/to/page?query=1&page=1#section3"
    print(url_to_folder_and_html_name(url))


if __name__ == "__main__":
    test_url_to_name()

    # python -m webu.files.paths
