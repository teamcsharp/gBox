"""#1988 analysis probe: OoT Master Quest (Europe) GameCube Edition (gc-eu-mq) loader/table addresses re-derived from the
owned ROM by gbox.oot_analysis (hi/lo pair xrefs in `code`, dma 28). Skips when the owned source is not staged."""
from pathlib import Path

import pytest

from gbox import n64_rom, oot_analysis as A, oot_writer as OW

OWNED = Path.home() / "gbox-cache/ff72441b33ff806b/source.zip"
pytestmark = pytest.mark.skipif(not OWNED.exists(), reason="owned MQ source not staged")


@pytest.fixture(scope="module")
def rep():
    rom = OW.Rom(n64_rom.read(str(OWNED)))
    return rom, A.analysis(rom)


def test_tables_are_referenced_from_code(rep):
    rom, r = rep
    assert r["version"] == "gc-eu-mq" and r["code"]["dma"] == 28
    assert r["gObjectTable"]["vram"] == r["code"]["vram"] + 0xE4F58
    assert r["gActorOverlayTable"]["vram"] == r["code"]["vram"] + 0xD4480
    assert len(r["gObjectTable"]["refs"]) == 6 and len(r["gActorOverlayTable"]["refs"]) == 2


def test_player_overlay_row_matches_dma34(rep):
    rom, r = rep
    p = r["ovl_player_actor"]
    assert p["dma"] == 34 and tuple(p["vrom"]) == (12291632, 12449088)
    assert p["vram"][1] - p["vram"][0] == p["vrom"][1] - p["vrom"][0] + p["bss"]  # vram span = file + bss
    assert set(r["player_entry_points"]) == {"Player_Init", "Player_Destroy", "Player_Update", "Player_Draw"}
    for e in r["player_entry_points"].values():
        assert p["vram"][0] <= e["vram"] < p["vram"][1]


def test_link_skeletons_match_inventory(rep):
    _rom, r = rep
    a, c = r["link_skeletons"]["adult"], r["link_skeletons"]["child"]
    assert (a["object"], a["header"], a["limbs"], a["lod"]) == (0x14, 0x377F4, 21, True)
    assert (c["object"], c["header"], c["limbs"]) == (0x15, 0x2CF6C, 21)
