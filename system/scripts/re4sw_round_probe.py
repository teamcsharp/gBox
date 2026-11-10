"""RE4 Switch: measure the round's RAM fields in ONE live Mercenaries round, read-only, from any PC.

What it fills (gbox/mercs/titles/re4_switch.py, docs/research/re4-parity.md section 7):
  the clock            two bss dumps ~3 s apart -> re4_switch.clock_candidates (the driver's own finder), module offsets
  kills/combo/score    bss dumps every ~4 s -> u32 / u16 fields that only ever step up by small amounts while the clock runs
  units                memory_search (worker side) for each class lead's vtable word in a heap window, then each object
                       read twice -> the f32 triple that moved at walking speed (U_POS), its health at +0x3c2, the class
                       with one object that moves as the bot walks (PLAYER_CLASS), the classes whose objects move and
                       lose health (ENEMY_CLASSES)

It never sends input, writes memory, launches or stops anything. It refuses a session the operator launched (a session
whose listing does not say agent_owned) unless --allow-operator is given by the operator himself. Every read is a
job the control plane records (read_memory / memory_search, actor "agent"). Frames prove the round was live: the run
waits for the HUD (re4_switch_screens.has_hud) and saves a frame with every sample.

    python system/scripts/re4sw_round_probe.py --out C:/tmp/re4probe            # finds the running RE4 session
    python system/scripts/re4sw_round_probe.py --session <sid> --out <dir> --samples 8

Each dump of the 18.4 MB bss is eleven parallel read_memory jobs (3.9 s measured 2026-11-09); the whole probe moves
about (2 + samples) x 18 MB from the Spark to this PC - run it on a wired PC when one is free (memory note: no heavy
transfers through JAYBUILTFINALE's Wi-Fi; 200 MB is not heavy, a loop of these would be).
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gbox.mercs.titles import re4_switch as D            # noqa: E402
from gbox.mercs.titles import re4_switch_screens as S    # noqa: E402

GAME_ID = "270a15eb98dab4d7"


class Api:
    def __init__(self, server, token_file):
        import httpx
        token = Path(token_file).read_text().strip()
        self.c = httpx.Client(base_url=server, timeout=90,
                              headers={"authorization": f"Bearer {token}", "x-gbox-actor": "agent"})

    def get(self, path, **params):
        r = self.c.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def post(self, path, body):
        r = self.c.post(path, json=body)
        r.raise_for_status()
        return r.json()

    def frame(self, sid) -> bytes:
        r = self.c.get(f"/api/sessions/{sid}/frame.jpg")
        r.raise_for_status()
        return r.content

    def hex(self, sid, addr, n) -> bytes:
        return bytes.fromhex(self.get(f"/api/sessions/{sid}/ram/hex", address=hex(addr), length=n)["hex"])

    def jobs(self, tool, inputs, timeout=120):
        """Submit every input as one job of `tool`, wait for all, return the finished job rows in order."""
        with ThreadPoolExecutor(11) as ex:
            ids = list(ex.map(lambda i: self.post("/api/jobs", {"tool": tool, "input": i})["id"], inputs))
        done, t0 = {}, time.time()
        while len(done) < len(ids) and time.time() - t0 < timeout:
            for j in ids:
                if j not in done:
                    row = self.get(f"/api/jobs/{j}")
                    if row.get("state") in ("succeeded", "failed", "cancelled", "error"):
                        done[j] = row
            time.sleep(0.2)
        return [done.get(j, {"state": "timeout", "id": j}) for j in ids]

    def artifact(self, sha) -> bytes:
        r = self.c.get(f"/api/artifacts/{sha}")
        r.raise_for_status()
        return r.content


def dump_bss(api, sid, base) -> dict:
    """{"rows": [(address, bytes)], "at": wall time of the middle read} through parallel read_memory jobs."""
    rows = [{"session_id": sid, "address": base + off, "length": n} for off, n in D.BSS_ROWS]
    t0 = time.time()
    done = api.jobs("read_memory", rows)
    with ThreadPoolExecutor(6) as ex:
        datas = list(ex.map(lambda j: api.artifact(j["output"]["sha256"]) if j.get("state") == "succeeded" else None,
                            done))
    fin = sorted(j.get("finished") for j in done if j.get("finished"))
    return {"rows": [(r["address"], d) for r, d in zip(rows, datas) if d is not None],
            "at": fin[len(fin) // 2] if fin else (t0 + time.time()) / 2,
            "spread_s": round(fin[-1] - fin[0], 2) if fin else None}


def gray_of(jpeg: bytes):
    import numpy as np
    from PIL import Image
    with Image.open(io.BytesIO(jpeg)) as im:
        rgb = np.asarray(im.convert("RGB").resize((S.W, S.H)), dtype=np.int16)
    return rgb.mean(axis=2)


def wait_round(api, sid, out, timeout_s):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        jpeg = api.frame(sid)
        if S.has_hud(gray_of(jpeg)):
            (out / "round-start.jpg").write_bytes(jpeg)
            return time.time()
        time.sleep(1.0)
    return None


def counters(dumps, base) -> list:
    """u32 / u16 bss fields that never fall and rose in small steps across the dumps (kills, combo, score shapes)."""
    import numpy as np
    out = []
    for kind, dt, size in (("u32", "<u4", 4), ("u16", "<u2", 2)):
        for k, (a, d0) in enumerate(dumps[0]["rows"]):
            series = [np.frombuffer(x["rows"][k][1][:len(d0) // size * size], dtype=dt).astype(np.int64)
                      for x in dumps if k < len(x["rows"]) and x["rows"][k][0] == a]
            if len(series) < 3:
                continue
            arr = np.stack(series)
            steps = np.diff(arr, axis=0)
            ok = (steps >= 0).all(axis=0) & (arr[-1] > arr[0]) & (steps.max(axis=0) <= 100000) & (arr[0] < 10**7)
            for i in np.nonzero(ok)[0][:400]:
                out.append({"offset": hex(a - base + size * int(i)), "type": kind, "series": [int(v) for v in arr[:, i]]})
    out.sort(key=lambda r: (len(set(r["series"])), r["offset"]), reverse=True)
    return out[:120]


def units(api, sid, base, window, samples=2, gap_s=3.0) -> dict:
    """Per class lead: the objects (worker-side memory_search for the vtable word), read `samples` times gap_s apart."""
    lo, hi = window
    found = {}
    for cls in D.UNIT_CLASS_LEADS + (D.MARKER_CLASS,):
        word = (base + cls) & 0xFFFFFFFF
        start = api.jobs("memory_search", [{"session_id": sid, "op": "start", "type": "u32", "value": word,
                                            "ranges": [[lo, hi - lo]]}], timeout=300)[0]
        nxt = api.jobs("memory_search", [{"session_id": sid, "op": "next", "type": "u32", "cmp": "eq",
                                          "value": word}], timeout=300)[0]
        sample = ((nxt.get("output") or {}).get("result") or {}).get("sample") or []
        addrs = []
        for row in sample:
            a = int(row["address"], 16)
            if a % 8 == 0 and struct.unpack("<Q", api.hex(sid, a, 8))[0] == base + cls:
                addrs.append(a)
        found[hex(cls)] = {"count": ((start.get("output") or {}).get("result") or {}).get("candidates"), "objects": addrs}
    reads = []
    for k in range(samples):
        if k:
            time.sleep(gap_s)
        at = time.time()
        snap = {}
        for cls, row in found.items():
            for a in row["objects"]:
                try:
                    snap[a] = api.hex(sid, a, 0x800)
                except Exception:                          # noqa: BLE001 - an object freed between reads
                    pass
        reads.append((at, snap))
    report = {}
    for cls, row in found.items():
        votes, objs = {}, []
        for a in row["objects"]:
            raw = [r[1].get(a) for r in reads]
            if any(x is None for x in raw):
                continue
            hp = [struct.unpack_from("<H", x, D.U_HP)[0] for x in raw]
            moved = []
            for off in range(0x40, 0x800 - 12, 4):
                p0 = struct.unpack_from("<3f", raw[0], off)
                p1 = struct.unpack_from("<3f", raw[-1], off)
                if not all(math.isfinite(v) for v in p0 + p1) or not -500 < p0[1] < 5000 \
                        or max(abs(p0[0]), abs(p0[2])) > 1e5 or max(abs(p0[0]), abs(p0[2])) < 50:
                    continue
                d = math.hypot(p1[0] - p0[0], p1[2] - p0[2])
                if 30 <= d <= 1500 and abs(p1[1] - p0[1]) < 200:
                    moved.append((off, round(d, 1)))
                    votes[off] = votes.get(off, 0) + 1
            objs.append({"addr": hex(a), "id": struct.unpack_from("<I", raw[0], D.U_ID)[0], "hp": hp,
                         "type": raw[0][D.U_TYPE], "moved_at": moved[:12]})
        report[cls] = {"count": row["count"], "objects": objs,
                       "position_offset_votes": sorted(((hex(o), n) for o, n in votes.items()), key=lambda t: -t[1])[:8]}
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", default="http://10.89.1.246:8765")
    ap.add_argument("--token-file", default=r"C:\_tools\gBox\system\gbox-data\api_token")
    ap.add_argument("--session")
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=6, help="bss dumps after the clock pair (counters)")
    ap.add_argument("--heap", default="0x5D50000000:0x5D60000000", help="the unit census window lo:hi")
    ap.add_argument("--wait", type=float, default=600.0, help="seconds to wait for a round's HUD")
    ap.add_argument("--allow-operator", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    api = Api(a.server, a.token_file)
    sessions = api.get("/api/sessions", include_ended="false")
    sess = next((s for s in sessions if (a.session and s["session_id"] == a.session)
                 or (not a.session and s.get("game_id") == GAME_ID)), None)
    if sess is None:
        sys.exit("no running RE4 Switch session")
    if not sess.get("agent_owned") and not a.allow_operator:
        sys.exit(f"{sess['session_id']} was not launched by an agent or MercMode: the operator's sessions are not probed")
    sid = sess["session_id"]
    base = D.KNOWN_BASES[0]
    if api.hex(sid, base + D.SIG_OFF, len(D.SIGNATURE)) != D.SIGNATURE:
        sys.exit("main is not at the known base this boot: run module_base's scan first")
    report = {"session": sid, "base": hex(base), "started": time.time()}
    t_round = wait_round(api, sid, out, a.wait)
    if t_round is None:
        sys.exit("no round HUD within the wait")
    report["round_hud_at"] = t_round
    first = dump_bss(api, sid, base)
    time.sleep(2.0)
    second = dump_bss(api, sid, base)
    dt = second["at"] - first["at"]
    cands = D.clock_candidates(first["rows"], second["rows"], dt)
    report["clock"] = {"dt": round(dt, 2), "spread_s": [first["spread_s"], second["spread_s"]],
                       "picked": hex(D.pick_clock(cands) - base) if cands else None,
                       "candidates": [(hex(x - base), round(v0, 3), round(v1, 3)) for x, v0, v1 in cands[:80]]}
    (out / "clock.jpg").write_bytes(api.frame(sid))
    print("clock:", report["clock"]["picked"], len(cands), "candidates over", round(dt, 2), "s", flush=True)
    lo, hi = (int(x, 16) for x in a.heap.split(":"))
    report["units"] = units(api, sid, base, (lo, hi))
    (out / "units.jpg").write_bytes(api.frame(sid))
    print("units:", {k: (v["count"], v["position_offset_votes"][:2]) for k, v in report["units"].items()}, flush=True)
    dumps = [first, second]
    for k in range(a.samples):
        time.sleep(2.0)
        dumps.append(dump_bss(api, sid, base))
        (out / f"sample-{k}.jpg").write_bytes(api.frame(sid))
    report["counters"] = counters(dumps, base)
    report["finished"] = time.time()
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print("report:", out / "report.json", "counters:", len(report["counters"]))


if __name__ == "__main__":
    main()
