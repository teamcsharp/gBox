"""Turn a recorded play session into an imitation mission: gameplay memory -> imitate.learn -> mission JSON.

    python system/tools/pso_learn_from_play.py --game-id 436e0bb84d5337d1 [--run <session_id>] [--out <dir>]

Reads the plane's gameplay-memory archive over HTTP with the local API token, picks the run with the most pad events (or the run you
name), and writes `profiles/missions/pso-learned-<run>.json` - a mission `autoplay` can run in its replay vocabulary. The learned
bursts, gaps and menu keys are recorded in the mission's provenance so a replay can always be traced to the session it imitated.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import pso_learn_play as LP                              # noqa: E402


def token() -> str:
    for candidate in (Path(r"C:\_tools\gBox\system\gbox-data\api_token"),
                      Path(__file__).resolve().parents[1] / "gbox-data" / "api_token"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    raise SystemExit("no API token found")


def get(path: str, base: str, tok: str):
    request = urllib.request.Request(base + path, headers={"authorization": "Bearer " + tok, "x-gbox-actor": "agent"})
    return json.loads(urllib.request.urlopen(request, timeout=60).read() or b"null")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--game-id", default="436e0bb84d5337d1")
    ap.add_argument("--run", default="")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "profiles" / "missions"))
    args = ap.parse_args()
    tok = token()
    status = get(f"/api/gameplay-memory?game_id={args.game_id}", args.base, tok)
    runs = status.get("runs") or []
    if not runs:
        print("no recorded runs for that game yet - play a session first")
        return 1
    if args.run:
        chosen = next((r for r in runs if r.get("id") == args.run), None)
    else:
        chosen = max(runs, key=lambda r: int((r.get("events") or {}).get("pad") or 0))
    if not chosen:
        print("that run is not in the archive")
        return 1
    run_id = chosen["id"]
    print(f"run {run_id}: events {chosen.get('events')}, started {chosen.get('started')}")
    archive = get(f"/api/gameplay-memory/runs/{run_id}?after=0", args.base, tok)
    events = archive.get("events") or []
    print(f"{len(events)} archived events, {sum(1 for e in events if e.get('kind') == 'pad')} pad events")
    mission, learned = LP.from_events(events, game_id=args.game_id,
                                      name=f"pso-learned-{run_id.split('-')[-1][:8]}", run=run_id)
    path = LP.save(mission, args.out)
    print(f"learned {len(learned.get('bursts') or [])} bursts, menu keys {learned.get('menu')}, "
          f"{len(mission['steps'])} mission steps")
    print("mission:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
