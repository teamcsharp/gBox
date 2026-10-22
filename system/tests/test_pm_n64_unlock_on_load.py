import struct
from pathlib import Path
import pytest
from gbox import pm_unlock as P

ROM = Path("/home/ehm_eckx/gBox_alt/gbox-cache/b74d223b195befba/rom.z64")


def make_slot(boots=0, partners=0):
    s = bytearray(P.SAVE_SIZE)
    s[:16] = P.MAGIC
    s[P.PLAYER + P.BOOTS] = boots
    s[P.PLAYER + P.PARTNERS + 8] = 1 if partners else 0
    P.seal(s)
    return bytes(s)


def flash_with(slot_idx=0, slot=None):
    f = bytearray(P.FLASH_SIZE)
    f[slot_idx * P.SLOT_STRIDE: slot_idx * P.SLOT_STRIDE + P.SAVE_SIZE] = slot or make_slot()
    return bytes(f)


def test_checksum_roundtrip_and_tamper():
    s = make_slot()
    assert P.slot_valid(s)
    bad = bytearray(s); bad[0x100] ^= 1
    assert not P.slot_valid(bytes(bad))


def test_unlock_sets_roster_and_resigns():
    s = P.unlock_save(make_slot(boots=1))
    assert P.slot_valid(s)
    for pid in range(1, 12):
        assert s[P.PLAYER + P.PARTNERS + pid * 8] == 1
    assert s[P.PLAYER + P.BOOTS] == 2 and s[P.PLAYER + P.HAMMER] == 2


def test_monotonic_never_lowers():
    s = bytearray(make_slot()); s[P.PLAYER + P.MAX_STAR_POWER] = 9; P.seal(s)
    assert P.unlock_save(bytes(s))[P.PLAYER + P.MAX_STAR_POWER] == 9


def test_story_flags_untouched():
    s = bytearray(make_slot()); s[0xFB0:0xFB8] = b"\xaa" * 8; P.seal(s)
    assert P.unlock_save(bytes(s))[0xFB0:0x10B0] == bytes(s)[0xFB0:0x10B0]


def test_invalid_slot_rejected_and_skipped():
    with pytest.raises(ValueError):
        P.unlock_save(bytes(P.SAVE_SIZE))
    new, changed = P.unlock_flash(bytes(P.FLASH_SIZE))
    assert changed == [] and new == bytes(P.FLASH_SIZE)


def test_flash_unlock_only_valid_slot():
    new, changed = P.unlock_flash(flash_with(2))
    assert changed == [2] and P.slot_valid(new[2 * P.SLOT_STRIDE:2 * P.SLOT_STRIDE + P.SAVE_SIZE])


def test_apply_backup_and_rollback(tmp_path):
    if not ROM.exists():
        pytest.skip("owned ROM absent")
    fl = tmp_path / "pm.fla"; orig = flash_with(0); fl.write_bytes(orig)
    r = P.apply(fl, ROM, tmp_path / "bak")
    assert r["applied"] and fl.read_bytes() != orig
    P.rollback(fl, Path(r["backup"]))
    assert fl.read_bytes() == orig


def test_apply_refuses_wrong_rom(tmp_path):
    rom = tmp_path / "x.z64"; rom.write_bytes(b"nope")
    fl = tmp_path / "pm.fla"; fl.write_bytes(flash_with(0))
    r = P.apply(fl, rom, tmp_path / "bak")
    assert r["state"] == "refused" and not r["applied"]


def test_rom_guard_owned_rom():
    if not ROM.exists():
        pytest.skip("owned ROM absent")
    assert P.rom_guard(ROM)["ok"]


def test_profile_honest():
    p = P.profile()
    assert not p["verified"] and not p["gameplay_verified"]
    assert set(p["scope"]) == {"characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras"}
