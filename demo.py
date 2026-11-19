# Demo run for the video: the same steps as check.py, but in a visible Chromium window on a virtual
# screen, at a pace a viewer can follow. The URL is typed into the address bar and the real mouse
# pointer moves to each element and clicks (xdotool), so the screen recording looks like a person.
# Writes /work/out/demo/captions.json with the times for the text overlays.
import json
import os
import subprocess
import time

from playwright.sync_api import sync_playwright

U, USER, PW = os.environ["NC_URL"].rstrip("/"), os.environ["NC_USER"], os.environ["NC_PASS"]
DOC = os.environ.get("NC_DOC", "monitor-test.docx")
LANG = os.environ.get("NC_LANG", "en")
L = {"en": {"words": "words", "skip": "Skip", "logout": "Log out", "locale": "en-US"},
     "de": {"words": "Wörter", "skip": "Überspringen", "logout": "Abmelden", "locale": "de-DE"}}[LANG]
EXPECT = f"{os.environ.get('NC_WORDS', '11')} {L['words']}"
OUT = "/work/out/demo"
T0 = float(os.environ["REC_START"])                 # when the screen recording started
captions, current = [], None
os.makedirs(OUT, exist_ok=True)
pos = [960, 540]


def caption(text):
    global current
    now = time.time() - T0
    if current:
        captions.append([current[0], now, current[1]])
    current = (now, text) if text else None


def xdo(*args):
    subprocess.run(["xdotool", *map(str, args)], check=True)


def glide(x, y, steps=30):
    sx, sy = pos
    for i in range(1, steps + 1):
        f = i / steps
        f = f * f * (3 - 2 * f)                      # ease in and out
        xdo("mousemove", int(sx + (x - sx) * f), int(sy + (y - sy) * f))
        time.sleep(0.015)
    pos[:] = [x, y]


def click(page, locator, pause=0.6):
    locator.wait_for(timeout=90000)
    box = locator.bounding_box()
    ox, oy = page.evaluate("[window.screenX + window.outerWidth - window.innerWidth,"
                           " window.screenY + window.outerHeight - window.innerHeight]")
    glide(int(ox + box["x"] + box["width"] / 2), int(oy + box["y"] + box["height"] / 2))
    time.sleep(pause)
    xdo("click", 1)


# no "save password?" bubble: it would cover the user menu
os.makedirs("/tmp/profile/Default", exist_ok=True)
json.dump({"credentials_enable_service": False, "profile": {"password_manager_enabled": False}},
          open("/tmp/profile/Default/Preferences", "w"))

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        "/tmp/profile", headless=False, no_viewport=True, locale=L["locale"],
        args=["--window-position=0,0", "--window-size=1920,1080", "--no-first-run", "--lang=de-DE",
              "--disable-features=Translate", "--test-type"],
        ignore_default_args=["--enable-automation"])
    page = browser.pages[0] if browser.pages else browser.new_page()
    time.sleep(2)

    caption("1  Open the browser and type the address")
    time.sleep(1.5)
    xdo("key", "ctrl+l")
    time.sleep(0.5)
    xdo("type", "--delay", "90", U.replace("https://", ""))
    time.sleep(0.8)
    xdo("key", "Return")
    page.locator("#user").wait_for(timeout=30000)
    time.sleep(1.5)

    caption(f"2  Log in as the test user {USER}")
    click(page, page.locator("#user"))
    page.keyboard.type(USER, delay=80)
    click(page, page.locator("#password"))
    page.keyboard.type(PW, delay=40)
    time.sleep(0.6)
    click(page, page.locator("button[type=submit]").first)
    row = page.locator(f'[data-cy-files-list-row-name="{DOC}"]').first
    row.wait_for(timeout=45000)
    time.sleep(2)

    caption("3  Click the Word document")
    click(page, row.locator(".files-list__row-name-link, .files-list__row-name").first, pause=1.0)
    t_open = time.time()
    caption("4  Wait until Collabora has loaded the document …")
    frame = page.frame_locator("iframe[name^=collaboraframe], iframe#richdocumentsframe").first
    frame.locator("#StateWordCount").filter(has_text=EXPECT).wait_for(timeout=90000)
    load = time.time() - t_open
    caption(f"   Loaded after {load:.1f} s – the status bar shows “{EXPECT}”"
            + (f" ({os.environ.get('NC_WORDS', '11')} words)" if LANG != "en" else ""))
    time.sleep(1.0)
    skip = frame.get_by_text(L["skip"], exact=True)
    if skip.count():
        click(page, skip.first)
    time.sleep(3.5)

    caption("5  Close the document")
    click(page, frame.locator("#closebutton"), pause=0.8)
    row.wait_for(timeout=30000)
    time.sleep(2)

    caption("6  Log out")
    click(page, page.locator("#user-menu button, #user-menu").first)
    time.sleep(1.2)
    page.screenshot(path=f"{OUT}/menu.png")
    click(page, page.get_by_text(L["logout"], exact=True).first)
    try:
        page.wait_for_url(lambda u: "/login" in u, timeout=15000)
    except Exception:
        page.screenshot(path=f"{OUT}/after_logout_click.png")
        raise
    time.sleep(1)
    caption("✓  Test passed: log in, open the document, close it, log out")
    time.sleep(4)
    caption(None)
    browser.close()

json.dump(captions, open(f"{OUT}/captions.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(captions, ensure_ascii=False, indent=1))
