"""Two ways to isolate Leon's health, in one pass.

1. Deterministic: if the layout keeps `hp` and `hp_max` adjacent (the GameCube build does: 0x320 / 0x322), then a real
   health address has 100 at both `A` and `A+2`. Count how many of the 400 candidates satisfy that - no gameplay needed.
2. Behavioural: walk into the village long enough to be hit, then keep only addresses whose value DROPPED.
"""
import json
import os
import struct
import time
import urllib.error
import urllib.request

TOKEN = open(os.path.expanduser("~/gBox/system/gbox-data/api_token")).read().strip()
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json"}
BASE = "http://127.0.0.1:8765"
SESSION = json.load(open("/tmp/re4_session.json"))["session"]
OUT = "/tmp/re4_hp2.json"


def call(method, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return {"detail": exc.read()[:200].decode("utf-8", "replace")}


def read(address, length):
    payload = call("GET", f"/api/sessions/{SESSION}/ram/hex?address={address}&length={length}")
    return bytes.fromhex(payload.get("hex") or "")


listing = call("GET", f"/api/sessions/{SESSION}/ram/search?limit=400")
candidates = [row["address"] for row in listing.get("candidates_list") or []]
print("candidates:", len(candidates), flush=True)

pairs = []
for address in candidates:
    try:
        window = read(address - 4, 12)
    except Exception:
        continue
    if len(window) < 12:
        continue
    before, here, after = (struct.unpack_from("<h", window, off)[0] for off in (0, 4, 6))
    # `here` is the health (u16 == 100); a max beside it is the layout the GameCube build uses
    if after == 100 or before == 100:
        pairs.append({"address": address, "before": before, "here": here, "after": after})
print("candidates with 100 adjacent (hp/hp_max layout):", len(pairs), flush=True)
for row in pairs[:10]:
    print("   %#x before %d here %d after %d" % (row["address"], row["before"], row["here"], row["after"]), flush=True)

print("walking into the village for ~45 s", flush=True)
for _ in range(8):
    call("POST", "/api/jobs", {"tool": "session_op", "require_worker": SESSION.split("-")[0],
                               "input": {"session_id": SESSION, "op": "send_input",
                                         "args": {"events": [{"key": "w", "down": True}]}}})
    time.sleep(5)
    call("POST", "/api/jobs", {"tool": "session_op", "require_worker": SESSION.split("-")[0],
                               "input": {"session_id": SESSION, "op": "send_input",
                                         "args": {"events": [{"key": "w", "down": False}]}}})
    time.sleep(1)
result = call("POST", f"/api/sessions/{SESSION}/ram/search/sample", {"op": "decreased"})
print("decreased sample:", {k: result.get(k) for k in ("candidates", "mode")} if "detail" not in result
      else result["detail"][:200], flush=True)
rows = (call("GET", f"/api/sessions/{SESSION}/ram/search?limit=50").get("candidates_list") or [])
print("survivors:", [row["address_hex"] for row in rows[:10]], flush=True)
json.dump({"pairs": pairs, "decreased": rows}, open(OUT, "w"), indent=1)
print("written", OUT, flush=True)
