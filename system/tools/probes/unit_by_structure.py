"""Find the player unit by structure, not by playing: a unit starts with a pointer, a stray 100 does not.

The previous pass filtered on behaviour (`decreased` after walking) and lost everything because Leon was never hit. This
one needs no gameplay: search `.bss` for the health value, then keep only candidates whose implied unit
(`address - 0x3C2`) begins with a pointer that lands in the module or the guest heap. A field inside a table of
incrementing counters does not look like that.
"""
import json
import os
import struct
import urllib.error
import urllib.request

TOKEN = open(os.path.expanduser("~/gBox/system/gbox-data/api_token")).read().strip()
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json"}
BASE_URL = "http://127.0.0.1:8765"
SESSION = json.load(open("/tmp/re4_session.json"))["session"]
MODULE_BASE = 0x3CA7C04000
HEALTH = 0x3C2
BSS = MODULE_BASE + 0xB2C738
WINDOW = 7_602_176          # the mapped extent measured last round
OUT = "/tmp/re4_unit_search.json"


def call(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return {"detail": exc.read()[:300].decode("utf-8", "replace")}


def read(address, length):
    payload = call("GET", f"/api/sessions/{SESSION}/ram/hex?address={address}&length={length}")
    return bytes.fromhex(payload.get("hex") or "")


def plausible_pointer(value: int) -> bool:
    """Inside the module image, or in the guest heap band the emulator maps above it."""
    return (MODULE_BASE <= value < MODULE_BASE + 0x02000000) or (0x3C00000000 <= value < 0x3D00000000)


print("starting a fresh search", flush=True)
started = call("POST", f"/api/sessions/{SESSION}/ram/search",
               {"type": "u16", "base": BSS, "size": WINDOW, "tolerance": 0})
if "detail" in started:
    print("start failed:", started["detail"], flush=True)
    raise SystemExit(1)
print("  candidates after the first snapshot:", started.get("candidates"), flush=True)
filtered = call("POST", f"/api/sessions/{SESSION}/ram/search/sample", {"op": "equals", "value": 100})
print("  equals 100 ->", filtered.get("candidates") if "detail" not in filtered else filtered["detail"][:200],
      flush=True)

listing = call("GET", f"/api/sessions/{SESSION}/ram/search?limit=400")
candidates = [row["address"] for row in listing.get("candidates_list") or []]
print("  fetched", len(candidates), "candidates", flush=True)

kept = []
for address in candidates:
    unit = address - HEALTH
    try:
        head = read(unit, 0x20)
    except Exception:
        continue
    if len(head) < 0x20:
        continue
    first = struct.unpack_from("<I", head, 0)[0]
    second = struct.unpack_from("<I", head, 4)[0]
    floats = [struct.unpack_from("<f", head, off)[0] for off in (0x10, 0x14, 0x18, 0x1C)]
    sane = sum(1 for f in floats if -1e6 < f < 1e6 and abs(f) > 1e-6)
    kept.append({"address": address, "unit": unit, "first": first, "second": second,
                 "first_ptr": plausible_pointer(first), "second_ptr": plausible_pointer(second),
                 "sane_floats": sane})

units = [row for row in kept if row["first_ptr"] or row["second_ptr"]]
print("  units whose head is a pointer:", len(units), "of", len(kept), flush=True)
for row in units[:12]:
    print("   %#x first %#x second %#x sane_floats %d" % (row["unit"], row["first"], row["second"],
                                                           row["sane_floats"]), flush=True)
json.dump({"candidates": len(candidates), "units": units}, open(OUT, "w"), indent=1)
print("written", OUT, flush=True)
