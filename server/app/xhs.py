"""XHS URL parsing. Pure string parsing only — never fetches any URL.

parse_xhs_note_id extracts the 24-lowercase-hex note id from xiaohongshu.com
URLs. xhslink.com short links return None: resolving them would require a
network fetch, which is forbidden (no automated scraping / crawling).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_NOTE_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_PATH_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-f]{24})(?:/|$)")


def parse_xhs_note_id(url: str | None) -> str | None:
    """Return the XHS note id parsed from a xiaohongshu.com URL, else None.

    Handled forms:
    - xiaohongshu.com/explore/<id>
    - xiaohongshu.com/discovery/item/<id>
    - any xiaohongshu.com URL with a noteId=<id> query parameter
    where <id> is exactly 24 lowercase hex characters.
    """
    if not url:
        return None
    candidate = url.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if host != "xiaohongshu.com" and not host.endswith(".xiaohongshu.com"):
        return None

    match = _PATH_RE.search(parsed.path)
    if match:
        return match.group(1)

    for value in parse_qs(parsed.query).get("noteId", []):
        if _NOTE_ID_RE.fullmatch(value):
            return value
    return None
