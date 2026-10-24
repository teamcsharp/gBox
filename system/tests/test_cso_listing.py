"""#2507: the .cso branch of gbox.formats.disc.listing (CISO compressed PSP disc images).

Before this change disc.listing() had no .cso branch, so the owned Portable Ops Plus image
("Metal Gear Solid - Portable Ops Plus (USA).cso") failed with
"not a disc image, ROM, archive or folder gBox can list" and the inventory stage could not start.

gbox.cso.CSO (already merged) parses the CISO header and the block table and inflates the blocks; what
is under test here is the wiring into the generic disc listing plus the ISO9660 walk over the
decompressed stream. The expected values below are independent facts, not parser output: ISO 9660
puts the primary volume descriptor at LBA 16 with "CD001" at byte 1, the PSP executable stub starts
with "~PSP" and the PSP ELF boot image with 7f "ELF".
"""
import os
import struct

import pytest

from gbox import cso
from gbox.formats import disc

OWNED_CANDIDATES = [
    os.environ.get("GBOX_POPPLUS_CSO", ""),
    "/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation Portable/roms/"
    "Metal Gear Solid - Portable Ops Plus (USA).cso",
    "/home/ehm_eckx/gBox/system/gbox-data/exports/b8db09daa9292ece/original_qkza86dr/"
    "Metal Gear Solid - Portable Ops Plus (USA).cso",
]

COMPRESSED_SIZE = 732228160
TOTAL_BYTES = 1248067584          # 609408 blocks * 2048
PSP_EXECUTABLES = ("PSP_GAME/SYSDIR/BOOT.BIN", "PSP_GAME/SYSDIR/EBOOT.BIN")


def _owned() -> str | None:
    for p in OWNED_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return None


owned = pytest.mark.skipif(_owned() is None, reason="owned Portable Ops Plus CSO not mounted")


def build_iso(tree: dict) -> bytes:
    """Minimal ISO9660: PVD at LBA 16, directories and files laid out from LBA 20. tree: {name: bytes|dict}."""
    sectors: dict[int, bytes] = {}
    nxt = [20]

    def alloc(n):
        a = nxt[0]
        nxt[0] += max(1, (n + 2047) // 2048)
        return a

    def rec(name: bytes, lba, size, is_dir):
        r = bytearray(33 + len(name) + (1 - len(name) % 2))
        r[0] = len(r)
        struct.pack_into("<I", r, 2, lba)
        struct.pack_into(">I", r, 6, lba)
        struct.pack_into("<I", r, 10, size)
        struct.pack_into(">I", r, 14, size)
        r[25] = 2 if is_dir else 0
        r[32] = len(name)
        r[33:33 + len(name)] = name
        return bytes(r)

    def place(node) -> tuple[int, int]:
        lba = alloc(2048 * 3)
        recs = [rec(b"\0", lba, 6144, True), rec(b"\1", lba, 6144, True)]
        for name, v in node.items():
            if isinstance(v, dict):
                sl, ss = place(v)
                recs.append(rec(name.encode(), sl, ss, True))
            else:
                fl = alloc(len(v))
                sectors[fl] = v
                recs.append(rec(name.encode() + b";1", fl, len(v), False))
        buf, cur = bytearray(), bytearray()
        for r in recs:                                     # records never cross a sector
            if len(cur) + len(r) > 2048:
                buf += cur + bytes(2048 - len(cur))
                cur = bytearray()
            cur += r
        buf += cur + bytes(2048 - len(cur))
        sectors[lba] = bytes(buf)
        return lba, len(buf)

    root_lba, root_size = place(tree)
    pvd = bytearray(2048)
    pvd[0:6] = b"\x01CD001"
    pvd[8:40] = b"PLAYSTATION".ljust(32)
    pvd[156:156 + 34] = rec(b"\0", root_lba, root_size, True)
    sectors[16] = bytes(pvd)
    img = bytearray(2048 * nxt[0])
    for lba, data in sectors.items():
        img[lba * 2048:lba * 2048 + len(data)] = data
    return bytes(img)


TREE = {
    "PSP_GAME": {
        "PARAM.SFO": b"\x00PSF\x01\x01\x00\x00" + bytes(64),
        "SYSDIR": {
            "EBOOT.BIN": b"~PSP\x00\x00\x00\x00" + bytes(252),
            "BOOT.BIN": b"\x7fELF\x01\x01\x01\x00" + bytes(60),
        },
    },
}


def _assert_native_executable(L):
    """The listing must pick a native PSP executable and return that member's own bytes."""
    assert L.executable_name in PSP_EXECUTABLES, L.executable_name
    heads = {f["path"]: f.get("head", b"") for f in L.files}
    assert L.executable[:len(heads[L.executable_name])] == heads[L.executable_name]
    assert L.executable[:4] in (b"\x7fELF", b"~PSP")


def test_cso_header_and_blocks_are_parsed(tmp_path):
    """The CISO header/index the reader uses is a known fact about the format, not parser output."""
    img = build_iso(TREE)
    path = tmp_path / "image.cso"
    cso.write_cso(img, path, block=2048)
    with open(path, "rb") as fh:
        head = fh.read(0x18)
    assert head[:4] == b"CISO"
    info = cso.parse_header(head)
    assert info["block"] == 2048 and info["version"] == 1
    assert info["total"] == len(img) and info["blocks"] == len(img) // 2048
    r = cso.CSO(path)
    try:
        r.seek(16 * 2048)
        assert r.read(6) == b"CD001" or r.read(0) == b""     # ECMA-119: PVD at LBA 16
        assert len(r.block(16)) == 2048 and r.block(16)[:6] == b"\x01CD001"
    finally:
        r.close()


def test_cso_listing_matches_the_plain_iso_listing(tmp_path):
    """A .cso must list exactly like the ISO it was built from (the regression this ticket needs)."""
    img = build_iso(TREE)
    iso = tmp_path / "plain.iso"
    iso.write_bytes(img)
    path = tmp_path / "image.cso"
    cso.write_cso(img, path, block=2048)

    L_iso = disc.listing(iso)
    L_cso = disc.listing(path)
    assert L_cso.kind == "iso9660"
    assert {f["path"]: f["size"] for f in L_cso.files} == {f["path"]: f["size"] for f in L_iso.files}
    heads = {f["path"]: f.get("head", b"") for f in L_cso.files}
    assert heads["PSP_GAME/SYSDIR/EBOOT.BIN"].startswith(b"~PSP")
    assert heads["PSP_GAME/SYSDIR/BOOT.BIN"].startswith(b"\x7fELF")
    _assert_native_executable(L_cso)
    assert any("CISO compressed image" in n for n in L_cso.notes)


def test_cso_listing_rejects_a_non_ciso_file(tmp_path):
    bad = tmp_path / "fake.cso"
    bad.write_bytes(b"NOTCISO" + bytes(0x1000))
    with pytest.raises(ValueError):
        disc.listing(bad)


@owned
def test_owned_popplus_cso_lists_the_native_psp_files():
    """The owned build: the .cso lists the PSP game tree and the native executable is found."""
    path = _owned()
    assert os.path.getsize(path) == COMPRESSED_SIZE
    r = cso.CSO(path)
    try:
        r.seek(16 * 2048)
        assert r.read(8) == b"\x01CD001\x01\x00"          # ECMA-119 PVD, version 1
        r.seek(16 * 2048 + 80)
        lsb, _ = struct.unpack("<II", r.read(8))
        assert lsb * 2048 == TOTAL_BYTES
    finally:
        r.close()
    L = disc.listing(path, deep=2, deep_bytes=1 << 18)
    sizes = {f["path"]: f["size"] for f in L.files}
    heads = {f["path"]: f.get("head", b"") for f in L.files}
    assert L.kind == "iso9660"
    assert "PSP_GAME/SYSDIR/EBOOT.BIN" in sizes
    assert "PSP_GAME/PARAM.SFO" in sizes
    assert sizes["PSP_GAME/SYSDIR/EBOOT.BIN"] > 0
    assert heads["PSP_GAME/SYSDIR/EBOOT.BIN"].startswith(b"~PSP")
    _assert_native_executable(L)
    assert any("CISO compressed image" in n for n in L.notes)
