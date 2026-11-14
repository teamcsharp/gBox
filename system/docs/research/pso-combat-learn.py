"""Learn the game's melee hit rules from the operator's recorded demonstrations.

The operator plays on the keyboard, so `demo-*.jsonl` traces contain A presses (`{'src': 'keyboard', 'keys': ['A']}`),
the player's position + heading at 15 Hz and the whole entity table with enemy HP. This streams those files and, for
every A press with an enemy in front, records the distance, the angle between the heading and the enemy, and whether
the enemy's HP fell within the next moments. The aggregate - hit rate per distance/angle bucket - is written to
`combat-model.json` and is what the bot's attack range and approach should be calibrated against ("monkey see,
monkey do" for combat).

    python pso-combat-learn.py
    python pso-combat-learn.py --max-mb 40
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib

OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
DEMOS = OUT
DISTANCE_EDGES = (3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 22.0, 28.0, 40.0)
ANGLE_EDGES = (10.0, 20.0, 35.0, 55.0, 90.0, 180.0)
HIT_WINDOW_S = 2.5


def bearing(player, entity):
    dx = float(entity["x"]) - float(player["x"])
    dz = float(entity["z"]) - float(player["z"])
    return math.degrees(math.atan2(dx, dz)) % 360.0


def angle_between(heading, target):
    diff = abs((heading - target + 180.0) % 360.0 - 180.0)
    return diff


def is_enemy(entity):
    cls = str(entity.get("class") or "")
    return ("Ene" in cls or str(entity.get("kind")) == "enemy") and entity.get("hp") is not None


def nearest_enemy(player, entities, limit=40.0):
    best = None
    for entity in entities:
        if not is_enemy(entity):
            continue
        distance = math.hypot(float(entity["x"]) - float(player["x"]), float(entity["z"]) - float(player["z"]))
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, entity)
    return best


def analyse_file(path, presses, hits_by_distance, hits_by_angle, files):
    """Stream one trace; append (distance, angle, hit) events into the caller's buckets."""
    player = None
    entities = []
    pending = []                      # presses waiting for a future HP observation
    previous_keys = None
    count = 0
    for raw in path.open("r", encoding="utf-8", errors="replace"):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        kind = row.get("kind")
        if kind == "sample":
            player = row.get("player")
            entities = row.get("entities") or []
            now = row.get("t")
            # resolve pending presses against this sample
            alive = []
            for item in pending:
                if now - item["t"] > HIT_WINDOW_S:
                    item["resolved"] = True
                    hits_by_distance.append((item["distance"], item["hit"]))
                    hits_by_angle.append((item["angle"], item["hit"]))
                    files["events"] += 1
                    files["hits"] += 1 if item["hit"] else 0
                    continue
                target = next((e for e in entities if str(e.get("ptr")) == item["ptr"]), None)
                if target is None:
                    item["hit"] = True                       # the target is gone: a kill counts as a hit
                elif target.get("hp") is not None and float(target["hp"]) < item["hp"]:
                    item["hit"] = True
                alive.append(item)
            pending = alive
        elif kind == "input" and row.get("src") == "keyboard":
            keys = set(row.get("keys") or [])
            if player is not None and previous_keys is not None:
                pressed_a = "A" in keys and "A" not in previous_keys
                if pressed_a:
                    target = nearest_enemy(player, entities)
                    if target is not None:
                        press = {"distance": target[0],
                                 "angle": angle_between(float(player.get("heading_deg") or 0),
                                                        bearing(player, target[1])),
                                 "ptr": str(target[1].get("ptr")), "hp": target[1].get("hp"),
                                 "t": row.get("t"), "hit": False}
                        pending.append(press)
                        presses.append(press)
                        count += 1
            previous_keys = keys
        elif kind == "input":
            if previous_keys is not None:
                previous_keys = None
    for item in pending:
        hits_by_distance.append((item["distance"], item["hit"]))
        hits_by_angle.append((item["angle"], item["hit"]))
    files["presses"] += count
    return count


def bucket(values, edges, hit_key):
    """[(value, hit)] -> [{range, presses, hits, rate}] for the fixed bucket edges."""
    rows = []
    low = 0.0
    for edge in edges:
        items = [hit for value, hit in values if low <= value < edge]
        rows.append({"from": low, "to": edge, "presses": len(items), "hits": sum(1 for h in items if h),
                     "rate": round(sum(1 for h in items if h) / len(items), 3) if items else None})
        low = edge
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="learn hit rules from the operator's demonstration traces")
    parser.add_argument("--max-mb", type=float, default=12.0)
    parser.add_argument("--limit-files", type=int, default=8)
    args = parser.parse_args(argv)
    files = sorted(DEMOS.glob("demo-*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    budget = args.max_mb * 1024 * 1024
    presses, hits_by_distance, hits_by_angle = [], [], []
    totals = {"files": 0, "presses": 0, "events": 0, "hits": 0}
    used = []
    for path in files:
        if any(marker in path.name for marker in ("-route",)):
            continue
        size = path.stat().st_size
        if size > budget:
            continue
        totals["files"] += 1
        used.append(path.name)
        analyse_file(path, presses, hits_by_distance, hits_by_angle, totals)
        if totals["files"] >= args.limit_files:
            break
    by_distance = bucket(hits_by_distance, DISTANCE_EDGES, "hit")
    by_angle = bucket(hits_by_angle, ANGLE_EDGES, "hit")
    # Suggested range: the longest edge where a bucket of at least five presses hit at least 60% of the time.
    usable = [row for row in by_distance if row["presses"] >= 5 and (row["rate"] or 0) >= 0.6]
    suggested_range = max((row["to"] for row in usable), default=None)
    usable_angle = [row for row in by_angle if row["presses"] >= 5 and (row["rate"] or 0) >= 0.6]
    suggested_angle = max((row["to"] for row in usable_angle), default=None)
    model = {"schema": 1, "created": __import__("time").time(), "files": used,
             "presses_with_target": len(presses), "presses_resolved": totals["events"], "hits": totals["hits"],
             "hit_rate": round(totals["hits"] / totals["events"], 3) if totals["events"] else None,
             "by_distance": by_distance, "by_angle": by_angle,
             "suggested_attack_range": suggested_range, "suggested_facing_angle_deg": suggested_angle}
    (OUT / "combat-model.json").write_text(json.dumps(model, indent=1), encoding="utf-8")
    print(json.dumps({k: model[k] for k in ("files", "presses_with_target", "presses_resolved", "hits", "hit_rate",
                                            "suggested_attack_range", "suggested_facing_angle_deg")}, indent=1))
    print(json.dumps({"by_distance": by_distance, "by_angle": by_angle}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
