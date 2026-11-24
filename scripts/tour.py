"""Drive the app and capture both themes. Usage: python output/tour.py <port>"""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8520"
URL = f"http://localhost:{PORT}"


def run(pw, scheme):
    b = pw.chromium.launch()
    pg = b.new_context(
        viewport={"width": 1440, "height": 1150}, color_scheme=scheme
    ).new_page()
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(4500)

    pg.get_by_role("tab", name="Long weekends").click()
    pg.wait_for_timeout(2500)
    pg.get_by_role("button", name="Auto-fill best combination").click()
    pg.wait_for_timeout(4500)
    pg.get_by_role("tab", name="Long weekends").click()
    pg.wait_for_timeout(2500)
    pg.screenshot(path=f"docs/screenshot-{scheme}-weekends.png")

    pg.get_by_role("tab", name="Getaways").click()
    pg.wait_for_timeout(2500)
    pg.screenshot(path=f"docs/screenshot-{scheme}-getaways.png")
    print(f"{scheme}: captured")
    b.close()


with sync_playwright() as pw:
    for scheme in ("dark", "light"):
        run(pw, scheme)
