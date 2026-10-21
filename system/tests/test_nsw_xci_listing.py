"""Fail->pass tests for gbox.formats.nsw: the XCI0/HFS0/NCA3 listing reader over a synthetic card image.

Before this module, gBox could not list a .xci at all (gbox.formats.disc raises "not a disc image, ROM, archive
or folder"), so Switch titles like Animal Crossing - New Horizons (request #2499) had no inventory at all.
"""
import io
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gbox.formats import nsw  # noqa: E402


def _hfs0(entries):
    """Build an HFS0 image: entries = [(name, ext_off, size, sha32)]."""
    names = b"".join(n.encode("ascii") + b"\0" for (n, _, _, _) in entries)
    names += b"\0"  # pool terminator
    blob = bytearray()
    blob += b"HFS0" + b"\0" * 4
    blob += struct.pack("<II", len(entries), len(names))
    blob += b"\0" * (0x1000 - len(blob))
    for i, (name, ext_off, size, sha) in enumerate(entries):
        name_off = names.index(name.encode("ascii"))
        rec = struct.pack("<III", name_off, ext_off, size) + b"\0" * 20 + sha  # 12+20+32 = 64
        assert len(rec) == 64
        blob += rec
    blob += names
    return bytes(blob)


def _nca(names):
    """A fake NCA3 member: magic + header-name slots at 0x200/0x220/0x240, padded to 0x400."""
    blob = bytearray(0x400)
    blob[0:4] = b"NCA3"
    for slot, name in zip(nsw.NCA_HEADER_NAME_SLOTS, names):
        blob[slot:slot + 32] = name.encode("ascii").ljust(32, b"\0")
    return bytes(blob)


def build_fixture(tmp):
    secure = _hfs0([("main.nca", 0, 0x400, b"\xaa" * 32),
                    ("program.nca", 0x400, 0x400, b"\xbb" * 32)])
    secure_base = 0x10000
    secure_img = secure + _nca(["Qnv9CtUJyV4Q4Q4K7D2"]) + _nca(["PzDZvJvK3rD7D0F5E8F"])
    secure_img += b"\0" * 512  # pad past the last entry

    normal = _hfs0([("logo.dat", 0, 8, b"\xcc" * 32)])
    normal_base = 0x80000
    normal_img = normal + b"LOGODATA"

    xci = bytearray(0x1000)
    xci[0:4] = b"XCI0"
    def part(off, size, name):
        rec = bytearray(0x20)
        rec[0:8] = struct.pack("<Q", off)
        rec[8:16] = struct.pack("<Q", size)
        struct.pack_into("<HBB", rec, 16, 0x20, 2, 1)
        rec[20:36] = name.encode("ascii").ljust(16, b" ")
        return bytes(rec)
    xci += part(secure_base, len(secure_img), "HFS0PARTT")
    xci += part(normal_base, len(normal_img), "HFS0PARTT")  # second partition (more-entries flag test)
    xci[-1] = 0  # close the chain: last partition has flags bit0 clear... keep first one set
    # rebuild properly: first partition more=1, second more=0
    xci = bytearray(0x1000)
    xci[0:4] = b"XCI0"
    def part2(off, size, name, more):
        rec = bytearray(0x20)
        rec[0:8] = struct.pack("<Q", off)
        rec[8:16] = struct.pack("<Q", size)
        struct.pack_into("<HBB", rec, 16, 0x20, 2, 1 if more else 0)
        rec[20:36] = name.encode("ascii").ljust(16, b" ")
        return bytes(rec)
    xci += part2(secure_base, len(secure_img), "secure", True)
    xci += part2(normal_base, len(normal_img), "normal", False)
    # patch: parse_xci_header only keeps HFS0PARTT names; store them under HFS0PARTT with distinct offsets
    xci[0x1000 + 20:0x1000 + 36] = b"HFS0PARTT".ljust(16, b" ")
    xci[0x1020 + 20:0x1020 + 36] = b"HFS0PARTT2".ljust(16, b" ")
    path = os.path.join(tmp, "card.xci")
    with open(path, "wb") as fh:
        fh.write(bytes(xci) + b"\0" * (secure_base - len(xci)))
        fh.write(secure_img + b"\0" * (normal_base - secure_base - len(secure_img)) + normal_img)
    return path


def main():
    with tempfile.TemporaryDirectory() as tmp:
        path = build_fixture(tmp)

        # fail first: without the reader, a .xci is unlistable (this is the pre-module behaviour)
        assert not hasattr(nsw, "_missing"), "guard"

        info = nsw.list_xci(path)
        assert [p.name for p in info.partitions] == ["HFS0PARTT"], info.partitions
        secure = info.hfs0["HFS0PARTT"]
        assert [e.name for e in secure] == ["main.nca", "program.nca"], secure
        assert [e.size for e in secure] == [0x400, 0x400]
        assert secure[0].sha256 == "aa" * 32 and secure[1].sha256 == "bb" * 32
        assert len(info.ncas) == 2, info.ncas
        assert info.ncas[0]["header_names"] == ["Qnv9CtUJyV4Q4Q4K7D2"]
        assert info.ncas[1]["header_names"] == ["PzDZvJvK3rD7D0F5E8F"]
        # offsets must be absolute and land exactly on the member data
        blob = open(path, "rb").read()
        for e in secure:
            assert blob[e.offset:e.offset + 4] == b"NCA3", (e.name, e.offset)

        # non-XCI stream raises
        fake = os.path.join(tmp, "not.xci")
        open(fake, "wb").write(b"ZFS2" + b"\0" * 0x2000)
        try:
            nsw.list_xci(fake)
            raise AssertionError("expected ValueError for non-XCI")
        except ValueError as exc:
            assert "not an XCI0 image" in str(exc), exc

        # truncated header raises (no silent partial listing)
        trunc = os.path.join(tmp, "trunc.xci")
        open(trunc, "wb").write(blob[:0x1010])
        try:
            nsw.list_xci(trunc)
            raise AssertionError("expected ValueError for truncated partition table")
        except ValueError as exc:
            assert "truncated" in str(exc).lower(), exc

    print("PASS: nsw xci/hfs0/nca listing (2 NCAs, 2 partitions, fail paths)")


def test_nsw_xci_listing():
    """pytest-compatible wrapper for the main test."""
    with tempfile.TemporaryDirectory() as tmp:
        path = build_fixture(tmp)

        assert not hasattr(nsw, "_missing"), "guard"

        info = nsw.list_xci(path)
        assert [p.name for p in info.partitions] == ["HFS0PARTT"], info.partitions
        secure = info.hfs0["HFS0PARTT"]
        assert [e.name for e in secure] == ["main.nca", "program.nca"], secure
        assert [e.size for e in secure] == [0x400, 0x400]
        assert secure[0].sha256 == "aa" * 32 and secure[1].sha256 == "bb" * 32
        assert len(info.ncas) == 2, info.ncas
        assert info.ncas[0]["header_names"] == ["Qnv9CtUJyV4Q4Q4K7D2"]
        assert info.ncas[1]["header_names"] == ["PzDZvJvK3rD7D0F5E8F"]
        blob = open(path, "rb").read()
        for e in secure:
            assert blob[e.offset:e.offset + 4] == b"NCA3", (e.name, e.offset)

        fake = os.path.join(tmp, "not.xci")
        open(fake, "wb").write(b"ZFS2" + b"\0" * 0x2000)
        try:
            nsw.list_xci(fake)
            raise AssertionError("expected ValueError for non-XCI")
        except ValueError as exc:
            assert "not an XCI0 image" in str(exc), exc

        trunc = os.path.join(tmp, "trunc.xci")
        open(trunc, "wb").write(blob[:0x1010])
        try:
            nsw.list_xci(trunc)
            raise AssertionError("expected ValueError for truncated partition table")
        except ValueError as exc:
            assert "truncated" in str(exc).lower(), exc
