"""Focused tests for gbox.sc3_unlock (#2242): state-table overlay, code lines, revision guard, profile registration."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gbox import cheats, game_unlocks, sc3_unlock as s  # noqa: E402

GAME = {"game_id": s.GAME_ID, "platform": "ps2"}
EXE = Path("/home/ehm_eckx/gBox_alt/gbox-cache/.gbox-tiers/conflicts/20261013-081020-47889d/ps2/"
           "afe447a632bd5e6b/inventory/SLUS_212.16")


def nib(buf, i):
    b = buf[i // 2]
    return b >> 4 if i % 2 else b & 15


def test_overlay_is_monotonic_and_only_touches_covered_entries():
    src = bytearray(s.TABLE_BYTES)
    for i in range(s.TABLE_ENTRIES):                      # cycle all legal states 0..6
        src[i // 2] |= (i % 7) << (4 if i % 2 else 0)
    out = s.apply_to_table(bytes(src))
    cov = set(s.covered_entries())
    for i in range(s.TABLE_ENTRIES):
        if i in cov:
            assert nib(out, i) == 6
        else:
            assert nib(out, i) == nib(src, i)
    assert s.apply_to_table(out) == out                     # idempotent


def test_overlay_refuses_illegal_state_and_short_image():
    bad = bytearray(s.TABLE_BYTES)
    bad[0] = 0x0F                                          # state 15 in entry 0
    with pytest.raises(ValueError):
        s.apply_to_table(bytes(bad))
    with pytest.raises(ValueError):
        s.apply_to_table(b"\0" * 10)


def test_ranges_stay_inside_table_and_clamp_overshoot():
    assert max(s.covered_entries()) < s.TABLE_ENTRIES
    assert s.TABLE_ADDR + s.TABLE_BYTES == 0x5045CA < s.POINTER_ADDR   # never touches the 0x5045CC/0x5045D0 variables
    assert not any("509898" in line or "509B38" in line for line in s.code_lines())


def test_code_lines_decode_to_exactly_the_covered_bytes():
    ops, bad = cheats.decode("ps2", "\n".join(s.code_lines()))
    assert not bad
    got = set()
    for kind, addr, data in ops:
        assert kind == "w" and set(data) == {0x66}
        got |= set(range(addr, addr + len(data)))
    want = set()
    for lo, hi in s._merged_bytes():
        want |= set(range(lo, hi))
    assert got == want


def test_candidate_is_unverified_and_not_held_by_post_launch():
    assert s.codes_json()["verified"] is False
    assert game_unlocks.code_profile(GAME) is None          # no profiles/gamedata json: post_launch holds nothing
    held = []
    assert game_unlocks.post_launch("sid", GAME, lambda *a: held.append(a)) is None and not held


def test_inventory_covers_every_category_with_honest_status():
    inv = s.inventory()
    assert set(inv["categories"]) == set(s.CATEGORIES)
    assert all(v["status"] == "unknown" for v in inv["categories"].values())   # nothing claimed before runtime
    assert inv["runtime_verified"] is False and inv["entry_counts"]["characters"] == 44


def test_registered_in_game_unlocks_profile_and_pre_launch():
    prof = game_unlocks.profile_for(GAME)
    assert prof["status"] == "candidate_pending_runtime" and prof["verified"] is False
    assert prof["executable"]["sha256"] == s.EXE_SHA256
    res = game_unlocks.pre_launch(GAME, ctx=None)
    assert res["state"] == "candidate_pending_verification" and res["applied"] is False
    assert game_unlocks.profile_for({"game_id": s.GAME_ID, "platform": "ps3"})["status"] == "unsupported"


def test_revision_guard_rejects_other_files(tmp_path):
    other = tmp_path / "SLUS_212.16"
    other.write_bytes(b"\x7fELF" + b"\0" * 60)
    assert s.verify_executable(other)["ok"] is False


@pytest.mark.skipif(not EXE.is_file(), reason="owned executable not present on this host")
def test_owned_executable_matches_and_traced_accessors_are_present():
    r = s.verify_executable(EXE)
    assert r["ok"], r
    data = EXE.read_bytes()
    import struct
    # .text maps 0x100000 at file offset 0x1000 + ...; locate via the ELF section table.
    shoff = struct.unpack_from("<I", data, 0x20)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", data, 0x2E)
    secs = [struct.unpack_from("<IIIIII", data, shoff + i * shentsize) for i in range(shnum)]
    text = next(x for x in secs if x[3] == 0x100000)
    def word(va):
        return struct.unpack_from("<I", data, text[4] + va - 0x100000)[0]
    assert word(0x1FF048) == 0x00A0302D          # move $a2,$a1 (daddu) (set_state entry)
    assert word(0x1FF04C) >> 16 == 0x2C82 and word(0x1FF04C) & 0xFFFF == 0x0964   # sltiu $v0,$a0,0x964
    assert word(0x1FF0B8) == 0x30820001          # andi $v0,$a0,1 (get_state entry)
