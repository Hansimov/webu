from tclogger import norm_path, logger, logstr
from urllib.parse import quote, urlparse


WEBU_LIB_ROOT = norm_path(__file__).parents[1]
WEBU_SRC_ROOT = norm_path(__file__).parents[2]
WEBU_DATA_ROOT = WEBU_SRC_ROOT / "data"
WEBU_HTML_ROOT = WEBU_DATA_ROOT / "htmls"


def xquote(s: str) -> str:
    return quote(s, safe="")


def has_suffix(name: str) -> bool:
    return "." in name


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
    params = parsed.query
    anchor = parsed.fragment
    if keep_params and params:
        p += "?" + params
    if keep_anchor and anchor:
        p += "#" + anchor
    if not keep_slash and p.endswith("/"):
        p = p.rstrip("/")
    if p.startswith("/"):
        p = p.lstrip("/")
    if p and append_html and not has_suffix(p):
        p += ".html"
    if keep_domain:
        p = f"{parsed.netloc}/{p}"
    if keep_scheme:
        p = f"{parsed.scheme}://{p}"

    return xquote(p)


def url_to_segs(
    url: str,
    keep_scheme: bool = False,
    keep_domain: bool = False,
    keep_params: bool = False,
    keep_anchor: bool = False,
    keep_slash: bool = False,
    append_html: bool = False,
    seg_params: bool = False,
    seg_anchor: bool = False,
) -> list[str]:
    """<scheme>://<netloc>/<path>;<params>?<query>#<fragment>"""
    segs = []

    parsed = urlparse(url)
    p = parsed.path

    scheme = parsed.scheme
    domain = parsed.netloc
    if keep_scheme and scheme:
        segs.append(f"{scheme}://")
    if keep_domain and domain:
        segs.append(domain)

    path_segs = [seg for seg in p.split("/") if seg]
    if path_segs:
        pseg = path_segs[-1]
        if not keep_slash and p.endswith("/"):
            pseg = pseg.rstrip("/")
        if pseg.startswith("/"):
            pseg = pseg.lstrip("/")
        if pseg and append_html and not has_suffix(pseg):
            pseg += ".html"
    else:
        pseg = ""
    if pseg:
        path_segs[-1] = pseg
    segs.extend(path_segs)

    params = parsed.query
    anchor = parsed.fragment
    if keep_params and params:
        params_str = "?" + params
        if seg_params:
            segs.append(params_str)
        else:
            segs[-1] += params_str
    if keep_anchor and anchor:
        anchor_str = "#" + anchor
        if seg_anchor:
            segs.append(anchor_str)
        else:
            segs[-1] += anchor_str

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
        append_html=False,
    )


def url_to_folder_and_html_name(url: str) -> tuple[str, str]:
    folder_name = url_to_folder(url)
    html_name = url_to_html_name(url, keep_domain=False)
    return folder_name, html_name


def url_to_html_segs(
    url: str,
    keep_domain: bool = True,
    keep_params: bool = True,
    keep_anchor: bool = False,
    seg_params: bool = True,
    seg_anchor: bool = True,
) -> list[str]:
    return url_to_segs(
        url,
        keep_scheme=False,
        keep_domain=keep_domain,
        keep_params=keep_params,
        keep_anchor=keep_anchor,
        keep_slash=False,
        append_html=False,
        seg_params=seg_params,
        seg_anchor=seg_anchor,
    )


def test_url_to_html_name():
    urls = [
        "https://docs.python.org/3.14/whatsnew/3.14.html#incompatible-changes",
        "https://github.com/vllm-project/vllm/blob/main/docs/serving/offline_inference.md#ray-data-llm-api",
        "https://docs.vllm.ai/en/latest/examples/online_serving/api_client.html#api-client",
        "https://www.google.com/search?q=python+tutorial&source=lnt&tbs=qdr:w&sa=X&biw=1280&bih=613&dpr=1.5",
    ]
    for url in urls:
        logger.note(f"> {url}")
        folder, html_name = url_to_folder_and_html_name(url)
        logger.mesg(f"  * {folder} / {logstr.okay(html_name)}")
        segs = url_to_segs(
            url,
            keep_domain=True,
            keep_params=True,
            keep_anchor=True,
            seg_params=True,
            seg_anchor=False,
        )
        segs_str = " / ".join(segs)
        logger.file(f"  * {segs_str}")


if __name__ == "__main__":
    test_url_to_html_name()

    # python -m webu.files.paths
