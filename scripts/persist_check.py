"""End-to-end: does a plan survive a completely new browser session?

Usage: python output/persist_check.py <port>
"""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8521"
URL = f"http://localhost:{PORT}"


def open_app(pw):
    b = pw.chromium.launch()
    pg = b.new_context(viewport={"width": 1440, "height": 1150}).new_page()
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(4500)
    return b, pg


def hero(pg):
    return pg.locator(".ph-hero").first.inner_text().split("\n")[0].strip()


with sync_playwright() as pw:
    # --- session 1: build a plan -----------------------------------------
    b1, pg1 = open_app(pw)
    print("session 1 start, days off =", hero(pg1))

    pg1.get_by_role("tab", name="Commitments").click()
    pg1.wait_for_timeout(2000)
    pg1.get_by_label("What is it?").fill("Cousin's wedding")
    pg1.wait_for_timeout(1500)
    pg1.get_by_role("button", name="Lock these dates in").click()
    pg1.wait_for_timeout(4000)

    pg1.get_by_role("tab", name="Long weekends").click()
    pg1.wait_for_timeout(2000)
    pg1.get_by_role("button", name="Auto-fill best combination").click()
    pg1.wait_for_timeout(5000)
    built = hero(pg1)
    print("session 1 after planning, days off =", built)
    b1.close()

    # --- session 2: brand-new browser, no cookies, no session ------------
    b2, pg2 = open_app(pw)
    after = hero(pg2)
    print("session 2 (fresh browser), days off =", after)

    pg2.get_by_role("tab", name="Commitments").click()
    pg2.wait_for_timeout(2500)
    body = pg2.inner_text("body")
    pg2.screenshot(path="output/persisted.png")
    b2.close()

print()
assert built != "0", "session 1 never built a plan"
assert after == built, f"state lost across sessions: {built} -> {after}"
assert "Cousin's wedding" in body, "commitment label did not persist"
print(f"PASS: {built} days off and the commitment survived a new browser session")
