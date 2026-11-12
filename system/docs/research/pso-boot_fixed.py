"""Boot to the field with fixed timing, because the title animates.

The adaptive helper ("press until the screen changes") cannot work on these screens: the PSO title **animates**, so a frame-hash comparison always reports a change and the
sequence advances before the menu is even open. That is why the same chain that worked by hand kept collapsing to "PRESS START".

PlayStation-style fixed timing does work, because every step is a menu with a settled cursor:

    START            -> main menu
    DOWN             -> OFFLINE GAME
    A                -> SELECT GAME MODE
    A                -> SELECT CHARACTER
    A                -> Confirm / Cancel / Recreate
    A                -> SELECT EPISODE
    A                -> warp

Each press is one job carrying down+up together (the shape measured to reach the game), with a wait long enough for the next screen to build. Success is judged only
by the player pointer, which is unambiguous.
"""
import subprocess
import sys
import time

from pso_pad import Pad, call

GAME = "436e0bb84d5337d1"
STEPS = [("start", 2.4), ("down", 1.2), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 4.0), ("a", 4.0)]


def live():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def main() -> int:
    for row in live():
        sid = row["session_id"]
        print("stopping earlier session:", sid)
        call("/api/jobs", {"tool": "session_op", "require_worker": sid.split("-")[0],
                           "input": {"session_id": sid, "op": "stop_game", "args": {}}}, "POST")
        time.sleep(6)

    rows = call("/api/workers")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    worker_id = next((row["id"] for row in rows if row.get("online")), "")
    if not worker_id:
        print("no online worker")
        return 1
    print("worker:", worker_id)

    game = call("/api/catalog/" + GAME)
    job = call("/api/jobs", {"tool": "launch_game", "input": {"game": game},
                             "require_worker": worker_id}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(30):
        time.sleep(3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("launch:", row.get("state"), str(row.get("error"))[:80])
            if row.get("state") != "succeeded":
                return 1
            break

    sessions = live()
    if not sessions:
        print("no session")
        return 1
    pad = Pad(sessions[0]["session_id"])
    print("session:", pad.sid)
    time.sleep(32)   # the boot (logo, licence, title) takes ~20-30 s; pressing early does nothing

    for index, (key, wait) in enumerate(STEPS, 1):
        pad.send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(wait)
        pointer = pad.player_pointer()
        print(f"  {index}: {key:5s} (+{wait}s) -> player {pointer}")
        if pointer:
            break

    pointer = pad.player_pointer()
    print("\nplayer:", hex(pointer) if pointer else None, "| shot:", pad.shot("boot_fixed"))
    if not pointer:
        return 1

    print("starting keep_moving in the background")
    subprocess.Popen([sys.executable, "keep_moving.py"], cwd=r"C:\_tools\gBox\.tmp",
                     stdout=open(r"D:\gBox\pso-ds\keep_moving.log", "ab"), stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    print("the bot is moving")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
