"""Tests for gbox.pd_inventory: Perfect Dark N64 ROM inventory."""

import struct
import zlib

import pytest

from gbox.pd_inventory import (
    kind_of,
    read_names,
    read_u32_table,
    unzip_pd,
    inventory_with,
)


def zip_container(payload: bytes, padding: bytes = b"") -> bytes:
    """Build a Rare 0x1173 zip container around `payload` plus padding."""
    co = zlib.compressobj(wbits=-15)
    body = co.compress(payload) + co.flush()
    return b"\x11\x73" + b"\x00\x00\x00" + body + padding


def test_kind_of():
    assert kind_of("Cdark_combatZ") == "chr"
    assert kind_of("Gfalcon2Z") == "gun"
    assert kind_of("Aexec01M") == "audio"
    assert kind_of("LameE") == "lang"
    assert kind_of("PtargetZ") == "prop"
    assert kind_of("UsetupameZ") == "setup"
    assert kind_of("bgdata/bg_ame.seg") == "bgroom"
    assert kind_of("bgdata/bg_ame_padsZ") == "bgpads"
    assert kind_of("bgdata/bg_ame_tilesZ") == "bgtiles"
    assert kind_of("ob/ob_mid.seg") == "other"


def test_unzip_pd_roundtrip():
    payload = b"hello perfect dark" * 10
    blob = zip_container(payload, padding=b"\xff\xfe")
    data, unused = unzip_pd(blob)
    assert data == payload
    assert unused == 2


def test_unzip_pd_rejects_garbage():
    with pytest.raises((ValueError, zlib.error)):
        unzip_pd(b"\x11\x73\x00\x00\x00\x00\x01\x02\x03\x04")


def test_read_u32_table():
    blob = struct.pack(">IIIII", 0, 0x100, 0x200, 0x300, 0) + b"tail"
    assert read_u32_table(blob, 0) == [0, 0x100, 0x200, 0x300]


def build_mini_rom():
    """A tiny ROM exercising the full parse path.

    Layout: 0x40-byte header, data segment at 0x100 (zip holding the file
    offset table), file 1 (raw) at 0x200, file 2 (zipped) at 0x220, name
    table at 0x280.
    """
    f0, f1, names_addr = 0x200, 0x220, 0x280
    table = struct.pack(">IIIII", 0, f0, f1, names_addr, 0)
    data_seg = zip_container(table)

    names = b"Cjoan\x00Gfalcon2Z\x00\x00"
    # three name relocations (names[0] matches the table's leading 0 and is
    # unused; names[i+1] names file i)
    name_rels = struct.pack(">IIII", 0x10, 0x10, 0x16, 0)

    rom = bytearray(0x300)
    rom[0:4] = b"\x80\x37\x12\x40"
    rom[0x20:0x2C] = b"Perfect Dark"
    rom[0x100:0x100 + len(data_seg)] = data_seg
    rom[f0:f1] = b"\x00" * (f1 - f0)  # raw file content (any bytes)
    rom[f1:f1 + len(zip_container(b"gun model"))] = zip_container(b"gun model")
    rom[names_addr:names_addr + len(name_rels)] = name_rels
    rom[names_addr + 0x10:names_addr + 0x10 + len(names)] = names
    return bytes(rom), f0, f1, names_addr


def test_inventory_with_mini_rom():
    rom, f0, f1, names_addr = build_mini_rom()
    manifest = inventory_with(rom, "pal-final", files_off=0, data_off=0x100)

    assert manifest["file_count"] == 2
    assert manifest["kinds"] == {"chr": 1, "gun": 1}
    assert manifest["characters"] == ["joan"]

    f0entry = manifest["files"][0]
    assert f0entry["name"] == "Cjoan"
    assert f0entry["kind"] == "chr"
    assert f0entry["offset"] == f0 and f0entry["end"] == f1
    assert f0entry["zipped"] is False

    f1entry = manifest["files"][1]
    assert f1entry["name"] == "Gfalcon2Z"
    assert f1entry["zipped"] is True
    assert f1entry["dec_size"] == len(b"gun model")
    assert f1entry["dec_sha256"] is not None


def test_read_names_bounds():
    rom, _, _, names_addr = build_mini_rom()
    names = read_names(rom, names_addr, 3)
    assert names == ["Cjoan", "Cjoan", "Gfalcon2Z"]
