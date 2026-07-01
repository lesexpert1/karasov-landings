#!/usr/bin/env python3
"""
aaa_lead_receiver.py — приёмник лидов лендинга → Google Sheets (чистый stdlib).

Разворачивается НА RELAY (RU), чтобы отправка формы шла same-origin (без международного
хопа US↔relay) — максимальная надёжность захвата. Никаких pip-зависимостей: OAuth-refresh
и запись в таблицу — через urllib.

Каждый лид СНАЧАЛА пишется в локальный JSONL-бэкап, ПОТОМ в таблицу — лид не теряется,
даже если Sheets временно недоступен.

Конфиг — env-файл (KEY=VALUE), путь в переменной окружения AUDIT_LEAD_CONFIG
(по умолчанию /etc/audit-lead/config.env). Ключи:
  CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN  — OAuth (аккаунт lesexpert@gmail.com)
  SPREADSHEET_ID, SHEET_TAB                — цель записи
  BACKUP_PATH                              — файл JSONL-бэкапа
  PORT                                     — порт (127.0.0.1)
  TZ_OFFSET                                — смещение часов для метки времени (Иркутск = 8)

Формат строки (16 колонок, как в таблице-образце):
  date, name, phone, form_name, ym_client_id, yclid, utm_source, utm_medium,
  utm_campaign, utm_term, utm_content, utm_device_type, utm_placement,
  ga_client_id, comment, is_junk
"""
import json, os, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COLUMNS = ["date","name","phone","form_name","ym_client_id","yclid","utm_source",
           "utm_medium","utm_campaign","utm_term","utm_content","utm_device_type",
           "utm_placement","ga_client_id","comment","is_junk"]

def load_cfg():
    path = os.environ.get("AUDIT_LEAD_CONFIG", "/etc/audit-lead/config.env")
    cfg = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg

CFG = load_cfg()
TZ = timezone(timedelta(hours=int(CFG.get("TZ_OFFSET", "8"))))
_token = {"value": None, "exp": 0}

def access_token():
    if _token["value"] and time.time() < _token["exp"] - 60:
        return _token["value"]
    data = urllib.parse.urlencode({
        "client_id": CFG["CLIENT_ID"], "client_secret": CFG["CLIENT_SECRET"],
        "refresh_token": CFG["REFRESH_TOKEN"], "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        j = json.load(r)
    _token["value"] = j["access_token"]
    _token["exp"] = time.time() + j.get("expires_in", 3600)
    return _token["value"]

def append_row(row):
    tab = CFG.get("SHEET_TAB", "Все лиды")
    rng = urllib.parse.quote(f"{tab}!A1")
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{CFG['SPREADSHEET_ID']}"
           f"/values/{rng}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS")
    body = json.dumps({"values": [row]}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + access_token(),
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status in (200, 201)

def backup(payload):
    try:
        with open(CFG.get("BACKUP_PATH", "/var/lib/audit-lead/leads.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        print("backup error:", e, file=sys.stderr)

def build_row(d):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    d = {k: (str(v).strip() if v is not None else "") for k, v in d.items()}
    return [
        now, d.get("name",""), d.get("phone",""), d.get("form_name","Экспресс-аудит воронки"),
        d.get("ym_client_id",""), d.get("yclid",""), d.get("utm_source",""), d.get("utm_medium",""),
        d.get("utm_campaign",""), d.get("utm_term",""), d.get("utm_content",""),
        d.get("utm_device_type",""), d.get("utm_placement",""), d.get("ga_client_id",""),
        d.get("comment",""), "",
    ]

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204); self.end_headers()

    def do_GET(self):
        # health-check
        self._send(200, {"ok": True, "service": "audit-lead-receiver"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else b""
            ctype = self.headers.get("Content-Type", "")
            if "application/json" in ctype:
                d = json.loads(raw or b"{}")
            else:
                d = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8")).items()}
        except Exception as e:
            self._send(400, {"ok": False, "error": "bad payload"}); return

        # honeypot + минимальная валидация
        if d.get("website") or d.get("hp"):
            self._send(200, {"ok": True}); return
        if not (str(d.get("name","")).strip() or str(d.get("phone","")).strip()):
            self._send(422, {"ok": False, "error": "empty"}); return

        row = build_row(d)
        backup(d)                          # сначала бэкап — лид не потеряется
        try:
            append_row(row)
            self._send(200, {"ok": True})
        except Exception as e:
            print("sheets error:", e, file=sys.stderr)
            self._send(200, {"ok": True, "queued": True})   # лид в бэкапе, клиенту — успех

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    port = int(CFG.get("PORT", "8092"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"lead receiver on 127.0.0.1:{port}", file=sys.stderr)
    srv.serve_forever()
