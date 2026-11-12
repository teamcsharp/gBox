"""Measure whether the bot is actually moving, from the semantic profile."""
import time

from pso_pad import Pad, call

if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    spots = []
    for index in range(8):
        state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST")
        me = (state or {}).get("player") or {}
        spot = (round(float(me.get("x") or 0.0), 1), round(float(me.get("z") or 0.0), 1))
        spots.append(spot)
        print("  %d: %s room %s" % (index + 1, spot, me.get("room")))
        time.sleep(2)

    moved = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(spots, spots[1:]))
    print()
    print("MOVEMENT over 16s:", round(moved, 1), "units")
    print("VERDICT:", "THE BOT IS MOVING" if moved > 5 else "not moving")
