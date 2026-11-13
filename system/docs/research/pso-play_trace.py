"""Record the operator's play so it can be replayed and learned from.

The operator: *"I want the play that I'm giving you on this game being recreated and reused and learned from."*

This is the memory the system has been missing. Every previous improvement changed a **policy**; none of them gave the
bot a record of what a successful sequence looks like. The operator has demonstrated combat, a level clear and a boss
fight, and none of it was captured, so none of it could be reused.

**Format** — one JSON object per line in `operator-play.jsonl`, written by the controller relay at the moment it forwards
a change:

```
{"t": 1794575483.65, "sid": "…", "room": 13, "x": 120.5, "y": 32.0, "z": -44.2,
 "heading": 187.4, "hp": 68, "events": [{"key": "up", "down": true}]}
```

The state is recorded **with** each input, so the trace says not just what was pressed but where the character was and
which way it faced - which is what makes it replayable and comparable.

**Replay** sends the same events with the same inter-event timing, and reports the position at each step so a divergence
is visible immediately rather than guessed at.

Tracing never breaks play: every write is wrapped, and a failed append is reported once and then suppressed.
"""
import json
import pathlib
import time

TRACE = pathlib.Path(r"D:\gBox\pso-ds\operator-play.jsonl")
PROBLEM = {"reported": False}


def record(sid: str, events, state: dict) -> bool:
    """Append one input change with the game state beside it. Never raises."""
    try:
        player = (state or {}).get("player") or {}
        row = {
            "t": round(time.time(), 3),
            "sid": sid,
            "room": player.get("room"),
            "x": round(float(player.get("x") or 0), 2),
            "y": round(float(player.get("y") or 0), 2),
            "z": round(float(player.get("z") or 0), 2),
            "heading": round(float(player.get("heading_deg") or 0), 1),
            "hp": player.get("hp"),
            "events": [{"key": e.get("key"), "down": bool(e.get("down"))} for e in (events or [])],
        }
        with TRACE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        return True
    except Exception:                                     # noqa: BLE001 - tracing must never stop play
        if not PROBLEM["reported"]:
            PROBLEM["reported"] = True
            print("  (trace write failed - continuing without recording)", flush=True)
        return False


def load(path=None) -> list:
    path = pathlib.Path(path) if path else TRACE
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def summarise(rows) -> dict:
    """What a trace actually contains - so 'the operator played' can be checked rather than assumed."""
    if not rows:
        return {"rows": 0}
    rooms = sorted({r.get("room") for r in rows if r.get("room") is not None})
    keys = {}
    for row in rows:
        for event in row.get("events") or []:
            if event.get("down"):
                keys[event.get("key")] = keys.get(event.get("key"), 0) + 1
    return {
        "rows": len(rows),
        "seconds": round(float(rows[-1]["t"]) - float(rows[0]["t"]), 1),
        "rooms": rooms,
        "presses": dict(sorted(keys.items(), key=lambda kv: -kv[1])[:8]),
        "start": (rows[0].get("x"), rows[0].get("z")),
        "end": (rows[-1].get("x"), rows[-1].get("z")),
    }


def replay(pad, rows, call, speed: float = 1.0, log=None):
    """Re-send recorded events with their original timing. Returns how far the character actually got."""
    if not rows:
        return None
    start = time.time()
    base = float(rows[0]["t"])
    for row in rows:
        target = base + (float(row["t"]) - base) / max(0.05, speed)
        wait = target - (time.time() - start)
        if wait > 0:
            time.sleep(min(wait, 2.0))
        events = [{"key": e["key"], "down": e["down"]} for e in (row.get("events") or []) if e.get("key")]
        if not events:
            continue
        call("/api/jobs", {"tool": "session_op", "require_worker": pad.worker,
                           "input": {"session_id": pad.sid, "op": "send_input", "args": {"events": events}}}, "POST")
        if log and row.get("room"):
            log(f"  replay: room {row['room']} at ({row.get('x')}, {row.get('z')}) heading {row.get('heading')}")
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}
    player = state.get("player") or {}
    return {"x": player.get("x"), "z": player.get("z"), "room": player.get("room")}
