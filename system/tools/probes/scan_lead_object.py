"""Scan the object lead A points at for the values a unit carries: health (100 or 1000) and a position vector.

The document says enemies were seen "26 objects at health 1000" and that full health may not be 100. So this does not
assume a value: it reads the object and reports every offset holding 100 or 1000 as a u16, and every run of three floats
that looks like a world position, rather than searching the whole address space again.
"""
import json
import os
import struct
import urllib.error
import urllib.request

TOKEN = open(os.path.expanduser("~/gBox/system/gbox-data/api_token")).read().strip()
HEADERS = {"authorization": "Bearer " + TOKEN}
BASE = "http://127.0.0.1:8765"
LEADS = json.load(open("/tmp/re4_leads.json"))
SCAN = 0x800


def read(session, address, length):
    url = f"{BASE}/api/sessions/{session}/ram/hex?address={address}&length={length}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as r:
            payload = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        print("read failed:", exc.code, exc.read()[:120])
        return b""
    return bytes.fromhex(payload.get("hex") or "")


session = None
with urllib.request.urlopen(urllib.request.Request(BASE + "/api/sessions", headers=HEADERS), timeout=60) as r:
    rows = json.loads(r.read() or b"{}")
rows = rows if isinstance(rows, list) else rows.get("sessions") or []
live = [r for r in rows if r.get("state") == "running" and r.get("game_id") == "270a15eb98dab4d7"]
if not live:
    raise SystemExit("no RE4 session running")
session = live[0].get("session_id") or live[0].get("id")
print("session", session)

for label, row in LEADS.items():
    pointer = int(row["value"], 16) if row.get("value") else None
    if not pointer:
        continue
    blob = read(session, pointer, SCAN)
    print(f"== {label}: {row['slot']} -> {row['value']} ({len(blob)} bytes read)")
    if not blob:
        continue
    hits = {"100": [], "1000": []}
    for offset in range(0, len(blob) - 2, 2):
        value = struct.unpack_from("<H", blob, offset)[0]
        if value == 100:
            hits["100"].append(hex(offset))
        elif value == 1000:
            hits["1000"].append(hex(offset))
    print("   u16 == 100 at:", hits["100"][:12], f"({len(hits['100'])} total)")
    print("   u16 == 1000 at:", hits["1000"][:12], f"({len(hits['1000'])} total)")

    # a position: three consecutive floats in a sane world range, not tiny, not huge
    runs = []
    for offset in range(0, len(blob) - 12, 4):
        triple = struct.unpack_from("<3f", blob, offset)
        if all(-2000.0 < v < 2000.0 for v in triple) and sum(abs(v) > 0.5 for v in triple) >= 2:
            runs.append((hex(offset), [round(v, 1) for v in triple]))
    print("   position-like triples:", runs[:6], f"({len(runs)} total)")
