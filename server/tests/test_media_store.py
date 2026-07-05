"""LocalMediaStore: roundtrip, traversal rejection, extension whitelist."""

import pytest

from app.providers.media_local import LocalMediaStore


def test_save_open_exists_roundtrip(tmp_path):
    store = LocalMediaStore(str(tmp_path))
    payload = b"\x89PNG fake image bytes"

    relative = store.save(payload, "screenshot.PNG")

    assert not relative.startswith("/")
    assert relative.endswith(".png")
    assert store.exists(relative)
    assert store.open(relative) == payload
    assert (tmp_path / relative).is_file()


def test_save_rejects_disallowed_extensions(tmp_path):
    store = LocalMediaStore(str(tmp_path))
    for name in ("evil.exe", "page.html", "noext", "archive.tar.gz", "script.py"):
        with pytest.raises(ValueError):
            store.save(b"data", name)


@pytest.mark.parametrize(
    "traversal",
    ["../outside.png", "../../etc/passwd", "2026/../../outside.png"],
)
def test_open_and_exists_reject_traversal(tmp_path, traversal):
    root = tmp_path / "media"
    root.mkdir()
    (tmp_path / "outside.png").write_bytes(b"secret")
    store = LocalMediaStore(str(root))

    with pytest.raises(ValueError):
        store.open(traversal)
    with pytest.raises(ValueError):
        store.exists(traversal)


def test_exists_false_for_missing_file(tmp_path):
    store = LocalMediaStore(str(tmp_path))
    assert not store.exists("2026/07/deadbeef.png")
