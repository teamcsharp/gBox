"""SmackDown! 2 USA analysis pins and writer-format probe (#1332). Synthetic tests always run; the owned-build checks
skip when the staged EXE / disc image are absent."""
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import sd2_analysis as a
from gbox import yukes_sd as y

EXE = Path.home() / "gbox-cache/sdk_re/sd2/SLUS_012.34"
RAM = Path.home() / "gbox-cache/sdk_re/ghidra_ram.bin"
BIN = Path.home() / "gbox-cache/modbase/276334ad218ffb46/WWF SmackDown! 2 - Know Your Role (USA).bin"


def _tim(bpp: int, clut: tuple | None, rect=(0x300, 0x100, 4, 2)) -> bytes:
    px, py, pw, ph = rect
    out = struct.pack("<II", 0x10, bpp | (8 if clut else 0))
    if clut:
        cx, cy, cw, ch = clut
        out += struct.pack("<IHHHH", 12 + 2 * cw * ch, cx, cy, cw, ch) + np.arange(cw * ch, dtype="<u2").tobytes()
    return out + struct.pack("<IHHHH", 12 + 2 * pw * ph, px, py, pw, ph) + bytes((7 * i) & 0xFF for i in range(2 * pw * ph))


@pytest.mark.parametrize("bpp,clut", [(1, (0, 256, 256, 1)), (0, (0x100, 253, 16, 1)), (2, None)])
def test_tim_roundtrip_with_and_without_clut(bpp, clut):
    raw = _tim(bpp, clut)
    tim = y.tim_parse(raw)
    assert y.tim_build(tim) == raw
    assert y.repaintable(tim) == (bpp == 1)


def test_scan_reads_jal_and_lui_ori_magic():
    words = [0x3C012045, 0x34215042,                  # lui at,0x2045 ; ori at,at,0x5042  -> 'BPE '
             0x0C000000 | (0x800612A0 & 0x3FFFFFF) >> 2,  # jal bpe_decode
             0x3C028001, 0x2442FFF0,                  # lui v0,0x8001 ; addiu v0,v0,-0x10 -> 0x8000fff0
             a.JR_RA, 0]
    text = b"".join(struct.pack("<I", w) for w in words)
    calls, consts = a.scan(text, a.TEXT, a.TEXT + len(text))
    assert calls == {0x800612A0}
    assert {a.BPE, 0x8000FFF0} <= consts


def test_pins_are_consistent():
    for caller, callees in a.XREFS.items():
        assert caller in a.FUNCS and all(c in a.FUNCS or c == 0x80028778 for c in callees)
    for start, (end, _n, _r) in a.FUNCS.items():
        assert a.TEXT <= start < end <= a.TEXT + a.TEXT_SIZE and start % 4 == 0


@pytest.mark.skipif(not EXE.exists(), reason="owned SLUS_012.34 not staged")
def test_pins_hold_on_the_exact_exe():
    exe = EXE.read_bytes()
    rep = a.verify_exe(exe)
    assert rep["exact_build"] and rep["failed"] == []
    assert rep["functions"]["wrestler_part_load"]["calls"]
    if RAM.exists():
        assert a.ram_matches(exe, RAM.read_bytes()) == 1.0


@pytest.mark.skipif(not BIN.exists(), reason="owned disc image not staged")
def test_writer_format_probe_on_the_owned_disc():
    p = a.probe(y.read_files(BIN))
    assert all(not v["unsorted"] and not v["kept_mismatch"] for v in p.values())
    head, legs = p["ED1H.PAC"], p["ED1L.PAC"]
    assert head["item_ids"] == {"0,10": 291, "0,2,3,10": 201}
    assert {legs["kept_tims"][f"bpp0/row{r}/16"] for r in (253, 254, 255)} == {72}
    assert p["ED1B.PAC"]["kept_tims"]["bpp2/noclut"] == 20
