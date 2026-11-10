import struct
import pytest
from gbox.mk4_asset_dir import RECORDS_START, DATA_BASE, parse_asset_dir, read_asset
from gbox.mk4_patch_table import DEFAULT_ROM, load_rom


def _rom(recs):
    rom = bytearray(0x140000)
    p = RECORDS_START
    for i, s in recs:
        struct.pack_into(">HH", rom, p, i, s); p += 4
    struct.pack_into(">H", rom, p, 0xFFFF)
    return bytes(rom)


def test_synthetic_offsets_accumulate():
    es = parse_asset_dir(_rom([(0x8000, 0x10), (0x8001, 0x20), (2, 4)]))
    assert [(e.id, e.flag, e.offset, e.size) for e in es] == [
        (0, 1, DATA_BASE, 0x10), (1, 1, DATA_BASE + 0x10, 0x20), (2, 0, DATA_BASE + 0x30, 4)]
    assert len(read_asset(_rom([]), es[0])) == 0x10


def test_unterminated_rejected():
    with pytest.raises(ValueError):
        parse_asset_dir(bytes(0x140000), max_entries=4)


def test_owned_build():
    from pathlib import Path
    if not Path(DEFAULT_ROM).exists():
        pytest.skip("owned ROM not cached")
    es = parse_asset_dir(load_rom())
    assert len(es) == 612 and [e.id for e in es] == list(range(612))
    assert es[0].offset == 0x1333B0
    assert es[-1].offset + es[-1].size == 0x249304
    assert es[-1].offset == 0x248F84 and es[-1].size == 0x380
