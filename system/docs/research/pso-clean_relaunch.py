"""Relaunch the session for a clean inventory - but only once the operator has let go.

The character is unarmed and cannot be re-armed in this session: the inventory filled from repeated gifting over hours and every `give` now fails with "Not enough inventory slots". A fresh session
clears it, and arm-once (already in place) guarantees it is armed exactly once.

The reason this is a separate tool rather than something done inline: **restarting the session kills the game**, and pulling it out from under the operator mid-play is unacceptable. So it waits for
`operator-playing.flag` to be **absent for `QUIET_S` seconds** before acting, and reports what it did.

The loop relaunches by itself once the session is gone (`ensure_session` -> launch), and re-arms the new one, so all this needs to do is stop the old session at a safe moment.
"""
import argparse
import pathlib
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

from pso_pad import Pad, call                                     # noqa: E402

FLAG = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
QUIET_S = 20.0


def operator_quiet() -> bool:
    """True when the relay's pause flag has been absent or stale for QUIET_S seconds."""
    if not FLAG.exists():
        return True
    try:
        return (time.time() - FLAG.stat().st_mtime) > 15.0
    except OSError:
        return True


def live_sessions():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [r for r in rows if r.get("state") in ("running", "starting")]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="relaunch without waiting for the operator")
    parser.add_argument("--wait", type=float, default=600.0, help="seconds to wait for the operator to stop")
    args = parser.parse_args()

    deadline = time.time() + args.wait
    while not args.force:
        if operator_quiet():
            print("operator is idle - waiting a beat to be sure")
            time.sleep(QUIET_S)
            if operator_quiet():
                break
        if time.time() > deadline:
            print("operator still playing - not touching the session")
            raise SystemExit(0)
        time.sleep(3)

    sessions = live_sessions()
    if not sessions:
        print("no live session to restart - the loop will launch one")
        raise SystemExit(0)

    for row in sessions:
        sid = row["session_id"]
        print("stopping", sid, "for a clean inventory")
        call("/api/jobs", {"tool": "session_op", "require_worker": sid.split("-")[0],
                           "input": {"session_id": sid, "op": "stop_game", "args": {}}}, "POST")
    print("stopped - the loop relaunches and re-arms on its next cycle")
