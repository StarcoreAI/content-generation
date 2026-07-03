import re
from urllib.parse import urlparse


HOST_PREFIX_PARTS = {"www", "m", "wap", "mobile"}


def _canonical_host(host):
    parts = [part for part in (host or "").lower().split(".") if part]
    while parts and parts[0] in HOST_PREFIX_PARTS:
        parts.pop(0)
    return ".".join(parts)


def _canonical_title(title):
    text = str(title or "").strip().lower()
    text = re.sub(r"\s*[-_｜|]\s*(今日头条|搜狐|新浪|网易|腾讯|红安网)\s*$", "", text)
    text = text.replace("：", ":").replace("｜", "|").replace("，", ",")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[：:，,。.!！?？、；;|\\-_（）()【】\\[\\]《》<>\"'“”‘’]", "", text)
    return text


def canonical_article_key(title, url=""):
    parsed = urlparse(str(url or "").strip())
    host = _canonical_host(parsed.hostname or "")
    path = parsed.path.rstrip("/")

    if host and path:
        if host.endswith("toutiao.com"):
            match = re.search(r"/article/(\d+)$", path) or re.search(r"/a(\d+)$", path)
            if match:
                return f"url:toutiao:{match.group(1)}"
        return f"url:{host}{path.lower()}"

    normalized_title = _canonical_title(title)
    if normalized_title:
        return f"title:{normalized_title}"
    return ""
