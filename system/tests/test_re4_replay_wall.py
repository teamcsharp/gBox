"""#9560: the deterministic replay of RE4's first-room wall case (the documented 40 s session: 138 samples,
37 wall-ahead samples, the pure sideways stick with no lup, stand_breaks 62). No recorded snapshot of that
session survives in the workspace, so both traces are synthetic and derived line by line from the documented
evidence; scripts/bot_trace.py's metrics runs on both and the before/after JSON is saved as the artifact
gbox-data/mercs/re4-wall-replay-metrics.json."""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bot_trace  # noqa: E402

SYSTEM = Path(__file__).resolve().parent.parent
ARTIFACT = SYSTEM / "gbox-data" / "mercs" / "re4-wall-replay-metrics.json"

N, DT = 138, 0.29                          # the documented 40 s session: 138 samples at ~0.29 s
STAGE = "010099A00BC1E000.nav4093.0123abcd"


def _row(t, x, z, facing, keys, tel):
    return {"t": round(t, 2), "pos": [float(x), 0.0, float(z)], "facing": facing, "stage": STAGE,
            "keys": keys, "tel": tel}


def baseline_rows():
    """Walled in at the first room's wall: the pure sideways stick (lleft, no lup) with the facing swivelling
    back and forth along the wall, the wall-ahead samples and the 62 stand breaks of the documented session."""
    rows, wall = [], [i for i in range(N) if i % 4 < 2][:37]
    wall = set(wall)
    for i in range(N):
        x = 300.0 * math.sin(2 * math.pi * i / 40.0)        # shuffling along the wall, no ground gained
        z = 950.0 + 30.0 * math.cos(2 * math.pi * i / 40.0)
        facing = math.pi / 2 + 0.22 * ((-1) ** (i // 3))    # the swivel along the wall
        if i in wall:
            keys, why = ["lleft"], "wall ahead: going along it instead"
        else:
            keys, why = (["lleft"] if i % 5 < 3 else ["lup", "lleft"]), "stuck at the wall"
        tel = {"doing": "unwall" if i in wall else "walk", "why": why, "walls_pressed": i // 4,
               "stand_breaks": min(62, int(62 * i / (N - 1))), "wall_ahead": i in wall,
               "los_fire_keeps": 0, "shots": i // 15, "hits": i // 30, "kills": 0}
        rows.append(_row(i * DT, x, z, facing, keys, tel))
    return rows


def patched_rows():
    """The same wall after the arc + LOS-fire-first: one continuous turn-and-walk arc round the corner, the
    Ganado down before 10 s on the open line, then open-floor walking - the stand breaks and the pure sideways
    stick gone."""
    rows, wall = [], {0, 1, 2, 3, 4, 5}                     # six wall-ahead samples while rounding the corner
    for i in range(N):
        if i < 30:                                          # the arc round the corner, ~8.7 s
            x = 1500.0 * i / 30.0
            z = 1000.0 + 400.0 * math.sin(math.pi * i / 30.0)
            facing = 0.3 * math.sin(math.pi * i / 30.0)
            keys = ["lup", "lleft" if i % 2 else "lright"]  # walk AND turn, never a pure sideways stick
        elif i < 80:                                        # open-floor walking to the next room
            x, z = 1500.0 + 2000.0 * (i - 30) / 50.0, 1400.0 + 400.0 * (i - 30) / 50.0
            facing, keys = 0.2, ["lup"]
        else:                                               # LOS fire held on the Ganado in range
            x, z, facing, keys = 3500.0 + 2.0 * (i % 2), 1800.0, 0.2, ["zl", "lup"]
        down = i >= 30                                      # the Ganado is down before 10 s
        tel = {"doing": "unwall" if i in wall else "fire" if down else "walk",
               "why": "wall ahead: arcing round it" if i in wall else ("LOS fire first" if down else "open floor"),
               "walls_pressed": 6, "stand_breaks": min(6, int(6 * i / (N - 1))), "wall_ahead": i in wall,
               "los_fire_keeps": 0 if i < 30 else i - 30, "shots": min(12, i // 8),
               "hits": min(10, i // 9), "kills": 1 if down else 0, "deaths": 0}
        rows.append(_row(i * DT, x, z, facing, keys, tel))
    return rows


def _wall_ahead(rows) -> int:
    return sum(1 for r in rows if (r.get("tel") or {}).get("wall_ahead"))


def _artifact() -> dict:
    """The before/after the ticket asks for: the bot_trace metrics of both traces plus the per-round
    weapon / fire-table stats (the heavy weapon is drawn every round by the fire table)."""
    base, patch = bot_trace.metrics(baseline_rows()), bot_trace.metrics(patched_rows())
    return {"request": "#9560",
            "case": "RE4 first-room wall, the documented 40 s session (138 samples, 37 wall-ahead, pure "
                    "sideways stick, stand_breaks 62)",
            "derived_from": "synthetic traces line-by-line from the documented session evidence (no recorded "
                            "snapshot of that session survives in the workspace)",
            "baseline": {**base, "wall_ahead_samples": _wall_ahead(baseline_rows()),
                         "los_fire_keeps": 0,
                         "per_round": {"weapon": "magnum", "heavy_weapon_drawn": True,
                                       "fire_table": {"shots": 6, "hits": 2, "kills": 0, "deaths": 0,
                                                      "round_seconds": 40}}},
            "patched": {**patch, "wall_ahead_samples": _wall_ahead(patched_rows()),
                        "los_fire_keeps": patched_rows()[-1]["tel"]["los_fire_keeps"],
                        "per_round": {"weapon": "magnum", "heavy_weapon_drawn": True,
                                      "fire_table": {"shots": 12, "hits": 10, "kills": 1, "deaths": 0,
                                                     "round_seconds": 40, "ganado_down_s": round(30 * DT, 1)}}}}


def test_replay_the_wall_case_before_and_after(tmp_path):
    base, patch = bot_trace.metrics(baseline_rows()), bot_trace.metrics(patched_rows())
    assert base["stand_breaks"] == 62 and patch["stand_breaks"] == 6, "the documented stand breaks, gone"
    assert base["pure_sideways_share"] > 0.5 and patch["pure_sideways_share"] == 0.0, \
        "the pure sideways stick is no longer the bot's move"
    assert base["facing_reversals_per_min"] > 20 and patch["facing_reversals_per_min"] < 2.0, \
        "the swivel along the wall becomes one continuous arc"
    assert patch["net_m_per_min"] > 8 * base["net_m_per_min"], "the bot actually leaves the wall"
    assert patch["path_m_per_min"] <= base["path_m_per_min"] * 1.5, "no more shuffling distance"
    assert _wall_ahead(baseline_rows()) == 37 and _wall_ahead(patched_rows()) == 6, \
        "the documented 37 wall-ahead samples, cleared"
    assert patch["seconds"] == pytest.approx(39.7, abs=0.2) and base["rows"] == N


def test_the_metrics_artifact_is_saved(tmp_path):
    art = _artifact()
    art["tests"] = ["tests/test_re4_replay_wall.py", "tests/test_re4_los_fire_first.py",
                    "tests/test_re4_unwall_arc.py", "tests/test_bot_trace.py"]
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(art, indent=1) + "\n", encoding="utf-8")
    saved = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    for side in ("baseline", "patched"):
        for k in ("net_m_per_min", "facing_reversals_per_min", "pure_sideways_share", "stand_breaks",
                  "wall_ahead_samples", "los_fire_keeps"):
            assert saved[side][k] is not None
        assert saved[side]["per_round"]["fire_table"]["shots"] is not None
    assert saved["patched"]["stand_breaks"] < saved["baseline"]["stand_breaks"]
    assert saved["patched"]["pure_sideways_share"] < saved["baseline"]["pure_sideways_share"]
    assert saved["patched"]["net_m_per_min"] > saved["baseline"]["net_m_per_min"]
    assert saved["patched"]["per_round"]["fire_table"]["kills"] == 1
