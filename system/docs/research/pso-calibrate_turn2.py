"""Calibrate the turn rate properly, in degrees per second, so the controller can converge instead of oscillating.

The boss fight showed heading error swinging **-65 -> +174 -> -65 -> +174**, which is a controller overshooting its target by roughly 180 degrees every press, not a game problem.
Earlier measurements were coarse (one 0.5 s hold each): left +120 degrees, right -37 degrees. If those rates hold, my press formula `abs(error)/240` capped at 0.4 s can rotate
**96 degrees** in one go - far past a 30 degree target.

So: measure several small holds per direction, fit degrees per second, and print the press duration a given error actually needs. Everything else about movement follows from
getting this right - closing on an enemy, facing it, and staying in range long enough to swing.
"""
import math
import time

from pso_pad import Pad, call


def heading(pad):
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}
    player = state.get("player") or {}
    return float(player.get("heading_deg") or 0), player


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    for key in ("left", "right"):
        samples = []
        for seconds in (0.10, 0.20, 0.30):
            before, _ = heading(pad)
            pad.send([{"key": key, "down": True}])
            time.sleep(seconds)
            pad.send([{"key": key, "down": False}])
            time.sleep(0.35)
            after, _ = heading(pad)
            delta = ((after - before + 540.0) % 360.0) - 180.0
            rate = delta / seconds
            samples.append((seconds, round(delta, 1), round(rate, 1)))
            print(f"  {key:5s} {seconds:.2f}s -> delta {delta:+7.1f} deg  ({rate:+7.1f} deg/s)")
        if samples:
            avg = sum(s[2] for s in samples) / len(samples)
            print(f"  {key}: average {avg:+.1f} deg/s\n")
