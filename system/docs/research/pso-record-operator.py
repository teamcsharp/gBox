"""Record the operator's own controller while they play, as `imitate.learn`'s timeline.

gBox's gameplay-memory journal is the plane's archive, but it is bounded and only fills while a session is detected. This recorder is
the local backstop: it samples the operator's pad (`pad_bind`'s alive slot, so a ghost at slot 0 is never mistaken for them) at 30 Hz,
keeps a row only when the pressed set changes, and writes both a JSON timeline and a ready mission through
`gbox.pso_learn_play` when it stops.

    python pso_record_operator.py --pid 4420 --seconds 600
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\imitate-wt\system")

from gbox import pad_bind, pso_learn_play as LP, xinput          # noqa: E402

OUT = Path(r"D:\gBox\pso-ds")
BUTTONS = {0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y", 0x0010: "start", 0x0020: "back",
           0x0040: "l3", 0x0080: "r3", 0x0100: "r", 0x0200: "l", 0x0001: "dup", 0x0002: "ddown",
           0x0004: "dleft", 0x0008: "dright"}


def pressed(gamepad) -> frozenset:
    keys = {name for bit, name in BUTTONS.items() if gamepad.buttons & bit}
    if abs(gamepad.lx) > 7849:
        keys.add("right" if gamepad.lx > 0 else "left")
    if abs(gamepad.ly) > 7849:
        keys.add("down" if gamepad.ly > 0 else "up")
    if abs(gamepad.rx) > 7849:
        keys.add("cright" if gamepad.rx > 0 else "cleft")
    if abs(gamepad.ry) > 7849:
        keys.add("cdown" if gamepad.ry > 0 else "cup")
    return frozenset(keys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=900)
    ap.add_argument("--name", default="operator")
    args = ap.parse_args()
    fn = xinput.load()
    slot, keys, rows, start = None, frozenset(), [], time.time()
    print("recording the operator's pad; start playing", flush=True)
    last_report = 0.0
    while time.time() - start < args.seconds:
        states = {}
        for s in range(4):
            st = xinput.read(fn, s)
            if st is not None:
                g = st.gamepad
                states[s] = (g.buttons, g.lx, g.ly, g.rx, g.ry, g.lt, g.rt)
        alive = pad_bind.live_slots(states)
        slot = alive[0] if alive else slot
        if slot is None or slot not in states:
            time.sleep(1 / 30)
            continue
        st = xinput.read(fn, slot)
        if st is None:
            time.sleep(1 / 30)
            continue
        now = pressed(st.gamepad)
        if now != keys:
            rows.append((round(time.time() - start, 3), sorted(now)))
            keys = now
        if time.time() - last_report > 20:
            last_report = time.time()
            print(f"{time.strftime('%H:%M:%S')} slot {slot}: {len(rows)} changes, last {sorted(keys)}", flush=True)
        time.sleep(1 / 30)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    timeline = [(t, frozenset(k)) for t, k in rows]
    path = OUT / f"operator-timeline-{stamp}.json"
    path.write_text(json.dumps({"slot": slot, "started": start, "rows": rows}, indent=1), encoding="utf-8")
    print(f"timeline: {len(rows)} changes -> {path}")
    if len(timeline) >= 4:
        learned = LP.learn(timeline)
        mission = LP.mission(learned, game_id="436e0bb84d5337d1", name=f"pso-learned-{stamp}",
                             run=path.stem, objective="Replay the operator's recorded controller timeline")
        mpath = LP.save(mission, Path(r"D:\gBox\pso-ds\learned-missions"))
        print(f"learned {len(learned.get('bursts') or [])} bursts, menu keys {learned.get('menu')} -> {mpath}")
    else:
        print("too few input changes to learn from (play a little longer next time)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
