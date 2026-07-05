#!/usr/bin/env python3
"""Host-side wrapper for the golden-set provider eval harness (iron law #4).

The repo's tests/ directory is not baked into the api image, so this wrapper
mounts it at /golden and runs the real harness (server/app/eval/harness.py)
inside the api container. Run from anywhere; docker compose is invoked with
the repo root as the working directory.

Examples (from the repo root):

    # Structure check only (no API calls, exits 0) — safe for CI
    python scripts/eval_providers.py

    # Live eval of OCR + translation with cost columns
    python scripts/eval_providers.py --live --steps ocr,translation \
        --providers ocr=anthropic --providers translation=anthropic

    # Persist full JSON results (path is inside the mount; this example
    # lands at tests/eval-results.json on the host)
    python scripts/eval_providers.py --live --json /golden/eval-results.json

All arguments are passed through to `python -m app.eval.harness`; --golden
defaults to /golden/golden/posts (i.e. tests/golden/posts on the host).
"""

from __future__ import annotations

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    args = sys.argv[1:]
    if "--golden" not in args:
        args = ["--golden", "/golden/golden/posts", *args]
    command = [
        "docker", "compose", "run", "--rm", "--no-deps",
        "-v", f"{os.path.join(REPO_ROOT, 'tests')}:/golden",
        "api", "python", "-m", "app.eval.harness", *args,
    ]
    return subprocess.call(command, cwd=REPO_ROOT)


if __name__ == "__main__":
    sys.exit(main())
