"""Per-stage aggregation of the RE5 Reunion round log (pure; reads rounds.jsonl lines, never touches a game).

Request #3027 asks for S rank (60,000) on all eight Reunion stages, RAM-measured.  The sampler
(`r5score.py`) writes one JSON object per round; this module groups them by stage signature and reports, per
stage, how far the best/median round is from S, how much of a round is idle/facing a wall, and which idle
cause dominates, so each stage's work (route order, combos, ladders) can be targeted from measurements.
Stages with no rounds are listed as unmeasured: nothing is inferred for them.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict

S_SCORE = 60000
REUNION_STAGES = 8
RANKS = (("SS", 90000), ("S", 60000), ("A", 40000), ("B", 20000), ("C", 10000), ("D", 0))


def rank_of(score):
    if score is None:
        return None
    return next(r for r, at in RANKS if score >= at)


def stage_key(row: dict) -> str:
    """'<navmesh sig prefix>/<hourglasses>' (the signature's first two fields identify the mesh; hourglasses the stage)."""
    sig = str(row.get("stage") or "?")
    return "-".join(sig.split("-")[:2]) + "/" + str(row.get("hourglasses", "?"))


def load_rounds(lines) -> list[dict]:
    rows = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            rows.append(d)
    return rows


def _cause_kind(cause: str) -> str:
    """'gather_time | vt0x.. | front candidate; visibility unconfirmed' -> 'gather_time: front candidate; ...'."""
    parts = [p.strip() for p in cause.split("|")]
    return f"{parts[0]}: {parts[-1]}" if len(parts) > 1 else cause


def summarize(rows: list[dict]) -> dict:
    """Per-stage stats over completed rounds (end_reason 'results'); other rounds are only counted."""
    by = defaultdict(list)
    lost = Counter()
    for r in rows:
        k = stage_key(r)
        if r.get("end_reason") == "results" and isinstance(r.get("score"), (int, float)):
            by[k].append(r)
        else:
            lost[k] += 1
    out = {}
    for k in sorted(set(by) | set(lost)):
        rs = by.get(k, [])
        scores = [r["score"] for r in rs]
        causes = Counter()
        for r in rs:
            for c, s in (r.get("idle_causes") or {}).items():
                causes[_cause_kind(c)] += s
        entry = {"rounds": len(rs), "incomplete": lost[k]}
        if rs:
            best = max(rs, key=lambda r: r["score"])
            entry.update(
                best=best["score"], best_char=best.get("character"), best_rank=rank_of(best["score"]),
                median=statistics.median(scores), s_rounds=sum(s >= S_SCORE for s in scores),
                gap_to_s=max(0, S_SCORE - best["score"]),
                idle_mean_s=round(statistics.mean(r.get("idle_s", 0) for r in rs), 1),
                wall_mean_s=round(statistics.mean(r.get("wall_s", 0) for r in rs), 1),
                bonus_rounds=sum(1 for r in rs if (r.get("bonus_s") or 0) > 0),
                top_idle_causes=[(c, round(s / len(rs), 1)) for c, s in causes.most_common(3)])
        out[k] = entry
    return out


def render(summary: dict) -> str:
    n = len(summary)
    head = [f"Stages measured: {n} of {REUNION_STAGES}; S (>= {S_SCORE:,}) reached on "
            f"{sum(1 for e in summary.values() if e.get('s_rounds'))} of them.",
            "", "| stage | rounds | best | rank | median | gap to S | idle s | wall s | rounds with +time | top idle cause (s/round) |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for k, e in summary.items():
        if not e["rounds"]:
            head.append(f"| {k} | 0 ({e['incomplete']} incomplete) | - | - | - | - | - | - | - | - |")
            continue
        c = e["top_idle_causes"][0] if e["top_idle_causes"] else ("-", 0)
        head.append(f"| {k} | {e['rounds']} | {e['best']:,} ({e['best_char']}) | {e['best_rank']} | {e['median']:,.0f} | "
                    f"{e['gap_to_s']:,} | {e['idle_mean_s']} | {e['wall_mean_s']} | {e['bonus_rounds']} | {c[0]} ({c[1]}) |")
    if n < REUNION_STAGES:
        head += ["", f"{REUNION_STAGES - n} Reunion stage(s) have no measured round: the stage picker has not yet "
                 "produced them in the log, so nothing is claimed for them."]
    return "\n".join(head)


if __name__ == "__main__":  # python -m gbox.mercs.titles.re5_scoreboard path/to/rounds.jsonl
    import sys
    with open(sys.argv[1], encoding="utf-8") as fh:
        print(render(summarize(load_rounds(fh))))
