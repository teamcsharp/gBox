"""gbox.snes65816: opcode table + KI SNES palette-loader probe on the owned build."""
import pytest
from gbox import snes65816 as S
import zipfile
from pathlib import Path
import os

_STEM = 'Killer Instinct (USA) (Rev 1)'
OWNED = next((Path(c) for c in [os.environ.get('GBOX_KINST_SNES_SFC'), os.environ.get('GBOX_KINST_SNES_ZIP'),
    str(Path(__file__).resolve().parent.parent.parent / 'rom' / (_STEM + '.sfc')),
    str(Path(__file__).resolve().parent.parent.parent / 'rom' / (_STEM + '.zip'))] if c and Path(c).exists()), None)


def _rom():
    if OWNED is None:
        pytest.skip("owned KI SNES build not present")
    if OWNED.suffix == ".zip":
        z = zipfile.ZipFile(OWNED)
        return z.read([n for n in z.namelist() if n.endswith(".sfc")][0])
    return OWNED.read_bytes()


def test_opcode_table_complete_and_sizes():
    assert len(S.OPS) == 256
    i = S.disasm_one(bytes([0xA9, 0x34, 0x12]) + bytes(0x10000), 0xC0, 0, True, True)
    assert (i["name"], i["size"]) == ("LDA", 3)
    i = S.disasm_one(bytes([0xA9, 0x34, 0x12]) + bytes(0x10000), 0xC0, 0, False, True)
    assert i["size"] == 2


def test_reset_vector_and_trace():
    rom = _rom()
    assert S.reset_vector(rom) == 0x8452
    seen, calls = S.trace(rom, 0xC0, 0x8452)
    assert len(seen) > 1500 and (0x83, 0xDBF2) in calls


def test_palette_loads_are_raw_bgr555():
    rom = _rom()
    loads = S.palette_loads(rom)
    assert len(loads) >= 3
    assert all(l["raw_ok"] for l in loads)
    assert any(l["src"] == 0x3450 for l in loads)
    assert all(l["src"] < 0x10000 for l in loads)   # bank $C0 only


def test_c4_0000_is_apu_block_table_not_graphics():
    rom = _rom()
    t = S.spc_block_table(rom)
    assert t[0] == 0xC467A9 and all(0xC40000 <= v < 0xC50000 for v in t[:16])
