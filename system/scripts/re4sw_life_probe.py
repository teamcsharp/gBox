"""RE4 Switch: find the player's life in ONE live Mercenaries round, read-only, from any PC (run it ON the Spark).

The life is not in the player unit on Switch (re4_switch PLAYER_HP_IN_UNIT). This dumps the module's data + bss every
--every seconds from the round's HUD until the death screen (re4_switch_screens.is_dead_continue on the frame) or
--max seconds, then ranks the u16 / s16 fields that
  * start in LIFE_LO..LIFE_HI and equal to a neighbour (+2 or -2: the maximum beside it) at the first dump,
  * never rise (a heal would; the bot does not heal),
  * fall at least twice in damage-sized steps (DAMAGE_MIN..DAMAGE_MAX),
  * and end at or near 0 when the round ended on the death screen.
It never sends input or writes memory, and refuses an operator session (one not agent_owned).

    .venv-linux-aarch64/bin/python scripts/re4sw_life_probe.py --server http://127.0.0.1:8765 \\
        --token-file gbox-data/api_token --session <sid> --out ~/gBox_alt/re4life-<sid8>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # system/
sys.path.insert(0, str(Path(__file__).resolve().parent))

import re4sw_round_probe as P                               # noqa: E402  (Api, dump_bss, gray_of, wait_round)
from gbox.mercs.titles import re4_switch as D               # noqa: E402
from gbox.mercs.titles import re4_switch_screens as S       # noqa: E402

LIFE_LO, LIFE_HI = 100, 6000
DAMAGE_MIN, DAMAGE_MAX = 10, 2500


def is_dead(api, sid) -> bool:
    import io

    import numpy as np
    from PIL import Image
    jpeg = api.frame(sid)
    with Image.open(io.BytesIO(jpeg)) as im:
        rgb = np.asarray(im.convert("RGB").resize((S.W, S.H)), dtype=np.int16)
    return bool(S.is_dead_continue(rgb, rgb.mean(axis=2)))


def candidates(dumps, base, died: bool) -> list:
    import numpy as np
    out = []
    for kind, dt in (("u16", "<u2"), ("s16", "<i2")):
        for k, (a, d0) in enumerate(dumps[0]["rows"]):
            series = [np.frombuffer(x["rows"][k][1][:len(d0) // 2 * 2], dtype=dt).astype(np.int64)
                      for x in dumps if k < len(x["rows"]) and x["rows"][k][0] == a]
            if len(series) < 4:
                continue
            arr = np.stack(series)
            first, last = arr[0], arr[-1]
            steps = np.diff(arr, axis=0)
            drops = ((steps <= -DAMAGE_MIN) & (steps >= -DAMAGE_MAX)).sum(axis=0)
            nbr_r = np.concatenate([first[1:], [-1]])
            nbr_l = np.concatenate([[-1], first[:-1]])
            ok = ((first >= LIFE_LO) & (first <= LIFE_HI) & ((first == nbr_r) | (first == nbr_l))
                  & (steps <= 0).all(axis=0) & (drops >= 2))
            if died:
                ok &= last <= np.maximum(first // 10, 0)
            for i in np.nonzero(ok)[0][:200]:
                out.append({"offset": hex(a - base + 2 * int(i)), "type": kind, "series": [int(v) for v in arr[:, i]],
                            "drops": int(drops[i])})
    out.sort(key=lambda r: (-r["drops"], r["offset"]))
    return out[:60]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", default="http://127.0.0.1:8765")
    ap.add_argument("--token-file", default="gbox-data/api_token")
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=float, default=2.5)
    ap.add_argument("--max", type=float, default=240.0)
    ap.add_argument("--wait", type=float, default=300.0)
    a = ap.parse_args(argv)
    api = P.Api(a.server, a.token_file)
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    rows = api.get("/api/sessions", include_ended="false")
    rows = rows if isinstance(rows, list) else rows.get("items") or rows.get("sessions") or []
    row = next((r for r in rows if r.get("session_id") == a.session), None)
    if row is None or not row.get("agent_owned"):
        sys.exit("not an agent-owned running session: refused")
    t_hud = P.wait_round(api, a.session, out, a.wait)
    if t_hud is None:
        sys.exit("no round HUD within the wait")
    base = None
    rep = {"session": a.session, "hud_at": t_hud, "dumps": []}
    # the module base, the way the round probe finds it (its hex reads of the known bases)
    for cand in D.KNOWN_BASES:
        try:
            if api.hex(a.session, cand + D.SIG_OFF, len(D.SIGNATURE)) == D.SIGNATURE:
                base = cand
                break
        except Exception:                                    # noqa: BLE001
            continue
    if base is None:
        sys.exit("module base not found among the known bases")
    rep["base"] = hex(base)
    dumps, died, t0 = [], False, time.time()
    while time.time() - t0 < a.max:
        dumps.append(P.dump_bss(api, a.session, base))
        rep["dumps"].append({"at": dumps[-1]["at"], "spread_s": dumps[-1]["spread_s"]})
        if is_dead(api, a.session):
            died = True
            break
        time.sleep(max(0.0, a.every - 0.5))
    rep["died"] = died
    rep["candidates"] = candidates(dumps, base, died) if len(dumps) >= 4 else []
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    print("dumps:", len(dumps), "died:", died, "candidates:", len(rep["candidates"]))
    for c in rep["candidates"][:12]:
        print(c["offset"], c["type"], c["drops"], c["series"])


if __name__ == "__main__":
    main()
