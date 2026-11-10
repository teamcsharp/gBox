import pathlib
import pytest
from gbox import warzone_assets as wa
from gbox import warzone_boot as wb

ROM = next((p for p in (pathlib.Path.home()/"gBox_alt/gbox-cache/warzone/rom.z64",
                        pathlib.Path.home()/"gbox-cache/warzone/rom.z64") if p.exists()), None)


def test_handle_fields():
    f = wa.handle_fields(0x116E0000)
    assert f == {"type": 2, "index": 0x16E, "sub": 0}


@pytest.mark.skipif(ROM is None, reason="owned ROM not staged")
def test_type2_table_on_owned_build():
    pytest.importorskip("unicorn")
    rom = ROM.read_bytes()
    img, _ = wb.decompress_main(rom)
    t = wa.parse_type2_table(img)
    assert len(t) == 27
    assert t[0]["handle"] == 0x116E0000 and t[0]["rom_offset"] == 0xB73D6C and t[0]["size"] == 0x7DF0
    assert t[-1]["rom_offset"] == 0x1990 and t[-1]["size"] == 0xC448
    assert t[-1]["handle"] == 0x11180000 and t[-2]["handle"] == 0x11870000
    assert all(e["type"] == 2 for e in t)
    assert len({e["handle"] for e in t}) == 27
    assert wa.read_entry(rom, t[0]).startswith(b"CLIMBTHRUROPES")
    assert all(e["rom_offset"] + e["size"] <= len(rom) for e in t)
