import os
import struct
import zlib

import pytest

from gbox import acv_dcx as D
from gbox import acv_inventory as acv

ISO_PATH = os.environ.get(
    "ACV_ISO",
    "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/"
    "Armored Core V.iso")


def _make(payload: bytes) -> bytes:
    z = zlib.compress(payload, 9)
    return (b"DCX\0" + struct.pack(">5I", 0x10000, 0x18, 0x24, 0x24, 0x2C)
            + b"DCS\0" + struct.pack(">II", len(payload), len(z))
            + b"DCP\0DFLT" + struct.pack(">II", 0x20, 9) + b"\0" * 16
            + b"DCA\0" + struct.pack(">I", 8) + z)


def test_roundtrip_synthetic():
    p = b"FLVE" + bytes(range(100))
    info = D.parse_dcx(_make(p))
    assert info["method"] == "DFLT" and info["data_off"] == 0x4C
    assert D.decompress_dcx(_make(p)) == p


def test_bounds_rejected():
    raw = _make(b"x" * 50)
    with pytest.raises(ValueError):
        D.parse_dcx(raw[:-5])
    with pytest.raises(ValueError):
        D.parse_dcx(b"XXXX" + raw[4:])
    bad = bytearray(raw)
    bad[0x1C:0x20] = struct.pack(">I", 51)
    with pytest.raises(ValueError):
        D.decompress_dcx(bytes(bad))


@pytest.mark.skipif(not os.path.exists(ISO_PATH), reason="owned ISO absent")
def test_owned_iso_sample_decompress():
    with open(ISO_PATH, "rb") as h:
        def rd(lba, n):
            h.seek(lba * 2048)
            return h.read(n)
        r, s = acv.xiso_root(rd)
        bp = {e["path"]: e for e in acv.parse_xiso_directory(rd, r, s)}
        b = bp["bind/dvdbnd5.bhd"]
        bhd = rd(b["lba"], b["size"])
        d = bp["bind/dvdbnd.bdt"]
        recs = acv.parse_bhd5_buckets(bhd, d["size"])
        magics = set()
        n = 0
        for x in sorted(recs, key=lambda x: x["offset"])[::200]:
            if x["size"] > 2 << 20:
                continue
            h.seek(d["lba"] * 2048 + x["offset"])
            raw = h.read(x["size"])
            if raw[:4] != b"DCX\0":
                continue
            out = D.decompress_dcx(raw)
            assert len(out) == D.parse_dcx(raw)["uncompressed_size"]
            magics.add(out[:4])
            n += 1
        assert n >= 20
        assert magics & {b"BND3", b"TPF\0", b"FLVE"}
