import struct
import pytest
from gbox.formats.omchr import OmChrError, describe, parse_bres, parse_chr_misc


def _group(base, items):
    """items: [(name, data_off_rel_to_base)] -> (group bytes, strings placed after)."""
    n = len(items)
    hdr = 8 + 16 * (n + 1)
    strs = b""
    ents = [struct.pack(">HHHHII", 0xFFFF, 0, 0, 0, 0, 0)]
    for name, doff in items:
        raw = name.encode()
        pad = (-len(raw) - 1) % 4
        strs += struct.pack(">I", len(raw)) + raw + b"\0" * (1 + pad)
        no = hdr + len(strs) - len(raw) - 1 - pad
        ents.append(struct.pack(">HHHHII", 0, 0, 0, 0, no, doff))
    return struct.pack(">II", hdr + len(strs), n) + b"".join(ents) + strs


def make_bres():
    # root@0x10: 'root' size, group(folders) ; folder group; member
    root = 0x10
    fold_off_rel = 0x40  # relative to group base (root+8)
    gbase = root + 8
    top = _group(gbase, [("AnmScn(NW4R)", fold_off_rel)])
    body = bytearray(b"bres\xfe\xff\x00\x00" + b"\0\0\0\0" + struct.pack(">HH", root, 2))
    body += b"root" + b"\0\0\0\0" + top
    fbase = gbase + fold_off_rel
    body += b"\0" * (fbase - len(body))
    sub = _group(fbase, [("avoid_back", 0x80)])
    body += sub
    body += b"\0" * (fbase + 0x80 - len(body)) + b"SCN0" + b"\0" * 12
    body[8:12] = struct.pack(">I", len(body))
    return bytes(body)


def make_chr():
    bres = make_bres()
    bo = 0x100
    total = bo + len(bres)
    d = bytearray(total)
    d[:8] = b"chr_misc"
    d[8:0x10] = struct.pack(">II", 0xFF000100, 0x30)
    d[0x10:0x14] = struct.pack(">I", total)
    tbl = [0x60, 0x80, 0x90, bo, 0, 0, total - 4, 0, 0, 0, 0, 0]
    d[0x30:0x60] = struct.pack(">12I", *tbl)
    d[bo:] = bres
    return bytes(d)


def test_bres_walk():
    f = parse_bres(make_bres())
    assert f == {"AnmScn(NW4R)": [("avoid_back", "SCN0", f["AnmScn(NW4R)"][0][2])]}


def test_chr_misc_describe():
    info = describe(make_chr())
    assert info["kind"] == "chr_misc"
    assert info["sections"]["bres"] == 0x100
    assert info["bres_folders"] == {"AnmScn(NW4R)": [("avoid_back", "SCN0")]}


def test_padded_size_ok_and_bad_rejected():
    d = make_chr()
    assert parse_chr_misc(d + b"\0" * 8)["size"] == len(d)
    with pytest.raises(OmChrError):
        parse_chr_misc(d + b"\0" * 0x40)
    with pytest.raises(OmChrError):
        parse_chr_misc(b"xxxx" + d[4:])
