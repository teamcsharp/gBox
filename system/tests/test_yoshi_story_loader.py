import os, pathlib, pytest
from gbox import yoshi_story_loader as L

ROM = next((p for p in (pathlib.Path(os.path.expanduser("~/gbox-cache/n64-rom/96936e14621977e429f2b074.z64")),) if p.exists()), None)


def test_descriptor_fields():
    assert L.descriptor_fields(0x00001234) == (0, 0x1234)
    assert L.descriptor_fields(0x0C000010) == (3, 0x10)
    assert L.descriptor_fields(0x08000010) == (2, 0x10)


def test_vram_to_rom():
    assert L.vram_to_rom(0x80000470) == 0x1070
    assert L.vram_to_rom(0x800B4E90) == 0xB5A90
    with pytest.raises(ValueError):
        L.vram_to_rom(0x70000000)


@pytest.mark.skipif(ROM is None, reason="owned ROM not on host")
def test_owned_rom_loader_facts():
    import hashlib
    rom = ROM.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == L.Z64_SHA256
    assert L.word(rom, L.vram_to_rom(L.SLOT_LOADER)) == 0x27BDFF98  # addiu sp,sp,-0x68
    assert L.jal_callers(rom, L.SLOT_LOADER) == [0x800071A8, 0x80008978]
    assert L.jal_callers(rom, L.RELOCATOR) == [0x80008C98]
    t = L.unkbin_offset_table(rom)
    assert t[:4] == [0x3C40, 0x3C60, 0x3C80, 0x3CC0] and len(t) == 122
