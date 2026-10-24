"""Focused tests for the Star Fox - Assault native C3D/CHD/CBD inventory reader."""
import hashlib
import os
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbox.sfa_inventory import (  # noqa: E402
    MAGIC_C3D,
    MAGIC_CHD,
    character_roster,
    describe_disc,
    disc_identity,
    group_triplets,
    member_table,
    parse_header,
    read_asset,
    read_member,
    source_sha256,
)

ISO = os.environ.get(
    "SFA_ISO", "/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Star Fox - Assault (USA).iso"
)
HAVE_ISO = os.path.exists(ISO)


def _header(magic=MAGIC_C3D, version=0x0110, kind=0x21, count=3, table=0x40, blob=0x93E0):
    return magic + struct.pack(">HHHHI", version, kind, count, table, blob)


def test_parse_header_fields():
    head = parse_header(_header())
    assert head.magic == "C3Dp"
    assert head.version == 0x0110
    assert head.kind == 0x21
    assert head.count == 3
    assert head.table_offset == 0x40
    assert head.blob_size == 0x93E0


def test_parse_header_accepts_chd_magic():
    assert parse_header(_header(magic=MAGIC_CHD)).magic == "CHDp"


def test_parse_header_rejects_foreign_magic():
    with pytest.raises(ValueError):
        parse_header(b"AFS\x00" + b"\x00" * 20)


def test_parse_header_rejects_truncated_buffer():
    with pytest.raises(ValueError):
        parse_header(b"C3Dp")


def test_group_triplets_joins_members():
    entries = [
        {"path": "se/vs_chr1.c3d", "size": 2564},
        {"path": "se/vs_chr1.chd", "size": 2304},
        {"path": "se/vs_chr1.cbd", "size": 105440},
        {"path": "se/a0131.c3d", "size": 604},
        {"path": "fpc/vs_gfox.fpc", "size": 1664},
    ]
    joined = group_triplets(entries)
    assert set(joined) == {"vs_chr1", "a0131"}
    assert joined["vs_chr1"]["cbd"]["size"] == 105440


def test_roster_roles():
    entries = [
        {"path": f"se/{name}.{ext}", "size": 10}
        for name in ("se_p", "vs_chr1", "tel01")
        for ext in ("c3d", "chd", "cbd")
    ]
    roles = {row["name"]: row["role"] for row in character_roster(group_triplets(entries))}
    assert roles["se_p"] == "player"
    assert roles["vs_chr1"] == "versus_character"
    assert roles["tel01"] == "asset"


@pytest.mark.skipif(not HAVE_ISO, reason="owned Star Fox - Assault disc is not mounted")
def test_owned_disc_identity_is_the_real_build():
    ident = disc_identity(ISO)
    assert ident["game_code"] == "GF7E01"
    assert ident["title"].strip() == "STARFOX ASSAULT"
    assert ident["fst_size"] > 0
    assert ident["dol_offset"] > 0


@pytest.mark.skipif(not HAVE_ISO, reason="owned Star Fox - Assault disc is not mounted")
def test_member_table_uses_absolute_iso_offsets():
    table = member_table(ISO)
    assert len(table) == 962
    offset, size = table["se/se_p.c3d"]
    assert offset > 0x10000
    assert size > 16


@pytest.mark.skipif(not HAVE_ISO, reason="owned Star Fox - Assault disc is not mounted")
def test_read_member_returns_exact_bytes_and_honours_expected_size():
    table = member_table(ISO)
    offset, size = table["se/se_p.c3d"]
    data = read_member(ISO, "se/se_p.c3d", table=table)
    assert len(data) == size
    assert data[:4] == MAGIC_C3D
    with open(ISO, "rb") as fh:
        fh.seek(offset)
        assert fh.read(size) == data
    with pytest.raises(ValueError):
        read_member(ISO, "se/se_p.c3d", expected_size=size + 1, table=table)
    with pytest.raises(KeyError):
        read_member(ISO, "se/does_not_exist.c3d", table=table)


@pytest.mark.skipif(not HAVE_ISO, reason="owned Star Fox - Assault disc is not mounted")
def test_owned_disc_triplets_validate_against_cbd_size():
    manifest = describe_disc(ISO)
    assert manifest["kind"] == "gc_disc"
    assert manifest["executable"] == "main.dol"
    assert manifest["triplet_count"] == 100
    assert manifest["blob_size_checked"] == manifest["triplet_count"]
    assert manifest["blob_size_matched"] == manifest["triplet_count"]
    assert manifest["blob_size_mismatches"] == []


@pytest.mark.skipif(not HAVE_ISO, reason="owned Star Fox - Assault disc is not mounted")
def test_owned_player_asset_headers_match_cbd_length():
    manifest = describe_disc(ISO)
    row = next(r for r in manifest["roster"] if r["name"] == "se_p")
    asset = read_asset(ISO, "se_p")
    assert asset["header"]["magic"] == "C3Dp"
    assert asset["chd_header"]["magic"] == "CHDp"
    assert len(asset["cbd"]) == row["cbd_size"]
    assert asset["header"]["blob_size"] == len(asset["cbd"])
    assert asset["chd_header"]["blob_size"] == len(asset["cbd"])
    assert asset["sha256"]["cbd"] == hashlib.sha256(asset["cbd"]).hexdigest()


@pytest.mark.skipif(not HAVE_ISO, reason="owned Star Fox - Assault disc is not mounted")
def test_source_hash_is_streamed_from_the_owned_image():
    digest = source_sha256(ISO)
    assert len(digest) == 64
    reference = hashlib.sha256()
    with open(ISO, "rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            reference.update(chunk)
    assert digest == reference.hexdigest()
