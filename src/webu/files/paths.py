from tclogger import norm_path
from urllib.parse import quote


WEBU_LIB_ROOT = norm_path(__file__).parents[1]
WEBU_SRC_ROOT = norm_path(__file__).parents[2]
WEBU_DATA_ROOT = WEBU_SRC_ROOT / "data"


def url_to_name(url: str) -> str:
    return quote(url, safe="")
