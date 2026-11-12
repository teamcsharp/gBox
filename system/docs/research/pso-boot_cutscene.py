"""Boot to the field with the intro cutscene accounted for.

The failure mode, seen twice: the sequence presses START, DOWN and five A's, and when it reaches gameplay PSO plays its **intro cutscene** - the close-up of the character
with a rifle. The player entity does not exist during the cutscene, so a fixed wait of 3-4 seconds runs out, the remaining presses land on whatever follows, and the game
ends up back at "PRESS START".

So: the menu presses stay tightly timed (they are settled menus), then there is a **long wait for the cutscene**, and after that A presses continue until the player
appears - judged only by the semantic player, which is unambiguous.
"""
import subprocess
import sys
import time

from pso_pad import Pad, call

GAME = "436e0bb84d5337d1"
MENU = [("start", 2.6), ("down", 1.2), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.5)]


def live():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def player(pad):
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}
    return state.get("player") or {}


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

    game = call("/api/catalog/" + GAME)
    job = call("/api/jobs", {"tool": "launch_game", "input": {"game": game},
                             "require_worker": worker_id}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(30):
        time.sleep(3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("launch:", row.get("state"), str(row.get("error"))[:100])
            if row.get("state") != "succeeded":
                return 1
            break

    sessions = live()
    if not sessions:
        print("no session")
        return 1
    pad = Pad(sessions[0]["session_id"])
    print("session:", pad.sid)
    time.sleep(32)                       # logo, licence, title

    for index, (key, wait) in enumerate(MENU, 1):
        pad.send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(wait)
        print(f"  menu {index}: {key} -> player {bool(player(pad))}")

    print("\nwaiting for the intro cutscene (this is what used to strand the boot)...")
    for index in range(12):
        time.sleep(5)
        if player(pad):
            print(f"  player appeared after {(index + 1) * 5}s")
            break
        if index in (2, 5, 8):
            pad.send([{"key": "a", "down": True}, {"key": "a", "down": False}])
            print(f"  {(index + 1) * 5}s: pressed A")

    me = player(pad)
    if not me:
        print("\nno player; shot:", pad.shot("cutscene_wait_failed"))
        return 1
    print(f"\nIN THE FIELD at ({me.get('x')}, {me.get('z')}) room {me.get('room')}")
    print("shot:", pad.shot("boot_with_cutscene"))

    print("starting keep_moving")
    subprocess.Popen([sys.executable, "keep_moving.py"], cwd=r"C:\_tools\gBox\.tmp",
                     stdout=open(r"D:\gBox\pso-ds\keep_moving.log", "ab"), stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    print("the bot is moving")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
