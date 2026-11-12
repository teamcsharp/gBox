"""Does a launch through the panel's exact path actually start a game?

The panel posts `{tool: 'launch_game', input: {game: <CatalogEntry>}}` to `/api/jobs`. This does the same thing and watches the job to completion, then reports
whether a session appeared - so "it does not load" is answered by evidence rather than by another change.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402


def live_sessions():
    rows = S._call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


if __name__ == "__main__":
    game = S._call("/api/catalog/436e0bb84d5337d1")
    print("game:", str(game.get("title"))[:50], "| has launch:", "launch" in game)
    print("live before:", len(live_sessions()))

    job = S._call("/api/jobs", "POST", {"tool": "launch_game", "input": {"game": game}})
    job_id = job.get("id")
    print("job:", job_id, "| tool:", job.get("tool"))

    for attempt in range(20):
        time.sleep(3)
        row = S._call("/api/jobs/" + str(job_id))
        state = row.get("state")
        error = str(row.get("error") or "")[:70]
        print(f"  {attempt + 1}: {state} | {error}")
        if state in ("succeeded", "failed", "cancelled"):
            break

    live = live_sessions()
    print("live after:", len(live), [(str(x.get("session_id"))[:20], x.get("agent_owned")) for x in live[:3]])
    print("VERDICT:", "a session started" if live else "no session appeared")
