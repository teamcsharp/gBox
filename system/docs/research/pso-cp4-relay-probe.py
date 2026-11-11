"""CP4: try the worker-side input relay (the worker owns the docked window) now that the game reacts to nothing local."""
import sys
import time
import urllib.request
import json

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader, BASE                # noqa: E402
from gbox import pso_boot_walk as W                    # noqa: E402


def main():
    plane = Plane()
    session = plane.running()
    if not session:
        print("no session")
        return 1
    sid = session["session_id"]
    reader = Reader(plane, sid)
    token = plane.token

    def relay(keys, actor="agent", frames=4):
        body = json.dumps({"events": [{"key": k, "frames": frames} for k in keys]}).encode()
        req = urllib.request.Request(f"{BASE}/api/sessions/{sid}/input", data=body, headers={
            "authorization": f"Bearer {token}", "x-gbox-actor": actor, "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read().decode()

    for actor in ("agent", "autoplay"):
        for attempt in range(3):
            try:
                print(f"{actor} attempt {attempt + 1}: {relay(['start'], actor)}")
            except Exception as exc:                   # noqa: BLE001
                print(f"{actor} attempt {attempt + 1} failed: {exc}")
            time.sleep(2.5)
            state = W.state(reader)
            print(f"   mode={state.get('mode')} floor={state.get('floor')} player={state.get('player')}")
            if state.get("mode") not in (None, 0):
                print("the relay reached the game")
                return 0
    print("the relay did not reach the game either")
    return 2


if __name__ == "__main__":
    sys.exit(main())
