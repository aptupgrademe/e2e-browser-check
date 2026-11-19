# End-to-end browser checks for Nextcloud + Collabora and a website search

A real browser logs in to Nextcloud, opens a Word document in Collabora Online, waits until the document server
has really rendered it, closes it and logs out. A second check opens a website, uses its search and opens a hit.
Both run twice a day in a rootless Podman container with [Playwright](https://playwright.dev/python/), and
the results go to Zabbix: history, graphs, triggers and mails.

Background, decisions and a video of a run:
[blog post on apt-upgrade.me](https://www.apt-upgrade.me/2026/11/18/end-to-end-tests-with-playwright-and-zabbix/)

```
cron (06:57, 18:57)
  └─ run.sh ─ run.py ── per target in targets.ini ──┐
                │                                    ▼
                │                 podman run e2e-check (Playwright + Chromium)
                │                   check_nextcloud.py   or   check_site_search.py
                │                   └─ out/<target>/result.json (+ screenshot on failure)
                │
                ├─ failed? wait 2 min, run once more
                └─ Zabbix sender protocol ──► trapper items e2e.* ──► triggers ──► mail
                   (Zabbix unreachable: run.py mails the result itself)
```

## Why end-to-end

Most monitoring checks a **state**: the container runs, the port answers, `status.php` says
`installed: true`, the certificate is valid for 60 more days. All of that can be green while nobody can open a
document - because the WOPI callback between Nextcloud and Collabora fails, an app update broke the viewer,
a proxy header is missing, or the login form never renders because a JavaScript bundle 404s.

An end-to-end check tests the **effect**: it does what a person does and only reports success when the
person would have succeeded. It is the slowest and most fragile kind of check, so it runs rarely and only
on the paths that matter. It is most useful right after updates (Nextcloud, Collabora, the proxy, the OS):
the next run tells you whether the whole chain still works, not only each piece.

## What is checked

**Nextcloud + Collabora (`check_nextcloud.py`)**, six timed steps:

| Step | Passes when |
|---|---|
| login page | the login form (`#user`) is rendered, i.e. the JavaScript of the page works |
| login | the test user's password is accepted and the browser leaves `/login` |
| files list | the Files app lists the test document (uploaded through the browser on the very first run) |
| document loaded | Collabora's status bar shows the document's **word count**, e.g. "11 words" |
| document closed | the Collabora frame is gone and the file list is back |
| logout | the browser is back on `/login` |

Why the word count: the Collabora iframe appears long before the document is usable, and the document itself
is drawn on a canvas, so its text is not in the page. The word count in the status bar (`#StateWordCount`)
is computed by the document server from the real file. If it shows the expected number, the whole chain -
Nextcloud, WOPI, Collabora, file storage - has worked.

**Website search (`check_site_search.py`)**, three steps: home page, search (type a term, wait for hits that
contain it), open the first hit and check that its title, its text and its first image are really there. It
was written for a Hugo site with [Pagefind](https://pagefind.app/): the index is loaded and searched in the
browser, so no HTTP check can tell whether search works. The CSS selectors are environment variables, adapt
them to your theme.

## Files

| File | Purpose |
|---|---|
| `Containerfile` | image with Playwright and Chromium (`mcr.microsoft.com/playwright/python`) |
| `check_nextcloud.py` | the Nextcloud + Collabora check (runs in the container) |
| `check_site_search.py` | the website search check (runs in the container) |
| `make_docx.py` | writes the test document: heading, a sentence, a bar chart (standard library only) |
| `run.py` | runs all targets, retries a failure once, sends the results to Zabbix |
| `run.sh` | cron wrapper (sets `XDG_RUNTIME_DIR` for rootless Podman) |
| `zbx_setup.py` | creates the trapper items and triggers in Zabbix through the API |
| `targets.example.ini` | template for `targets.ini` (targets, Zabbix, mail fallback) |
| `.credentials.example` | template for a target's credentials file |
| `systemd/` | a user timer as an alternative to cron |
| `demo.py`, `demo.sh`, `Containerfile.demo` | records a demo video: visible Chrome window, real mouse pointer, captions |

## Setup

Tested on Debian 13 with Podman 5 (rootless), Nextcloud 31/32 with Collabora Online (richdocuments app),
Zabbix 7.0 LTS. Everything runs as a normal user.

**1. A dedicated test user on the Nextcloud** - no admin, no groups, small quota. On the Nextcloud host
(the password comes from stdin, so it is neither in the shell history nor in the process list):

```bash
read -rs OC_PASS; export OC_PASS
php occ user:add --password-from-env --display-name "Monitoring Check" monitor-check
php occ user:setting monitor-check files quota "100 MB"
php occ user:setting monitor-check core lang en      # NC_LANG must match (en or de)
unset OC_PASS
```

The check uses the browser login, not WebDAV: if `token_auth_enforced` is on (it should be), clients need app
passwords, and a WebDAV upload with the normal password gets HTTP 401. The browser login is not affected.
If you enforce two-factor authentication, exclude this user or the check cannot log in.

**2. Credentials and targets** on the monitoring host:

```bash
git clone https://github.com/aptupgrademe/e2e-browser-check ~/e2e-check && cd ~/e2e-check
cp .credentials.example .credentials-cloud && chmod 600 .credentials-cloud && $EDITOR .credentials-cloud
cp targets.example.ini targets.ini && chmod 600 targets.ini && $EDITOR targets.ini
```

**3. Image and first run:**

```bash
podman build -t localhost/local/e2e-check:latest .
python3 run.py --dry-run          # runs every target, prints the values, sends nothing
cat out/*/result.json
```

The first run of a cloud uploads `monitor-test.docx` (created by `make_docx.py`) through the browser:
"New" → "Upload files", like a person would. Results land in `out/<target>/`; on failure a screenshot and the
page text are in `out/<target>/fail/`.

**4. Zabbix.** The hosts must exist (any host works, the items need no interface). `zbx_setup.py` uses `zapi.py`
from [zabbix-podman-homelab](https://github.com/aptupgrademe/zabbix-podman-homelab):

```bash
ZABBIX_PASS_FILE=~/.config/zabbix/admin.pass python3 zbx_setup.py
python3 run.py                    # now the values go to Zabbix
```

**5. Schedule** - twice a day is enough for this kind of check (each run opens a real Collabora session):

```bash
( crontab -l; echo '57 6,18 * * * $HOME/e2e-check/run.sh' ) | crontab -
```

or the systemd user timer in `systemd/` (`loginctl enable-linger` once, so it runs without a login).

## Zabbix side

| Item (trapper) | Type | Content |
|---|---|---|
| `e2e.ok` | numeric | 1 passed, 0 failed |
| `e2e.seconds` | float, s | duration of the whole run |
| `e2e.load` | float, s | the step that matters: document rendered / search answered |
| `e2e.step` | text | failed step, empty when ok |
| `e2e.error` | text | error message, empty when ok |

| Trigger | Severity | Why |
|---|---|---|
| E2E test failed | High | depends on "internet unreachable" and the host's other High triggers: if the site is simply down, that alert already speaks, this one stays quiet |
| no result for 13 hours | Average | the check itself is broken (cron, image, credentials) - a check that silently stops is worse than none |
| slow (over 30 s) | Warning | creeping degradation, visible long before an outage |

The values are sent with the Zabbix sender protocol (`ZBXD\x01` + length + JSON) from `run.py` itself, so no
`zabbix_sender` package is needed. The trapper items only accept values from `trapper_hosts`.
A failed run is repeated once after two minutes before it is reported, so a single hiccup does not wake anybody.
If Zabbix itself cannot be reached, `run.py` mails the result to `[general] mail_to`.

## Pitfalls I hit

- **`ERR_NETWORK_CHANGED`**: with the default rootless network (pasta), Chromium saw a network change right
  after the container started and did not load the page's JavaScript - the login form never appeared.
  `--network=host` fixes it.
- **`--userns=keep-id` hung for minutes**: Podman made an ID-mapped copy of the 2.6 GB image on every new
  mapping. It is not needed: in rootless Podman, root in the container *is* your user on the host, so files in
  `out/` belong to you anyway.
- **"Browser not supported"**: Nextcloud sends unknown user agents to `/unsupported`. Use the real Chrome user
  agent (with `HeadlessChrome` replaced) and append a marker such as `e2e-check` for the logs.
- **`/apps/files/` gave 403** behind one nginx configuration; `/index.php/apps/files/` works everywhere.
- **The welcome tour** of Collabora covers the document on the first opening; `Escape` closes it.
- **Waiting for the iframe is not enough**: the frame is there seconds before the document. Wait for something
  only the document server can produce (the word count).
- **The upload button is not an `<input>` you can find**: it appears only after opening the "New" menu, so the
  check clicks the menu and catches the file chooser (`expect_file_chooser`).

## Demo video

`demo.sh` runs in the image from `Containerfile.demo` (adds ffmpeg, xdotool, fonts): a virtual screen (Xvfb),
a **visible** Chromium window, the address is typed into the address bar and the real mouse pointer moves and
clicks (xdotool), ffmpeg records the screen and adds a caption per step. Chrome's "save password?" bubble is
switched off in the profile (it covered the user menu) and `--test-type` hides the `--no-sandbox` warning bar.

```bash
podman build -f Containerfile.demo -t localhost/local/e2e-demo:latest .
podman run --rm --network=host -v ~/e2e-check:/work:Z -w /work --env-file .credentials-cloud \
  localhost/local/e2e-demo:latest bash /work/demo.sh      # -> out/demo/e2e-check-demo.mp4
```

## Security notes

- The test user has no admin rights, no groups and 100 MB quota; it only sees its own test document.
- Credentials live in `.credentials-*` files with mode 600, passed to the container with `--env-file`;
  they are never on a command line. `.gitignore` keeps them, `targets.ini` and the results out of git.
- Mind brute-force protection and fail2ban: a check with a wrong password retries only once, then reports.

## License

MIT, see [LICENSE](LICENSE).
