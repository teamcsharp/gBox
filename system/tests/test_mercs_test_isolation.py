"""The test suite never writes the operator's runtime files (the mercs telemetry, the learned aim books / menus / threats,
the RE4 sidebar settings): every module-level file a bot test can write is pointed at the test's own temp directory by
the autouse fixtures in conftest.py. This test is the rule itself - 2026-11-10: a synthetic round's blocked shots and
doorway crossings were found in the checkout's gbox-data/mercs, looking like the bot's live telemetry."""
from pathlib import Path


def _paths():
    from gbox.mercs import round_reports
    from gbox.mercs.core import aim_book, menu_pace
    from gbox.mercs.titles import re4_switch, re4_switch_mods, re4_walk
    out = {"re4 SIGHT_LOG": re4_switch.SIGHT_LOG, "re4 WALK_LOG": re4_switch.WALK_LOG,
           "re4 THREAT_FILE": re4_switch.THREAT_FILE, "re4 PACE_FILE": re4_switch.PACE_FILE,
           "re4 mods SETTINGS_FILE": re4_switch_mods.SETTINGS_FILE,
           "re4 walk CROSSING_LOG": re4_walk.CROSSING_LOG,
           "aim_book DATA": aim_book.DATA, "menu_pace LEARNED": menu_pace.LEARNED}
    return {name: Path(value) for name, value in out.items() if isinstance(value, (str, Path))}


def test_every_mercs_runtime_file_a_bot_test_writes_is_a_temporary_one():
    paths = _paths()
    assert {"re4 SIGHT_LOG", "re4 WALK_LOG", "re4 walk CROSSING_LOG", "re4 THREAT_FILE", "aim_book DATA"} <= set(paths)
    for name, path in paths.items():
        text = str(path).replace("\\", "/")
        assert "gbox-data" not in text and "learned/0100" not in text, f"{name} is the deployment's file: {path}"
        assert "pytest" in text or "tmp" in text.lower(), f"{name} is not a test's own file: {path}"


def test_a_bot_test_round_leaves_the_deployments_mercs_files_alone():
    """A real tick through the fight with a synthetic room writes its logs to the test's temp files only."""
    from gbox.mercs.titles import re4_switch as D
    paths = _paths()
    before = {p: p.stat().st_mtime_ns if p.exists() else None for p in paths.values()}
    room_rows = [[1] * 40 for _ in range(40)]
    rm = D.re4_room_map.RoomMap.from_mask("r400", (-5000.0, -5000.0), 250.0, room_rows,
                                          [(-3000.0, 1000.0, 3000.0, 1000.0, 0.0, 3000.0, 0)])
    s = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1},
         "enemies": [{"pos": (0.0, 0.0, 3000.0), "hp": 400, "hp_max": 400, "ptr": 100, "class": 0xAE7050}],
         "room_map": rm}
    b = D.Bot(stats={}, director=False)
    for k in range(30):
        b.tick(s, now=0.1 * k)
    after = {p: p.stat().st_mtime_ns if p.exists() else None for p in paths.values()}
    changed = [p for p in paths.values() if after[p] != before[p]]
    assert all("gbox-data" not in str(p).replace("\\", "/") for p in changed), \
        f"a test's round wrote the deployment's files: {changed}"
    assert any(p.exists() for p in changed), "the round's own (temporary) logs were written"
