import struct, pathlib, pytest
from gbox import warzone_boot as wb

ROM = next((p for p in (pathlib.Path.home()/"gBox_alt/gbox-cache/warzone/rom.z64",
                        pathlib.Path.home()/"gbox-cache/warzone/rom.z64") if p.exists()), None)

def test_boot_header_synthetic():
    rom = bytearray(0x2000)
    rom[0x1010:0x1010+44] = struct.pack(">11I", 0xB0B8E9E0, 0xB0BF5031, 0x8003C400,
        0x800E4050, 1, 0x80169C30, 0x8012A1C0, 0x801A43E0, 0, 0, 0)
    h = wb.boot_header(bytes(rom))
    assert h["rom_start"] == 0xB8E9E0 and h["rom_end"] == 0xBF5031
    assert h["dest"] == 0x8003C400 and h["entry"] == 0x800E4050 and h["compressed"] == 1

def test_roster_synthetic():
    dest = 0x8003C400
    img = bytearray(0x200000)
    o = wb.ROSTER_BASE - dest
    img[o:o+14] = b"SHAWN".ljust(14, b"\0"); img[o+14:o+28] = b"MICHAELS".ljust(14, b"\0")
    img[o+28:o+44] = b"HEARTBREAK KID".ljust(16, b"\0")
    r = wb.roster(bytes(img), dest, 3)
    assert r == [{"slot": 0, "vaddr": wb.ROSTER_BASE, "first": "SHAWN", "last": "MICHAELS", "nick": "HEARTBREAK KID"}]

@pytest.mark.skipif(ROM is None, reason="owned ROM not staged")
def test_decompress_owned_build():
    pytest.importorskip("unicorn")
    p = wb.probe(ROM.read_bytes())
    assert p["header"]["entry"] == "0x800e4050"
    assert p["image_len"] == 0xEDDBC
    names = {(r["first"], r["last"]) for r in p["roster"]}
    assert ("SHAWN", "MICHAELS") in names and ("BRET", "HART") in names
