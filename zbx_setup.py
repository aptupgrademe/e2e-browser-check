#!/usr/bin/env python3
"""Creates the Zabbix side of the end-to-end checks for every target in targets.ini (idempotent: items and
triggers that exist stay as they are). The hosts themselves must exist already (zabbix_host = technical name).

Trapper items on each target's host (run.py pushes the values after every run):
  e2e.ok        1 = all steps passed, 0 = failed
  e2e.seconds   duration of the whole run
  e2e.load      seconds of the step that matters most (Collabora shows the document / the site search answers)
  e2e.step      failed step ("" when ok)
  e2e.error     error message ("" when ok)
Triggers:
  - run failed (High). It depends on the host's other triggers and on the "internet unreachable" trigger
    ([zabbix] internet_trigger), so it only speaks when the simple checks look fine but the way through the
    application does not - no second mail for an outage that is already reported.
  - no result for 13 hours (Average): the check itself is broken (container, cron, credentials, image).
  - slow (Warning): the measured step took longer than 30 seconds.

Uses zapi.py from https://github.com/aptupgrademe/zabbix-podman-homelab (directory in ZAPI_DIR, default
~/zabbix-podman-homelab) and its settings ZABBIX_URL / ZABBIX_USER / ZABBIX_PASS_FILE.
"""
import configparser
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser(os.environ.get("ZAPI_DIR", "~/zabbix-podman-homelab")))
import zapi  # noqa: E402

TEXT = {
    "en": {"ok": "E2E: test passed", "sec": "E2E: total duration", "load": "E2E: key step (document / search)",
           "step": "E2E: failed step", "err": "E2E: error message", "desc": "Sent by run.py after every run.",
           "nc": "log in, open document, log out", "site": "home page, search, page",
           "fail": "{h}: E2E test failed ({w})", "nodata": "{h}: E2E test has sent no result for 13 hours",
           "slow": "{h}: E2E slow (over 30 s)", "op": "Step: {ITEM.LASTVALUE2}"},
    "de": {"ok": "E2E: Test bestanden", "sec": "E2E: Dauer gesamt", "load": "E2E: wichtigster Schritt (Dokument geladen / Suche)",
           "step": "E2E: fehlgeschlagener Schritt", "err": "E2E: Fehlermeldung", "desc": "Gesendet von run.py nach jedem Lauf.",
           "nc": "Anmelden, Dokument öffnen, abmelden", "site": "Startseite, Suche, Beitrag",
           "fail": "{h}: E2E-Test fehlgeschlagen ({w})", "nodata": "{h}: E2E-Test liefert seit 13 Stunden kein Ergebnis",
           "slow": "{h}: E2E langsam (über 30 s)", "op": "Schritt: {ITEM.LASTVALUE2}"},
}

cfg = configparser.ConfigParser()
cfg.read(os.path.join(HERE, "targets.ini"))
zbx = dict(cfg["zabbix"]) if cfg.has_section("zabbix") else {}
L = TEXT[zbx.get("lang", "en")]
ITEMS = [("e2e.ok", L["ok"], 3, ""), ("e2e.seconds", L["sec"], 0, "s"), ("e2e.load", L["load"], 0, "s"),
         ("e2e.step", L["step"], 4, ""), ("e2e.error", L["err"], 4, "")]   # value_type 0 float, 3 unsigned, 4 text

t = zapi.login()
internet = []
if zbx.get("internet_trigger"):
    internet = [x["triggerid"] for x in zapi.call("trigger.get", {"output": ["description"],
                "search": {"description": zbx["internet_trigger"]}}, t)]

for name in cfg.sections():
    if name in ("general", "zabbix"):
        continue
    H = cfg[name]["zabbix_host"]
    host = zapi.call("host.get", {"output": ["hostid", "name"], "filter": {"host": [H]}}, t)[0]
    hid, label = host["hostid"], host["name"]
    have = {i["key_"] for i in zapi.call("item.get", {"output": ["key_"], "hostids": hid}, t)}
    for key, iname, vtype, units in ITEMS:
        if key not in have:
            zapi.call("item.create", {"hostid": hid, "name": iname, "key_": key, "type": 2, "value_type": vtype,
                                      "units": units, "trapper_hosts": zbx.get("trapper_hosts", "127.0.0.1,::1"),
                                      "history": "90d", "tags": [{"tag": "check", "value": "e2e"}],
                                      "description": L["desc"]}, t)
            print(H, "item", key)
    existing = zapi.call("trigger.get", {"output": ["triggerid", "description", "priority"], "hostids": hid}, t)
    if any("E2E" in x["description"] for x in existing):
        continue                                             # already set up
    others = [x["triggerid"] for x in existing if int(x["priority"]) >= 4]   # outages, not certificate warnings
    what = L["nc"] if cfg[name]["kind"] == "nextcloud" else L["site"]
    for desc, expr, prio, opdata, dep in [
            (L["fail"].format(h=label, w=what), f"last(/{H}/e2e.ok)=0 and length(last(/{H}/e2e.step))>=0", 4,
             L["op"], internet + others),
            (L["nodata"].format(h=label), f"nodata(/{H}/e2e.ok,13h)=1", 3, "", []),
            (L["slow"].format(h=label), f"last(/{H}/e2e.load)>30", 2, "{ITEM.LASTVALUE1}", [])]:
        zapi.call("trigger.create", {"description": desc, "expression": expr, "priority": prio, "opdata": opdata,
                                     "dependencies": [{"triggerid": d} for d in dep],
                                     "tags": [{"tag": "check", "value": "e2e"}]}, t)
        print(H, "trigger", desc, "dependencies", len(dep))
