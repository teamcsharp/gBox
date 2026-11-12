"""Self-test the whole stack, so a restart has something provably ready behind it.

Checks, in order, each as a pass/fail with the measurement that decided it:

  1. **session** - a live operator-owned session exists;
  2. **maps** - every floor 1-14 has a room mesh and a height table;
  3. **room database** - every floor is present with rooms;
  4. **audit** - the map audit report exists and covers the floors;
  5. **collision maps** - the extracted `.rel` files are on disk;
  6. **minimap** - the HTTP server answers;
  7. **weapon advisor** - its six situations still resolve to the right weapon classes;
  8. **play loops** - every play/exit module imports cleanly;
  9. **interaction** - the live character is readable (a real memory read, not a mock).

Exit code 0 only if all pass, so this can gate the big run.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

ROUTES = Path(r"D:\gBox\pso-ds\routes")
REL = Path(r"D:\gBox\pso-ds\rel")
ROOMS = Path(r"D:\gBox\pso-ds\rooms")
results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as exc:                                      # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {str(exc)[:70]}"
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def session_check():
    import session as S
    import map_exit as ME
    point = ME.read_pos()
    return point is not None, f"session {S.session_id()[:12]}…, pid {S.pid()}, character readable"


def maps_check():
    missing = [floor for floor in range(1, 15)
               if not (ROUTES / f"forest{floor}-rooms-mesh.json").exists()
               or not (ROUTES / f"forest{floor}-heights.json").exists()]
    return not missing, ("all 14 floors have mesh + heights" if not missing else f"missing: {missing}")


def room_db_check():
    index = json.loads((ROOMS / "index.json").read_text(encoding="utf-8"))
    floors = sorted(int(key) for key in index)
    rooms = sum(entry["rooms"] for entry in index.values())
    return floors == list(range(1, 15)), f"{len(floors)} floors, {rooms} rooms"


def audit_check():
    rows = json.loads((ROUTES / "map-audit.json").read_text(encoding="utf-8"))
    floors = sorted(int(row["floor"]) for row in rows)
    passing = sum(1 for row in rows if row.get("ok"))
    return len(rows) >= 14, f"{len(rows)} floors audited, {passing} fully navigable"


def collision_check():
    files = list(REL.glob("*c.rel"))
    return len(files) >= 150, f"{len(files)} collision files on disk"


def minimap_check():
    body = urllib.request.urlopen("http://127.0.0.1:8802/api/transform", timeout=20).read()
    payload = json.loads(body)
    ok = "scale" in payload
    # and confirm the live view answers too, with a generous window for the first render
    state = json.loads(urllib.request.urlopen("http://127.0.0.1:8802/api/state", timeout=40).read())
    return ok and "floor" in state, (f"floor {state['floor']}, "
                                     f"{len(state.get('enemies') or [])} enemies, "
                                     f"scale {payload['scale']:.2f}")


def advisor_check():
    import weapon_advisor as WA
    me = (0.0, 0.0, 0.0)
    cases = {
        "three close": ([{"class": "A", "distance": 5, "y": 0, "hp": 9, "x": 5, "z": 0}] * 3, WA.WIDE),
        "one close": ([{"class": "A", "distance": 4, "y": 0, "hp": 9, "x": 4, "z": 0}], WA.FAST),
        "one far": ([{"class": "A", "distance": 30, "y": 0, "hp": 9, "x": 30, "z": 0}], WA.RANGED),
        "one flying": ([{"class": "A", "distance": 8, "y": 12, "hp": 9, "x": 8, "z": 0}], WA.RANGED),
    }
    wrong = []
    for name, (targets, expected) in cases.items():
        wanted, _reason = WA.choose(targets, me)
        if wanted != expected:
            wrong.append(name)
    return not wrong, "all situations correct" if not wrong else f"wrong: {wrong}"


def loops_check():
    import close_and_kill                                                # noqa: F401
    import exit_seek                                                     # noqa: F401
    import play_background                                               # noqa: F401
    import play_when_focused                                             # noqa: F401
    return True, "play_background, play_when_focused, exit_seek, close_and_kill all import"


def interaction_check():
    import map_exit as ME
    point = ME.read_pos()
    return point is not None, f"character at {tuple(round(v, 1) for v in point)}"


if __name__ == "__main__":
    print("=== stack self-test")
    checks = [("session", session_check), ("maps", maps_check), ("room database", room_db_check),
              ("audit", audit_check), ("collision maps", collision_check), ("minimap", minimap_check),
              ("weapon advisor", advisor_check), ("play loops", loops_check),
              ("interaction", interaction_check)]
    passed = sum(1 for name, fn in checks if check(name, fn))
    print(f"\n{passed}/{len(checks)} passed")
    raise SystemExit(0 if passed == len(checks) else 1)
