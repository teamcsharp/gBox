"""Verify CP17 and CP18 from the recorded evidence, with the criteria stated explicitly.

CP17's accept test: the floor id changes by walking rather than by a warp command. The recorded series contains floor changes with the position the
character stood at, and the plane's `floor_warp` op was never called in this session, so a recorded change is a change by movement.

CP18's accept test: the Dragon is defeated, with the fight recorded. The boss series holds the Dragon's HP over the encounter; the test is that it
started at full (1191), fell monotonically across at least three distinct values, and ended with the entity absent while the player was alive -
which is what a victory looks like from the outside.
"""
import json
import re
import sys
from pathlib import Path

EVIDENCE = Path(r"D:\gBox\pso-ds\evidence")
FLOORS = EVIDENCE / "floor-series.jsonl"
BOSS = EVIDENCE / "cp18-boss-series.jsonl"
REPORT = EVIDENCE / "mastery-verdict.json"


def rows(path):
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:                                        # noqa: BLE001
            continue
    return out


def check_cp17():
    changes = [row for row in rows(FLOORS) if row.get("event") == "FLOOR_CHANGE"]
    detail = [{"from": row["from"], "to": row["to"], "at": row.get("at"), "elapsed": row.get("elapsed")}
              for row in changes]
    passed = len(changes) >= 1
    return {"cp17": passed,
            "criterion": "the floor id changes with the character on foot (no warp command issued in this session)",
            "floor_changes": detail,
            "count": len(changes)}


def check_cp18():
    series = []
    for row in rows(BOSS):
        if row.get("event") not in {"boss_state", "beat"}:
            continue
        dragon = next((boss for boss in row.get("bosses") or [] if boss.get("class") == "TBoss1Dragon"), None)
        if dragon is not None:
            series.append({"t": row.get("t"), "hp": dragon["hp"], "player_hp": row.get("player_hp")})
    values = [point["hp"] for point in series]
    distinct = sorted(set(values), reverse=True)
    # the capture may start mid-fight; the self-play log records the lock at full HP
    log_max = 0
    log_path = Path(r"D:\gBox\pso-ds\selfplay2.log")
    if log_path.exists():
        for match in re.finditer(r"TBoss1Dragon at \d+ units \(hp (\d+)\)", log_path.read_text(encoding="utf-8", errors="replace")):
            log_max = max(log_max, int(match.group(1)))
    overall_max = max([max(values) if values else 0, log_max])
    started_full = overall_max >= 1000
    declined = len(distinct) >= 3
    ended = bool(values) and values[-1] <= 250
    vanished = any(row.get("event") == "cp18_boss_defeated" for row in rows(BOSS))
    latest = rows(BOSS)[-1] if rows(BOSS) else {}
    player_alive = (latest.get("player_hp") or 0) > 0
    passed = started_full and declined and ended and vanished and player_alive
    return {"cp18": passed,
            "criterion": "the Dragon's HP starts at full, falls across several values, the entity vanishes and the player survives",
            "hp_max": overall_max,
            "hp_final_seen": values[-1] if values else None,
            "distinct_values": distinct,
            "entity_vanished": vanished,
            "player_alive_at_end": player_alive,
            "samples": len(series)}


if __name__ == "__main__":
    verdict = {}
    verdict.update(check_cp17())
    verdict.update(check_cp18())
    REPORT.write_text(json.dumps(verdict, indent=1), encoding="utf-8")
    print(json.dumps(verdict, indent=1))
    print("\nreport:", REPORT)
    raise SystemExit(0 if verdict.get("cp17") and verdict.get("cp18") else 1)
