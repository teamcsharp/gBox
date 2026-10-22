"""Focused tests for the AC4 native asset probes.

Offline cases use synthetic blobs; the owned-ISO cases are skipped when the
image is not mounted.
"""
from __future__ import annotations

import hashlib
import importlib
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ISO = Path("/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Armored Core 4.iso")
BS = b"\\"


def _load(name):
    for base in (ROOT, ROOT / "system"):
        pkg = base / "gbox"
        if (pkg / "__init__.py").exists() or (pkg / (name + ".py")).exists():
            if str(base) not in sys.path:
                sys.path.insert(0, str(base))
            break
    return importlib.import_module("gbox." + name)


probe = _load("ac4_native_probe")
inv = _load("ac4_inventory")

needs_iso = pytest.mark.skipif(not ISO.exists(), reason="owned Armored Core 4 ISO not mounted")


def _win(*parts):
    return BS.join(parts)


def _rmb_blob(name=b"s000_000", size=2332):
    path = _win(b"N:", b"AC4", b"data", b"model", b"poly", b"m000", b"ap2",
                name + b".ap2")
    blob = bytearray(0x100)
    struct.pack_into(">2I", blob, 0, 1, size)
    struct.pack_into(">I", blob, 0x4C, len(name))
    struct.pack_into(">I", blob, 0x50, 17)
    blob[0x54:0x54 + len(name)] = name
    blob[0x54 + len(name)] = 0
    off = 0x55 + len(name)
    blob[off:off + len(path)] = path
    return bytes(blob)


def _anc_blob():
    blob = bytearray(0x80)
    blob[0x20:0x28] = b"#ANIEDIT"
    blob[0x30:0x3A] = b"ac_4_n.ane"
    blob[0x40:0x43] = b"ANE"
    return bytes(blob)


def _member(parts, want):
    sector, length = inv.resolve(ISO, parts)
    entries = inv.parse_dir(inv.extract(ISO, sector, length))
    for e in entries:
        if e.name == want:
            return e
    raise AssertionError("member %s not found under %s" % (want, parts))


def test_parse_rmb_header_synthetic():
    h = probe.parse_rmb_header(_rmb_blob())
    assert h["version"] == 1
    assert h["declared_size"] == 2332
    assert h["name"] == "s000_000"
    assert h["name_len"] == 8
    assert h["root_prefix_len"] == 17
    assert h["path_slashes"].startswith("N:/AC4/data/model/")
    assert h["path_slashes"].endswith("s000_000.ap2")


def test_parse_anc_header_synthetic():
    h = probe.parse_anc_header(_anc_blob())
    assert h["magic"] == "#ANIEDIT"
    assert h["magic_offset"] == 0x20
    assert h["name"] == "ac_4_n.ane"
    assert h["tag"] == "ANE"


def test_sector_offset():
    assert probe.sector_offset(1199028) == 1199028 * 2048


def test_member_row_digest():
    blob = _anc_blob()
    row = probe.member_row("ane/ac/ac_4_n.anc", 6049, len(blob), blob)
    assert row["container"] == "XDVDFS"
    assert row["byte_offset"] == 6049 * 2048
    assert row["sha256"] == hashlib.sha256(blob).hexdigest()


@needs_iso
def test_owned_rmb_header_matches_member_size():
    e = _member(("model", "poly", "m000"), "s000_000.rmb")
    blob = inv.extract(ISO, e.sector, e.size)
    h = probe.parse_rmb_header(blob)
    assert h["version"] == 1
    assert h["declared_size"] == e.size
    assert h["name"] == "s000_000"
    assert h["name_len"] == len(h["name"])
    assert h["path_slashes"].endswith("s000_000.ap2")


@needs_iso
def test_owned_second_rmb_header_matches_member_size():
    e = _member(("model", "poly", "m000"), "s900_000.rmb")
    blob = inv.extract(ISO, e.sector, e.size)
    h = probe.parse_rmb_header(blob)
    assert h["declared_size"] == e.size
    assert h["name"] == "s900_000"
    assert h["name_len"] == len(h["name"])


@needs_iso
def test_owned_anc_header():
    e = _member(("ane", "ac"), "ac_4_n.anc")
    blob = inv.extract(ISO, e.sector, e.size)
    h = probe.parse_anc_header(blob)
    assert h["magic"] == "#ANIEDIT"
    assert h["name"] == "ac_4_n.ane"
    assert h["tag"] == "ANE"


@needs_iso
def test_owned_manifest_row():
    e = _member(("ane", "ac"), "ac_4_n.anc")
    blob = inv.extract(ISO, e.sector, e.size)
    row = probe.member_row("ane/ac/ac_4_n.anc", e.sector, e.size, blob)
    assert row["sector"] == e.sector
    assert row["size"] == e.size
    assert row["byte_offset"] == e.sector * 2048
    assert row["sha256"] == hashlib.sha256(blob).hexdigest()
