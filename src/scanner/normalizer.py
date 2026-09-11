"""
URL normalization and crawl-boundary rules from section 11.4:
remove fragments, normalize hostname casing, remove default ports,
normalize trailing slashes consistently, reject unsupported schemes,
skip known asset extensions, and never cross to an external host.
"""
from urllib.parse import urljoin, urlsplit, urlunsplit

ASSET_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".css", ".js", ".mjs",
    ".pdf", ".zip", ".rar", ".tar", ".gz", ".7z",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".xml.gz",
}

DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(url: str, base_url: str | None = None) -> str | None:
    """
    Returns a normalized absolute URL, or None if the URL should be
    skipped entirely (unsupported scheme, obvious asset, etc).
    """
    if base_url:
        url = urljoin(base_url, url)

    parts = urlsplit(url)

    if parts.scheme not in ("http", "https"):
        return None

    hostname = (parts.hostname or "").lower()
    if not hostname:
        return None

    netloc = hostname
    if parts.port and parts.port != DEFAULT_PORTS.get(parts.scheme):
        netloc = f"{hostname}:{parts.port}"

    path = parts.path or "/"
    # Consistent trailing-slash rule: strip trailing slash except for root.
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    lowered_path = path.lower()
    if any(lowered_path.endswith(ext) for ext in ASSET_EXTENSIONS):
        return None

    # Fragments are removed entirely; query strings are kept since they
    # can represent distinct content on many sites.
    normalized = urlunsplit((parts.scheme, netloc, path, parts.query, ""))
    return normalized


def is_same_registrable_host(url_a: str, url_b: str) -> bool:
    """
    Conservative same-host check for Build 1: exact hostname match only
    (ignoring a leading 'www.'). This intentionally does not implement
    full public-suffix-list registrable-domain parsing yet — cross-domain
    expansion after redirects is rejected outright rather than guessed at.
    """

    def _bare(host: str) -> str:
        host = host.lower()
        return host[4:] if host.startswith("www.") else host

    host_a = _bare(urlsplit(url_a).hostname or "")
    host_b = _bare(urlsplit(url_b).hostname or "")
    return bool(host_a) and host_a == host_b
