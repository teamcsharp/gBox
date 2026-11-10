"""scripts/bot_trace.py: a recorded (or replayed) bot trace drawn over the room's walls with the controls strip, the
stage key resolved to its room map, and the API token read but never printed."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bot_trace.py"
spec = importlib.util.spec_from_file_location("bot_trace", SCRIPT)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


def _rows():
    """6 s of a walk by the Castle's west doorway (r402's mesh: 4093 triangles), the controls as the frame carries
    them (plan.keys / tap) and, for the last rows, as a replay's raw plan.controls."""
    rows = []
    for k in range(30):
        t = 100.0 + 0.2 * k
        keys = ["b", "lup"] if k < 10 else ["zl"] if k < 20 else ["lleft", "lup"]
        plan = {"phase": "walk" if k < 10 else "fire" if k < 20 else "flank",
                "route": [[16235.0, 3073.0, -26348.0], [14929.0, 3073.0, -26359.0]]}
        row = {"t": t, "pos": [16900.0 - 30.0 * k, 3073.0, -27600.0 + 20.0 * k], "facing": -0.7, "hp": 1000,
               "plan": plan, "stage": "010099A00BC1E000.nav4093.0123abcd",
               "enemies": [{"pos": [14929.0, 3073.0, -26359.0], "hp": 400}],
               "tel": {"doing": plan["phase"], "why": "test", "shots": k // 2, "room_map_route_legs": k}}
        if k < 20:
            row.update(keys=keys, tap="zr" if 10 <= k < 20 and k % 2 else None)
        else:
            plan["controls"] = {"keys": keys, "tap": None, "stick": {}}
        rows.append(row)
    return rows


def test_draw_makes_the_picture_with_the_walls_and_the_controls_strip(tmp_path, capsys):
    pytest.importorskip("PIL")
    src, out = tmp_path / "t.jsonl", tmp_path / "t.png"
    src.write_text("".join(json.dumps(r) + "\n" for r in _rows()), encoding="utf-8")
    s = bt.draw(str(src), str(out))
    from PIL import Image
    img = Image.open(out)
    assert img.size[0] == 1100 and img.size[1] > 1100, "the map, then the strip under it"
    assert s["walls_drawn"] > 50 and s["time_per_phase_s"]["fire"] == pytest.approx(2.0, abs=0.01)
    assert s["walked_m"] == pytest.approx(1.0, abs=0.05)
    strip = img.crop((0, 1100, 1100, img.size[1])).convert("L")
    assert strip.getextrema()[0] < 100, "the key rows are drawn"
    assert '"walked_m"' in capsys.readouterr().out


def test_the_stage_key_finds_the_room_and_the_keys_come_from_the_frame_or_a_replay():
    room = bt.room_for("010099A00BC1E000.nav4093.0123abcd")
    assert room is not None and room.name == "r402.json" and room.exists()
    assert bt.room_for("something else") is None and bt.room_for(None) is None
    rows = _rows()
    assert bt._keys(rows[0]) == ({"b", "lup"}, None) and bt._keys(rows[11]) == ({"zl"}, "zr")
    assert bt._keys(rows[25]) == ({"lleft", "lup"}, None)
    assert bt._keys({"plan": {"keys": ["zl"], "tap": "zr"}}) == ({"zl"}, "zr")


def test_the_token_is_read_and_never_printed(monkeypatch, capsys):
    monkeypatch.setenv("GBOX_TOKEN", "tok-not-for-print-123")
    assert bt.token() == "tok-not-for-print-123"
    assert bt.main([]) == 2
    out = capsys.readouterr()
    assert "tok-not-for-print-123" not in out.out + out.err
