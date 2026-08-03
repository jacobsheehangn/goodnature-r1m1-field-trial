from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture
def page():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.fail(
                "Chromium is not installed. Run `playwright install chromium` "
                "or use the included GitHub Actions workflow. " + str(exc),
                pytrace=False,
            )
        context = browser.new_context()
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()
