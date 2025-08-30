from tclogger import norm_path, logger, logstr
from urllib.parse import quote, urlparse, parse_qs, urlencode


WEBU_LIB_ROOT = norm_path(__file__).parents[1]
WEBU_SRC_ROOT = norm_path(__file__).parents[2]
WEBU_DATA_ROOT = WEBU_SRC_ROOT / "data"
WEBU_HTML_ROOT = WEBU_DATA_ROOT / "htmls"


def xquote(s: str) -> str:
    return quote(s, safe="")


def has_suffix(name: str) -> bool:
    return "." in name


def filter_qs(
    qs: str, include_qs: list[str] = None, exclude_qs: list[str] = None
) -> str:
    if not qs:
        return ""
    if not include_qs and not exclude_qs:
        return qs

    qs_dict = parse_qs(qs)
    if include_qs and exclude_qs:
        filtered_dict = {
            k: v for k, v in qs_dict.items() if k in include_qs and k not in exclude_qs
        }
    elif include_qs:
        filtered_dict = {k: v for k, v in qs_dict.items() if k in include_qs}
    elif exclude_qs:
        filtered_dict = {k: v for k, v in qs_dict.items() if k not in exclude_qs}
    else:
        filtered_dict = qs_dict
    return urlencode(filtered_dict, doseq=True)


def url_to_name(
    url: str,
    keep_scheme: bool = False,
    keep_domain: bool = False,
    keep_ps: bool = False,
    keep_qs: bool = False,
    keep_anchor: bool = False,
    keep_slash: bool = False,
    append_html: bool = False,
) -> str:
    """<scheme>://<netloc>/<path>;<params>?<query>#<fragment>"""
    parsed = urlparse(url)
    p = parsed.path
    ps = parsed.params
    qs = parsed.query
    anchor = parsed.fragment
    if keep_ps and ps:
        p += ";" + ps
    if keep_qs and qs:
        p += "?" + qs
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
    keep_ps: bool = False,
    keep_qs: bool = False,
    keep_anchor: bool = False,
    keep_slash: bool = False,
    append_html: bool = False,
    seg_ps: bool = False,
    seg_qs: bool = False,
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

    ps = parsed.params
    qs = parsed.query
    anchor = parsed.fragment
    if keep_ps and ps:
        ps_str = ";" + ps
        if seg_ps:
            segs.append(";" + ps_str)
        else:
            segs[-1] += ";" + ps_str
    if keep_qs and qs:
        qs_str = "?" + qs
        if seg_qs:
            segs.append(qs_str)
        else:
            segs[-1] += qs_str
    if keep_anchor and anchor:
        anchor_str = "#" + anchor
        if seg_anchor:
            segs.append(anchor_str)
        else:
            segs[-1] += anchor_str

    return [xquote(seg) for seg in segs if seg]


def url_to_domain(url: str) -> str:
    domain = urlparse(url).netloc
    return xquote(domain)


def test_url_to_html_name():
    urls = [
        "scheme://netloc/path;params?query#fragment",
        "https://docs.python.org/3.14/whatsnew/3.14.html#incompatible-changes",
        "https://github.com/vllm-project/vllm/blob/main/docs/serving/offline_inference.md#ray-data-llm-api",
        "https://docs.vllm.ai/en/latest/examples/online_serving/api_client.html#api-client",
        "https://www.google.com/search?q=python+tutorial&source=lnt&tbs=qdr:w&sa=X&biw=1280&bih=613&dpr=1.5",
    ]
    for url in urls:
        logger.note(f"> {url}")
        folder = url_to_domain(url)
        html_name = url_to_name(
            url,
            keep_domain=False,
            keep_ps=True,
            keep_qs=True,
            keep_anchor=False,
            keep_slash=False,
            append_html=True,
        )
        logger.mesg(f"  * {folder} / {logstr.okay(html_name)}")
        segs = url_to_segs(
            url,
            keep_domain=True,
            keep_qs=True,
            keep_anchor=True,
            seg_qs=True,
            seg_anchor=False,
        )
        segs_str = " / ".join(segs)
        logger.file(f"  * {segs_str}")


if __name__ == "__main__":
    test_url_to_html_name()

    # python -m webu.files.paths
