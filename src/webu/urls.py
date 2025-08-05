from urllib.parse import quote


def url_to_name(url: str) -> str:
    return quote(url, safe="")
