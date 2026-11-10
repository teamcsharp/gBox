"""The small-data bases: read from the init code, then used to enumerate the game's r13-relative globals."""
import struct

import pytest

from gbox import pso_sda as S


def test_the_two_bases_are_the_ones_the_init_code_sets():
    assert S.SDA_BASE == 0x805CA600 and S.SDA2_BASE == 0x805CFD00
    assert S.INIT_SECTION_CODE == 0x8000C180


def test_a_displacement_resolves_within_the_small_data_window():
    assert S.sda_address(-0x5260) == 0x805CA600 - 0x5260 == 0x805C53A0
    assert S.sda_address(0x7FFF) == 0x805CA600 + 0x7FFF
    assert S.sda_address(-0x8000) == 0x805CA600 - 0x8000
    # the class-name table at 0x805d3138 is *outside* the window: that is why no direct code reference exists
    with pytest.raises(ValueError):
        S.sda_address(0x8B38)


def _synthetic_dol():
    """One text section with three r13 accesses and one non-r13 access."""
    words = [
        0x3C60805C,       # lis r3, 0x805c            (not an r13 access; must be ignored)
        0x80A3FFE0,       # lwz r5, -0x20(r3)
        0x90CD0000 | ((-0x10) & 0xFFFF),   # stw r6, -0x10(r13)
        0x806D0000 | (0x20 & 0xFFFF),      # lwz r3, 0x20(r13)
        0x38600001,       # li r3, 1
    ]
    section_va, section_off, section_size = 0x80010000, 0x100, 0x40
    header = bytearray(0x100)
    struct.pack_into(">I", header, 0x00, section_off)
    struct.pack_into(">I", header, 0x48, section_va)
    struct.pack_into(">I", header, 0x90, section_size)
    body = b"".join(struct.pack(">I", w & 0xFFFFFFFF) for w in words)
    return bytes(header) + body + bytes(section_size - len(body))


def test_every_d_form_access_through_r13_is_recorded():
    found = S.globals_used(_synthetic_dol())
    assert set(found) == {S.sda_address(-0x10), S.sda_address(0x20)}
    assert found[S.sda_address(-0x10)] == [0x80010008]
    assert found[S.sda_address(0x20)] == [0x8001000C]


def test_the_known_globals_get_their_names(monkeypatch):
    rows = S.candidates(_synthetic_dol(), known={S.sda_address(0x20): "floor"})
    by_name = {row["name"]: row for row in rows if row["name"]}
    assert by_name["floor"]["address"] == S.sda_address(0x20)
    assert all(row["uses"] >= 1 for row in rows)


def test_the_real_disc_has_thousands_of_small_data_globals():
    import pathlib
    from gbox import gcdisc
    disc = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                        r"\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    dol = gcdisc.GCDisc(str(disc)).read("PsoV3.dol")
    found = S.globals_used(dol)
    assert len(found) > 1000
    lo, hi = S.SDA_BASE - 0x8000, S.SDA_BASE + 0x7FFF
    assert all(lo <= addr <= hi for addr in found)
    # FLOOR (pso_ram) lives above the window, so it cannot appear here - the reason for this whole module
    from gbox import pso_ram
    assert pso_ram.FLOOR not in found
