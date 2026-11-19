# End-to-end check of a website with a client-side search (here a Hugo blog with Pagefind), the way a visitor
# uses it: open the home page, open the search, search for a term, wait for the hits (the index is loaded and
# searched in the browser, which no HTTP check can see), open the first hit and check that the page and its
# first image are really there.
#
# Runs inside the Playwright container. Environment:
#   SITE_URL, SITE_TERM          site and a search term that must find something (default: example.org / "e2e")
#   SEL_TOGGLE, SEL_INPUT, SEL_HIT, SEL_TITLE, SEL_ARTICLE
#                                CSS selectors of the search button, search field, hit links, page title and
#                                article body - adjust them to your theme (defaults fit apt-upgrade.me)
#   OUT_DIR                      where result.json and, on failure, fail/screenshot.png + fail/page.txt go
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

U = os.environ.get("SITE_URL", "https://www.example.org").rstrip("/")
TERM = os.environ.get("SITE_TERM", "e2e")
OUT = os.environ.get("OUT_DIR", "/work/out/site")
SEL = {k: os.environ.get(f"SEL_{k.upper()}", v) for k, v in {
    "toggle": ".search-toggle", "input": ".search-drop input[name=q]", "hit": ".search-drop .search-results a.hit",
    "title": "h1.entry-title", "article": "article.post"}.items()}
STEPS = ["home page", "search results", "page opened"]

steps, t0 = [], time.time()
result = {"ok": False, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": steps}


def done(name, since):
    steps.append({"step": name, "seconds": round(time.time() - since, 1)})
    return time.time()


def run(page):
    t = time.time()
    page.goto(f"{U}/", wait_until="domcontentloaded")
    page.locator(SEL["toggle"]).first.wait_for(timeout=30000)
    page.locator("a[href]").nth(5).wait_for(timeout=30000)
    t = done("home page", t)

    page.locator(SEL["toggle"]).first.click()
    box = page.locator(SEL["input"]).first
    box.wait_for(state="visible", timeout=10000)
    box.fill(TERM)
    box.press("Enter")
    hit = page.locator(SEL["hit"]).first
    hit.wait_for(timeout=30000)
    if TERM.lower() not in hit.inner_text().lower():
        raise AssertionError(f"first hit does not mention {TERM!r}: {hit.inner_text()[:80]!r}")
    t = done("search results", t)

    hit.click()
    page.locator(SEL["title"]).first.wait_for(timeout=30000)
    if TERM.lower() not in page.locator(SEL["article"]).first.inner_text().lower():
        raise AssertionError(f"opened page does not contain {TERM!r}")
    img = page.locator(SEL["article"] + " img").first
    img.wait_for(timeout=15000)
    img.scroll_into_view_if_needed()
    page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=img.element_handle(), timeout=15000)
    done("page opened", t)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ua = browser.new_page().evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome") + " e2e-check"
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="de-DE", user_agent=ua)
    page = ctx.new_page()
    try:
        run(page)
        result["ok"] = True
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
        result["failed_step"] = STEPS[len(steps)] if len(steps) < len(STEPS) else "?"
        result["url"] = page.url
        os.makedirs(f"{OUT}/fail", exist_ok=True)
        try:
            page.screenshot(path=f"{OUT}/fail/screenshot.png")
            open(f"{OUT}/fail/page.txt", "w").write(page.inner_text("body")[:5000])
        except Exception:
            pass
    finally:
        ctx.close()
        browser.close()

result["seconds"] = round(time.time() - t0, 1)
os.makedirs(OUT, exist_ok=True)
json.dump(result, open(f"{OUT}/result.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(result, ensure_ascii=False))
sys.exit(0 if result["ok"] else 1)
