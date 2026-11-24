from playwright.sync_api import sync_playwright

JS = """() => {
    const tabs = document.querySelector('[data-testid="stTabs"]');
    if (!tabs) return ["no stTabs element"];
    const out = [];
    const walk = (el, d) => {
        if (d > 4) return;
        const attrs = [...el.attributes]
            .map(a => a.name + '="' + a.value.slice(0, 80) + '"').join(' ');
        out.push('  '.repeat(d) + '<' + el.tagName.toLowerCase() + ' ' + attrs + '>');
        [...el.children].slice(0, 3).forEach(c => walk(c, d + 1));
    };
    walk(tabs, 0);
    return out;
}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.goto("http://localhost:8517", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(4000)
    for line in pg.evaluate(JS):
        print(line)
    b.close()
