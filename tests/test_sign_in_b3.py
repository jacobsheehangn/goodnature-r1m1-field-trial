"""Part B batch 3: the sign-in page. The gate is unchanged (see test_auth.py); what changed is how a refusal reads: "Incorrect password." as a line under a
red-ringed field, and, from the fifth refusal, a panel in its place."""
import re

from playwright.sync_api import Page, expect

from test_auth import TEST_PASSWORD, password_app  # noqa: F401  (the fixture that serves a copy with a password)

PANEL_TITLE = "Several attempts have failed"
PANEL_HELP = "Check the password with the trial lead."


def _field(page: Page):
    return page.locator('input[type="password"][aria-label="Password"]').first


def _refuse(page: Page, wrong: str = "not-the-password") -> None:
    _field(page).fill(wrong)
    _field(page).press("Enter")
    page.wait_for_timeout(900)


def _ringed(page: Page) -> int:
    return page.locator('[class*="st-key-login_wrong"]').count()


def test_a_refusal_is_a_line_under_a_ringed_field(page: Page, password_app: str) -> None:
    page.goto(password_app, wait_until="domcontentloaded", timeout=60_000)
    expect(_field(page)).to_be_visible(timeout=30_000)
    assert _field(page).get_attribute("placeholder") == "Trial password"
    assert _ringed(page) == 0 and page.get_by_text("Incorrect password.").count() == 0

    _refuse(page)
    expect(page.get_by_text("Incorrect password.", exact=True)).to_be_visible(timeout=15_000)
    assert _ringed(page) == 1, "the field is ringed while the line is showing"
    assert page.get_by_text(PANEL_TITLE).count() == 0, "one refusal is not several"
    assert page.get_by_role("button", name=re.compile(r"^sign in$", re.I)).count() == 1
    # the typed password is still in the field, as the board draws it (dots remain)
    assert _field(page).input_value() == "not-the-password"


def test_five_refusals_show_the_panel_and_a_right_password_still_signs_in(page: Page, password_app: str) -> None:
    page.goto(password_app, wait_until="domcontentloaded", timeout=60_000)
    expect(_field(page)).to_be_visible(timeout=30_000)
    for attempt in range(1, 5):
        _refuse(page, f"wrong-{attempt}")
        expect(page.get_by_text("Incorrect password.", exact=True)).to_be_visible(timeout=15_000)
        assert page.get_by_text(PANEL_TITLE).count() == 0, f"attempt {attempt}: not yet"
    _refuse(page, "wrong-5")
    expect(page.get_by_text(PANEL_TITLE, exact=True)).to_be_visible(timeout=15_000)
    expect(page.get_by_text(PANEL_HELP, exact=True)).to_be_visible()
    assert page.get_by_text("Incorrect password.", exact=True).count() == 0, "the panel replaces the line"
    assert _ringed(page) == 0, "and the field is no longer ringed"

    # unchanged gate logic: five refusals do not lock anyone out
    _field(page).fill(TEST_PASSWORD)
    page.get_by_role("button", name=re.compile(r"^sign in$", re.I)).click()
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    assert page.get_by_text(PANEL_TITLE).count() == 0


def test_the_field_carries_a_lock(page: Page, password_app: str) -> None:
    page.goto(password_app, wait_until="domcontentloaded", timeout=60_000)
    expect(_field(page)).to_be_visible(timeout=30_000)
    lock = page.evaluate(
        """() => { const el = document.querySelector('[data-testid="stTextInputRootElement"]');
                   const cs = getComputedStyle(el, '::before'); return [cs.content, cs.width, cs.height]; }"""
    )
    assert lock[0] not in ("none", "normal"), lock
    assert lock[1] == "20px" and lock[2] == "20px", lock
