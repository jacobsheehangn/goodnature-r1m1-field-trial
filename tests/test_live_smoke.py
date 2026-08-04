from __future__ import annotations

import os
import re
import time

import pytest
from playwright.sync_api import Page


BASE_URL = os.environ.get("R1M1_TEST_URL", "").rstrip("/")
PASSWORD = os.environ.get("R1M1_TEST_PASSWORD", "")

pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="Set R1M1_TEST_URL to run the optional deployed-app smoke test.",
)


def test_deployed_app_responds(page: Page) -> None:
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=120_000)

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        password = page.locator('input[type="password"][aria-label="Password"]').first
        if password.count() and password.is_visible():
            assert PASSWORD, "The deployed app requires R1M1_TEST_PASSWORD."
            password.fill(PASSWORD)
            page.get_by_role(
                "button", name=re.compile(r"^(sign in|log in)$", re.I)
            ).click()
            page.wait_for_timeout(1000)

        body = (page.locator("body").inner_text() or "").strip()
        if "Trap sites" in body or "R1/M1 Field Trial" in body:
            return

        page.wait_for_timeout(500)

    raise AssertionError("The deployed app did not render a recognisable page within 120 seconds.")
