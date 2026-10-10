"""CDI (DiscJuggler) reading for gbox.gdrom — hermetic synthetic image + a real-disc smoke test.

A .cdi is raw CD sectors behind an optional header and a 150-sector pregap. The ISO9660 primary volume
descriptor (LBA 16) and the next descriptor one sector later pin the sector stride and the LBA-0 base, so
CDIRom/GDRom can list and read files without chdman. This test builds a tiny in-memory CDI and checks the
reader end to end; the real Jet Grind Radio .cdi (a DCRES repack) is exercised when it is present.
"""
import struct
from pathlib import Path

import pytest

from gbox.gdrom import CDIRom, GDRom

HELLO = b"jet grind radio model\n"
JGR_CDI = "/mnt/gbox/quickswap2/Emulation/_emulation/_dc iso/[CDI] Jet Grind Radio (US)[DCRES]/Jet Grind Radio (US)[DCRES].cdi"


def _dir_record(extent: int, size: int, flags: int, name: str) -> bytes:
    nb = name.encode()
    rec = bytearray(34 + len(nb))
    rec[0] = 34 + len(nb)
    struct.pack_into("<I", rec, 2, extent)
    struct.pack_into(">I", rec, 6, extent)
    struct.pack_into("<I", rec, 10, size)
    struct.pack_into(">I", rec, 14, size)
    rec[25] = flags
    rec[32] = len(nb)
    rec[33:33 + len(nb)] = nb
    return bytes(rec)


def make_cdi(sector_size: int = 2336, header: bytes = bytes(8), pregap: int = 150) -> bytes:
    """A minimal single-file CDI: header + pregap + 16 system sectors + PVD + terminator + root dir + one file."""
    pvd = bytearray(2048)
    pvd[0] = 0x01
    pvd[1:6] = b"CD001"
    pvd[156:156 + 34] = _dir_record(18, 2048, 2, "\x00")   # root directory at LBA 18

    term = bytearray(2048)
    term[0] = 0xFF
    term[1:6] = b"CD001"

    root = bytearray(2048)
    root[0:len(_dir_record(19, len(HELLO), 0, "HELLO.TXT;1"))] = _dir_record(19, len(HELLO), 0, "HELLO.TXT;1")

    def sec(payload: bytes) -> bytes:
        return payload + bytes(sector_size - len(payload))

    return (header
            + bytes(pregap * sector_size)
            + bytes(16 * sector_size)          # LBA 0..15 (system area)
            + sec(bytes(pvd)) + sec(bytes(term)) + sec(bytes(root)) + sec(HELLO))


def _write(tmp_path, img, name="disc.cdi") -> Path:
    p = tmp_path / name
    p.write_bytes(img)
    return p


def test_cdir_lists_and_reads_file(tmp_path):
    p = _write(tmp_path, make_cdi())
    cdi = CDIRom(p)
    assert cdi.sector_size == 2336
    assert cdi.base == 8 + 150 * 2336
    assert "HELLO.TXT" in cdi.files
    assert cdi.read("HELLO.TXT") == HELLO
    # GDRom exposes the same interface for a .cdi path
    g = GDRom(p)
    assert g.files == cdi.files
    assert g.read("HELLO.TXT") == HELLO


def test_cdir_detects_2352_stride(tmp_path):
    p = _write(tmp_path, make_cdi(sector_size=2352))
    cdi = CDIRom(p)
    assert cdi.sector_size == 2352
    assert cdi.read("HELLO.TXT") == HELLO


def test_cdir_rejects_non_cd_image(tmp_path):
    bad = tmp_path / "bad.cdi"
    bad.write_bytes(b"not a cd image at all")
    with pytest.raises(ValueError):
        CDIRom(bad)


@pytest.mark.skipif(not Path(JGR_CDI).exists(), reason="real JGR .cdi not mounted on this node")
def test_real_jgr_cdi_lists_dummy():
    cdi = CDIRom(JGR_CDI)
    assert cdi.sector_size == 2336
    assert "DUMMY.DAT" in cdi.files
    _lba, size = cdi.files["DUMMY.DAT"]
    assert size > 40_000_000
