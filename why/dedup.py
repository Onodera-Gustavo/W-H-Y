"""Dedup keys. The same story must map to the same key across runs, whatever tracking noise
the feed adds to its link."""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# query parameters that change between fetches without changing the article
TRACKING_PARAMS = {"oc", "gclid", "fbclid", "mc_cid", "mc_eid", "cmpid", "ref", "ncid"}


def normalize_link(link: str | None) -> str | None:
    """Canonical form of an article URL, or None when there is no usable http(s) link.

    Drops the fragment, tracking parameters and a leading www, sorts the remaining query,
    ignores the scheme (http and https count as the same) and a trailing slash."""
    if not link:
        return None
    parts = urlsplit(link.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower().removeprefix("www.")
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(query), ""))


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def dedup_key(link: str | None, title: str | None, source: str | None) -> str:
    """16 hex chars. Normalized link when there is one, title + source otherwise."""
    normalized = normalize_link(link)
    if normalized:
        basis = f"link:{normalized}"
    else:
        basis = f"title:{_normalize_text(title)}|source:{_normalize_text(source)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
