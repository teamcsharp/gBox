"""Poll all four XInput slots and report which one changes while the operator presses buttons."""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox import xinput                                        # noqa: E402


def snapshot(fn):
    out = {}
    for s in range(4):
        st = xinput.read(fn, s)
        out[s] = None if st is None else (st.gamepad.buttons, st.gamepad.lt, st.gamepad.rt,
                                          st.gamepad.lx, st.gamepad.ly, st.gamepad.rx, st.gamepad.ry)
    return out


def main(seconds=12.0):
    fn = xinput.load()
    print("watching slots 0-3 for 12 s - press buttons / move sticks on the controller")
    first = snapshot(fn)
    changed = {s: 0 for s in range(4)}
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.1)
        now = snapshot(fn)
        for s in range(4):
            if first.get(s) is not None and now.get(s) != first.get(s):
                changed[s] += 1
                first[s] = now[s]
    final = snapshot(fn)
    for s in range(4):
        state = "connected" if final[s] is not None else "empty"
        print(f"slot {s}: {state}, {changed[s]} changes")
    best = max(changed, key=changed.get)
    print(f"the controller that moved is most likely XInput slot {best}" if changed[best] else
          "no slot changed - no button presses were seen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
