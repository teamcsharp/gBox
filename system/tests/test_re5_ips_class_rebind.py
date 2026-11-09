"""The IPS32 class-rebind patch: exact bytes, no-op control and an apply round-trip."""
import struct

from gbox.re5_ips import OFFSET, ORIGINAL, REBIND, apply_patch, assert_original, make_ips


def test_ips_records_the_uem11_to_uem10_immediate():
    ips = make_ips()
    assert ips[:5] == b"IPS32"
    assert ips[-4:] == b"EEOF"
    off, size = struct.unpack_from(">IH", ips, 5)
    assert off == OFFSET == 0x4F824
    assert size == 4
    assert ips[11:15] == struct.pack("<I", REBIND)
    assert struct.unpack("<I", ips[11:15])[0] == 0x110C0284


def test_a_noop_ips_writes_the_original_bytes_back():
    ips = make_ips(noop=True)
    assert ips[11:15] == struct.pack("<I", ORIGINAL)
    assert struct.unpack("<I", ips[11:15])[0] == 0x11100284


def test_apply_patch_changes_only_the_four_immediate_bytes():
    blob = bytearray(b"\xaa" * 0x500000)
    struct.pack_into("<I", blob, OFFSET, ORIGINAL)
    assert_original(bytes(blob))
    out = apply_patch(blob)
    assert bytes(out[:OFFSET]) == b"\xaa" * OFFSET
    assert struct.unpack_from("<I", out, OFFSET)[0] == REBIND
    assert bytes(out[OFFSET + 4:]) == b"\xaa" * (len(out) - OFFSET - 4)
