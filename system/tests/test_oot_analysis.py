"""#1325 analysis probe: OoT USA Rev B (ntsc-1.2) Link draw path, DL tables and object loaders, re-derived from the
owned ROM and pinned against the Ghidra project ~/gBox_alt/gbox-cache/1aa2e4bb5797493f/ghidra/oot12.gpr (out/xrefs.txt)."""
import struct
from pathlib import Path

import pytest

from gbox import oot_analysis as A

OWNED = Path.home() / "gBox_alt/gbox-cache/1aa2e4bb5797493f/source.zip"


def _mips(*ws) -> bytes:
    return struct.pack(f">{len(ws)}I", *ws)


def test_hilo_refs_pairs_lui_with_addiu_and_loads():
    data = _mips(0x3C04800F,             # lui a0, 0x800F
                 0x00000000,
                 0x24848060,             # addiu a0, a0, -0x7FA0 -> 0x800F8060... (0x800F0000 + 0x8060 sign-extended)
                 0x3C05800F,             # lui a1, 0x800F
                 0x8CA57F28,             # lw a1, 0x7F28(a1) -> 0x800F7F28
                 0x3C05800E,             # lui a1 again ends the first a1 search
                 0x24A50000)             # addiu a1, a1, 0 -> 0x800E0000
    refs = A.hilo_refs(data, 0x80000000, 0x80000000, 0x80800000)
    assert refs == [(0x80000008, 0x800E8060), (0x80000010, 0x800F7F28), (0x80000018, 0x800E0000)]


def test_func_bounds_and_calls_follow_jr_ra():
    data = _mips(0x03E00008, 0, 0, 0,                    # previous function's jr ra + delay, nop padding
                 0x27BDFFE8, 0x0C000010, 0, 0x03E00008, 0x27BD0018)
    assert A.func_bounds(data, 0x80000000, 0x80000014) == (0x80000010, 0x80000024)
    assert A.calls_in(data, 0x80000000, 0x80000010, 0x80000024) == [0x80000040]


@pytest.fixture(scope="module")
def rom():
    if not OWNED.exists():
        pytest.skip("owned OoT USA Rev B zip not cached")
    from gbox import n64_rom, oot_writer as OW
    r = OW.Rom(n64_rom.read(OWNED))
    assert r.version == "ntsc-1.2"
    return r


def test_player_overlay_and_entry_points(rom):
    kt = A.kaleido_table(rom)
    assert kt["player"]["row"] == 0x800FEAEC and kt["player"]["vram"] == (0x808301C0, 0x80856900)
    assert kt["player"]["vrom"] == tuple(rom.dma[34][:2])
    ep = A.player_entry_points(rom)
    assert {n: e["vram"] for n, e in ep.items()} == {"Player_Init": 0x80844E6C, "Player_Destroy": 0x80848C38,
                                                     "Player_Update": 0x8084804C, "Player_Draw": 0x80848704}


def test_draw_chain_reaches_skelanime_flex_lod(rom):
    dc = A.draw_chain(rom)
    assert dc["Player_DrawGameplay"]["vram"] == 0x80848284
    assert (dc["Player_DrawImpl"]["vram"], dc["Player_DrawImpl"]["end"]) == (0x8007A5D8, 0x8007A984)
    assert dc["SkelAnime_DrawFlexLod"] == 0x80089AF4 and dc["sDListsLodOffset"] == 0x8011C5F4


def test_dlist_groups_name_every_writer_hand_table(rom):
    g = A.dlist_groups(rom)
    assert g["vram"] == 0x800F8060
    assert {A.func_bounds(rom.file(27), 0x800116E0, r)[0] for r in g["refs"]} == {0x80079B8C, 0x80079C78}
    names = {e[0]: e[2] for e in g["entries"]}
    assert names["RH_SHIELD"] == "sPlayerRightHandShieldDLs" and names["RH_CLOSED"] == "sPlayerRightHandClosedDLs"
    assert g["waist_ptrs"] == [0x800F80B0]


def test_writer_patch_sites_hold_the_original_object_words(rom):
    from gbox.oot_swap import LINK_ARRAYS
    sites = A.patch_sites(rom)
    assert len(sites) == 95 and sum(s["age"] == "adult" for s in sites) == 49
    for s in sites:
        assert s["word"] == 0x06000000 | LINK_ARRAYS[s["table"]][1][s["index"]]
    # every patched table is reachable by the game: through sPlayerDListGroups, the waist pointer, or a direct ref
    g = A.dlist_groups(rom)
    reached = {e[1] for e in g["entries"]} | {0x800F7FB8}
    fp = A.analysis(rom)["first_person_refs"]
    assert all(fp[n] for n in A.FIRST_PERSON)
    pos = A.table_positions(rom)
    reached |= {pos[n][0] for n in A.FIRST_PERSON}
    tables = {s["vram"] - 4 * s["index"] for s in sites}
    assert tables <= reached | {0x800F7E08}                # shield table (16 entries) starts with the closed hand


def test_link_skeletons_and_object_loaders(rom):
    sk = A.link_skeletons(rom)
    for age, hdr in (("adult", 0x377F4), ("child", 0x2CF6C)):
        s = sk[age]
        assert (s["header"], s["limbs"], s["lod"], s["dlcount"], s["drawn"]) == (hdr, 21, True, 18, 18)
        assert all(d == 0 or d >> 24 == 6 and (d & 0xFFFFFF) < s["size"] for ds in s["dls"] for d in ds)
    ol = A.object_loaders(rom)
    assert set(ol) == {0x8007C72C, 0x80081920, 0x80081B60, 0x80081CE8, 0x80081D70, 0x80838F78}
    assert 0x80000F80 in ol[0x80081920]["calls"]          # Object_SpawnPersistent: synchronous DMA
    assert 0x80000EB8 in ol[0x80081B60]["calls"]          # Object_UpdateEntries: asynchronous DMA
