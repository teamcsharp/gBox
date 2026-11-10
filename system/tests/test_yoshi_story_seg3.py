import hashlib, os, pathlib, pytest
from gbox import yoshi_story_seg3 as S

ROM = pathlib.Path(os.path.expanduser("~/gbox-cache/n64-rom/96936e14621977e429f2b074.z64"))


@pytest.mark.skipif(not ROM.exists(), reason="owned ROM not on host")
def test_seg3_layout_owned_rom():
    rom = ROM.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == "e8a63388c38f8f0bea37e9b13a97f0898ac5496e08ca2028afb8db9a866e0ce9"
    L = S.seg3_layout(rom)
    assert L["frames"] == 1180
    assert L["tlut_offsets"] == [0x400]
    assert L["tiles_per_frame"] == {6: 1179, 1: 1}
    assert L["distinct_tile_offsets"] == 101
    assert set(L["tile_offset_mod_0x400"]) == {0, 0x200}
    assert L["min_tile_offset"] == 0x600
    assert L["max_tile_end"] == 62872
