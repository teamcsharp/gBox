import os, struct, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gbox import capcom_dee as dee, capcom_disc as disc
from gbox.psxdisc import RawBin, fix_sector

REAL = os.environ.get("CAPCOM_GEN_BIN", "/home/ehm_eckx/.bin")


def _sector(lba, payload):
    s = bytearray(2352)
    s[1:11] = b"\xff" * 10
    s[15] = 2
    s[16:24] = bytes([0, 0, 8, 0, 0, 0, 8, 0])
    s[24:24 + len(payload)] = payload
    return fix_sector(s)


def _rec(name, lba, size, flags=0):
    n = name.encode()
    r = bytearray(33 + len(n)); r[0] = len(r) + (len(r) & 1) - 0
    r = bytearray(r + (b"\0" if len(r) & 1 else b""))
    r[0] = len(r)
    struct.pack_into("<I", r, 2, lba); struct.pack_into(">I", r, 6, lba)
    struct.pack_into("<I", r, 10, size); struct.pack_into(">I", r, 14, size)
    r[25] = flags; r[32] = len(n); r[33:33 + len(n)] = n
    return bytes(r)


def make_image(path, dee_blob, size_pad=0):
    pvd = bytearray(2048); pvd[0] = 1; pvd[1:6] = b"CD001"
    root = _rec("\0", 20, 2048, 2)
    pvd[156:156 + len(root)] = root
    struct.pack_into("<I", pvd, 158, 20); struct.pack_into("<I", pvd, 166, 2048)
    dr = _rec("\0", 20, 2048, 2) + _rec("\1", 20, 2048, 2) + _rec("A.DEE;1", 21, len(dee_blob) + size_pad)
    sectors = {16: bytes(pvd), 20: dr, 21: dee_blob.ljust(((len(dee_blob) + size_pad + 2047) // 2048) * 2048, b"\0")}
    with open(path, "wb") as f:
        for lba in range(0, 24):
            if lba == 21:
                n = (len(sectors[21]) + 2047) // 2048
                for i in range(n):
                    f.write(_sector(21 + i, sectors[21][i * 2048:(i + 1) * 2048]))
            elif lba > 21 and lba < 21 + (len(sectors[21]) + 2047) // 2048:
                continue
            else:
                f.write(_sector(lba, sectors.get(lba, b"")))


def _tim():
    pix = bytes(range(256)) * 2
    hdr = struct.pack("<II", 0x10, 8)
    clut = struct.pack("<IHHHH", 12 + 32, 0, 0, 16, 1) + bytes(32)
    img = struct.pack("<IHHHH", 12 + len(pix), 0, 0, 128, 8) + pix  # 8bpp? mode 8 below
    return struct.pack("<II", 0x10, 8) + clut + img


def test_noop_and_changed(tmp_path):
    raw = _tim()
    blob = dee.dee_pack(raw)
    src = str(tmp_path / "a.bin"); out = str(tmp_path / "b.bin")
    make_image(src, blob, size_pad=2000)
    before = open(src, "rb").read()
    done = disc.replace_dee(src, out, {"A.DEE": blob})
    assert done["A.DEE"] >= 1
    assert open(src, "rb").read() == before
    assert open(out, "rb").read() == before  # no-op rebuild is byte identical
    assert dee.dee_unpack(disc.RawBin(out, False).read("A.DEE")) == raw
    raw2 = raw[:-10] + b"\xaa" * 10
    disc.replace_dee(src, out, {"A.DEE": dee.dee_pack(raw2)})
    assert dee.dee_unpack(RawBin(out, False).read("A.DEE")) == raw2
    assert open(out, "rb").read() != before


def test_refuses_oversize_and_inplace(tmp_path):
    blob = dee.dee_pack(b"\x01" * 64)
    src = str(tmp_path / "a.bin"); make_image(src, blob)
    with pytest.raises(disc.DeeDoesNotFit):
        disc.replace_dee(src, str(tmp_path / "o.bin"), {"A.DEE": blob + b"x" * 4096})
    with pytest.raises(ValueError):
        disc.replace_dee(src, src, {"A.DEE": blob})


@pytest.mark.skipif(not os.path.exists(REAL), reason="owned image not present")
def test_real_image_noop_and_donor(tmp_path):
    name = "1943/43CHAR7.DEE"
    d = RawBin(REAL, False); orig = d.read(name); d.close()
    raw = dee.dee_unpack(orig)
    out = str(tmp_path / "mod.bin")
    disc.replace_dee(REAL, out, {name: dee.dee_pack(raw)})
    assert dee.dee_unpack(RawBin(out, False).read(name)) == raw
    info = dee.parse_tim(raw)
    off = 8 + (info["clut"]["size"] if "clut" in info else 0) + 12
    px = bytearray(raw[off:off + info["image"]["size"] - 12])
    px[:16] = b"\x11" * 16
    donor = dee.tim_replace_image(raw, bytes(px))
    out2 = str(tmp_path / "mod2.bin")
    disc.replace_dee(REAL, out2, {name: dee.dee_pack(donor)})
    assert dee.dee_unpack(RawBin(out2, False).read(name)) == donor
    # other files untouched
    a, b = RawBin(REAL, False), RawBin(out2, False)
    assert a.read("1943/43CARD.DEE") == b.read("1943/43CARD.DEE")
