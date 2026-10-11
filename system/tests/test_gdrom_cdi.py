import struct
from pathlib import Path

import pytest

from gbox.gdrom import CDIRom, GDRom

JGR_CDI = "/mnt/gbox/quickswap2/Emulation/_emulation/_dc iso/[CDI] Jet Grind Radio (US)[DCRES]/Jet Grind Radio (US)[DCRES].cdi"
HELLO = b"jet grind radio model\n"


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


MARK = b"\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff"
SS_CODE = {2048: 0, 2336: 1, 2352: 2}


def _raw(payload: bytes, sector_size: int, mode: int) -> bytes:
    """One raw sector carrying a 2048-byte user payload at the offset DiscJuggler stores it."""
    head = {2048: 0, 2336: 8}.get(sector_size, 16 if mode == 1 else 24)
    sec = bytes(head) + payload.ljust(2048, b"\x00")
    return sec.ljust(sector_size, b"\xee")         # non-zero EDC/ECC filler must not leak into user data


def _iso_sectors(start_lba: int, file_data: bytes, file_name: str) -> list[bytes]:
    """User payloads for LBAs start_lba .. : 16 system sectors, PVD, terminator, root dir, file."""
    pvd = bytearray(2048)
    pvd[0] = 0x01
    pvd[1:6] = b"CD001"
    pvd[156:156 + 34] = _dir_record(start_lba + 18, 2048, 2, "\x00")
    term = bytearray(2048)
    term[0] = 0xFF
    term[1:6] = b"CD001"
    root = bytearray(2048)
    rec = _dir_record(start_lba + 19, len(file_data), 0, file_name + ";1")
    root[0:len(rec)] = rec
    return [bytes(2048)] * 16 + [bytes(pvd), bytes(term), bytes(root), file_data]


def _track_block(pregap: int, length: int, mode: int, start_lba: int, sector_size: int) -> bytes:
    name = b"C:\\fake.cdi"
    return (struct.pack("<I", 0) + MARK + MARK + bytes(4) + bytes([len(name)]) + name
            + bytes(11 + 4 + 4) + struct.pack("<I", 0) + bytes(2)
            + struct.pack("<II", pregap, length) + bytes(6) + struct.pack("<I", mode) + bytes(12)
            + struct.pack("<II", start_lba, pregap + length) + bytes(16)
            + struct.pack("<I", SS_CODE[sector_size]) + bytes(29) + bytes(5) + struct.pack("<I", 0))


def make_cdi(sector_size: int = 2336, mode: int = 2, pregap: int = 150,
             sessions: list[tuple[int, bytes, str]] | None = None, footer: bool = True) -> bytes:
    """A DiscJuggler v3.5 image: one data track per session, each session holding its own ISO9660 volume."""
    sessions = sessions or [(0, HELLO, "HELLO.TXT")]
    body, foot = b"", struct.pack("<H", len(sessions))
    for start_lba, data, name in sessions:
        payloads = _iso_sectors(start_lba, data, name)
        body += b"".join(_raw(b"", sector_size, mode) for _ in range(pregap))
        body += b"".join(_raw(x, sector_size, mode) for x in payloads)
        foot += struct.pack("<H", 1) + _track_block(pregap, len(payloads), mode, start_lba, sector_size)
        foot += bytes(4 + 8 + 1)                    # end of session
    if not footer:
        return body
    foot += bytes(32)                               # disc info (unused by the reader)
    return body + foot + struct.pack("<II", 0x80000006, len(foot) + 8)


def _write(tmp_path: Path, img: bytes, name: str = "disc.cdi") -> Path:
    p = tmp_path / name
    p.write_bytes(img)
    return p


def test_cdir_lists_and_reads_file(tmp_path: Path):
    p = _write(tmp_path, make_cdi())
    cdi = CDIRom(p)
    assert cdi.sector_size == 2336
    assert cdi.base == 150 * 2336 + 8
    assert [t["start_lba"] for t in cdi.tracks_info] == [0]
    assert cdi.read("HELLO.TXT") == HELLO
    g = GDRom(p)
    assert g.files == cdi.files
    assert g.read("HELLO.TXT") == HELLO


@pytest.mark.parametrize("mode", [1, 2])
def test_cdir_reads_2352_sectors(tmp_path: Path, mode: int):
    cdi = CDIRom(_write(tmp_path, make_cdi(sector_size=2352, mode=mode)))
    assert cdi.sector_size == 2352
    assert cdi.read("HELLO.TXT") == HELLO


def test_cdir_reads_later_session_filesystem(tmp_path: Path):
    """DCRES-style: a decoy ISO in session 1 and the real game files in session 2 at a gapped LBA."""
    p = _write(tmp_path, make_cdi(sessions=[(0, b"decoy", "DUMMY.DAT"), (11420, b"session two\n", "1ST_READ.BIN")]))
    cdi = CDIRom(p)
    assert [t["start_lba"] for t in cdi.tracks_info] == [0, 11420]
    assert cdi.read("DUMMY.DAT") == b"decoy"
    assert cdi.read("1ST_READ.BIN") == b"session two\n"
    assert GDRom(p).read("1ST_READ.BIN") == b"session two\n"


def test_cdir_without_footer_falls_back_to_descriptor_stride(tmp_path: Path):
    p = _write(tmp_path, bytes(8) + make_cdi(footer=False))
    cdi = CDIRom(p)
    assert cdi.tracks_info == []
    assert cdi.sector_size == 2336
    assert cdi.base == 8 + 150 * 2336 + 8
    assert cdi.read("HELLO.TXT") == HELLO


def test_cdir_rejects_non_cd_image(tmp_path: Path):
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


@pytest.mark.skipif(not Path(JGR_CDI).exists(), reason="real JGR .cdi not mounted on this node")
def test_real_jgr_cdi_reads_real_files():
    cdi = CDIRom(JGR_CDI)
    assert "1ST_READ.BIN" in cdi.files
    assert "JETRADIO/PLAYER.AFS" in cdi.files
    player = cdi.read("JETRADIO/PLAYER.AFS")
    assert player[:4] == b"AFS\x00"
    ini = cdi.read("DP2.INI")
    assert ini.startswith(b"#\n# dp2.ini")


@pytest.mark.parametrize("suffix", [".cdi", ".CDI", ".chd"])
def test_native_disc_patch_refuses_unverified_container_before_output(tmp_path, suffix):
    from gbox.gdrom import patch_gdi
    out = tmp_path / "native-output"
    source = tmp_path / ("missing" + suffix)
    with pytest.raises(ValueError, match="GDI.*CDI support is read-only"):
        patch_gdi(source, out, "candidate", {"1ST_READ.BIN": b"new"}, reuse_modified_slack=True)
    assert not out.exists() and not source.exists()


def test_cdi_metadata_is_retained_for_readers(tmp_path):
    source = _write(tmp_path, make_cdi())
    with CDIRom(source) as disc:
        assert (0, 18) in disc.metadata_ranges and (18, 19) in disc.metadata_ranges
        assert disc.read("HELLO.TXT") == HELLO
    assert disc._mm.closed and disc._fh.closed
    wrapper = GDRom(source)
    try:
        assert wrapper.metadata_ranges == wrapper._cdi.metadata_ranges
    finally:
        wrapper._cdi.close()


@pytest.mark.parametrize("failure", ["short_record", "cycle"])
def test_malformed_cdi_directory_is_rejected(tmp_path, failure):
    data = bytearray(make_cdi())
    directory = (150 + 18) * 2336 + 8
    if failure == "short_record":
        data[directory] = 1
    else:
        record = _dir_record(18, 2048, 2, "LOOP")
        data[directory:directory + len(record)] = record
    with pytest.raises(ValueError, match="directory"):
        CDIRom(_write(tmp_path, data))


def test_cdi_read_rejects_a_truncated_user_sector(tmp_path):
    with CDIRom(_write(tmp_path, make_cdi(footer=False)[:-400])) as disc:
        with pytest.raises(ValueError, match="user sector outside"):
            disc.read("HELLO.TXT")



def test_cdi_footer_track_extent_cannot_cover_footer_bytes(tmp_path):
    data = make_cdi()
    original = _track_block(150, 20, 2, 0, 2336)
    invalid = _track_block(150, 200, 2, 0, 2336)
    assert data.count(original) == 1
    data = data.replace(original, invalid)
    with pytest.raises(ValueError, match="tracks extend into the footer"):
        CDIRom(_write(tmp_path, data))
