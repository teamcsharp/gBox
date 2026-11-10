"""Focused tests for gbox.thrasher_psx_inventory.

Synthetic tests (no disc) validate the ZAL header parser, the PS-X EXE header
parser and the TABLES.ZAL name->file decoder against hand-built byte buffers.
Tests tagged ``owned`` run only when the owned Thrasher disc image is present
(env ``THRASHER_BIN``) and validate the parsers against the real mastered
image, including the stable SHA256 identity constants.
"""

import os
import struct

import pytest

from gbox.thrasher_psx_inventory import (
    DISK_BIN_SHA256,
    EXE_SHA256,
    LEVEL_ZALS,
    ZAL_MAGIC,
    exe_header,
    parse_tables_zal,
    zal_header,
)


def _zal(count: int) -> bytes:
    """Build a minimal ZAL header: magic + 12 zero bytes + ver=1 + count."""
    return struct.pack("<I", ZAL_MAGIC) + bytes(12) + struct.pack("<HH", 1, count)


def test_zal_header_confirmed_fields():
    h = zal_header(_zal(18))
    assert h["magic"] == ZAL_MAGIC
    assert h["version"] == 1
    assert h["kind"] == "table"
    assert h["count"] == 18


def test_zal_header_data_kind_flag():
    h = zal_header(struct.pack("<I", ZAL_MAGIC) + bytes(12) + struct.pack("<HH", 0x8001, 16609))
    assert h["kind"] == "data"


def test_zal_header_bad_magic_raises():
    with pytest.raises(ValueError):
        zal_header(b"\x00\x00\x00\x00" + bytes(16))


def test_zal_header_short_input_raises():
    with pytest.raises(ValueError):
        zal_header(b"")


def test_exe_header_standard_layout():
    # PS-X EXE: magic, then at 0x10 the 10-word table pc0/gp0/t_addr/t_size/...
    hdr = bytearray(0x800)
    hdr[:8] = b"PS-X EXE"
    struct.pack_into("<10I", hdr, 0x10,
                     0x8005D1B0, 0, 0x80010000, 0x7B000, 0, 0, 0, 0, 0x801FFF00, 0)
    hdr[0x4C:0x4C + 8] = b"N.A.\x00\x00\x00\x00"
    h = exe_header(bytes(hdr))
    assert h["magic"] == "PS-X EXE"
    assert h["pc0"] == 0x8005D1B0
    assert h["t_addr"] == 0x80010000 and h["t_size"] == 0x7B000
    assert h["text_span"] == (0x80010000, 0x80010000 + 0x7B000)


def test_exe_header_bad_magic():
    assert exe_header(b"NOTANEXE" + bytes(0x800))["magic"] is None


def _tables_record(name: bytes, zalname: bytes) -> bytes:
    """One TABLES.ZAL row matching the real layout: 16-byte title
    (left-justified, null-padded) + 12-byte filename (right-justified,
    null-led) ending in '.ZAL'."""
    return name.ljust(16, b"\0") + zalname.rjust(12, b"\0") + b".ZAL"


def test_parse_tables_zal_extracts_filenames():
    body = (
        _tables_record(b"SFHILL", b"SF_HILL")
        + _tables_record(b"INDO", b"HM_INDUS")
        + b"\x00" * 16  # trailing pad
    )
    recs = parse_tables_zal(body)
    assert [r["zal"] for r in recs] == ["SF_HILL", "HM_INDUS"]
    # title fragments survive null-stripping
    assert recs[0]["name"].startswith("SFHILL")


# --- owned-disc tests (gated) -------------------------------------------

BIN = os.environ.get("THRASHER_BIN", "")


@pytest.mark.skipif(not (BIN and os.path.isfile(BIN)), reason="owned disc not present")
class TestOwnedDisc:
    def test_disc_identity_sha256(self):
        from gbox.thrasher_psx_inventory import _sha256
        assert _sha256(BIN) == DISK_BIN_SHA256

    def test_exe_header_matches_boot_exe(self):
        from gbox import psxdisc
        rb = psxdisc.RawBin(BIN, writable=False)
        try:
            raw = rb.read("SLUS_009.35")
            from gbox.thrasher_psx_inventory import _sha256
            assert raw[:8] == b"PS-X EXE"
            h = exe_header(raw)
            assert h["t_addr"] == 0x80010000
            assert h["s_addr"] == 0x801FFF00
        finally:
            rb.close()

    def test_every_level_zal_has_header(self):
        from gbox import psxdisc
        rb = psxdisc.RawBin(BIN, writable=False)
        try:
            for lvl in LEVEL_ZALS:
                data = rb.read(f"ASSETS/{lvl}.ZAL")
                h = zal_header(data)
                assert h["magic"] == ZAL_MAGIC
                assert h["kind"] == "data"        # level archives are data ZALs
                assert h["version"] >= 0x8000
        finally:
            rb.close()

    def test_metadata_zal_files_are_table_kind(self):
        from gbox import psxdisc
        rb = psxdisc.RawBin(BIN, writable=False)
        try:
            for name in ("TABLES", "GEOMETRY", "MISCDATA", "REPLAY"):
                h = zal_header(rb.read(f"ASSETS/{name}.ZAL"))
                assert h["kind"] == "table"
                assert h["version"] == 0x0001
        finally:
            rb.close()

    def test_tables_zal_maps_real_level_files(self):
        from gbox import psxdisc
        rb = psxdisc.RawBin(BIN, writable=False)
        try:
            recs = parse_tables_zal(rb.read("ASSETS/TABLES.ZAL"))
            zals = {r["zal"] for r in recs}
            # every on-disc level archive is referenced from the table
            missing = set(LEVEL_ZALS) - zals - {"RBINTART"}
            assert not missing, f"levels missing from TABLES.ZAL: {missing}"
        finally:
            rb.close()
