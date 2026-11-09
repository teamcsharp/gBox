"""The SS campaign for RE5 Switch No Mercy: every round's result on one ledger, the board it adds up to, the objective
the tuner learns on, and the next MercMode queue that fills the board's holes.

The operator, 2026-11-09: "the goal in RE5 is to get the bot to 400 kills as fast as possible with a combo being
maintained the entire time. I need that to be done faster and faster with the bot auto improving until it has SS rank
on every level for every costume for every character for the entire game." No Mercy is won at 400 kills (the results
come up the moment the 400th Majini falls); the first win of the night was Public Assembly, 400 routed, max combo 40x,
499,288 points, rank SS, 14:38 left.

THE LEDGER. One record per game round, built from the round Notebook (curriculum/<title>/rounds.sqlite, one row per
round EVIDENCE fragment). A fragment is not a round: a bot reload, a stopped autoplay or a lost read closes the
evidence ("interrupted", "lost", "ended") while the game plays on, and the next play_round opens a new row that starts
mid-round (2026-11-09: both 400-kill wins are the second fragment of their round; the row of the win names neither the
stage nor the character because the new fragment never saw the selects). stitch() joins them: the same session, a
non-terminal fragment, the next one starting at or above its kills on the same stage, within CONT_GAP_S. Per round:

    stage        the stage NAME: the round's navigation signature (rounds.stage, e.g. 1636-2187-... = Public Assembly;
                 SIGNATURES, measured over the 1,687 rows) or the cycle-confirmed data.stage. Never tuning_stage: until
                 this change the bot stamped it with the NEXT round's target (re5_switch._new_round asked stage_target()
                 after the cycle had already moved on), and 70 % of the rows name a stage they were not played on.
    character    the row's character, data.character, or the bot's identity fallback (ss_character_source); a
                 continuation fragment inherits its round's
    outcome      won (400 kills, results), died, timeout (the clock ran out: results, a rank, not a win), unfinished
                 (the evidence stopped and no fragment followed)
    kills, score, max_combo, combo_breaks (round_combo_breaks summed over the fragments), deaths (the round ended in a
                 death), dying (the dying episodes, round_dying), holds, heals
    play_s       real play seconds: the bot's own round clock when the round carries it (ss_round_play_s: wall seconds
                 of the round's playing ticks from its first, a clock that did not run - a pause, a frozen read - not
                 counted; it carries over a fragment boundary), else the fragments' seconds (explore_seconds, the run
                 capture's) plus the gaps between them. time_source says which.
    to_400_s     play_s of a won round (the results come at the 400th kill; ss_kill400_s when recorded)
    rank         the results screen's rank from RAM when the bot read it (cGameSys +0x994, see RANK_INDEX), else
                 DERIVED from the score with the game's own No Mercy table (RANKS); none for a death (no results
                 screen) or an unfinished round. rank_source says which.

THE RANK TABLE (RANKS). Read from main's rodata (build EBFFDB22..., the RE5 Switch ELF on the Spark, static analysis
2026-11-09): main+0x17C1B7C holds three rows of six s32 thresholds, SS..D, stride 0x18 - 90,000 / 60,000 / 40,000 /
20,000 / 10,000 / 0 (the solo Mercenaries table the guides quote), 150,000 / 120,000 / 80,000 / 40,000 / 20,000 / 0
(duo), and 400,000 / 300,000 / 150,000 / 60,000 / 30,000 / 0. The rank code at main+0xECD38 picks the row with
`ldrb w10, [cGameSys, #0xA76]; csel w20, wzr, #2, eq` - cGameSys +0xA76 is the No Mercy flag (re5_switch) - so No
Mercy uses the third row; it walks the score (+0x990, plus the pending +0x958) down the row and stores the rank index
(0 = SS ... 5 = D) at cGameSys +0x994 and the exchange points (main+0x17C1BC4: 5000 / 3000 / 1500 / 1000 / 600 / 200)
at +0x998. The night's win agrees (499,288 >= 400,000: SS). Still to see live: one results screen between 90,000 and
400,000 points (a 388-kill timeout at 335,260 must read S, not SS) - the driver records the RAM index beside the
derived rank on every results screen from now on (result_rank_ram / result_rank_derived).

THE BOARD (board(), report()): stage x character - attempts, wins, deaths, the best rank, the best score, the best
time to 400. 8 stages x the select's characters (CHARACTERS: 14 names, two pages; an entry past them is "character N").

THE OBJECTIVE (round_cost(), objective()): what the tuner judges a trial on for this title. Lower is better, in
seconds: a won round costs its time to 400; a round not won costs its projected time to 400 at the pace it had
(play_s x 400 / kills) plus NOT_WON_S, and a death DEATH_S more on top, so any win beats any loss and any loss beats
any death; each combo break adds COMBO_BREAK_S and the max combo takes off up to MAX_COMBO_CREDIT_S. Judged per stage:
each trial round against its own stage's baseline mean (stage_baselines), the ratios pooled over every stage, so a
trial confirms on the rounds of a day rather than a stage's handful.

THE PLANNER (plan_queue()): the next QUEUE_MAX MercMode queue entries - (stage, character) pairs without SS first
(fewest attempts, then the best score so far), then the slowest SS times - mixed so that no two entries in a row share
the stage or the character, each {"title": "re5", "mode": "no_mercy", "character", "stage"(, "mod": build)}.

THE ROUND CLOCK (RoundClock): the bot's live side - fed every tick by the RE5 Switch driver, it keeps the round's real
play seconds across fragment boundaries (one round = one player object of one boot) and writes the ss_* stats the
ledger reads. Nothing in this module reads or writes the game.

    python -m gbox.mercs.ss_ledger [--db rounds.sqlite] [--maps round_maps/010018100CD46000] [--json] [--plan BUILD]
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
import sys
import time
from contextlib import closing
from pathlib import Path

TITLE = "010018100CD46000"
GOAL_KILLS = 400
# re5_switch.STAGE_NAMES / CHARACTERS (kept here so the CLI runs with no package; a test holds them equal)
STAGE_NAMES = ("Public Assembly", "The Mines", "Village", "Ancient Ruins", "Experimental Facility", "Missile Area",
               "Ship Deck", "Prison")
CHARACTERS = ("Chris (BSAA)", "Chris (Safari)", "Chris (STARS)", "Sheva (BSAA)", "Sheva (Clubbin)", "Sheva (Tribal)",
              "Jill (BSAA)", "Jill (Battle Suit)", "Wesker (Midnight)", "Wesker (STARS)",
              "Josh (BSAA)", "Excella", "Barry (STARS)", "Rebecca (STARS)")
# The stage's navigation signature (re5_switch_native_nav learning_sig; the Notebook's rounds.stage) -> its name.
# Measured 2026-11-09 over the 1,687 rows: each signature appears with exactly one cycle-confirmed data.stage.
SIGNATURES = {
    "1636-2187-d3a75164ca01dcaa-e1163f7867c9": "Public Assembly",
    "1152-1565-d7cf9f4b54c4a7fb-1624cb963fc4": "The Mines",
    "1186-1572-0b4558ee57f63925-594262a20d44": "Village",
    "907-1033-cb4639c6c8490575-e18ef1ac1659": "Ancient Ruins",
    "754-906-9c9fd6b418e2f567-8ff65fd20a50": "Experimental Facility",
    "1350-1664-ff6314937b448650-a383d0a7b930": "Missile Area",
    "1411-1783-0e2aca27a1246fdf-8120ec8d2f85": "Ship Deck",
    "1411-1725-7fee6ff36812b399-0fb005b38d0c": "Prison",
}
RANKS = (("SS", 400000), ("S", 300000), ("A", 150000), ("B", 60000), ("C", 30000), ("D", 0))   # No Mercy (above)
RANK_INDEX = tuple(r for r, _ in RANKS)          # cGameSys +0x994: 0 = SS ... 5 = D
RANK_SOURCE_TABLE = "main+0x17C1BAC (No Mercy row; static, build EBFFDB22)"
TERMINAL = ("completed", "died")
CONT_GAP_S = 180.0          # a continuation fragment starts at most this long after the one it continues ended
CONT_KILL_SLACK = 3         # ... at or above its kills (less this: a read at the boundary may lag)
CONT_GAP_KILLS = 30         # ... and at most this many more (a few may fall in the gap while no bot runs)
FRAGMENT_GAP_CAP_S = 180.0  # a gap between two fragments counts as play up to this (the game's clock ran on)
# the objective (seconds; lower is better)
NOT_WON_S = 1800.0
DEATH_S = 1800.0
COMBO_BREAK_S = 10.0
MAX_COMBO_CREDIT_S, MAX_COMBO_PER_S = 60.0, 0.5   # 0.5 s off per combo step, at most 60 s
PACE_FLOOR_KILLS = 10       # a round with fewer kills projects at this many (a 3-kill death is not a 40-minute pace)
QUEUE_MAX = 20              # gbox.mercmode.QUEUE_MAX
RANK_ORDER = {r: i for i, r in enumerate(RANK_INDEX)}


def rank_of(score) -> str | None:
    """The No Mercy rank of a final score (the game's own table, RANKS); None without a score."""
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
        return None
    return next(r for r, at in RANKS if score >= at)


def rank_name(index) -> str | None:
    """cGameSys +0x994 (the results' rank index) -> its name, None for anything else."""
    return RANK_INDEX[index] if type(index) is int and 0 <= index < len(RANK_INDEX) else None


def better_rank(a, b):
    """The better of two ranks (None counts as no rank)."""
    if a is None:
        return b
    if b is None:
        return a
    return a if RANK_ORDER.get(a, 99) <= RANK_ORDER.get(b, 99) else b


def stage_of_signature(sig) -> str | None:
    return SIGNATURES.get(sig) if isinstance(sig, str) else None


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) else None


def _int(value):
    v = _num(value)
    return int(v) if v is not None else None


# --- fragments -> rounds ---------------------------------------------------------------------------------------------

def fragment(row: dict, run_map: dict | None = None) -> dict:
    """One Notebook row as the ledger reads it. row: {id, ts, stage, mode, character, outcome, data|observed};
    run_map: its run map's summary (map_summary), which gives the fragment's first kills and both ends' clock."""
    d = row.get("data") if isinstance(row.get("data"), dict) else row.get("observed") or {}
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            d = {}
    sig = row.get("stage") if isinstance(row.get("stage"), str) and row.get("stage") not in ("", "unknown") else None
    sig = sig or (d.get("round_map_stage") if d.get("round_map_stage") in SIGNATURES else None)
    named = d.get("stage") if d.get("stage") in STAGE_NAMES else None
    stage = stage_of_signature(sig) or named or (d.get("ss_stage") if d.get("ss_stage") in STAGE_NAMES else None)
    char = row.get("character") if isinstance(row.get("character"), str) and row.get("character") != "unknown" else None
    char = char or (d.get("character") if isinstance(d.get("character"), str) and d.get("character") != "unknown"
                    else None)
    rm = run_map if isinstance(run_map, dict) else {}
    play = _num(d.get("ss_fragment_play_s"))
    source = "bot clock" if play is not None else None
    if play is None and _num(rm.get("play_s")) is not None:
        play, source = _num(rm["play_s"]), "run map"
    if play is None:
        play, source = _num(d.get("explore_seconds")), "run capture"
    if play is None:
        play, source = _num(d.get("doctrine_played_s")), "doctrine ticks"
    if play is None:
        source = None
    ram_rank = d.get("result_rank") if d.get("result_rank_verified") is True and d.get("result_rank") in RANK_ORDER \
        else None
    t0 = _int(d.get("ss_t0_kills"))
    t0 = t0 if t0 is not None else _int(rm.get("t0_kills"))
    return {"id": row.get("id"), "ts": _num(row.get("ts")) or 0.0, "sig": sig, "stage": stage, "character": char,
            "character_source": d.get("ss_character_source") or ("row" if char else None),
            "outcome": row.get("outcome"), "session": d.get("source_session_id") or d.get("source_autoplay_job_id"),
            "kills": _int(d.get("kills")) or 0, "score": _int(d.get("score")), "max_combo": _int(d.get("max_combo")),
            "timer": _num(d.get("timer")), "combo_breaks": _int(d.get("round_combo_breaks", d.get("combo_breaks"))),
            "dying": _int(d.get("round_dying")), "holds": _int(d.get("round_holds")), "heals": _int(d.get("round_heals")),
            "mine_blast_hp_loss": _int(d.get("round_mine_blast_hp_loss")), "play_s": play, "play_source": source,
            "t0_kills": t0, "t0_timer": _num(d.get("ss_t0_timer")) if d.get("ss_t0_timer") is not None
            else _num(rm.get("t0_timer")), "t1_timer": _num(rm.get("t1_timer")),
            "round_key": d.get("ss_round_key"),
            "round_play_s": _num(d.get("ss_round_play_s")), "kill400_s": _num(d.get("ss_kill400_s")),
            "rank_ram": ram_rank, "rank_ram_index": _int(d.get("result_rank_ram")),
            "tuning_version": d.get("tuning_version"), "map": d.get("round_map_file")}


def _continues(a: dict, b: dict) -> bool:
    """Whether fragment b is the same game round as a (a ended first)."""
    if a["outcome"] in TERMINAL or not a["session"] or a["session"] != b["session"]:
        return False
    if a.get("round_key") and b.get("round_key"):
        return a["round_key"] == b["round_key"]
    if a["sig"] and b["sig"] and a["sig"] != b["sig"]:
        return False
    if b["t0_kills"] is not None:                         # the bot's clock saw the fragment's first tick
        return b["t0_kills"] > 0 and a["kills"] - CONT_KILL_SLACK <= b["t0_kills"] <= a["kills"] + CONT_GAP_KILLS
    if b["kills"] < a["kills"]:
        return False
    start = b["ts"] - (b["play_s"] or 0.0)
    return -5.0 <= start - a["ts"] <= CONT_GAP_S


def stitch(fragments: list) -> list:
    """[[fragment, ...] per game round], oldest first."""
    rounds, open_by_session = [], {}
    for f in sorted(fragments, key=lambda x: x["ts"]):
        prev = open_by_session.get(f["session"]) if f["session"] else None
        if prev is not None and _continues(prev[-1], f):
            prev.append(f)
        else:
            prev = [f]
            rounds.append(prev)
        if f["session"]:
            open_by_session[f["session"]] = prev
    return rounds


def round_record(frags: list) -> dict:
    """One game round from its fragments (oldest first)."""
    last = frags[-1]
    kills = max(f["kills"] for f in frags)
    score = next((f["score"] for f in reversed(frags) if f["score"] is not None), None)
    stage = next((f["stage"] for f in frags if f["stage"]), None)
    char = next((f["character"] for f in frags if f["character"]), None)
    char_source = next((f["character_source"] for f in frags if f["character"]), None)
    if last["outcome"] == "completed":
        outcome = "won" if kills >= GOAL_KILLS else "timeout"
    elif last["outcome"] == "died":
        outcome = "died"
    else:
        outcome = "unfinished"
    if last["round_play_s"] is not None:
        play, source = last["round_play_s"], "bot clock"
    else:
        parts = [f["play_s"] for f in frags]
        if any(p is None for p in parts):
            play, source = None, None
        else:
            play = sum(parts)
            for a, b in zip(frags, frags[1:]):
                # between two fragments the game ran on with no bot, or it was paused (MercMode parks a game): the
                # round clock's fall over the gap where both ends were read, else the wall gap (at most the cap)
                if a.get("t1_timer") is not None and b.get("t0_timer") is not None:
                    gap = a["t1_timer"] - b["t0_timer"]
                else:
                    gap = (b["ts"] - b["play_s"]) - a["ts"]
                play += min(max(gap, 0.0), FRAGMENT_GAP_CAP_S)
            sources = sorted({f["play_source"] for f in frags})
            source = sources[0] if len(frags) == 1 else f"{len(frags)} fragments ({', '.join(sources)})"
    to_400 = None
    if outcome == "won":
        to_400 = last["kill400_s"] if last["kill400_s"] is not None else play
    rank, rank_source = None, None
    if outcome in ("won", "timeout"):
        if last["rank_ram"]:
            rank, rank_source = last["rank_ram"], "ram"
        else:
            rank, rank_source = rank_of(score), "derived"
    breaks = [f["combo_breaks"] for f in frags if f["combo_breaks"] is not None]
    def total(key):
        vals = [f[key] for f in frags if f[key] is not None]
        return sum(vals) if vals else None
    return {"round_id": last["id"], "fragments": [f["id"] for f in frags], "session": last["session"],
            "started_at": frags[0]["ts"] - (frags[0]["play_s"] or 0.0), "ended_at": last["ts"],
            "stage": stage, "sig": next((f["sig"] for f in frags if f["sig"]), None), "character": char,
            "character_source": char_source, "outcome": outcome, "kills": kills, "score": score,
            "max_combo": max((f["max_combo"] for f in frags if f["max_combo"] is not None), default=None),
            "combo_breaks": sum(breaks) if breaks else None, "deaths": 1 if outcome == "died" else 0,
            "dying": total("dying"), "holds": total("holds"), "heals": total("heals"),
            "mine_blast_hp_loss": total("mine_blast_hp_loss"),
            "play_s": round(play, 1) if play is not None else None, "time_source": source,
            "to_400_s": round(to_400, 1) if to_400 is not None else None, "rank": rank, "rank_source": rank_source,
            "tuning_versions": sorted({f["tuning_version"] for f in frags if f["tuning_version"]})}


def ledger(rows, maps: dict | None = None) -> list:
    """Every game round in these Notebook rows, oldest first. maps: {round id: map_summary} (load_maps)."""
    maps = maps or {}
    return [round_record(fr) for fr in stitch([fragment(r, maps.get(r.get("id"))) for r in rows])]


def read_rows(path, since: float = 0.0, limit: int = 20000) -> list:
    """The Notebook's rows (read-only), oldest first: [{id, ts, stage, mode, character, outcome, data}]."""
    path = Path(path)
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        found = db.execute("SELECT id, ts, stage, mode, character, outcome, data FROM rounds WHERE ts>=? "
                           "ORDER BY ts DESC LIMIT ?", (since, limit)).fetchall()
    out = []
    for rid, ts, stage, mode, char, outcome, data in reversed(found):
        try:
            d = json.loads(data) if data and len(data) <= 512 * 1024 else {}
        except ValueError:
            d = {}
        out.append({"id": rid, "ts": ts, "stage": stage, "mode": mode, "character": char, "outcome": outcome,
                    "data": d})
    return out


MAP_GAP_CAP_S = 2.5          # a run map's sample gap counts at most this (a frozen read, no player: not play)


def map_summary(rec: dict) -> dict | None:
    """A run map (gbox.mercs.run_capture, format gbox.run_map/1) as the ledger reads it: its round id, the play seconds
    (the 5 Hz samples' intervals, each at most MAP_GAP_CAP_S), and the clock's first and last [timer, kills]."""
    if not isinstance(rec, dict) or rec.get("format") != "gbox.run_map/1" or not rec.get("round_id"):
        return None
    t = [s[0] for s in rec.get("route") or () if isinstance(s, list) and s and isinstance(s[0], (int, float))]
    clock = [c for c in rec.get("clock") or () if isinstance(c, list) and len(c) >= 5]
    return {"round_id": rec["round_id"],
            "play_s": round(sum(min(b - a, MAP_GAP_CAP_S) for a, b in zip(t, t[1:]) if b > a), 2) if t else None,
            "t0_kills": _int(clock[0][4]) if clock else None, "t0_timer": _num(clock[0][1]) if clock else None,
            "t1_timer": _num(clock[-1][1]) if clock else None}


def load_maps(maps_dir, ids=None) -> dict:
    """{round id: map_summary} for the run maps under maps_dir (round_maps/<title>/<stage>/<stamp>-<id8>.json); ids:
    only the maps of these round ids (by their file name's 8-character prefix)."""
    want = {str(i)[:8] for i in ids} if ids is not None else None
    out = {}
    root = Path(maps_dir)
    if not root.is_dir():
        return out
    for p in root.glob("*/*.json"):
        if want is not None and p.stem.rsplit("-", 1)[-1] not in want:
            continue
        try:
            s = map_summary(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if s:
            out[s["round_id"]] = s
    return out


# --- the board -------------------------------------------------------------------------------------------------------

def board(rounds: list, characters=CHARACTERS) -> dict:
    """{(stage, character): cell} over the rounds; every stage x character of the select is there (unplayed: 0)."""
    cells = {}
    for s in STAGE_NAMES:
        for c in characters:
            cells[(s, c)] = _cell(s, c)
    for r in rounds:
        if r["outcome"] == "unfinished" and not r["kills"]:
            continue
        key = (r["stage"] or "unknown stage", r["character"] or "unknown character")
        cell = cells.setdefault(key, _cell(*key))
        cell["attempts"] += 1
        cell["wins"] += r["outcome"] == "won"
        cell["deaths"] += r["deaths"]
        cell["best_rank"] = better_rank(cell["best_rank"], r["rank"])
        if r["score"] is not None and (cell["best_score"] is None or r["score"] > cell["best_score"]):
            cell["best_score"] = r["score"]
        cell["best_kills"] = max(cell["best_kills"], r["kills"] or 0)
        if r["to_400_s"] is not None and (cell["best_to_400_s"] is None or r["to_400_s"] < cell["best_to_400_s"]):
            cell["best_to_400_s"], cell["best_round"] = r["to_400_s"], r["round_id"]
        cell["last_at"] = max(cell["last_at"] or 0.0, r["ended_at"])
    return cells


def _cell(stage, character):
    return {"stage": stage, "character": character, "attempts": 0, "wins": 0, "deaths": 0, "best_rank": None,
            "best_score": None, "best_kills": 0, "best_to_400_s": None, "best_round": None, "last_at": None}


def _clock(s):
    if s is None:
        return "-"
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def report(rounds: list, cells: dict | None = None, characters=CHARACTERS) -> str:
    """The SS board as text: a summary, the stage x character grid of best ranks, and the cells played."""
    cells = board(rounds, characters) if cells is None else cells
    known = [c for (s, ch), c in cells.items() if s in STAGE_NAMES and ch in characters]
    won = [r for r in rounds if r["outcome"] == "won"]
    lines = []
    outc = {}
    for r in rounds:
        outc[r["outcome"]] = outc.get(r["outcome"], 0) + 1
    ss = sum(1 for c in known if c["best_rank"] == "SS")
    lines.append(f"RE5 Switch No Mercy - the SS board: {len(rounds)} game rounds "
                 f"({', '.join(f'{k} {v}' for k, v in sorted(outc.items()))}); {len(won)} won at {GOAL_KILLS}; "
                 f"SS on {ss} of {len(known)} stage x character cells")
    if won:
        best = min((r for r in won if r["to_400_s"] is not None), key=lambda r: r["to_400_s"], default=None)
        if best:
            lines.append(f"fastest 400: {_clock(best['to_400_s'])} ({best['stage']}, {best['character']}, "
                         f"max combo {best['max_combo']}, score {best['score']:,}, rank {best['rank']} "
                         f"[{best['rank_source']}], round {best['round_id'][:8]})")
    lines.append("rank: the results screen's from RAM where read, else derived from the score with the game's No Mercy "
                 "table (SS 400,000 / S 300,000 / A 150,000 / B 60,000 / C 30,000); '.' unplayed, '-' played, no rank "
                 "(died / unfinished)")
    abbrev = [c.replace("(", "").replace(")", "").replace("Battle Suit", "Btl").replace("Midnight", "Mid")
              .replace("Clubbin", "Club").replace("Tribal", "Trib").replace("Safari", "Saf") for c in characters]
    width = max(len(a) for a in abbrev)
    lines.append("")
    lines.append(f"{'':22s}" + "".join(f"{i + 1:>4d}" for i in range(len(characters))))
    for s in STAGE_NAMES:
        row = []
        for c in characters:
            cell = cells.get((s, c))
            row.append("   ." if not cell or not cell["attempts"] else f"{cell['best_rank'] or '-':>4s}")
        lines.append(f"{s:22s}" + "".join(row))
    lines.append("   " + "  ".join(f"{i + 1}={a}" for i, a in enumerate(abbrev)))
    extra = [c for (s, ch), c in cells.items() if (s not in STAGE_NAMES or ch not in characters) and c["attempts"]]
    lines.append("")
    lines.append(f"{'stage':22s} {'character':{max(width, 18)}s} tries wins died  best  score     kills  best 400")
    for c in sorted((c for c in cells.values() if c["attempts"]),
                    key=lambda c: (STAGE_NAMES.index(c["stage"]) if c["stage"] in STAGE_NAMES else 99,
                                   list(characters).index(c["character"]) if c["character"] in characters else 99)):
        lines.append(f"{c['stage'][:22]:22s} {c['character'][:max(width, 18)]:{max(width, 18)}s} {c['attempts']:5d} "
                     f"{c['wins']:4d} {c['deaths']:4d}  {c['best_rank'] or '-':>4s}  "
                     f"{(format(c['best_score'], ',') if c['best_score'] is not None else '-'):>9s} {c['best_kills']:5d}"
                     f"  {_clock(c['best_to_400_s']):>7s}")
    if extra:
        lines.append(f"({len(extra)} cells name an unknown stage or character: rows from before the identity capture)")
    return "\n".join(lines)


# --- the objective ---------------------------------------------------------------------------------------------------

def round_cost(r: dict) -> float | None:
    """The operator's goal as one number (seconds, lower is better; see the module text). None for a round that
    cannot be judged (unfinished, or no play time)."""
    if r.get("outcome") not in ("won", "timeout", "died"):
        return None
    combo = COMBO_BREAK_S * (r.get("combo_breaks") or 0) \
        - min(MAX_COMBO_CREDIT_S, MAX_COMBO_PER_S * (r.get("max_combo") or 0))
    if r["outcome"] == "won":
        t = r.get("to_400_s") if r.get("to_400_s") is not None else r.get("play_s")
        return None if t is None else round(t + combo, 1)
    play = r.get("play_s")
    if play is None:
        return None
    pace = play * GOAL_KILLS / max(r.get("kills") or 0, PACE_FLOOR_KILLS)
    return round(pace + NOT_WON_S + (DEATH_S if r["outcome"] == "died" else 0.0) + combo, 1)


def stage_baselines(rounds: list, last_n: int = 10) -> dict:
    """{stage: mean cost} over each stage's last_n judged rounds, and "*" over all of them."""
    by, every = {}, []
    for r in rounds:
        c = round_cost(r)
        if c is None:
            continue
        by.setdefault(r.get("stage") or "*", []).append(c)
        every.append(c)
    out = {s: statistics.fmean(v[-last_n:]) for s, v in by.items() if s != "*"}
    if every:
        out["*"] = statistics.fmean(every[-max(last_n, 30):])
    return out


def objective(rounds: list, baselines: dict) -> dict | None:
    """A trial's rounds against their own stages' baselines: {"ratio": mean cost / baseline, "rounds", "wins",
    "deaths", "deaths_rate", "per_stage": {stage: [ratios]}}; None without a judged round."""
    ratios, per = [], {}
    for r in rounds:
        c = round_cost(r)
        base = baselines.get(r.get("stage") or "*") or baselines.get("*")
        if c is None or not base:
            continue
        x = c / base
        ratios.append(x)
        per.setdefault(r.get("stage") or "*", []).append(round(x, 3))
    if not ratios:
        return None
    judged = [r for r in rounds if round_cost(r) is not None]
    return {"ratio": round(statistics.fmean(ratios), 4), "rounds": len(ratios),
            "wins": sum(r["outcome"] == "won" for r in judged), "deaths": sum(r["deaths"] for r in judged),
            "deaths_rate": round(sum(r["deaths"] for r in judged) / len(judged), 3), "per_stage": per}


# --- the planner -----------------------------------------------------------------------------------------------------

def attempts_tier(n: int) -> int:
    """Pairs tried about as often are one tier: never, once or twice, 3-9 times, 10 or more."""
    return 0 if n <= 0 else 1 if n <= 2 else 2 if n <= 9 else 3


def plan_queue(cells: dict, build: str | None = None, n: int = QUEUE_MAX, characters=CHARACTERS) -> list:
    """The next n (<= QUEUE_MAX) MercMode queue entries for RE5 Switch No Mercy.

    Order: the (stage, character) pairs without SS, the least-tried tier first (attempts_tier: a pair never played
    before one played a few times), and inside a tier the pair nearest SS (the best score) first; then the pairs with
    SS, the slowest time to 400 first. Mixed: each pick is, among its tier's pairs, the one whose stage and character
    the plan has used least so far, and never the stage or the character of the entry before it when another pair of
    the tier allows (the playlist moves on every round, as the operator asked: "multiple characters and stages
    transitioning")."""
    n = max(0, min(int(n), QUEUE_MAX))
    pairs = [(s, c) for s in STAGE_NAMES for c in characters]
    def cell(p):
        return cells.get(p) or _cell(*p)
    def tier(p):
        c = cell(p)
        return (1, 0) if c["best_rank"] == "SS" else (0, attempts_tier(c["attempts"]))
    def worth(p):                                                     # inside a tier: lower goes first
        c = cell(p)
        return -(c["best_to_400_s"] or 0.0) if c["best_rank"] == "SS" else -(c["best_score"] or 0)
    pool = sorted(pairs, key=lambda p: (tier(p), worth(p), STAGE_NAMES.index(p[0]), list(characters).index(p[1])))
    used_s, used_c, out, last = {}, {}, [], None
    while pool and len(out) < n:
        head = tier(pool[0])
        same = [p for p in pool if tier(p) == head]
        fresh = [p for p in same if last is None or (p[0] != last[0] and p[1] != last[1])] \
            or [p for p in same if p[0] != last[0] or p[1] != last[1]] or same
        pick = min(fresh, key=lambda p: (used_s.get(p[0], 0) + used_c.get(p[1], 0), pool.index(p)))
        pool.remove(pick)
        used_s[pick[0]] = used_s.get(pick[0], 0) + 1
        used_c[pick[1]] = used_c.get(pick[1], 0) + 1
        entry = {"title": "re5", "mode": "no_mercy", "character": pick[1], "stage": STAGE_NAMES.index(pick[0])}
        if build:
            entry["mod"] = build
        out.append(entry)
        last = pick
    return out


# --- the bot's live side: the round clock ----------------------------------------------------------------------------
CLOCK_STILL_S = 1.0          # a tick gap longer than this with the round clock unchanged: paused / frozen, not counted
CLOCK_GAP_MAX_S = 30.0       # ... and no single gap counts for more than this
_CLOCKS: dict = {}           # (main base, player pointer) -> RoundClock: one per round, across fragment boundaries
RELOAD_KEEP = ("_CLOCKS",)   # gbox.hot_reload: a round's clock survives a bot reload mid-round


class RoundClock:
    """One game round's real play seconds and its ledger stats, fed by the driver on every tick (clock_tick: observe
    while playing; the results close it). A round is one player object of one boot: a fragment that starts mid-round (a
    bot reload, a restarted autoplay) finds the clock of its round in _CLOCKS and carries on from it.

    Real seconds: a tick gap up to CLOCK_STILL_S counts as it is. A longer one (the engine pressing a prompt, a held
    frame, the bot down between two fragments) counts for as much as the game's own clock fell over it - the round
    clock counts real time and stops in a pause or a frozen read, so a pause adds nothing - and, when the clock rose
    over it (a kill's or a statue's seconds), for the gap itself, at most CLOCK_GAP_MAX_S."""

    def __init__(self, key, now: float, wall: float, kills, timer):
        self.key, self.first_at, self.wall0 = key, now, wall
        self.t, self.timer, self.play_s = now, timer, 0.0
        self.kills0, self.timer0 = kills, timer
        self.kill400_s = None
        self.fragments, self.fragment_play0, self.evidence = 0, 0.0, None

    def observe(self, now: float, kills, timer) -> None:
        dt = now - self.t
        if dt > 0:
            if dt <= CLOCK_STILL_S:
                self.play_s += dt
            elif isinstance(timer, (int, float)) and isinstance(self.timer, (int, float)):
                fall = self.timer - timer
                self.play_s += min(dt, fall) if fall > 1e-3 else 0.0 if fall > -1e-3 else min(dt, CLOCK_GAP_MAX_S)
            else:
                self.play_s += min(dt, CLOCK_GAP_MAX_S)
        self.t, self.timer = now, timer if isinstance(timer, (int, float)) else self.timer
        if self.kill400_s is None and isinstance(kills, int) and kills >= GOAL_KILLS:
            self.kill400_s = self.play_s

    def stats(self) -> dict:
        return {"ss_round_key": self.key, "ss_round_play_s": round(self.play_s, 2),
                "ss_fragment_play_s": round(self.play_s - self.fragment_play0, 2), "ss_fragments": self.fragments,
                "ss_t0_kills": self.kills0, "ss_t0_timer": self.timer0, "ss_first_tick_at": round(self.wall0, 2),
                "ss_kill400_s": round(self.kill400_s, 2) if self.kill400_s is not None else None}


RESULT_KEYS = ("result_rank_ram", "result_rank_derived", "result_rank_verified", "result_rank_source", "no_mercy")


def clock_tick(stats: dict | None, snap: dict, where: str, now: float, wall: float | None = None) -> RoundClock | None:
    """The driver's hook, every tick: playing -> the round's clock runs; results -> the 400th kill closes it. Writes
    the ss_* stats into the bot's live stats (the row keeps them). Never raises."""
    try:
        p = snap.get("player") if isinstance(snap, dict) else None
        base = snap.get("module_base") if isinstance(snap, dict) else None
        kills, timer = snap.get("kills"), snap.get("timer")
        wall = time.time() if wall is None else wall
        if where == "playing" and isinstance(p, dict) and p.get("ptr") and base:
            key = f"{base:x}:{p['ptr']:x}" if isinstance(base, int) and isinstance(p["ptr"], int) \
                else f"{base}:{p['ptr']}"
            clock = _CLOCKS.get(key)
            if clock is None:
                if len(_CLOCKS) > 8:
                    _CLOCKS.clear()
                clock = _CLOCKS[key] = RoundClock(key, now, wall, kills if isinstance(kills, int) else None,
                                                  timer if isinstance(timer, (int, float)) else None)
            evidence = (stats or {}).get("round_evidence_id")
            if stats is not None and (clock.evidence != evidence or stats.get("ss_round_key") != key):
                clock.fragments += 1                             # this fragment's (this evidence row's) first tick
                clock.fragment_play0, clock.evidence = clock.play_s, evidence
                for k in RESULT_KEYS:                            # the last round's results are not this one's
                    stats.pop(k, None)
            clock.observe(now, kills, timer)
            if stats is not None:
                stats.update(clock.stats())
            return clock
        if where == "results" and stats is not None and stats.get("ss_round_key") in _CLOCKS:
            clock = _CLOCKS[stats["ss_round_key"]]
            if clock.kill400_s is None and isinstance(kills, int) and kills >= GOAL_KILLS:
                clock.kill400_s = clock.play_s                   # the results come up at the 400th kill
            stats.update(clock.stats())
            return clock
    except Exception as exc:                                     # noqa: BLE001 - the ledger never costs a tick
        if stats is not None:
            stats["ss_clock_error"] = f"{type(exc).__name__}: {exc}"[:160]
    return None


def result_rank(stats: dict | None, snap: dict) -> None:
    """At the results screen: the rank the game computed (snapshot rank_index, cGameSys +0x994) beside the one the
    score gives by the No Mercy table; verified when both agree. stats: result_rank, result_rank_verified,
    result_rank_ram, result_rank_derived, result_rank_source. Never raises."""
    if stats is None or not isinstance(snap, dict):
        return
    try:
        derived = rank_of(snap.get("score"))
        ram = rank_name(snap.get("rank_index"))
        if snap.get("no_mercy") is False:
            derived = None                                       # not the No Mercy table: no derived rank
        agree = bool(ram and derived and ram == derived)
        # result_rank is the Notebook's "observed" rank (result_rank_observed, s_rank_verified): only a RAM rank the
        # score's own table agrees with goes there; a disagreement keeps both numbers and no rank
        stats.update(result_rank_ram=snap.get("rank_index") if ram else None, result_rank_derived=derived,
                     result_rank_verified=agree, no_mercy=snap.get("no_mercy"),
                     result_rank_source=("ram cGameSys+0x994 = the score's table" if agree else
                                         "ram cGameSys+0x994 disagrees with the score's table" if ram and derived else
                                         "ram cGameSys+0x994" if ram else
                                         "derived from the score (" + RANK_SOURCE_TABLE + ")" if derived else None))
        if agree:
            stats["result_rank"] = ram
        else:
            stats.pop("result_rank", None)
    except Exception as exc:                                     # noqa: BLE001
        stats["result_rank_error"] = f"{type(exc).__name__}: {exc}"[:160]


# --- the CLI ---------------------------------------------------------------------------------------------------------

def data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "gbox-data" / "mercs"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.mercs.ss_ledger", description="The RE5 Switch No Mercy SS board")
    ap.add_argument("--db", default=None, help="the Notebook (default <data>/mercs/curriculum/<title>/rounds.sqlite)")
    ap.add_argument("--maps", default=None, help="the run maps (default <data>/mercs/round_maps/<title>; 'none': "
                                                 "rows only)")
    ap.add_argument("--since", type=float, default=0.0, help="only rows at or after this unix time")
    ap.add_argument("--json", action="store_true", help="the ledger and the board as JSON")
    ap.add_argument("--plan", nargs="?", const="", default=None, metavar="BUILD",
                    help="also print the next MercMode queue (optionally with this build)")
    ap.add_argument("--rounds", type=int, default=0, help="also list the last N game rounds")
    a = ap.parse_args(argv)
    rows = read_rows(a.db or data_dir() / "curriculum" / TITLE / "rounds.sqlite", since=a.since)
    maps = {} if a.maps == "none" else load_maps(a.maps or data_dir() / "round_maps" / TITLE,
                                                 ids=[r["id"] for r in rows])
    rounds = ledger(rows, maps)
    refined = sum(1 for r in rounds if "run map" in str(r["time_source"]))
    cells = board(rounds)
    if a.json:
        out = {"rounds": rounds, "board": [c for c in cells.values() if c["attempts"]], "rounds_timed_by_maps": refined}
        if a.plan is not None:
            out["plan"] = plan_queue(cells, a.plan or None)
        print(json.dumps(out, indent=1, default=str))
        return 0
    print(report(rounds, cells))
    if a.rounds:
        print("")
        print(f"the last {a.rounds} game rounds:")
        for r in rounds[-a.rounds:]:
            print(f"  {time.strftime('%m-%d %H:%M', time.gmtime(r['ended_at']))}Z {r['round_id'][:8]} "
                  f"{(r['stage'] or '?')[:16]:16s} {(r['character'] or '?')[:18]:18s} {r['outcome']:10s} "
                  f"k {r['kills']:3d} mc {r['max_combo'] if r['max_combo'] is not None else '-':>3} "
                  f"breaks {r['combo_breaks'] if r['combo_breaks'] is not None else '-':>3} "
                  f"score {(format(r['score'], ',') if r['score'] is not None else '-'):>9s} "
                  f"rank {r['rank'] or '-':>2s} play {_clock(r['play_s'])} ({r['time_source']}) "
                  f"frags {len(r['fragments'])}")
    print(f"\n({len(rows)} Notebook rows, {len(maps)} run maps; {refined} rounds timed by their run maps)")
    if a.plan is not None:
        print("\nthe next MercMode queue (stage x character pairs without SS first, then the slowest SS):")
        for e in plan_queue(cells, a.plan or None):
            print("  " + json.dumps(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
