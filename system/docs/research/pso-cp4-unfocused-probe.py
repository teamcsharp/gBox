"""CP4/CP16: does Dolphin take unfocused key input? Press START without raising the window and watch `mode`."""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader                     # noqa: E402
from gbox import pso_boot_walk as W                    # noqa: E402
import pso_boot_local as L                             # noqa: E402


def main():
    plane = Plane()
    session = plane.running()
    if not session:
        print("no session")
        return 1
    sid = session["session_id"]
    reader = Reader(plane, sid)
    pid = L.emulator_pid()
    print(f"session {sid}, emulator pid {pid}, focus={L.foreground_is(pid)}")
    for attempt in range(4):
        for name in ("start",):
            scan, ext = L.scancode(name)
            L.send(scan, ext)
        time.sleep(0.15)
        for name in ("start",):
            scan, ext = L.scancode(name)
            L.release(scan, ext)
        time.sleep(2.5)
        state = W.state(reader)
        print(f"attempt {attempt + 1}: mode={state.get('mode')} floor={state.get('floor')} "
              f"player={state.get('player')} focus={L.foreground_is(pid)}")
        if state.get("mode") not in (None, 0):
            print("the game reacted to an UNFOCUSED press")
            return 0
    print("no reaction to unfocused presses")
    return 2


if __name__ == "__main__":
    sys.exit(main())
