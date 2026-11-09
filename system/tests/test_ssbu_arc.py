"""SSBU `data.arc` reader: Hash40 paths, table location and extraction against the operator's own archive.

The real archive lives only on the machine that owns the game, so those tests skip elsewhere; the hash function and
the error paths run everywhere.
"""
import struct
import zlib
from pathlib import Path

import pytest

from gbox import ssbu_arc as A

REAL = Path(r"C:\_tools\gBox\.tmp\ssbu_romfs\data.arc")
SONIC = "fighter/sonic/model/body/c00/model.numdlb"
MARIO = "fighter/mario/model/body/c00/model.numdlb"


def test_hash40_is_crc32_with_the_byte_length():
    crc, length = A.path_hash("abc")
    assert length == 3 and crc == (zlib.crc32(b"abc") & 0xFFFFFFFF)
    assert A.path_hash("") == (0, 0)


def test_texture_names_are_not_confused_with_paths():
    assert A.path_hash("fighter/sonic/model/body/c00/eye2_sonic_001_col.nutexb") != A.path_hash(
        "fighter/sonic/model/body/c00/deyes_sonic_d_col.nutexb")


def test_a_missing_file_raises_with_the_path(tmp_path):
    arc = A.DataArc.__new__(A.DataArc)
    arc.files = {}
    arc.path = tmp_path / "data.arc"
    with pytest.raises(A.ArcError, match="not in data.arc"):
        arc.find("fighter/nobody/model/body/c00/model.numdlb")


def test_a_bad_magic_is_refused(tmp_path):
    bad = tmp_path / "data.arc"
    bad.write_bytes(struct.pack("<7Q", 0x1234, 0x38, 0, 0, 0x100, 0, 0) + bytes(0x100))
    with pytest.raises(A.ArcError, match="not an SSBU data.arc"):
        A.DataArc(bad)


@pytest.mark.skipif(not REAL.is_file(), reason="the operator's data.arc is not on this machine")
class TestRealArchive:
    @pytest.fixture(scope="class")
    def arc(self):
        arc = A.DataArc(REAL)
        yield arc
        arc.close()

    def test_the_tables_land_on_the_measured_offsets(self, arc):
        # measured on this file: the tables must be found exactly, not approximately
        assert arc.groups_at - arc.hdr2 == 0x1BD24
        assert arc.group_data_at - arc.hdr2 == 0x163D7C
        assert arc.multi_at - arc.hdr2 == 0x291658
        assert arc.records_at - arc.hdr2 == 0x14A6B68

    def test_it_finds_and_decodes_sonic_and_mario_models(self, arc):
        for path in (SONIC, MARIO):
            entry = arc.find(path)
            assert entry["compressed"] and entry["decoded_size"] > 1000
            data = arc.read(path)
            assert len(data) == entry["decoded_size"]
            # the SSBU wrapper is a 16-byte HBSS prefix, then the little-endian model magic
            assert data[:4] == b"HBSS" and data[0x10:0x14] == b"LDOM"

    def test_an_absent_sibling_is_reported_as_absent(self, arc):
        assert not arc.exists("fighter/sonic/model/body/c00/model.not_a_real_extension")
