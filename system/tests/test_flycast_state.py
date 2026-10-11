import struct
import zlib

import pytest

from gbox import flycast_state as fs


def _vmu():
    flash = bytearray(128 * 1024)
    flash[0xFF * 512:0xFF * 512 + 16] = b"\x55" * 16
    return bytes(flash) + bytes(192 + 48 * 32)


def _port(pn):
    return (b"\x00" + bytes([pn]) + b"\x01" + bytes([pn]) + _vmu() + b"\x03" + bytes([pn]) + bytes(8)
            + b"\x0a" * 3)


def _state(pending=0, dma=(), pvr_sof1=0x57A000, ports=(0, 1, 2, 3)):
    out = bytearray(struct.pack("<i", fs.FLYCAST_V59)) + bytes(4096)
    out += bytes([pending, 0]) + struct.pack("<I", len(dma))
    for addr, words in dma:
        out += struct.pack("<II", addr, len(words)) + b"".join(struct.pack("<I", w) for w in words)
    for pn in ports:
        out += _port(pn)
    regs = bytearray(0x8000)
    regs[0:8] = fs.HOLLY_ID
    struct.pack_into("<I", regs, 0x60, pvr_sof1)
    struct.pack_into("<I", regs, 0x50, 0x57A000)
    out += bytes(64) + regs
    return bytes(out)


def test_unpack_rzip_rastate_roundtrip():
    mem = _state()
    ra = b"RASTATE\x01" + b"MEM " + struct.pack("<I", len(mem)) + mem + bytes((-len(mem)) % 8) + b"END " + bytes(4)
    comp = zlib.compress(ra)
    rz = b"#RZIPv\x01#" + struct.pack("<IQ", 131072, len(ra)) + struct.pack("<I", len(comp)) + comp
    assert fs.unpack(rz) == mem
    assert fs.version(fs.unpack(rz)) == 854


def test_maple_table_decoded_exactly():
    m = fs.maple_devices(_state())
    assert m["pending_reset"] is False and m["dma_out"] == []
    assert [d["type"] for d in m["ports"][0] if d] == ["SegaController", "SegaVMU", "PurupuruPack"]
    assert m["ports"][3][0]["player_num"] == 3
    assert m["ports"][0][3:] == [None, None, None]


def test_maple_header_with_pending_dma():
    m = fs.maple_devices(_state(pending=1, dma=[(0x0C001000, [1, 2, 3])]))
    assert m["pending_reset"] is True
    assert m["dma_out"] == [(0x0C001000, 3)]


def test_compare_maple_detects_topology_change():
    assert fs.compare_maple(_state(), _state())["same"]
    assert not fs.compare_maple(_state(), _state(ports=(0, 0, 1, 2)))["same"]


def test_pvr_rtt_flag():
    assert fs.pvr_framebuffer(_state())["last_render_is_rtt"] is False
    p = fs.pvr_framebuffer(_state(pvr_sof1=0x1000000 | 0x200000))
    assert p["last_render_is_rtt"] is True and p["FB_R_SOF1"] == 0x57A000


def test_rejects_container_without_mem():
    with pytest.raises(ValueError):
        fs.unpack(b"RASTATE\x01END " + bytes(4))
