"""Unit tests for app.xhs.parse_xhs_note_id (pure string parsing, no network)."""

from __future__ import annotations

import pytest

from app.xhs import parse_xhs_note_id

NOTE_ID = "665f0e2c000000001e01a4b2"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # explore path
        (f"https://www.xiaohongshu.com/explore/{NOTE_ID}", NOTE_ID),
        (f"https://xiaohongshu.com/explore/{NOTE_ID}", NOTE_ID),
        (f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token=ABC&source=webshare", NOTE_ID),
        (f"https://www.xiaohongshu.com/explore/{NOTE_ID}/", NOTE_ID),
        # discovery/item path
        (f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}", NOTE_ID),
        (f"http://www.xiaohongshu.com/discovery/item/{NOTE_ID}?app_platform=ios", NOTE_ID),
        # noteId query param
        (f"https://www.xiaohongshu.com/user/profile/abc?noteId={NOTE_ID}", NOTE_ID),
        (f"https://www.xiaohongshu.com/some/page?foo=1&noteId={NOTE_ID}", NOTE_ID),
        # scheme-less input still parses
        (f"www.xiaohongshu.com/explore/{NOTE_ID}", NOTE_ID),
        # xhslink short links: None (resolving requires a network fetch — forbidden)
        ("http://xhslink.com/a/AbCdEf123", None),
        ("https://xhslink.com/m/9zXy", None),
        # wrong host
        (f"https://example.com/explore/{NOTE_ID}", None),
        (f"https://notxiaohongshu.com/explore/{NOTE_ID}", None),
        # malformed ids: uppercase, too short, too long, non-hex
        (f"https://www.xiaohongshu.com/explore/{NOTE_ID.upper()}", None),
        (f"https://www.xiaohongshu.com/explore/{NOTE_ID[:23]}", None),
        (f"https://www.xiaohongshu.com/explore/{NOTE_ID}0", None),
        ("https://www.xiaohongshu.com/explore/zzzf0e2c000000001e01a4b2", None),
        (f"https://www.xiaohongshu.com/user/profile/abc?noteId={NOTE_ID[:10]}", None),
        # no id at all / empty / None
        ("https://www.xiaohongshu.com/explore/", None),
        ("https://www.xiaohongshu.com/", None),
        ("", None),
        (None, None),
        ("   ", None),
    ],
)
def test_parse_xhs_note_id(url, expected):
    assert parse_xhs_note_id(url) == expected
