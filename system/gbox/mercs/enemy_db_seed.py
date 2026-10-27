"""One-off, read-only bootstrap of the enemy knowledge database (gbox.mercs.enemy_db) from the evidence the Mercenaries
bots already wrote, where its fields allow it.

  * Round maps (gbox-data/mercs/round_maps/<title>/<stage>/*.json):
      - RE5 PS3's shot records: distance, the weapon, the zone aimed and where the laser dot sat, hit or miss (no enemy
        class: they teach the title's every-class level);
      - every title's hit events: RE4's "by" names the attacker (em id, type, full health -> the class key
        "em16.0b.hp1400"), his attack kind and distance; RE5 PS3's give the distance and the bot's attack word.
  * The run lessons' shot rows (gbox-data/mercs/lessons/<title>/runs/*.jsonl, RE5 PS3's shot learning): distance,
    weapon, where the dot sat, hit / headshot / miss - except inside rounds whose round map already has shot records.
  * The player-damage ledger (the control plane's gbox.sqlite3, kind player_damage, and each receipt artifact; where it
    has receipts for a title its hits replace that title's round-map hit events - the same hits, without a class):
      - the snapshot at the hit: the nearest living enemy's class key (enemy_db.class_key: his full health there) and
        distance, and "hold" when the player's own state byte says he was held (re5_switch.MOTION_HELD,
        re6_switch.HELD_STATES);
      - the bot's stats.look inside it: its last shots, with target, distance, outcome and the health they took,
        deduplicated across receipts (the look keeps its last 30), the target's class from the same snapshot.
  * Not imported: the Notebook rows (per-round totals: no class, distance or single shot), the RE5 aim calibration and
    the impact lessons (aggregates of the same round-map shots and hits: they would count twice), stats.look outside
    the receipts (live telemetry, never stored).

Every source is opened read only (SQLite mode=ro; files read). Only the knowledge database is written: this tool's
earlier seed samples are replaced, then the cells are rebuilt from every sample (enemy_db.rebuild); a running bot
reloads them by itself (the database's generation changes).

    python -m gbox.mercs.enemy_db_seed --data-dir ~/gBox/system/gbox-data --dry-run   # what it finds, writes nothing
    python -m gbox.mercs.enemy_db_seed --data-dir ~/gBox/system/gbox-data             # write mercs/knowledge
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from . import enemy_db as K

UNITS_PER_M = {"G4BE08": 1000.0}          # the RAM maps' units_per_m (profiles/gamedata/<map>-ram.json); others cm
SOURCE_MAPS, SOURCE_LEDGER, SOURCE_LOOK = "seed:round_maps", "seed:damage_ledger", "seed:look"
SOURCE_LESSONS = "seed:lessons"
CLASS_MEMORY_S = 60.0                     # a look shot's target gone from its receipt's snapshot: his class from the
                                          # same session's snapshot this recent (a pointer can be reused by a spawn)
BY = re.compile(r"^(?:boss )?(?P<kind>[a-z_]+) slot (?P<slot>-?\d+) id (?P<id>0x[0-9a-f]+) type (?P<type>0x[0-9a-f]+) "
                r"hp (?P<hp>-?\d+)/(?P<hpmax>\d+) at (?P<dist>\d+)")
GATE_ZONE = re.compile(r"\b(?:dot|on) (?:on )?(head|body|leg)s?\b")


def _units(title) -> float:
    return UNITS_PER_M.get(title, 100.0)


def _num(v):
    return K._num(v)


def _held_sets() -> dict:
    """The player state bytes that mean he is held, per title, from the drivers (the literal values if they don't
    import)."""
    out = {"010018100CD46000": ("motion", frozenset({100, 106, 107, 113, 114})),
           "01002A000CD48000": ("state", frozenset({8, 9, 25}))}
    try:
        from .titles import re5_switch
        out["010018100CD46000"] = ("motion", frozenset(re5_switch.MOTION_HELD))
    except Exception:                                   # noqa: BLE001
        pass
    try:
        from .titles import re6_switch
        out["01002A000CD48000"] = ("state", frozenset(re6_switch.HELD_STATES))
    except Exception:                                   # noqa: BLE001
        pass
    return out


# --- round maps ---------------------------------------------------------------------------------------------------------
def round_map_events(data_dir, titles=None, stats=None):
    """Shots and hits from the round maps, as enemy_db events (oldest first per file)."""
    base = Path(data_dir) / "mercs" / "round_maps"
    stats = stats if stats is not None else {}
    if not base.is_dir():
        return
    for tdir in sorted(p for p in base.iterdir() if p.is_dir()):
        title = K._title(tdir.name)
        if not title or (titles and title not in titles):
            continue
        upm = _units(title)
        for path in sorted(tdir.glob("*/*.json")):
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                stats["unreadable_maps"] = stats.get("unreadable_maps", 0) + 1
                continue
            if not isinstance(d, dict):
                continue
            stats["maps"] = stats.get("maps", 0) + 1
            started = _num(d.get("started"))
            rid = str(d.get("round_id") or "")[:40] or None
            if d.get("shots") and started:
                seconds = _num(d.get("seconds")) or 0.0
                stats.setdefault("_covered", {}).setdefault(title, []).append((started - 2.0, started + seconds + 5.0))
            for rec in d.get("shots") or ():
                ev = _map_shot(title, rec, started, rid, upm)
                if ev:
                    yield ev
            for e in d.get("events") or ():
                ev = _map_hit(title, e, rid, upm)
                if ev:
                    yield ev


def _map_shot(title, rec, started, rid, upm):
    if not isinstance(rec, dict) or rec.get("result") not in ("hit", "miss"):
        return None                                     # unattributed / unconfirmed / pending: no outcome
    t = _num(rec.get("t"))
    if t is None:
        return None
    ts = t if t > 1e9 else (started + t if started else None)
    if ts is None:
        return None
    where = rec.get("where") if rec.get("where") in ("head", "body", "leg") else None
    zone = K._zone(where or rec.get("zone"))
    dist = _num(rec.get("dist"))
    wid = rec.get("wid")
    return {"k": "shot", "ti": title, "t": ts, "c": "unknown", "s": None,
            "w": K._weapon(wid if isinstance(wid, int) else None), "d": K._dist(dist / upm) if dist is not None else None,
            "o": rec["result"], "hd": None, "u": None, "l": None, "z": zone, "m": None, "e": None, "hm": None,
            "r": rid, "src": SOURCE_MAPS}


def _map_hit(title, e, rid, upm):
    if not isinstance(e, dict) or e.get("kind") != "hit":
        return None
    ts = _num(e.get("t"))
    if ts is None or ts < 1e9:
        return None
    dist = _num(e.get("dist"))
    m = BY.match(str(e.get("by") or ""))
    cls, state, attack = None, None, e.get("attack")
    if m:
        cls = f"em{int(m['id'], 16):02x}.{int(m['type'], 16):02x}.hp{int(m['hpmax'])}"
        state = "~" + m["kind"]                         # the attack kind, the RE4 bot's reading of the act byte
        attack = attack or m["kind"]
        dist = _num(m["dist"]) if dist is None else dist
    elif title == "BLUS30491":
        cls = "unknown"                                 # RE5 PS3's hit events name no class (the nearest's distance)
    loss = _num(e.get("loss"))
    return {"k": "damage", "ti": title, "t": ts, "c": cls, "s": state, "d": K._dist(dist / upm) if dist is not None else None,
            "a": K._safe(attack, 30) if attack else None, "loss": abs(loss) if loss is not None else None,
            "e": None, "pre": [], "hm": None, "ps": None, "r": rid,
            "src": SOURCE_MAPS + (":boss" if e.get("boss") else "")}


# --- the run lessons' shot rows -------------------------------------------------------------------------------------------
def lesson_shot_events(data_dir, titles=None, covered=None, stats=None):
    """RE5 PS3's per-shot rows in its run lessons ({"kind": "shot", "t", "result", "dot", "dist_cm", "weapon",
    "target"}), outside the time ranges whose round maps already gave the same shots (covered: title -> ranges)."""
    base = Path(data_dir) / "mercs" / "lessons"
    stats = stats if stats is not None else {}
    covered = covered or {}
    if not base.is_dir():
        return
    for tdir in sorted(p for p in base.iterdir() if (p / "runs").is_dir()):
        title = K._title(tdir.name)
        if not title or (titles and title not in titles):
            continue
        ranges = sorted(covered.get(title) or ())
        for path in sorted((tdir / "runs").glob("*.jsonl")):
            try:
                with path.open("rb") as f:
                    for line in f:
                        if b'"shot"' not in line:              # most rows are navigation samples: parse only these
                            continue
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        ev = _lesson_shot(title, row, path.stem)
                        if ev is None:
                            continue
                        if any(lo <= ev["t"] <= hi for lo, hi in ranges):
                            stats["lesson_shots_in_round_maps"] = stats.get("lesson_shots_in_round_maps", 0) + 1
                            continue
                        yield ev
            except OSError:
                stats["unreadable_runs"] = stats.get("unreadable_runs", 0) + 1


def _lesson_shot(title, row, run):
    if not isinstance(row, dict) or row.get("kind") != "shot":
        return None
    t = _num(row.get("t"))
    result = str(row.get("result") or "")
    if t is None or t < 1e9:
        return None
    if result in ("hit", "headshot"):
        outcome = "hit"
    elif result.startswith("miss"):
        outcome = "miss"
    else:
        return None                                     # bow observations: unconfirmed, never a hit or a miss
    dot = row.get("dot") if row.get("dot") in ("head", "body", "leg") else None
    zone = "head" if result == "headshot" else K._zone(dot)
    dist = _num(row.get("dist_cm"))
    weapon = row.get("weapon")
    return {"k": "shot", "ti": title, "t": t, "c": "unknown", "s": None,
            "w": K._weapon(weapon if isinstance(weapon, int) else None),
            "d": K._dist(dist / _units(title)) if dist is not None else None, "o": outcome, "hd": None, "u": None,
            "l": None, "z": zone, "m": None, "e": None, "hm": None, "r": K._safe(run, 40), "src": SOURCE_LESSONS}


# --- the player-damage ledger ---------------------------------------------------------------------------------------------
def ledger_events(data_dir, titles, stats=None, limit=None):
    """Hits and look shots from the player-damage receipts of the given titles (read only)."""
    from .round_reports import TITLES
    from .incident import unpack_context
    stats = stats if stats is not None else {}
    db_path = Path(data_dir) / "gbox.sqlite3"
    if not db_path.is_file():
        return
    games = {g: t for t, gs in TITLES.items() if t in titles for g in gs}
    if not games:
        return
    held = _held_sets()
    seen_shots: set = set()
    memory: dict = {}                                   # (session, enemy pointer) -> (seen at, his class key)
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10.0)) as db:
        db.execute("pragma query_only=ON")
        marks = ",".join("?" * len(games))
        rows = db.execute("select json_extract(body,'$.game_id'), json_extract(body,'$.receipt') from docs "
                          f"where kind='player_damage' and json_extract(body,'$.game_id') in ({marks}) "
                          "order by json_extract(body,'$.observed_at')", tuple(games)).fetchall()
    for n, (game, receipt) in enumerate(rows):
        if limit is not None and n >= limit:
            break
        title = games.get(game)
        if not isinstance(receipt, str) or not re.fullmatch(r"[a-f0-9]{64}", receipt):
            stats["receipts_missing"] = stats.get("receipts_missing", 0) + 1
            continue
        path = Path(data_dir) / "artifacts" / receipt[:2] / receipt
        try:
            event = unpack_context(json.loads(path.read_bytes())["event"])
        except (OSError, ValueError, KeyError, TypeError):
            stats["receipts_unreadable"] = stats.get("receipts_unreadable", 0) + 1
            continue
        stats["receipts"] = stats.get("receipts", 0) + 1
        snap = event.get("snapshot") or {}
        sid, at = event.get("session_id"), _num(event.get("observed_at")) or 0.0
        for e in snap.get("enemies") or ():
            if isinstance(e, dict) and e.get("ptr", e.get("slot")) is not None:
                memory[(sid, str(e.get("ptr", e.get("slot"))))] = (at, K.class_key(e), _num(e.get("hp_max")))
        if len(memory) > 20000:
            for k in sorted(memory, key=lambda k: memory[k][0])[:10000]:
                memory.pop(k, None)
        ev = _ledger_hit(title, event, snap, held.get(title))
        if ev:
            yield ev
        look = ((event.get("logic") or {}).get("look") or {}).get("shots") or ()
        for shot in look:
            key = (sid, shot.get("t") if isinstance(shot, dict) else None,
                   ((shot.get("target") or {}).get("id")) if isinstance(shot, dict) else None)
            if key in seen_shots:
                continue
            seen_shots.add(key)
            ev = _look_shot(title, shot, snap, event, memory)
            if ev:
                if ev.get("remembered"):
                    stats["look_classes_remembered"] = stats.get("look_classes_remembered", 0) + 1
                ev.pop("remembered", None)
                yield ev


def _flat(a, b):
    return math.hypot(b[0] - a[0], b[2] - a[2])


def _vec(v):
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(_num(x) is not None for x in v)


def _ledger_hit(title, event, snap, held):
    ts = _num(event.get("observed_at"))
    player = snap.get("player") or {}
    if ts is None or not _vec(player.get("pos")):
        return None
    upm = _units(title)
    living = [e for e in snap.get("enemies") or () if isinstance(e, dict) and _vec(e.get("pos"))
              and (_num(e.get("hp")) or 0) > 0]
    nearest = min(living, key=lambda e: _flat(player["pos"], e["pos"]), default=None)
    attack = None
    if held is not None and player.get(held[0]) in held[1]:
        attack = "hold"                                 # the player's own state byte: held / strangled
    loss = _num(event.get("loss"))
    cls = K.class_key(nearest) if nearest is not None else None
    dist = _flat(player["pos"], nearest["pos"]) / upm if nearest is not None else None
    return {"k": "damage", "ti": title, "t": ts, "c": cls, "s": None, "d": K._dist(dist), "a": attack,
            "loss": abs(loss) if loss is not None else None, "e": K._eid(nearest.get("ptr")) if nearest else None,
            "pre": [], "hm": _num(nearest.get("hp_max")) if nearest else None,
            "ps": K.state_key(player.get(held[0])) if held else None, "r": K._safe(event.get("round_id"), 40) or None,
            "src": SOURCE_LEDGER}


def _look_shot(title, shot, snap, event, memory=None):
    if not isinstance(shot, dict):
        return None
    outcome = K._outcome(shot.get("outcome"))
    ts = _num(shot.get("t"))
    if outcome is None or ts is None or ts < 1e9:
        return None                                     # "unknown": the hit window had not passed yet
    target = shot.get("target") or {}
    tid = target.get("id")
    enemy = next((e for e in snap.get("enemies") or () if isinstance(e, dict) and tid is not None
                  and str(e.get("ptr", e.get("slot"))) == str(tid)), None)
    cls, hp_max, remembered = "unknown", None, False
    if enemy is not None:
        cls, hp_max = K.class_key(enemy), _num(enemy.get("hp_max"))
    elif tid is not None and memory:                   # gone from this snapshot (dead, or despawned): the session's
        seen = memory.get((event.get("session_id"), str(tid)))   # last sight of that pointer, if recent
        if seen is not None and abs(ts - seen[0]) <= CLASS_MEMORY_S:
            cls, hp_max, remembered = seen[1], seen[2], True
    m = GATE_ZONE.search(str(shot.get("gate") or ""))
    return {"k": "shot", "ti": title, "t": ts, "c": cls, "s": None, "w": K._weapon(shot.get("weapon")),
            "d": K._dist(target.get("dist_m")), "o": outcome, "hd": _num(shot.get("hp_delta")), "u": None, "l": None,
            "z": K._zone(m.group(1)) if m else None, "m": None, "e": None, "hm": hp_max,
            "r": K._safe(event.get("round_id"), 40) or None, "src": SOURCE_LOOK, "remembered": remembered}


# --- assembling and writing --------------------------------------------------------------------------------------------------
def collect(data_dir, *, titles=None, ledger_titles=None, ledger_limit=None) -> tuple:
    """Every seed event by title, and the reading stats. ledger_titles: the titles whose hits come from the damage
    ledger (default: every title it has receipts for). Its receipts carry the snapshot (the attacker's class key and
    distance), so a title's round-map hit events - the same hits, without a class - are used only where the ledger
    has none (RE4)."""
    from .round_reports import TITLES
    stats: dict = {}
    by_title: dict = {}
    if ledger_titles is None:
        ledger_titles = [t for t in TITLES if not titles or t in titles]
    for ev in ledger_events(data_dir, set(ledger_titles), stats, limit=ledger_limit):
        by_title.setdefault(ev["ti"], []).append(ev)
    from_ledger = {t for t, evs in by_title.items() if any(e["src"] == SOURCE_LEDGER for e in evs)}
    for ev in round_map_events(data_dir, titles, stats):
        if ev["k"] == "damage" and ev["ti"] in from_ledger:
            stats["map_hits_in_ledger"] = stats.get("map_hits_in_ledger", 0) + 1
            continue
        by_title.setdefault(ev["ti"], []).append(ev)
    covered = stats.pop("_covered", {})
    for ev in lesson_shot_events(data_dir, titles, covered, stats):
        by_title.setdefault(ev["ti"], []).append(ev)
    for evs in by_title.values():
        evs.sort(key=lambda e: e["t"])
    return by_title, stats


def tally(by_title) -> dict:
    """{title: {"sources": {source: n}, "classes": {class: {"shots", "hits", "damage", "bands": {...}}}}}"""
    out = {}
    for title, evs in sorted(by_title.items()):
        row = out.setdefault(title, {"sources": {}, "classes": {}})
        for ev in evs:
            src = ev["src"].split(":boss")[0]
            row["sources"][src] = row["sources"].get(src, 0) + 1
            cls = ev["c"] if ev["c"] is not None else "(unattributed)"
            c = row["classes"].setdefault(cls, {"shots": 0, "hits": 0, "damage": 0, "bands": {}})
            if ev["k"] == "shot":
                c["shots"] += 1
                c["hits"] += ev["o"] in ("hit", "kill")
            else:
                c["damage"] += 1
            b = K.band(ev["d"]) or "?"
            c["bands"][b] = c["bands"].get(b, 0) + 1
    return out


def preview(by_title, now=None) -> dict:
    """The plans the seed alone would give (enemy_db.summary over an in-memory model)."""
    now = time.time() if now is None else now
    models: dict = {}
    batch: dict = {}
    ctx = {"kills": {}, "last": {}}
    for evs in by_title.values():
        for ev in evs:
            K._apply(models, batch, ctx, ev)
    for (ti, key), cell in batch.items():
        models.setdefault(ti, {})[key] = cell
    return {title: K.summary(title, models, now) for title in sorted(models)}


def write(by_title, out_root, *, now=None) -> dict:
    """Replace this tool's earlier seed samples with these, then rebuild each title's cells."""
    now = time.time() if now is None else now
    out = {}
    for title, evs in sorted(by_title.items()):
        path = K.db_path(title, out_root)
        with closing(K._connect(path)) as db:
            with db:
                db.execute("delete from samples where source like 'seed:%'")
                db.executemany(f"insert into samples({','.join(K.SAMPLE_COLS)}) values "
                               f"({','.join('?' * len(K.SAMPLE_COLS))})", [K._row_of(ev) for ev in evs])
                counts = {}
                for ev in evs:
                    counts[ev["src"]] = counts.get(ev["src"], 0) + 1
                db.execute("insert or replace into meta values('seeded', ?)",
                           (json.dumps({"at": round(now, 3), "samples": counts}, sort_keys=True),))
        out[title] = K.rebuild(title, out_root, now=now)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.mercs.enemy_db_seed", description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", required=True, help="the gBox data dir (gbox-data): round maps, gbox.sqlite3, artifacts")
    ap.add_argument("--out", help="the knowledge root to write (default <data-dir>/mercs/knowledge)")
    ap.add_argument("--titles", nargs="*", help="only these titles (map ids)")
    ap.add_argument("--ledger-titles", nargs="*", help="titles whose hits come from the damage ledger "
                    "(default: the titles without round-map hits)")
    ap.add_argument("--ledger-limit", type=int, help="read at most this many receipts (a quick look)")
    ap.add_argument("--dry-run", action="store_true", help="count and preview only; write nothing")
    ap.add_argument("--json", action="store_true", help="print the full JSON")
    a = ap.parse_args(argv)
    t0 = time.time()
    by_title, stats = collect(a.data_dir, titles=a.titles, ledger_titles=a.ledger_titles, ledger_limit=a.ledger_limit)
    report = {"read": stats, "found": tally(by_title), "preview": preview(by_title), "seconds": round(time.time() - t0, 1)}
    if not a.dry_run:
        out_root = Path(a.out) if a.out else Path(a.data_dir) / "mercs" / "knowledge"
        report["written"] = write(by_title, out_root)
    if a.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f"read: {json.dumps(stats)}  ({report['seconds']} s)")
        for title, row in report["found"].items():
            print(f"{title}: {json.dumps(row['sources'])}")
            for cls, c in sorted(row["classes"].items(), key=lambda kv: -(kv[1]["shots"] + kv[1]["damage"])):
                print(f"  {cls}: {c['shots']} shots ({c['hits']} hits), {c['damage']} hits taken, bands {c['bands']}")
            print(f"  plan preview: {report['preview'].get(title, {}).get('text')}")
        if "written" in report:
            print("written: " + json.dumps(report["written"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
