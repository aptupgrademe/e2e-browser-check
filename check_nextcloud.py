# End-to-end check of Nextcloud + Collabora Online, the way a person uses it:
# open the login page, log in, open the Files app, click a Word document, wait until Collabora has really
# rendered it (its status bar shows the word count, which only the document server can know), close the
# document, log out.
#
# Runs inside the Playwright container (see Containerfile). Environment:
#   NC_URL, NC_USER, NC_PASS   the cloud and a dedicated test user (no admin, no groups)
#   NC_LANG                    language of the test user's interface: en (default) or de
#   NC_DOC                     test document in the user's root folder (default monitor-test.docx)
#   NC_WORDS                   word count of that document as shown by Collabora (default 11, see make_docx.py)
#   DOC_FILE                   local copy that is uploaded if the document is missing (default /work/out/monitor-test.docx)
#   OUT_DIR                    where result.json and, on failure, fail/screenshot.png + fail/page.txt go
#   RECORD=1                   also record a video (Playwright's own recorder, no mouse pointer)
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

U, USER, PW = os.environ["NC_URL"].rstrip("/"), os.environ["NC_USER"], os.environ["NC_PASS"]
LANG = os.environ.get("NC_LANG", "en")
DOC = os.environ.get("NC_DOC", "monitor-test.docx")
DOC_FILE = os.environ.get("DOC_FILE", "/work/out/monitor-test.docx")
OUT = os.environ.get("OUT_DIR", "/work/out")
RECORD = os.environ.get("RECORD") == "1"
# visible labels of the interface; selectors by id are preferred, these are the few places without a stable id
LABELS = {
    "en": {"new": "New", "upload": "Upload files", "logout": "Log out", "words": "words", "locale": "en-US"},
    "de": {"new": "Neu", "upload": "Dateien hochladen", "logout": "Abmelden", "words": "Wörter", "locale": "de-DE"},
}[LANG]
EXPECT = f"{os.environ.get('NC_WORDS', '11')} {LABELS['words']}"
STEPS = ["login page", "login", "files list", "document loaded", "document closed", "logout"]

steps, t0 = [], time.time()
result = {"ok": False, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": steps}


def done(name, since):
    steps.append({"step": name, "seconds": round(time.time() - since, 1)})
    return time.time()


def run(page):
    t = time.time()
    page.goto(f"{U}/login", wait_until="domcontentloaded")
    page.locator("#user").wait_for(timeout=30000)
    t = done("login page", t)

    page.locator("#user").fill(USER)
    page.locator("#password").fill(PW)
    page.locator("button[type=submit]").first.click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=45000)
    t = done("login", t)

    if "/apps/files" not in page.url:
        page.goto(f"{U}/index.php/apps/files/")          # with index.php: works without pretty URLs too
    row = page.locator(f'[data-cy-files-list-row-name="{DOC}"]')
    page.locator("[data-cy-files-list-row-name]").first.wait_for(timeout=45000)
    if row.count() == 0:                                # first run on a new cloud: upload the test document
        page.get_by_role("button", name=LABELS["new"]).first.click()
        with page.expect_file_chooser() as fc:
            page.get_by_text(LABELS["upload"], exact=True).first.click()
        fc.value.set_files(DOC_FILE)
    row.first.wait_for(timeout=45000)
    t = done("files list", t)

    row.first.locator(".files-list__row-name-link, .files-list__row-name").first.click()
    frame = page.frame_locator("iframe[name^=collaboraframe], iframe#richdocumentsframe").first
    frame.locator("#StateWordCount").filter(has_text=EXPECT).wait_for(timeout=90000)
    t = done("document loaded", t)

    page.keyboard.press("Escape")                       # closes the welcome tour shown on first use
    frame.locator("#closebutton").click(timeout=15000)
    row.first.wait_for(timeout=30000)
    page.locator("iframe[name^=collaboraframe]").wait_for(state="detached", timeout=30000)
    t = done("document closed", t)

    page.locator("#user-menu button, #user-menu").first.click()
    page.get_by_text(LABELS["logout"], exact=True).first.click()
    page.wait_for_url(lambda u: "/login" in u, timeout=30000)
    done("logout", t)


with sync_playwright() as p:
    browser = p.chromium.launch()
    # a normal Chrome user agent: Nextcloud sends "HeadlessChrome" and unknown agents to /unsupported
    ua = browser.new_page().evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome") + " e2e-check"
    kw = {"viewport": {"width": 1440, "height": 900}, "locale": LABELS["locale"], "user_agent": ua}
    if RECORD:
        kw.update(record_video_dir=f"{OUT}/video", record_video_size={"width": 1440, "height": 900})
    ctx = browser.new_context(**kw)
    page = ctx.new_page()
    try:
        run(page)
        result["ok"] = True
    except Exception as e:                              # any step that times out or fails
        result["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
        result["failed_step"] = STEPS[len(steps)] if len(steps) < len(STEPS) else "?"
        result["url"] = page.url.replace(U, "")
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
