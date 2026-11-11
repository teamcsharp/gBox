"""End-to-end self-test for the level editor.

One command that exercises every layer against the live viewer and prints a pass/fail line per check, so the whole editing chain can be
verified without a game - and re-verified after any change.

Checks:
  1. rooms exist for both floors and their counts are the ones measured (Forest 1: 11, Forest 2: 14);
  2. objects decode for both floors (150 / 196);
  3. a point known to be inside a room validates as inside (Forest 1, room 7 at 7.1 units);
  4. the real void sensor position validates as outside;
  5. placing inside a room succeeds AND the structure check passes with every original record intact;
  6. placing in the void is refused;
  7. the edited file on disk still satisfies the structural invariants against the original.

Exit code 0 only if every check passes.
"""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8801"
REL = Path(r"D:\gBox\pso-ds\rel")
EDITED = REL / "edited"
CHECK = Path(r"C:\_tools\gBox\.tmp\set_check.py")
RESULTS = []


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as reply:
        return json.loads(reply.read())


def post(path, payload):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(BASE + path, data=body, method="POST",
                                     headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as reply:
        return json.loads(reply.read())


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def main():
    print("=== level editor self-test")
    try:
        get("/api/rooms?floor=1")
    except Exception as exc:                                        # noqa: BLE001
        print("viewer not reachable:", type(exc).__name__, str(exc)[:100])
        return 2

    rooms1 = get("/api/rooms?floor=1")
    rooms2 = get("/api/rooms?floor=2")
    check("Forest 1 rooms", len(rooms1.get("rooms") or []) == 11, f"{len(rooms1.get('rooms') or [])} rooms")
    check("Forest 2 rooms", len(rooms2.get("rooms") or []) == 14, f"{len(rooms2.get('rooms') or [])} rooms")
    check("Forest 1 doorways", len(rooms1.get("doors") or []) > 0, f"{len(rooms1.get('doors') or [])} edges")
    check("Forest 2 doorways", len(rooms2.get("doors") or []) > 0, f"{len(rooms2.get('doors') or [])} edges")

    objects1 = get("/api/objects?floor=1")
    objects2 = get("/api/objects?floor=2")
    check("Forest 1 objects", len(objects1.get("objects") or []) == 150, f"{len(objects1.get('objects') or [])} objects")
    check("Forest 2 objects", len(objects2.get("objects") or []) == 196, f"{len(objects2.get('objects') or [])} objects")

    inside = post("/api/place", {"floor": 1, "record": 3, "x": -300, "y": 0, "z": 400})
    check("place inside a room accepted", inside.get("ok") is True, f"room {inside.get('room')} at {inside.get('distance')} units")
    check("structure verified after the placement", inside.get("structure_ok") is True,
          str(inside.get("structure") or "")[:90])

    outside = post("/api/place", {"floor": 1, "record": 3, "x": 1082, "y": 0, "z": 1030})
    check("place in the void refused", outside.get("ok") is not True, str(outside.get("why"))[:70])

    edited = EDITED / "map_forest01d.dat"
    original = REL / "map_forest01d.dat"
    if edited.exists():
        finished = subprocess.run([sys.executable, str(CHECK), str(edited), str(original)],
                                  capture_output=True, text=True, timeout=60)
        tail = (finished.stdout or "").strip().splitlines()
        check("edited file still well-formed on disk", finished.returncode == 0,
              tail[-1] if tail else "no output")
    else:
        check("edited file exists", False, "missing")

    passed = sum(1 for _name, ok, _detail in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 3


if __name__ == "__main__":
    raise SystemExit(main())
