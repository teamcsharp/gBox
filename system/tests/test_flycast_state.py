"""Offline save-state diagnostics: source-aligned topology and hostile boundaries."""
import struct
import zlib

import pytest

from gbox import flycast_state as fs


def _vmu():
    flash = bytearray(128 * 1024)
    flash[0xFF * 512:0xFF * 512 + 16] = b"\x55" * 16
    return bytes(flash) + bytes(192 + 48 * 32)


def _port(pn, *, microphone=False, no_vmu=False):
    # mcfg_Create places expansion devices at 0/1 and the main controller at 5.
    first = b"\x0a" if no_vmu else b"\x01" + bytes([pn]) + _vmu()
    second = (b"\x02" + bytes([pn]) + struct.pack("<I??", 15, True, False)
              if microphone else b"\x03" + bytes([pn]) + bytes(8))
    return first + second + b"\x0a" * 3 + b"\x00" + bytes([pn])


def _state(pending=0, dma=(), pvr_sof1=0x57A000, ports=(0, 1, 2, 3),
           *, microphone=False, no_vmu=False, v=fs.FLYCAST_V59, prefix=None):
    out = bytearray(struct.pack("<i", v)) + (bytes(4096) if prefix is None else prefix)
    header_offset = len(out)
    out += bytes([pending, 0]) + struct.pack("<I", len(dma))
    for addr, words in dma:
        out += struct.pack("<II", addr, len(words)) + b"".join(struct.pack("<I", w) for w in words)
    for pn in ports:
        out += _port(pn, microphone=microphone, no_vmu=no_vmu)
    regs = bytearray(fs.PVR_REG_BYTES)
    regs[:8] = fs.HOLLY_ID
    struct.pack_into("<I", regs, 0x60, pvr_sof1)
    struct.pack_into("<I", regs, 0x50, 0x57A000)
    out += bytes(fs.YUV_SERIALIZED_BYTES) + regs
    return bytes(out), header_offset


def _ra(mem, extra=()):
    def block(tag, value):
        return tag + struct.pack("<I", len(value)) + value + bytes((-len(value)) % 8)
    return (b"RASTATE\x01" + b"".join(block(tag, value) for tag, value in extra)
            + block(b"MEM ", mem) + b"END " + bytes(4))


def _rz(data, chunk_size=131072, *, codec=1, compress=zlib.compress):
    chunks = [compress(data[i:i + chunk_size]) for i in range(0, len(data), chunk_size)]
    return (b"#RZIPv" + bytes([codec]) + b"#" + struct.pack("<IQ", chunk_size, len(data))
            + b"".join(struct.pack("<I", len(c)) + c for c in chunks))


def test_unpack_multiple_rzip_chunks_rastate_blocks_and_raw():
    mem, _ = _state()
    assert fs.unpack(_rz(_ra(mem, [(b"RPLY", b"12345")]))) == mem
    assert fs.unpack(mem) == mem
    assert fs.version(mem) == 854


def test_maple_source_slot_order_and_exact_serializer_endpoint():
    mem, offset = _state()
    m = fs.maple_devices(mem)
    assert m["offset"] == offset and m["table_offset"] == offset + 6
    assert m["end"] + 540 == fs.pvr_framebuffer(mem)["offset"]
    assert m["pending_reset"] is False and m["dma_out"] == []
    assert [d["type"] if d else None for d in m["ports"][0]] == [
        "SegaVMU", "PurupuruPack", None, None, None, "SegaController"]
    assert [port[5]["player_num"] for port in m["ports"]] == [0, 1, 2, 3]


def test_maple_header_with_pending_dma_and_microphone_u32_gain():
    mem, offset = _state(pending=1, dma=[(0x0C001000, [1, 2, 3])], microphone=True)
    m = fs.maple_devices(mem)
    assert m["offset"] == offset and m["pending_reset"] is True
    assert m["dma_out"] == [(0x0C001000, 3)]
    assert all(port[1]["type"] == "Microphone" for port in m["ports"])
    assert [port[5]["player_num"] for port in m["ports"]] == [0, 1, 2, 3]


def test_compare_maple_detects_actual_controller_topology_change():
    original, _ = _state()
    changed, _ = _state(ports=(0, 0, 1, 2))
    assert fs.compare_maple(original, original)["same"]
    assert not fs.compare_maple(original, changed)["same"]


def test_vmu_free_topology_requires_explicit_serializer_offset():
    mem, offset = _state(no_vmu=True)
    with pytest.raises(ValueError, match="validated Maple"):
        fs.maple_devices(mem)
    assert fs.maple_devices(mem, offset=offset)["ports"][3][5]["player_num"] == 3


def test_false_earlier_vmu_anchor_is_skipped():
    # A full VMU-looking payload elsewhere must not override the real endpoint.
    decoy = b"\x00\x00\x00\x00\x00\x00\x01\x00" + _vmu() + bytes(32)
    mem, offset = _state(prefix=decoy)
    assert fs.maple_devices(mem)["offset"] == offset


def test_excessive_overlapping_vmu_patterns_are_bounded():
    mem, _ = _state(prefix=b"\x55" * 512)
    with pytest.raises(ValueError, match="scan exceeds inspection budget"):
        fs.maple_devices(mem)


def test_ambiguous_maple_header_is_rejected_instead_of_first_match():
    # Both headers validly end at the same table. One queues a one-word DMA;
    # the second (12 bytes later) queues no DMA. Scanning must not select one.
    prefix = bytes(4096) + b"\x00\x00\x01\x00\x00\x00" + bytes(4) + b"\x01\x00"
    mem, _ = _state(prefix=prefix)
    with pytest.raises(ValueError, match="found 2"):
        fs.maple_devices(mem)


@pytest.mark.parametrize("v", [841, 855, -1])
def test_maple_rejects_unverified_serializer_versions(v):
    mem, _ = _state(v=v)
    with pytest.raises(ValueError, match="unsupported Maple serializer"):
        fs.maple_devices(mem)


@pytest.mark.parametrize("payload", [b"", b"\x01\x00", b"\x02\x00\x00", b"\x03\x00\x00", b"\x09\x00"])
def test_truncated_or_unsupported_maple_payloads_raise_value_error(payload):
    with pytest.raises(ValueError):
        fs._parse_table(payload, 0)


def test_maple_dma_payload_cannot_skip_past_table_end():
    mem, offset = _state(dma=[(0x0C001000, [1])])
    broken = bytearray(mem)
    struct.pack_into("<I", broken, offset + 10, 0xFFFFFFFF)
    with pytest.raises(ValueError, match="DMA payload"):
        fs.maple_devices(bytes(broken), offset=offset)


def test_pvr_write_rtt_bit_is_register_fact_only():
    mem, _ = _state(pvr_sof1=0x1000000 | 0x200000)
    p = fs.pvr_framebuffer(mem)
    assert p["fb_write_is_rtt"] and p["FB_R_SOF1"] == 0x57A000
    assert "recoverable" not in p


def test_pvr_rejects_incomplete_ambiguous_or_negative_scan():
    mem, _ = _state()
    with pytest.raises(ValueError, match="found 0"):
        fs.pvr_framebuffer(fs.HOLLY_ID + bytes(100))
    with pytest.raises(ValueError, match="found 2"):
        fs.pvr_framebuffer(mem + fs.HOLLY_ID + bytes(fs.PVR_REG_BYTES))
    with pytest.raises(ValueError, match="scan offset"):
        fs.pvr_framebuffer(mem, -1)


@pytest.mark.parametrize("value", [b"", b"\x56", bytes(3)])
def test_version_rejects_short_values(value):
    with pytest.raises(ValueError, match="serializer version"):
        fs.version(value)


@pytest.mark.parametrize("raw", [
    b"#RZIPv", b"#RZIPv\x03#" + bytes(12), b"#RZIPv\x01!" + bytes(12),
    b"#RZIPv\x01#" + struct.pack("<IQ", 0, 1),
    b"#RZIPv\x01#" + struct.pack("<IQ", fs.MAX_RZIP_CHUNK + 1, 1),
    b"#RZIPv\x01#" + struct.pack("<IQ", 32, fs.MAX_STATE_BYTES + 1),
    b"#RZIPv\x01#" + struct.pack("<IQ", 32, 1) + bytes(3),
    b"#RZIPv\x01#" + struct.pack("<IQ", 32, 1) + struct.pack("<I", 999) + b"x",
    b"#RZIPv\x01#" + struct.pack("<IQ", 32, 1) + bytes(4),
])
def test_rzip_header_and_chunk_bounds(raw):
    with pytest.raises(ValueError):
        fs.unpack(raw)


def test_rzip_declared_output_budget_and_trailing_data():
    comp = zlib.compress(bytes(1024 * 1024))
    bomb = b"#RZIPv\x01#" + struct.pack("<IQI", 16, 16, len(comp)) + comp
    with pytest.raises(ValueError, match="oversized"):
        fs.unpack(bomb)
    for bad in (_rz(b"abc")[:-1], _rz(b"abc") + b"extra",
                _rz(b"abc", compress=lambda d: zlib.compress(d) + b"extra")):
        with pytest.raises(ValueError):
            fs.unpack(bad)
    with pytest.raises(ValueError, match="budget"):
        fs.unpack(b"12345", max_bytes=4)


@pytest.mark.parametrize("raw", [
    b"RASTATE", b"RASTATE\x02", b"RASTATE\x01MEM ",
    b"RASTATE\x01MEM " + struct.pack("<I", 99) + b"abc",
    b"RASTATE\x01MEM " + struct.pack("<I", 3) + b"abc",
    b"RASTATE\x01END " + bytes(4),
    _ra(b"abc")[:-8], _ra(b"abc") + b"extra",
    _ra(b"abc", [(b"MEM ", b"second")]),
    b"RASTATE\x01END " + struct.pack("<I", 8) + bytes(8),
])
def test_rastate_rejects_versions_truncated_padding_duplicate_mem_and_bad_end(raw):
    with pytest.raises(ValueError):
        fs.unpack(raw)


def test_zstd_uses_declared_codec_and_bounds_unknown_size_frames():
    zstd = pytest.importorskip("zstandard")
    data = bytes(10000)
    comp = zstd.ZstdCompressor(write_content_size=False).compress
    assert fs.unpack(_rz(data, codec=2, compress=comp)) == data
    # A v2 declaration cannot silently select deflate by inspecting its payload.
    with pytest.raises(ValueError):
        fs.unpack(_rz(data, codec=2))
    packed = comp(data)
    bomb = b"#RZIPv\x02#" + struct.pack("<IQI", 16, 16, len(packed)) + packed
    with pytest.raises(ValueError):
        fs.unpack(bomb)
    known_size = zstd.ZstdCompressor().compress(data)
    with pytest.raises(ValueError, match="oversized"):
        fs.unpack(b"#RZIPv\x02#" + struct.pack("<IQI", 16, 16, len(known_size)) + known_size)
    with pytest.raises(ValueError):
        fs.unpack(_rz(data, codec=2, compress=lambda d: comp(d) + comp(d)))
