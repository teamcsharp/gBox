"""Focused tests for the Splinter Cell (GameCube, GCEE41) owned-build inventory helpers."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from gbox.splinter_inventory import (
    GC_MAGIC,
    UmdError,
    disc_identity,
    member_name,
    read_chunks,
    read_chunks_bytes,
)

ISO = Path("/home/ehm_eckx/gBox_alt/gbox-cache/modbase/a4ed2cf4d1966815/splinter.iso")


def _umd(payloads):
    out = bytearray()
    for p in payloads:
        comp = zlib.compress(p)
        out += struct.pack(">II", len(p), len(comp)) + comp
    return bytes(out)


def test_disc_identity_reads_platform_and_region():
    head = bytearray(0x440)
    head[0:6] = b"GCEE41"
    head[0x20:0x20 + 13] = b"Tom Clancy's"
    struct.pack_into(">I", head, 0x1C, GC_MAGIC)
    struct.pack_into(">I", head, 0x18, 0)
    bi2 = bytearray(0x440)
    struct.pack_into(">I", bi2, 0x18, 1)
    ident = disc_identity(bytes(head), bytes(bi2))
    assert ident["disc_id"] == "GCEE41"
    assert ident["platform"] == "gamecube"
    assert ident["region"] == "NTSC-U"
    assert ident["region_code"] == 1


def test_member_name_finds_unreal_package_name():
    data = b"\x00" * 7 + b"0_0_2.unr\x00" + b"\x11" * 32
    assert member_name(data) == "0_0_2.unr"
    assert member_name(b"\x00" * 64) is None


def test_read_chunks_walks_the_flat_record_chain(tmp_path):
    payloads = [b"0_0_2.unr" + b"\x01" * 20, b"second" + b"\x02" * 10]
    path = tmp_path / "x.umd"
    path.write_bytes(_umd(payloads))
    chunks, end, size = read_chunks(path)
    assert [c["uncompressed_size"] for c in chunks] == [29, 16]
    assert chunks[0]["name"] == "0_0_2.unr"
    assert end == size
    assert chunks[0]["offset"] == 0
    assert chunks[1]["offset"] == 8 + len(zlib.compress(payloads[0]))


def test_read_chunks_rejects_a_record_whose_header_lies(tmp_path):
    path = tmp_path / "bad.umd"
    comp = zlib.compress(b"x" * 32)
    path.write_bytes(struct.pack(">II", 99, len(comp)) + comp)
    with pytest.raises(UmdError):
        read_chunks(path)


def test_read_chunks_rejects_a_non_zlib_payload(tmp_path):
    path = tmp_path / "bad2.umd"
    path.write_bytes(struct.pack(">II", 4, 4) + b"nope")
    with pytest.raises(UmdError):
        read_chunks(path)


def test_read_chunks_stops_at_a_truncated_tail(tmp_path):
    blob = _umd([b"a" * 16])
    path = tmp_path / "trunc.umd"
    path.write_bytes(blob + struct.pack(">II", 64, 64) + b"abc")
    chunks, end, size = read_chunks(path)
    assert len(chunks) == 1
    assert end < size


def test_read_chunks_bytes_matches_the_file_reader(tmp_path):
    payloads = [b"0_0_2.unr" + b"\x01" * 20, b"second" + b"\x02" * 10]
    blob = _umd(payloads)
    path = tmp_path / "y.umd"
    path.write_bytes(blob)
    assert read_chunks_bytes(blob, "y") == read_chunks(path)


@pytest.mark.skipif(not ISO.exists(), reason="owned Splinter Cell ISO is not unpacked here")
def test_owned_build_manifest_matches_the_disc():
    from gbox.splinter_inventory import inventory
    manifest = inventory(ISO)
    assert manifest["disc"]["disc_id"] == "GCEE41"
    assert manifest["disc"]["platform"] == "gamecube"
    assert manifest["disc"]["region"] == "NTSC-U"
    assert manifest["file_count"] == 316
    assert manifest["main_dol"]["entry"].startswith("0x8000")
    assert manifest["unpacked_iso"]["size"] == 1459978240
    assert len(manifest["unpacked_iso"]["sha256"]) == 64
    warlins = manifest["umd_archives"]["System/warlins.umd"]
    assert warlins["records"] == 74
    assert warlins["chunks"][0]["name"] == "0_0_2.unr"
    assert "0_0_2.unr" in warlins["named_records"]
    warship = manifest["umd_archives"]["System/warship.umd"]
    assert warship["is_ini_text"] is True
    assert warship["records"] == 0
