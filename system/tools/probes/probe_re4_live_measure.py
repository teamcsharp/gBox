"""Measure the RE4 Switch anchors against the session that is ALREADY running - read-only, no boot, no rotation pause.

The previous probe's measurements came back empty because it read `api()` (which returns `(status, payload)`) as a dict.
That is fixed here, and the script does not launch or stop anything: it takes the live session, proves the round is live
from the clock's corner, then runs the two searches.

Usage: probe_re4_live_measure.py [--session SID] [--out FILE]
"""
import argparse
import collections
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GID = "270a15eb98dab4d7"
MODULE = 0x3CA7C04000
BSS = MODULE + 0xB2C738
WINDOW = 7_602_176
CLOCK_BOX = (16, 8, 210, 64)


def api(method, path, body=None, timeout=600):
    """Returns (status, payload) - callers unpack it. The earlier probe indexed the tuple as a dict, which is why its
    measurements were empty."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"detail": exc.read()[:300].decode("utf-8", "replace")}
    except Exception as exc:                                   # noqa: BLE001
        return None, {"detail": str(exc)[:160]}


def payload_of(result):
    return result[1] if isinstance(result, tuple) and len(result) == 2 else result


def frame(session):
    try:
        url = f"{BASE}/api/sessions/{session}/frame.jpg"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                          # noqa: BLE001
        return None


def read(session, address, length):
    status, body = api("GET", f"/api/sessions/{session}/ram/hex?address={address}&length={length}")
    return bytes.fromhex(body["hex"]) if isinstance(body, dict) and body.get("hex") else b""


def clock_ticking(session):
    from io import BytesIO

    from PIL import Image
    first = frame(session)
    time.sleep(4)
    second = frame(session)
    if not first or not second:
        return False, 0
    a = Image.open(BytesIO(first)).convert("L").crop(CLOCK_BOX)
    b = Image.open(BytesIO(second)).convert("L").crop(CLOCK_BOX)
    diff = sum(abs(p - q) for p, q in zip(a.getdata(), b.getdata()))
    return diff > 2000, diff


def search(session, kind, base, size):
    api("DELETE", f"/api/sessions/{session}/ram/search")
    status, body = api("POST", f"/api/sessions/{session}/ram/search", {"type": kind, "base": base, "size": size})
    return body if isinstance(body, dict) else {"detail": "no payload"}


def sample(session, **body):
    status, payload = api("POST", f"/api/sessions/{session}/ram/search/sample", body)
    return payload if isinstance(payload, dict) else {"detail": "no payload"}


def candidates(session, limit=400):
    status, body = api("GET", f"/api/sessions/{session}/ram/search?limit={limit}")
    rows = (body.get("candidates_list") or []) if isinstance(body, dict) else []
    return [(row.get("address"), row.get("address_hex")) for row in rows if row.get("address") is not None]


def measure_clock(session):
    started = search(session, "f32", BSS, WINDOW)
    if "detail" in started:
        return {"error": started["detail"]}
    ranged = sample(session, op="range", lo=1.0, hi=130.0)
    time.sleep(6)
    dropped = sample(session, op="decreased")
    rows = []
    for address, address_hex in candidates(session, 40):
        blob = read(session, address, 4)
        if len(blob) == 4:
            rows.append({"address": address_hex, "value": round(struct.unpack("<f", blob)[0], 3)})
    return {"in_range": ranged.get("candidates"), "decreased": dropped.get("candidates"),
            "rows": sorted(rows, key=lambda row: abs((row["value"] or 0.0) - 120.0))[:10]}


def measure_stride(session):
    started = search(session, "u16", BSS, WINDOW)
    if "detail" in started:
        return {"error": started["detail"]}
    filtered = sample(session, op="equals", value=1000)
    addresses = sorted(address for address, _ in candidates(session, 400))
    gaps = collections.Counter(current - previous for previous, current in zip(addresses, addresses[1:])
                               if 0x10 <= current - previous <= 0x4000)
    return {"candidates": filtered.get("candidates"), "fetched": len(addresses),
            "top_gaps": [(hex(gap), count) for gap, count in gaps.most_common(8)],
            "first": [hex(address) for address in addresses[:10]]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session")
    parser.add_argument("--out", default="/tmp/re4_live_measure.json")
    args = parser.parse_args()
    session = args.session
    if not session:
        status, body = api("GET", "/api/sessions")
        rows = body if isinstance(body, list) else (body.get("sessions") or []) if isinstance(body, dict) else []
        live = [row for row in rows if row.get("state") == "running" and row.get("game_id") == GID]
        session = (live[0].get("session_id") or live[0].get("id")) if live else None
    if not session:
        raise SystemExit("no running RE4 Switch session")
    report = {"session": session}
    ticking, diff = clock_ticking(session)
    report["clock_ticking"] = ticking
    report["clock_diff"] = diff
    print(f"MARK session {session} | clock ticking: {ticking} (diff {diff})", flush=True)
    if not ticking:
        print("MARK not in a live round: measuring anyway, results may be from a menu", flush=True)
    signature = read(session, MODULE + 0x100000, 32).hex()[:32]
    report["module_signature_ok"] = signature == "fd7b07a9fdc30191355100b0b5c646f9"
    print("MARK signature ok:", report["module_signature_ok"], flush=True)
    report["stride"] = measure_stride(session)
    print("MARK stride:", json.dumps(report["stride"])[:400], flush=True)
    report["clock"] = measure_clock(session)
    print("MARK clock:", json.dumps(report["clock"])[:400], flush=True)
    api("DELETE", f"/api/sessions/{session}/ram/search")
    json.dump(report, open(args.out, "w"), indent=1)
    print("MARK written", args.out, flush=True)


if __name__ == "__main__":
    main()
