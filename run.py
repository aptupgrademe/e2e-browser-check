#!/usr/bin/env python3
"""Runs the end-to-end checks of all targets in targets.ini and hands the results to Zabbix.

For every target the check runs once in the Playwright container. A failed run is repeated once after two
minutes before it counts, so a single hiccup does not raise an alarm. The values go to the trapper items e2e.*
of the target's Zabbix host (see zbx_setup.py); Zabbix keeps the history, evaluates the triggers and sends
the mails. Only when Zabbix itself cannot be reached does this script send a mail of its own ([general] mail_to,
through the local "mail" command).

  run.py              all targets
  run.py cloud blog   only these sections of targets.ini
  run.py --dry-run    run and print what would be sent, send nothing
Standard library only.
"""
import configparser
import datetime as dt
import json
import os
import socket
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "run.log")
SCRIPTS = {"nextcloud": "check_nextcloud.py", "site": "check_site_search.py"}
RETRY_AFTER = 120


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def check(name, t, general):
    """One run of the container for one target; returns the parsed result.json."""
    out_dir = os.path.join(HERE, "out", name)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "result.json")
    if os.path.exists(out):
        os.remove(out)
    # --network=host: with the default rootless network Chromium saw ERR_NETWORK_CHANGED right after the start.
    # No --userns=keep-id: container root already is the calling user, and keep-id made Podman copy the image.
    cmd = ["timeout", "300", "podman", "run", "--rm", "--network=host", "-e", f"TZ={general.get('tz', 'UTC')}",
           "-e", f"OUT_DIR=/work/out/{name}", "-v", f"{HERE}:/work:Z", "-w", "/work"]
    if t.get("credentials"):
        cmd += ["--env-file", os.path.join(HERE, t["credentials"])]
    for kv in t.get("env", "").split():
        cmd += ["-e", kv]
    cmd += [general.get("image", "localhost/local/e2e-check:latest"), "python3", SCRIPTS[t["kind"]]]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.load(open(out))
    except (OSError, ValueError):
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        return {"ok": False, "failed_step": "container", "error": f"rc={r.returncode} " + " | ".join(tail)[:300]}


def zabbix_send(server, host, values):
    """Zabbix sender protocol: "ZBXD\\x01" + 8-byte length + JSON. Returns the server's info string."""
    data = json.dumps({"request": "sender data",
                       "data": [{"host": host, "key": k, "value": str(v)} for k, v in values.items()]}).encode()
    with socket.create_connection(server, timeout=15) as s:
        s.sendall(b"ZBXD\x01" + struct.pack("<Q", len(data)) + data)
        head = s.recv(13)
        body = b""
        while len(body) < struct.unpack("<Q", head[5:13])[0]:
            body += s.recv(4096)
    reply = json.loads(body)
    if reply.get("response") != "success" or "failed: 0" not in reply.get("info", ""):
        raise RuntimeError(reply.get("info", reply))
    return reply["info"]


def run_target(name, t, general, server, dry):
    res = check(name, t, general)
    if not res.get("ok"):
        log(f"{name}: first attempt failed at {res.get('failed_step')}: {res.get('error')}; retry in {RETRY_AFTER} s")
        time.sleep(RETRY_AFTER)
        res = check(name, t, general)
    steps = {s["step"]: s["seconds"] for s in res.get("steps", [])}
    values = {
        "e2e.ok": 1 if res.get("ok") else 0,
        "e2e.seconds": res.get("seconds", 0),
        # the step that matters most: Collabora showing the document, or the site search answering
        "e2e.load": steps.get("document loaded", steps.get("search results", 0)),
        "e2e.step": "" if res.get("ok") else res.get("failed_step", "?"),
        "e2e.error": "" if res.get("ok") else res.get("error", ""),
    }
    log(f"{name}: " + ("OK " if res.get("ok") else "FAILED ") + json.dumps(values, ensure_ascii=False))
    if dry:
        print(name, json.dumps(values, ensure_ascii=False))
        return None
    try:
        log(f"{name}: zabbix: " + zabbix_send(server, t["zabbix_host"], values))
        return None
    except Exception as e:                                   # Zabbix down: report it by mail below
        log(f"{name}: zabbix unreachable: {e}")
        return f"{name}: test {'ok' if res.get('ok') else 'FAILED'}, zabbix: {e}\n{json.dumps(values, ensure_ascii=False)}"


def main():
    dry = "--dry-run" in sys.argv
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(HERE, "targets.ini"))
    general = dict(cfg["general"]) if cfg.has_section("general") else {}
    zbx = dict(cfg["zabbix"]) if cfg.has_section("zabbix") else {}
    server = (zbx.get("server", "127.0.0.1"), int(zbx.get("port", "10051")))
    if not os.path.exists(os.path.join(HERE, "out", "monitor-test.docx")):
        os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
        subprocess.run([sys.executable, "-I", os.path.join(HERE, "make_docx.py"),
                        os.path.join(HERE, "out", "monitor-test.docx")], check=True)
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = [n for n in cfg.sections() if n not in ("general", "zabbix") and (not only or n in only)]
    problems = [p for p in (run_target(n, dict(cfg[n]), general, server, dry) for n in names) if p]
    if problems and general.get("mail_to"):                 # fallback mail only when Zabbix could not be told
        text = ("The end-to-end check could not report to Zabbix.\n\n" + "\n\n".join(problems)
                + f"\n\nChecked {dt.datetime.now():%Y-%m-%d %H:%M} on {socket.gethostname()}.\n")
        subprocess.run(["mail", "-s", "[e2e] Zabbix unreachable", general["mail_to"]],
                       input=text, text=True, capture_output=True)


if __name__ == "__main__":
    main()
