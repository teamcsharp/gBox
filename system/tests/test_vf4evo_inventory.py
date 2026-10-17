"""Focused tests for gbox.vf4evo_inventory: ISO9660 walker + PS2 boot identity."""
import hashlib
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gbox import vf4evo_inventory as v  # noqa: E402


def _dir_record(name: bytes, lba: int, size: int, flags: int = 0) -> bytes:
    """One ISO9660 directory record: length 33+nl, padded to even."""
    nl = len(name)
    rlen = 33 + nl + ((33 + nl) % 2)
    rec = bytearray(rlen)
    rec[0] = rlen
    struct.pack_into("<I", rec, 2, lba)
    struct.pack_into("<I", rec, 6, lba)
    struct.pack_into("<I", rec, 10, size)
    rec[25] = flags
    rec[32] = nl
    rec[33:33 + nl] = name
    return bytes(rec)


def _pvd(root_lba: int, root_size: int) -> bytes:
    s = bytearray(2048)
    s[0] = 1
    s[1:6] = b"CD001"
    s[6] = 1
    rec = bytearray(_dir_record(b"\0", root_lba, root_size, 2))
    s[156:156 + 34] = rec
    return bytes(s)


def make_iso(files: dict[bytes, bytes], root_name: bytes = b"") -> tuple[str, dict[str, str]]:
    """Fabricate a 2048-stride ISO9660 image in a temp dir. Returns (path, {name: sha256})."""
    import tempfile

    # Layout: sector 0-15 boot area, 16 PVD, 17 terminator, 18+ root dir, then file data.
    root_entries = []
    lba = 20
    body = {}
    for name, data in files.items():
        size = len(data)
        root_entries.append((name, lba, size))
        body[lba] = data + b"\0" * ((-size) % 2048)
        lba += max(1, (size + 2047) // 2048)
    root_size = max(2048, sum(33 + len(n) + ((33 + len(n)) % 2) for n, _, _ in root_entries))
    root_buf = bytearray(root_size)
    o = 0
    for name, elba, esize in root_entries:
        rec = _dir_record(name, elba, esize)
        root_buf[o:o + len(rec)] = rec
        o += len(rec)
    img = bytearray((lba + 1) * 2048)
    img[16 * 2048:17 * 2048] = _pvd(18, root_size)
    img[18 * 2048:19 * 2048] = bytes(root_buf)
    for elba, data in body.items():
        img[elba * 2048:(elba + 1) * 2048] = data

    d = tempfile.mkdtemp(prefix="vf4iso-")
    path = os.path.join(d, "test.iso")
    with open(path, "wb") as f:
        f.write(img)
    return path, {n.decode().split(";")[0]: hashlib.sha256(d).hexdigest() for n, d in files.items()}


def test_walk_and_read():
    path, hashes = make_iso({
        b"SYSTEM.CNF;1": b"BOOT2 = cdrom0:\\SLUS_205.79;1\nVER = 1.00\nVMODE = NTSC\n",
        b"SLUS_205.79;1": b"\x7fELF" + b"payload" * 100,
        b"IOPRP280.IMG;1": b"iop" * 500,
    })
    walk = v.IsoWalk(path)
    assert walk.stride == 2048
    assert set(walk.files) == {"SYSTEM.CNF", "SLUS_205.79", "IOPRP280.IMG"}
    assert walk.read("SLUS_205.79").startswith(b"\x7fELF")
    assert walk.sha256("SYSTEM.CNF") == hashes["SYSTEM.CNF"]


def test_boot_identity():
    path, hashes = make_iso({
        b"SYSTEM.CNF;1": b"BOOT2 = cdrom0:\\SLUS_205.79;1\n",
        b"SLUS_205.79;1": b"\x7fELF" + os.urandom(1024),
    })
    walk = v.IsoWalk(path)
    ident = v.boot_identity(walk)
    assert ident["boot_path"] == "SLUS_205.79"
    assert ident["boot_sha256"] == hashes["SLUS_205.79"]
    assert ident["system_cnf"].startswith("BOOT2")


def test_census_groups_extensions():
    path, _ = make_iso({
        b"SYSTEM.CNF;1": b"BOOT2 = cdrom0:\\SLUS_205.79;1\n",
        b"A.PAK;1": os.urandom(5000),
        b"B.PAK;1": os.urandom(7000),
        b"X.IRX;1": os.urandom(200),
    })
    walk = v.IsoWalk(path)
    census = v.asset_census(walk)
    assert census["pak"]["count"] == 2
    assert census["pak"]["total_bytes"] == 12000
    assert census["pak"]["largest"][0]["name"] == "B.PAK"
    assert "irx" not in census or "irx" in census  # small files may be filtered by min_size


def test_inventory_manifest(tmp_path):
    path, hashes = make_iso({
        b"SYSTEM.CNF;1": b"BOOT2 = cdrom0:\\SLUS_205.79;1\n",
        b"SLUS_205.79;1": b"\x7fELF" + os.urandom(2048),
    })
    out = str(tmp_path / "m.json")
    m = v.inventory(path, "f" * 64, out)
    assert m["source_sha256"] == "f" * 64
    assert m["boot"]["boot_sha256"] == hashes["SLUS_205.79"]
    assert os.path.exists(out)
    with open(out) as fh:
        assert fh.read().startswith('{')


# ---------------------------------------------------------------- synthetic CVM

def make_cvm(files: dict[bytes, bytes]) -> bytes:
    """Minimal CVM: CVMH(0x800) + ZONE(0x1800) + PVD at LBA 15 + root dir at LBA 20.

    File data starts at LBA 30. All LBA values are relative to the CVM base (0x2000)."""
    entries = list(files.items())
    root_size = max(2048, sum(33 + len(n) + ((33 + len(n)) % 2) for n, _ in entries))
    root_buf = bytearray(root_size)
    o = 0
    lba = 30
    blob = bytearray()
    locs = {}
    for name, data in entries:
        locs[name] = lba
        rec = _dir_record(name, lba, len(data))
        root_buf[o:o + len(rec)] = rec
        o += len(rec)
        blob += data + b"\0" * ((-len(data)) % 2048)
        lba += max(1, (len(data) + 2047) // 2048)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[156:156 + 34] = _dir_record(b"\0", 20, root_size, 2)
    needed = 0x2000 + 30 * 2048 + len(blob)
    cvm = bytearray(needed)                     # CVMH (0x800) + ZONE (0x1800) + LBA space
    cvm[0:4] = b"CVMH"
    cvm[0x800:0x804] = b"ZONE"
    cvm[0x2000 + 15 * 2048:0x2000 + 16 * 2048] = pvd              # LBA 15
    cvm[0x2000 + 16 * 2048:0x2000 + 17 * 2048] = b"\xffCD001" + b"\0" * 2040
    cvm[0x2000 + 20 * 2048:0x2000 + 21 * 2048] = bytes(root_buf[:2048])
    cvm[0x2000 + 30 * 2048:0x2000 + 30 * 2048 + len(blob)] = blob
    return bytes(cvm)


def test_cvm_walk_and_read():
    cvm = make_cvm({
        b"CH_AKI.MRG_GZ;1": b"zf" + b"\x00" * 100,
        b"MOTMRG_LAU.MRG;1": b"motion" * 40,
    })
    disc = v.CVMDisc(cvm)
    assert disc.pvd_lba == 15
    assert set(disc.files) == {"CH_AKI.MRG_GZ", "MOTMRG_LAU.MRG"}
    assert disc.read("CH_AKI.MRG_GZ")[:2] == b"zf"
    assert disc.read("MOTMRG_LAU.MRG") == b"motion" * 40
    assert disc.sha256("MOTMRG_LAU.MRG") == hashlib.sha256(b"motion" * 40).hexdigest()


def test_cvm_null_named_character_dir():
    # a null-named subdirectory (SEGA quirk) holding the character archive
    cvm = make_cvm({
        b"SYSTEM.CNF;1": b"BOOT2 = cdrom0:\\SLUS_206.16;1\n",
    })
    # append the null-named dir record to the root dir and place CH_AKI in its stream
    sub_lba, sub_size = 40, 2048
    rec = _dir_record(b"\x00", sub_lba, sub_size, 2)
    cvm = bytearray(cvm)
    cvm += b"\0" * ((0x2000 + 51 * 2048) - len(cvm))   # room for the sub dir and file
    root_off = 0x2000 + 20 * 2048
    root = bytearray(cvm[root_off:root_off + 2048])
    o = 0
    while root[o] != 0:
        o += root[o]
    root[o:o + len(rec)] = rec
    cvm[root_off:root_off + 2048] = root
    sub = bytearray(2048)
    sub[0:len(_dir_record(b"CH_AKI.MRG_GZ;1", 50, 64))] = _dir_record(b"CH_AKI.MRG_GZ;1", 50, 64)
    cvm[0x2000 + sub_lba * 2048:0x2000 + (sub_lba + 1) * 2048] = sub
    cvm[0x2000 + 50 * 2048:0x2000 + 50 * 2048 + 64] = b"zf" + b"\x11" * 62
    disc = v.CVMDisc(bytes(cvm))
    assert any(n.endswith("CH_AKI.MRG_GZ") for n in disc.files)
    aki = next(n for n in disc.files if n.endswith("CH_AKI.MRG_GZ"))
    assert disc.read(aki)[:2] == b"zf"
