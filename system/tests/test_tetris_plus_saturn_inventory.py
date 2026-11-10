import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import tetris_plus_saturn_inventory as inv


def _mk_iso(tmp_path, raw):
    ss, off = (2352, 16) if raw else (2048, 0)
    img = bytearray(ss * 30)

    def put(lba, data):
        for i in range(0, len(data), 2048):
            img[(lba + i // 2048) * ss + off:(lba + i // 2048) * ss + off + len(data[i:i + 2048])] = data[i:i + 2048]

    pvd = bytearray(2048)
    pvd[0:6] = b"\x01CD001"
    rec = bytearray(34)
    rec[0] = 34
    rec[2:6] = struct.pack("<I", 20)
    rec[10:14] = struct.pack("<I", 2048)
    rec[25] = 2
    pvd[156:190] = rec
    put(16, bytes(pvd))
    payload = b"hello-saturn" * 10
    name = b"0MAIN.BIN;1"
    fr = bytearray(33 + len(name) + (1 if len(name) % 2 == 0 else 0))
    fr[0] = len(fr)
    fr[2:6] = struct.pack("<I", 22)
    fr[10:14] = struct.pack("<I", len(payload))
    fr[32] = len(name)
    fr[33:33 + len(name)] = name
    put(20, bytes(fr))
    put(22, payload)
    p = tmp_path / ("t.bin" if raw else "t.iso")
    p.write_bytes(bytes(img))
    return p, payload


@pytest.mark.parametrize("raw", [True, False])
def test_synthetic_listing_and_hash(tmp_path, raw):
    p, payload = _mk_iso(tmp_path, raw)
    assert inv.listing(p) == [("0MAIN.BIN", 22, len(payload))]
    out = inv.inventory(p)
    assert out["executable_sha256"] == hashlib.sha256(payload).hexdigest()


def test_member_table_shape():
    assert len(inv.MEMBERS) == 33 and inv.EXECUTABLE in inv.MEMBERS
    assert all(len(v[2]) == 64 for v in inv.MEMBERS.values())


@pytest.mark.skipif(not os.environ.get("TETRIS_PLUS_SATURN_BIN"), reason="owned disc image not provided")
def test_real_disc_matches_recorded_manifest():
    p = Path(os.environ["TETRIS_PLUS_SATURN_BIN"])
    assert inv.saturn_header(p).startswith(inv.SATURN_HEADER)
    got = {r["path"]: [r["lba"], r["size"], r["sha256"]] for r in inv.inventory(p)["files"]}
    assert got == {k: list(v) for k, v in inv.MEMBERS.items()}


def test_chr_header_synthetic():
    h = inv.chr_header(bytes.fromhex("0104 8c00 0000 a000 e018".replace(" ", "")))
    assert (h["mode"], h["width"], h["height"], h["pad_ok"]) == (4, 160, 224, True)
    assert inv.chr_header(bytes.fromhex("0184000000001000 10cc".replace(" ", "")))["width"] == 16
    with pytest.raises(ValueError):
        inv.chr_header(b"\x02" * 12)


@pytest.mark.skipif(not os.environ.get("TETRIS_PLUS_SATURN_BIN"), reason="owned disc image not provided")
def test_real_disc_chr_headers():
    p = Path(os.environ["TETRIS_PLUS_SATURN_BIN"])
    with open(p, "rb") as fh:
        for nm, (lba, sz, _h) in inv.MEMBERS.items():
            if nm.endswith(".CHR"):
                h = inv.chr_header(inv.read_extent(fh, lba, 16))
                assert h["pad_ok"] and 8 <= h["width"] <= 160 and 8 <= h["height"] <= 240, nm
