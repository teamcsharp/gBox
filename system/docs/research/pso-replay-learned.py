"""Replay the operator's recorded play (gbox.pso_learn_play mission) through the working keyboard input path.

The mission stores pad-level steps (`press key n`, `wait secs`); win_send_keys maps those same pad names to Dolphin's keyboard
bindings, so a press of "a" here is the A button exactly as the adapter would send it. Time can be scaled (1.0 = the recorded pace).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

MISSION = Path(r"D:\gBox\pso-ds\learned-missions\pso-learned-20261110-210547.json")
PID = 36964


def gbox_hwnd():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.strip() == "gBox":
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def press(events):
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(2):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.08)
        try:
            answer = win_send_keys(PID, events)
            if answer.get("sent"):
                return answer
        except Exception:                                        # noqa: BLE001
            time.sleep(0.08)
    return {"sent": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=800)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--shot-every", type=float, default=30.0)
    args = ap.parse_args()
    mission = json.loads(MISSION.read_text(encoding="utf-8"))
    steps = mission["steps"][:args.steps]
    print(f"replaying {len(steps)} of {len(mission['steps'])} steps at {args.scale}x")
    started = last_shot = time.time()
    sent = 0
    for index, step in enumerate(steps):
        op = step.get("op")
        if op == "press":
            count = int(step.get("n") or 1)
            for _ in range(count):
                sent += press([{"key": step["key"], "down": True}, {"key": step["key"], "down": False}]).get("sent", 0)
                time.sleep(0.05)
        elif op == "wait":
            time.sleep(max(0.0, float(step.get("secs") or 0)) * args.scale)
        if time.time() - last_shot >= args.shot_every:
            cap.main()
            print(f"  step {index}/{len(steps)} sent={sent} elapsed={time.time()-started:.0f}s", flush=True)
            last_shot = time.time()
    cap.main()
    print(f"done: {len(steps)} steps, {sent} events, {time.time()-started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
