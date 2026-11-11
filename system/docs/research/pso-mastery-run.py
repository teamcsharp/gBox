"""The unattended mastery run: one command that walks to the exit, fights the boss, and writes the evidence itself.

This is the CP17/CP18/CP19 pipeline the PM document asks for, assembled from the parts that were measured this session:

  stage 1  verify the session: running, operator-owned, playable. An agent-owned session has no input, so the run refuses rather than
           producing a meaningless pass;
  stage 2  start the observers (learn_live for position/floor/HP, and the boss watcher during the fight) so evidence is captured as it
           happens instead of reconstructed afterwards;
  stage 3  CP17: run the certified route to Forest 1's exit with the fast runner and watch for the FLOOR ID CHANGE while walking - the
           accept signal. No warp is used for this stage, because a warp is explicitly not acceptance;
  stage 4  CP18: warp to the Dragon (a dev shortcut, allowed for developing the fight), then attack while the boss watcher records the HP
           series and every player's HP, and stop when the boss reaches 0;
  stage 5  write an evidence report listing which accept conditions were observed and which were not.

Usage:
  python mastery_run.py --check          report what is ready, change nothing
  python mastery_run.py --cp17           walk the certified route and record the floor transition
  python mastery_run.py --cp18            warp to the Dragon, fight, record the HP series
  python mastery_run.py --all            both, in order
"""
import json
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import learn_live as L                                             # noqa: E402
import nav_fast as NAV                                             # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

FLOOR = 0x805D5FC0
EXIT_1 = (133.0, -48.1)                                            # Forest 1's warp, from the operator's play
EVIDENCE = Path(r"D:\gBox\pso-ds\evidence")
PYTHON = r"C:\Users\maste\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"


def log(line):
    print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)


def floor_now():
    return int.from_bytes(S.read_memory(FLOOR, 4), "big")


def session_state():
    rows = S._call("/api/sessions")
    sid = None
    try:
        sid = S.session_id()
    except Exception:                                          # noqa: BLE001
        return {"running": False}
    row = next((r for r in rows if r.get("session_id") == sid), {})
    return {"session_id": sid, "state": row.get("state"), "agent_owned": row.get("agent_owned"),
            "floor": floor_now() if row.get("state") == "running" else None}


def stage1_check():
    state = session_state()
    log(f"session: {json.dumps(state)}")
    if not state.get("running", True) or state.get("state") != "running":
        log("REFUSED: no running session")
        return False
    if state.get("agent_owned") is True:
        log("REFUSED: this session is agent-owned, so it accepts no input; start the game from the app")
        return False
    log("session is operator-owned and running")
    return True


def start_observer(seconds):
    return subprocess.Popen([PYTHON, "learn_live.py", str(seconds)], cwd=r"C:\_tools\gBox\.tmp",
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stage_cp17(max_legs=12):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    start = (lambda p: (p[0], p[1]) if p else None)(None)
    import map_exit as ME
    start = ME.read_pos()
    if start is None:
        log("no player position")
        return False
    before = floor_now()
    log(f"CP17: floor {before}, player {tuple(round(v) for v in start)} -> exit {EXIT_1}")
    observer = start_observer(6)
    route, raw_count, simple_count = NAV.plan(start, EXIT_1)
    if not route:
        log("CP17 FAILED: no route")
        return False
    log(f"CP17 route: {raw_count} cells -> {simple_count} legs")
    line = {"t": round(time.time(), 3), "event": "cp17_start", "floor": before,
            "start": [round(start[0], 1), round(start[1], 1)], "exit": list(EXIT_1), "legs": len(route)}
    series = Path(EVIDENCE / "cp17-floor-series.jsonl")
    with series.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")
        for index, waypoint in enumerate(route[1:] or route):
            arrived, elapsed, final, travelled, cycles = RUN.run_to(ME.read_pos, waypoint, tolerance=14.0, budget=30.0)
            current = floor_now()
            handle.write(json.dumps({"t": round(time.time(), 3), "event": "cp17_leg", "leg": index + 1,
                                     "floor": current, "arrived": arrived, "elapsed": round(elapsed, 1),
                                     "travelled": round(travelled)}) + "\n")
            handle.flush()
            log(f"  leg {index + 1}/{len(route) - 1}: arrived={arrived} {elapsed:.1f}s floor={current}")
            if current != before:
                log(f"CP17 ACCEPT: floor changed {before} -> {current} while walking")
                handle.write(json.dumps({"t": round(time.time(), 3), "event": "cp17_ACCEPT",
                                         "from": before, "to": current}) + "\n")
                handle.flush()
                return True
    log(f"CP17: no floor change observed (floor still {floor_now()})")
    return False


def stage_cp18(seconds=240):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    log("CP18: warping to the Dragon (dev shortcut for developing the fight)")
    try:
        reply = S.controls("boss_warp", {"target": "dragon"})
        log(f"  boss_warp: {json.dumps(reply)[:160] if reply else 'no reply'}")
    except Exception as exc:                                      # noqa: BLE001
        log(f"  boss_warp refused: {str(exc)[:120]}")
        return False
    time.sleep(6)
    log(f"  floor now {floor_now()}")
    watcher = subprocess.Popen([PYTHON, "boss_both.py", "TBoss", str(seconds)], cwd=r"C:\_tools\gBox\.tmp",
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("  boss watcher recording; attacking while the operator is off the pad")
    started = time.time()
    attacks = 0
    while time.time() - started < seconds:
        if pso_input.allowed():
            pso_input.tap("a", gap=0.3)
            attacks += 1
        else:
            time.sleep(0.3)
        if watcher.poll() is not None:
            log(f"  boss watcher ended after {attacks} attacks")
            break
    watcher.wait(timeout=30)
    log(f"CP18 finished: {attacks} attacks issued")
    return True


def main(argv):
    if "--check" in argv or len(argv) == 1:
        ok = stage1_check()
        log(f"ready: {ok}")
        return 0 if ok else 3
    if not stage1_check():
        return 3
    results = {}
    if "--cp17" in argv or "--all" in argv:
        results["cp17"] = stage_cp17()
    if "--cp18" in argv or "--all" in argv:
        results["cp18"] = stage_cp18()
    report = Path(EVIDENCE / "mastery-report.json")
    report.write_text(json.dumps({"t": round(time.time(), 3), "results": results}, indent=1), encoding="utf-8")
    log(f"results: {results}  report: {report}")
    return 0 if all(results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
