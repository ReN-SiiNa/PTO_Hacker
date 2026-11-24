"""Screenshot a running instance. Usage: python scripts/shoot.py <port> <out.png>"""
import sys

from playwright.sync_api import sync_playwright

port = sys.argv[1] if len(sys.argv) > 1 else "8501"
out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
scheme = sys.argv[3] if len(sys.argv) > 3 else "light"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_context(
        viewport={"width": 1440, "height": 1000}, color_scheme=scheme
    ).new_page()
    pg.goto(f"http://localhost:{port}", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(4500)
    pg.screenshot(path=out)
    tabs = pg.locator('[data-testid="stTab"]').count()
    sel = pg.locator('[data-testid="stTab"][aria-selected="true"]')
    bg = sel.evaluate("el => getComputedStyle(el).backgroundColor") if sel.count() else "n/a"
    print(f"   {out}  tabs={tabs}  active-tab-bg={bg}")
    b.close()
