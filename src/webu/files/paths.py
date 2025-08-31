from copy import deepcopy
from tclogger import norm_path, logger, logstr, dict_to_str
from urllib.parse import quote, unquote, urlparse, urlencode


WEBU_LIB_ROOT = norm_path(__file__).parents[1]
WEBU_SRC_ROOT = norm_path(__file__).parents[2]
WEBU_DATA_ROOT = WEBU_SRC_ROOT / "data"
WEBU_HTML_ROOT = WEBU_DATA_ROOT / "htmls"


def xquote(s: str) -> str:
    return quote(s, safe="")


def has_suffix(name: str) -> bool:
    return "." in name


def lstrip_slash(s: str) -> str:
    return s.lstrip("/").lstrip("%252F").lstrip("%2F")


def qs_to_kvs(qs: str, qn: str = "?", eq: str = "=", sep: str = "&") -> dict:
    qs = qs.strip().lstrip(qn)
    if not qs:
        return {}
    kv_dict = {}
    for kv in qs.split(sep):
        if not kv:
            continue
        if eq in kv:
            k, v = kv.split(eq, 1)
            kv_dict[k] = v
        else:
            kv_dict[kv] = None
    return kv_dict


def filter_qs(
    qs: str, include_qs: list[str] = None, exclude_qs: list[str] = None
) -> str:
    if not qs:
        return ""
    if not include_qs and not exclude_qs:
        return qs

    qs_dict = qs_to_kvs(qs)
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


URL_SEGS_DICT = {
    "scheme": "",
    "domain": "",
    "paths": [],
    "ps": "",
    "qs": "",
    "anchor": "",
}


def url_to_segs_dict(url: str) -> dict:
    """<scheme>://<netloc>/<path>;<params>?<query>#<fragment>"""
    segs_dict = deepcopy(URL_SEGS_DICT)
    parsed = urlparse(url)
    segs_dict["scheme"] = parsed.scheme
    segs_dict["domain"] = parsed.netloc
    segs_dict["paths"] = [seg for seg in parsed.path.split("/") if seg]
    segs_dict["ps"] = parsed.params
    segs_dict["qs"] = parsed.query
    segs_dict["anchor"] = parsed.fragment
    segs_dict = {
        k: v if isinstance(v, str) else [s for s in v] for k, v in segs_dict.items()
    }
    return segs_dict


def url_to_segs_list(
    url: str,
    keep_scheme: bool = True,
    keep_domain: bool = True,
    keep_ps: bool = True,
    keep_qs: bool = True,
    keep_anchor: bool = True,
    prefix_slash: bool = True,
    suffix_slash: bool = True,
    include_qs: list[str] = [],
    exclude_qs: list[str] = [],
    seg_ps: bool = False,
    seg_qs: bool = False,
    seg_anchor: bool = False,
    use_quote: bool = False,
) -> list:
    """<scheme>://<domain>/<paths>;<ps>?<qs>#<anchor>"""
    segs_dict = url_to_segs_dict(url)
    scheme = segs_dict["scheme"]
    domain = segs_dict["domain"]
    paths: list[str] = segs_dict["paths"]
    ps = segs_dict["ps"]
    qs = segs_dict["qs"]
    anchor = segs_dict["anchor"]

    segs = []
    if keep_scheme and scheme:
        segs.append(f"{scheme}://")
    if keep_domain and domain:
        segs.append(domain)
    if paths:
        if not suffix_slash and paths[-1].endswith("/"):
            paths[-1] = paths[-1].rstrip("/")
        if prefix_slash:
            slash_paths = [f"/{p}" for p in paths]
            segs.extend(slash_paths)
        else:
            segs.extend(paths)
    if keep_ps and ps:
        ps_str = ";" + ps
        if seg_ps:
            segs.append(ps_str)
        else:
            segs[-1] += ps_str
    if keep_qs and qs:
        qs = filter_qs(qs, include_qs=include_qs, exclude_qs=exclude_qs)
        if qs:
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
    if use_quote:
        segs = [xquote(s) for s in segs]
    return segs


def url_to_domain(url: str) -> str:
    domain = urlparse(url).netloc
    return xquote(domain)


def test_url_to_segs():
    urls = [
        "scheme://netloc/path;params?q=v#fragment",
        "https://docs.python.org/3.14/whatsnew/3.14.html#incompatible-changes",
        "https://github.com/vllm-project/vllm/blob/main/docs/serving/offline_inference.md#ray-data-llm-api",
        "https://docs.vllm.ai/en/latest/examples/online_serving/api_client.html#api-client",
        "https://www.google.com/search?q=python+tutorial&source=lnt&tbs=qdr:w&sa=X&biw=1280&bih=613&dpr=1.5",
    ]
    for url in urls:
        logger.note(f"> {url}")
        segs_dict = url_to_segs_dict(url)
        logger.file(dict_to_str(segs_dict), indent=4)
        segs_params = {
            "keep_scheme": True,
            "keep_domain": True,
            "keep_ps": True,
            "keep_qs": True,
            "keep_anchor": True,
            "prefix_slash": True,
            "suffix_slash": True,
            "seg_ps": True,
            "seg_qs": True,
            "seg_anchor": True,
            "use_quote": True,
        }
        segs_list = url_to_segs_list(url, **segs_params)
        logger.mesg(f"  * {segs_list}")
        folder = url_to_domain(url)
        name_params = deepcopy(segs_params)
        name_params.update(
            {
                "keep_scheme": False,
                "keep_domain": False,
                "include_qs": ["q"],
            }
        )
        name_segs = url_to_segs_list(url, **name_params)
        name = lstrip_slash("".join(name_segs))
        name = xquote(name)
        logger.mesg(f"  * {folder} / {logstr.okay(name)}")


if __name__ == "__main__":
    test_url_to_segs()

    # python -m webu.files.paths
