"""gbox.sm64_inventory: level-script scan on synthetic bytes, plus the owned EU build when its cache is present."""
import os
import struct
from pathlib import Path

import pytest

from gbox import sm64_inventory as I

EU = Path(os.environ.get("GBOX_SM64_EU_ROM", Path.home() / "gbox-cache/66062703301f4969/source.zip"))


def _mio0_literal(payload: bytes) -> bytes:
    """A MIO0 stream that stores every byte literally (all flag bits set)."""
    nwords = (len(payload) + 31) // 32
    flags = b"\xff\xff\xff\xff" * nwords
    comp = 16 + len(flags)
    return b"MIO0" + struct.pack(">III", len(payload), comp, comp) + flags + payload


def _image():
    rom = bytearray(0x4000)
    geo = bytes([0x20, 0, 0, 0x64, 0x01, 0, 0, 0])                       # CULLING_RADIUS, END
    blob = _mio0_literal(b"\0" * 0x40 + geo)
    rom[0x1000:0x1000 + len(blob)] = blob
    script = bytearray()
    script += bytes([0x18, 0x0C, 0, 0x05]) + struct.pack(">II", 0x1000, 0x1000 + len(blob))   # LOAD_MIO0 seg 5
    script += bytes([0x17, 0x0C, 0, 0x0C]) + struct.pack(">II", 0x2000, 0x2100)               # LOAD_RAW seg C
    script += bytes([0x22, 0x08]) + struct.pack(">HI", 0x00C3, 0x0C000000)                     # bobomb buddy
    script += bytes([0x22, 0x08]) + struct.pack(">HI", 0x0001, 0x0C000004)                     # Mario -> END
    script += bytes([0x02, 0x04, 0, 0])                                                         # EXIT
    rom[0x3000:0x3000 + len(script)] = script
    rom[0x2000:0x2008] = geo
    return bytes(rom), blob


def test_level_loads_and_containers():
    rom, blob = _image()
    loads = I.level_loads(rom)
    assert [(l["kind"], l["seg"], l["start"]) for l in loads] == [("mio0", 5, 0x1000), ("raw", 0x0C, 0x2000)]
    cs = I.containers(rom, loads)
    assert cs[0]["decoded"] == 0x48 and cs[0]["segments"] == ["0x5"] and cs[1]["kind"] == "raw"


def test_load_without_mio0_magic_or_sane_successor_is_rejected():
    rom = bytearray(_image()[0])
    rom[0x1000:0x1004] = b"XXXX"
    assert [l["kind"] for l in I.level_loads(bytes(rom))] == ["raw"]
    rom = bytearray(_image()[0])
    rom[0x3018] = 0xFF                                                   # garbage after LOAD_RAW
    assert [l["kind"] for l in I.level_loads(bytes(rom))] == ["mio0"]


def test_execute_loads_level_segment():
    rom = bytearray(0x2000)
    rom[0x100:0x110] = bytes([0x00, 0x10, 0, 0x0E]) + struct.pack(">III", 0x1000, 0x1800, 0x0E000010)
    rom[0x110:0x114] = bytes([0x02, 0x04, 0, 0])
    assert [(l["seg"], l["start"]) for l in I.level_loads(bytes(rom))] == [(0x0E, 0x1000)]
    rom[0x10C:0x110] = struct.pack(">I", 0x0D000010)                   # entry outside its own segment
    assert I.level_loads(bytes(rom)) == []


def test_models_resolve_to_named_geo():
    rom, _ = _image()
    loads = I.level_loads(rom)
    ms = I.resolve_models(rom, loads, I.model_loads(rom))
    assert [(m["model"], m["container"]) for m in ms] == [(0xC3, "0x2000"), (1, "0x2000")]
    rom = bytearray(rom)
    rom[0x2000] = 0xFF                                                   # not a geo opcode -> unresolved
    assert I.resolve_models(bytes(rom), loads, I.model_loads(bytes(rom)))[0]["container"] is None
    assert I.named_models(ms) == {"bobomb_buddy": ["0xc000000"], "mario": ["0xc000004"]}


@pytest.mark.skipif(not EU.exists(), reason="owned SM64 EU source not cached")
def test_owned_eu_build():
    m = I.inventory(EU)
    rom = m["rom"]
    assert rom["sha1"] == "4ac5721683d0e0b6bbb561b58a71740845dceea9" and rom["game_code"] == "NSMP"
    assert rom["sha256"] == "c792e5ebcba34c8d98c0c44cf29747c8ee67e7b907fcc77887f9ff2523f80572"
    assert rom["cic"] == "6102" and rom["known"]["region"] == "EU" and m["launch"]["video"] == "PAL 50 Hz"
    assert m["writer_compatible"] and m["mario_model_loads"] == ["0x28cf20"]
    lay = m["layout"]
    seg04 = next(c for c in lay["containers"] if c["start"] == "0xf5330")
    assert seg04["decoded"] == 217976 and seg04["segments"] == ["0x4"]
    assert lay["named_models"]["mario"] == ["0x17002dd4"] and lay["named_models"]["marios_cap"] == ["0x16000ca4"]
    assert lay["model_loads_resolved"] >= 480
    mario = m["characters"]["mario"]
    assert (mario["joints"], mario["triangles"], mario["animations"]) == (20, 752, 209)
    assert len(mario["textures"]) == 5
