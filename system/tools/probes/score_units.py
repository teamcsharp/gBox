"""From 400 addresses holding 100, find the player unit.

`RE4_REASON` says the health lives at `unit + 0x3C2`, so each candidate address `A` implies a unit at `A - 0x3C2`. What
separates a real unit from a coincidental 100 is the neighbourhood: a unit has a **maximum health** beside its health, and
a position somewhere in its first 0x200 bytes. This reads a window around every candidate's unit and scores it, without
touching the game.
"""
import json
import os
import urllib.request

TOKEN = open(os.path.expanduser("~/gBox/system/gbox-data/api_token")).read().strip()
HEADERS = {"authorization": "Bearer " + TOKEN}
BASE = "http://127.0.0.1:8765"
SESSION = json.load(open("/tmp/re4_session.json"))["session"]
HEALTH = 0x3C2
OUT = "/tmp/re4_units.json"


def get(path):
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers=HEADERS), timeout=120) as r:
        return json.loads(r.read() or b"{}")


def read(address, length):
    payload = get(f"/api/sessions/{SESSION}/ram/hex?address={address}&length={length}")
    return bytes.fromhex(payload.get("hex") or "")


import struct  # noqa: E402

listing = get(f"/api/sessions/{SESSION}/ram/search?limit=400")
candidates = [row["address"] for row in listing.get("candidates_list") or []]
print("candidates:", len(candidates), flush=True)

scored = []
for address in candidates:
    unit = address - HEALTH
    try:
        window = read(unit, 0x400)
    except Exception:
        continue
    if len(window) < 0x400:
        continue
    health = struct.unpack_from("<h", window, HEALTH)[0]
    if health != 100:
        continue
    # a maximum health right beside it, and a second plausible one a little further on
    neighbours = [struct.unpack_from("<h", window, HEALTH + off)[0] for off in (2, 4, 6, -2)]
    max_like = [v for v in neighbours if v == 100]
    # a unit carries floats: count values that look like a coordinate or an angle
    floats = [struct.unpack_from("<f", window, off)[0] for off in range(0, 0x200, 4)]
    sane = sum(1 for f in floats if -1e5 < f < 1e5 and (f == 0.0 or abs(f) > 1e-4))
    scored.append({"unit": unit, "health": health, "neighbours": neighbours, "max_like": len(max_like),
                   "sane_floats": sane, "score": len(max_like) * 10 + sane / 64.0})

scored.sort(key=lambda row: -row["score"])
print("units with health 100:", len(scored), flush=True)
for row in scored[:10]:
    print("  unit %#x  neighbours %s  max_like %d  sane_floats %d/128  score %.2f"
          % (row["unit"], row["neighbours"], row["max_like"], row["sane_floats"], row["score"]), flush=True)
json.dump(scored[:40], open(OUT, "w"), indent=1)
print("written", OUT, flush=True)
