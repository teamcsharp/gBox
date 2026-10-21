"""What every Mercenaries run teaches, kept per title: gbox-data/mercs/lessons (docs/mercenaries_engine.md, section 6).

    from gbox.mercs import lessons
    lessons.append("G4BE08", {"kind": "coach", "text": "...", "session_id": sid})      # notes and reports
    run = lessons.Run("G4BE08")                                                       # one run's events
    run.log("hit_taken", attacker={...}, player_state=[1, 0, 1, 0])
    lessons.analyze("G4BE08")       # -> candidate signatures: enemy values seen just before hits, with lead times

Notes and reports (the deployment layer's coaching notes and improvement reports) go to <root>/<map id>.jsonl, one JSON
object a line; a run's events to <root>/<map id>/runs/<run id>.jsonl. Nothing here reads or writes the game.
"""
from __future__ import annotations

import collections
import json
import statistics
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "gbox-data" / "mercs" / "lessons"
_LOCK = threading.Lock()


def configure(data_dir) -> Path:
    """Put the lessons under a deployment's data dir (the server's config.data_dir): <data_dir>/mercs/lessons."""
    global ROOT
    ROOT = Path(data_dir) / "mercs" / "lessons"
    return ROOT


def _safe(map_id: str) -> str:
    s = "".join(c for c in str(map_id) if c.isalnum() or c in "-_")
    if not s:
        raise ValueError(f"bad map id {map_id!r}")
    return s


def path_for(map_id: str, run: str | None = None) -> Path:
    base = ROOT / _safe(map_id)
    return base / "runs" / f"{_safe(run)}.jsonl" if run else ROOT / f"{_safe(map_id)}.jsonl"


def append(map_id: str, entry: dict, run: str | None = None) -> Path:
    """Append one entry. Without run: a note / report ({"ts", "kind": "coach" | "report", "text", ...}, the
    deployment layer's schema, kept as given; ts filled when missing). With run: an engine event of that run."""
    if not isinstance(entry, dict):
        raise TypeError("an entry is a dict")
    p = path_for(map_id, run)
    row = dict(entry)
    row.setdefault("ts" if run is None else "wall", round(time.time(), 3))
    line = json.dumps(row, default=_jsonable, separators=(",", ":"))
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return p


def _jsonable(v):
    if isinstance(v, (set, frozenset, tuple)):
        return list(v)
    if isinstance(v, bytes):
        return v.hex()
    return str(v)


def read(map_id: str, run: str | None = None, kinds=None) -> list[dict]:
    p = path_for(map_id, run)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if kinds is None or row.get("kind") in kinds:
            out.append(row)
    return out


def runs(map_id: str) -> list[str]:
    d = ROOT / _safe(map_id) / "runs"
    return sorted(p.stem for p in d.glob("*.jsonl")) if d.is_dir() else []


class Run:
    """One run's event log: log(kind, **fields) appends {"t": seconds since the run started, "kind", ...}."""

    def __init__(self, map_id: str, run_id: str | None = None, clock=time.time, **head):
        self.map_id, self.clock = map_id, clock
        self.id = run_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.t0 = clock()
        self.counts: collections.Counter = collections.Counter()
        self.log("run", map=map_id, **head)

    def log(self, kind: str, **fields) -> None:
        self.counts[kind] += 1
        append(self.map_id, {"t": round(self.clock() - self.t0, 3), "kind": kind, **fields}, run=self.id)


def analyze(map_id: str, window_s: float = 1.5, min_seen: int = 2, known: dict | None = None) -> list[dict]:
    """Candidate signatures from the runs: the enemy values (state / act / motion) seen on the attackers in the hits the
    player took, with how long the attacker had been in that value (the lead time), skipping values that already have
    a signature (known: {"act": {values}, ...}). A candidate is a lead, not a fact: check it (a ram_search labeled
    search or a live check) before it goes into the map."""
    known = known or {}
    seen: dict = collections.defaultdict(list)
    for run in runs(map_id):
        for ev in read(map_id, run, kinds=("hit_taken",)):
            for a in (ev.get("attackers") or [])[:1]:              # the nearest one
                for field in ("act", "state", "motion"):
                    v = a.get(field)
                    if v is None or v in known.get(field, ()):
                        continue
                    lead = a.get("in_value_s")
                    if lead is None or lead <= window_s * 4:
                        seen[(field, v)].append((lead, a.get("dist")))
    out = []
    for (field, v), xs in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        if len(xs) < min_seen:
            continue
        leads = [x for x, _ in xs if x is not None]
        dists = [d for _, d in xs if d is not None]
        out.append({"field": field, "value": v, "hits": len(xs),
                    "lead_s": round(statistics.median(leads), 2) if leads else None,
                    "reach": round(max(dists)) if dists else None, "confidence": "candidate",
                    "evidence": f"{len(xs)} hits taken with the attacker in this {field} (lessons {map_id})"})
    return out


def main(argv=None) -> int:
    """python -m gbox.mercs.lessons analyze <map id>: the candidates, one JSON line each."""
    import sys
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 2 and a[0] == "analyze":
        for c in analyze(a[1]):
            print(json.dumps(c))
        return 0
    print(main.__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
