import os
import struct
import zlib

import pytest

from gbox import acv_bnd3 as B
from gbox import acv_dcx as D
from gbox import acv_flve as F
from gbox import acv_inventory as acv

ISO_PATH = os.environ.get(
    "ACV_ISO",
    "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/"
    "Armored Core V.iso")


def _flve(n_bones=3):
    h = bytearray(0x60)
    h[:8] = b"FLVE" + b"R\0B\0"
    struct.pack_into(">8I", h, 8, 0x20009, 0x50, 0x10, 1, 1, n_bones, 1, 1)
    struct.pack_into(">6f", h, 0x28, -1, -1, -1, 1, 1, 1)
    struct.pack_into(">II", h, 0x40, 10, 10)
    h[0x48] = 16
    return bytes(h)


def _bnd3(payload, name=b"a.flv"):
    z = zlib.compress(payload)
    fmt = 0x26  # ids + names1 + compression
    n_off = 0x20 + 24
    d_off = n_off + len(name) + 1
    hdr = bytearray(0x20)
    hdr[:4] = b"BND3"
    hdr[4:9] = b"JP100"
    hdr[0x0C] = fmt
    hdr[0x0D] = 1
    struct.pack_into(">II", hdr, 0x10, 1, d_off)
    ent = struct.pack(">BxxxIIIII", 0x40, len(z), d_off, 7, n_off, len(payload))
    return bytes(hdr) + ent + name + b"\0" + z


def test_bnd3_flve_synthetic():
    raw = _bnd3(_flve())
    t = B.parse_bnd3(raw)
    e = t["entries"][0]
    assert e["name"] == "a.flv" and e["id"] == 7 and t["big_endian"]
    p = B.read_entry(raw, e)
    hd = F.parse_flve_header(p)
    assert hd["bone_count"] == 3 and hd["index_bits"] == 16


def test_bounds_rejected():
    raw = _bnd3(_flve())
    with pytest.raises(ValueError):
        B.parse_bnd3(raw[:-3])
    with pytest.raises(ValueError):
        B.parse_bnd3(b"XXXX" + raw[4:])
    f = bytearray(_flve())
    struct.pack_into(">I", f, 0x10, 1 << 20)
    with pytest.raises(ValueError):
        F.parse_flve_header(bytes(f))
    f = bytearray(_flve())
    f[6] = ord("L")
    with pytest.raises(ValueError):
        F.parse_flve_header(bytes(f))


@pytest.mark.skipif(not os.path.exists(ISO_PATH), reason="owned ISO absent")
def test_owned_iso_bnd3_flve_sample():
    with open(ISO_PATH, "rb") as h:
        def rd(lba, n):
            h.seek(lba * 2048)
            return h.read(n)
        r, s = acv.xiso_root(rd)
        bp = {e["path"]: e for e in acv.parse_xiso_directory(rd, r, s)}
        b = bp["bind/dvdbnd5.bhd"]
        d = bp["bind/dvdbnd.bdt"]
        recs = acv.parse_bhd5_buckets(rd(b["lba"], b["size"]), d["size"])
        bnds = flves = 0
        for x in sorted(recs, key=lambda x: x["offset"])[::80]:
            if x["size"] > 2 << 20:
                continue
            h.seek(d["lba"] * 2048 + x["offset"])
            raw = h.read(x["size"])
            if raw[:4] == b"DCX\0":
                raw = D.decompress_dcx(raw)
            if raw[:4] != b"BND3":
                continue
            try:
                t = B.parse_bnd3(raw)
            except ValueError:
                continue
            bnds += 1
            for en in t["entries"]:
                p = B.read_entry(raw, en)
                if p[:4] == b"FLVE":
                    hd = F.parse_flve_header(p)
                    assert hd["index_bits"] == 16 and hd["bone_count"] <= 4096
                    flves += 1
        assert bnds >= 20 and flves >= 20
