from urllib.parse import urlparse


GENERIC_PLATFORM_VALUES = {
    "",
    "unknown",
    "www",
    "m",
    "com",
    "cn",
    "net",
    "org",
    "html",
    "shtml",
    "未知",
}

DOMAIN_SUFFIX_PARTS = {
    "com",
    "cn",
    "net",
    "org",
    "edu",
    "gov",
    "io",
    "co",
}

HOST_PREFIX_PARTS = {"www", "m", "wap", "mobile"}


def normalize_ref_platform(platform, url=""):
    raw = str(platform or "").strip()
    if raw and raw.lower() not in GENERIC_PLATFORM_VALUES:
        return raw

    host = urlparse(str(url or "")).hostname or ""
    parts = [part.lower() for part in host.split(".") if part]
    parts = [part for part in parts if part not in HOST_PREFIX_PARTS]
    while parts and parts[-1] in DOMAIN_SUFFIX_PARTS:
        parts.pop()

    if parts:
        return parts[-1]
    return raw or "未知"
