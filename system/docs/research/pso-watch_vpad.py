"""Does a press actually reach the virtual pad, or is it lost before it?

Everything else has been ruled out for this freeze: `walk_through` off changes nothing, the vpad exists on XInput slot 0, no menu or dialogue is on screen, HP is 68/68, and the
world is live (enemies move). The same `send_input` API moved the character 211 units earlier.

So watch the pad itself: hold a direction, and while it is held read XInput slot 0. If the buttons change, the press **is** reaching the virtual pad and the game is refusing it
(a game-side state). If slot 0 stays at zero, the press is being lost between the job and the pad - which would be the same family of bug as the `/input` route that never
delivered.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pad_route, xinput                     # noqa: E402
from pso_pad import Pad, call                          # noqa: E402


def read_slot(slot: int = 0):
    handle = xinput.load()
    state = xinput.read(handle, slot)
    if state is None:
        return None
    reading = pad_route.slot_reading(state)
    return {"buttons": reading.get("buttons"), "lx": reading.get("lx"), "ly": reading.get("ly")}


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    print("idle slot 0:", read_slot())

    for key in ("up", "left", "a"):
        pad.send([{"key": key, "down": True}])
        time.sleep(0.5)
        held = read_slot()
        pad.send([{"key": key, "down": False}])
        time.sleep(0.4)
        released = read_slot()
        print(f"  {key:5s}: held {held} | after release {released}")

    # and does the game care? one long hold, position before and after
    import math
    def player():
        state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
        return state.get("player") or {}

    before = player()
    start = (float(before.get("x") or 0), float(before.get("z") or 0))
    pad.send([{"key": "up", "down": True}])
    time.sleep(2.0)
    mid = player()
    pad.send([{"key": "up", "down": False}])
    time.sleep(0.5)
    after = player()
    end = (float(after.get("x") or 0), float(after.get("z") or 0))
    print(f"\n2 s hold: {start} -> {end} | moved {math.dist(start, end):.1f} units")
    print(f"  y during hold: {mid.get('y')} (was {before.get('y')})")
