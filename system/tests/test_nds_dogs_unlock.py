import hashlib
from pathlib import Path
from gbox import nds_dogs_unlock as m, game_unlocks


def test_ops_in_ram_and_unverified():
    ops = m.unlock_ops()
    assert len(ops) == 3 and all(not o["gameplay_verified"] for o in ops)
    assert ops[0]["hex_bytes"] == (999999999).to_bytes(4, "little").hex()


def test_guard_refuses_until_pinned(tmp_path):
    rom = tmp_path / "a.nds"
    rom.write_bytes(b"x")
    assert m.rom_guard(rom)["ok"] is False
    assert m.profile()["writes_enabled"] is False


def test_pre_launch_state_exists():
    src = Path(game_unlocks.__file__).read_text()
    assert "nds-dogs-database-candidate-v1" in src
