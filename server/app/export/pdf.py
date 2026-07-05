"""PDF rendering via Playwright/Chromium (M7 task 7.2; approved stack choice).

The deliverable HTML variant is rendered to A4 with print backgrounds on.
Import and launch failures surface as PdfRendererUnavailable so the route can
answer 503 with a reason instead of a blind 500.
"""

from __future__ import annotations


class PdfRendererUnavailable(RuntimeError):
    """Playwright is not installed or Chromium cannot be launched."""


def render_pdf(html: str) -> bytes:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # playwright not installed in this environment
        raise PdfRendererUnavailable(f"playwright not installed: {exc}") from exc

    try:
        with sync_playwright() as playwright:
            # --no-sandbox / --disable-dev-shm-usage: required to run Chromium
            # as root inside the api container; the page only ever loads our
            # own generated, fully self-contained HTML.
            browser = playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                return page.pdf(
                    format="A4",
                    print_background=True,
                    margin={
                        "top": "18mm",
                        "bottom": "20mm",
                        "left": "16mm",
                        "right": "16mm",
                    },
                )
            finally:
                browser.close()
    except PlaywrightError as exc:  # e.g. chromium executable missing
        raise PdfRendererUnavailable(str(exc)) from exc
