"""The lessons log: one JSONL per run (<root>/<map id>/runs/<run>.jsonl), {"t", "frame", "kind", ...} per line.

    run        map id, title, engine version
    fight      start / end: characters, health, frames, why it ended
    attack     an opponent's attack seen: move, class, onset frame, frames to its first active frame
    answer     what the engine pressed: answer, the frame it was sent, the frame the game showed it (input latency),
               reaction frames from the attack's onset, then its outcome and reward
    hit_taken  the player lost health: how much, and the attacker's state just before (move, class, move frame,
               attack tags, distance) and how long it had been in that move: the raw material for new signatures
    punish     a punish pressed after a successful answer and what it dealt

`python -m gbox.fightbot.lessons analyze <root> <map id>` lists the attacker moves seen just before hits that have no
signature yet, with the frames from their onset to the hit: candidates to check (live or in the code) and add."""
from __future__ import annotations

import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

VERSION = 1


class Run:
    def __init__(self, root: Path | str | None, map_id: str, run_id: str | None = None, clock=time.time):
        self.map_id, self.clock = map_id, clock
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
        self.path = Path(root) / map_id / "runs" / f"{self.run_id}.jsonl" if root else None
        self.lock = threading.Lock()
        self.counts: dict[str, int] = defaultdict(int)
        self.tail: list[dict] = []
        self.log("run", map=map_id, engine=VERSION)

    def log(self, kind: str, frame: int | None = None, **fields):
        row = {"t": round(self.clock(), 3), "frame": frame, "kind": kind, **fields}
        with self.lock:
            self.counts[kind] += 1
            self.tail = (self.tail + [row])[-50:]
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")
        return row


def analyze(root: Path | str, map_id: str) -> list[dict]:
    """Attacker moves seen just before hits, by how often, without a signature (attack tags) yet."""
    hits: dict[tuple, list] = defaultdict(list)
    for path in sorted((Path(root) / map_id / "runs").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") != "hit_taken":
                continue
            att = row.get("attacker") or {}
            if (att.get("tags") or {}).get("attack"):
                continue
            hits[(att.get("chara"), att.get("move"), att.get("move_class"))].append(row.get("in_move_frames"))
    out = []
    for (chara, move, cls), frames in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        known = sorted(f for f in frames if isinstance(f, int))
        out.append({"chara": chara, "move": move, "move_class": cls, "hits": len(frames),
                    "frames_into_move": [known[0], known[len(known) // 2], known[-1]] if known else None})
    return out


HIT_WITHIN = 60                 # frames: a P2 move followed by a hit on P1 this soon counts as one that hit


def classes(root: Path | str, map_id: str) -> list[dict]:
    """Per P2 move class (and per move): how often it started, how often a hit on P1 followed within HIT_WITHIN
    frames, and the frames from its start to that hit: the classes with a high hit rate are the attack candidates
    (logged by titles with log_moves)."""
    starts: dict[tuple, int] = defaultdict(int)
    hits: dict[tuple, list] = defaultdict(list)
    for path in sorted((Path(root) / map_id / "runs").glob("*.jsonl")):
        recent: list[tuple] = []                   # (frame, class, move) of the last P2 move starts
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            f = row.get("frame")
            if row.get("kind") == "p2_move" and isinstance(f, int):
                key = (row.get("move_class"), row.get("move"))
                starts[key] += 1
                recent = (recent + [(f, *key)])[-8:]
            elif row.get("kind") == "hit_taken" and isinstance(f, int):
                before = [r for r in recent if 0 <= f - r[0] <= HIT_WITHIN]
                if before:
                    start, cls, move = before[-1]
                    hits[(cls, move)].append(f - start)
    by_class: dict = defaultdict(lambda: {"starts": 0, "hits": 0, "frames": []})
    for (cls, move), n in starts.items():
        by_class[cls]["starts"] += n
        by_class[cls]["hits"] += len(hits.get((cls, move), []))
        by_class[cls]["frames"] += hits.get((cls, move), [])
    out = []
    for cls, r in by_class.items():
        fr = sorted(r["frames"])
        out.append({"move_class": cls, "starts": r["starts"], "hits": r["hits"],
                    "hit_rate": round(r["hits"] / r["starts"], 3) if r["starts"] else 0.0,
                    "frames_to_hit": [fr[0], fr[len(fr) // 2], fr[-1]] if fr else None})
    return sorted(out, key=lambda r: (-r["hit_rate"], -r["starts"]))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3 or argv[0] not in ("analyze", "classes"):
        print("python -m gbox.fightbot.lessons analyze|classes <root> <map id>")
        return 2
    for row in (analyze if argv[0] == "analyze" else classes)(argv[1], argv[2]):
        print(json.dumps(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
