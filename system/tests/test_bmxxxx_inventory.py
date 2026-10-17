"""Focused tests for gbox.bmxxxx_inventory: ZAL directory, IFF chunk walk, FMDL summary.

These build synthetic little-endian Z-Axis containers in memory so the parser is pinned
without needing the 1.4 GB disc; a real-disc inventory runs only when the ISO is present
(GBOX_BMXXXX_ISO), so CI stays hermetic.
"""
import os
import struct
from pathlib import Path

from gbox.bmxxxx_inventory import iff_chunks, model_summary, zal_index


def _chunk(tag: str, payload: bytes) -> bytes:
    return tag.encode() + struct.pack("<I", len(payload)) + payload


def _zal(entries: list[tuple[str, bytes]]) -> bytes:
    """entries: list of (name, blob) -> a full ZAL archive."""
    body = b""
    grid, dlen, body_off, names = [], [], [], b""
    for name, blob in entries:
        grid.append(0)
        dlen.append(0x60000000 | len(blob))
        body_off.append(len(body))
        names += name.encode() + b"\0"
        body += blob
    count = len(entries)
    didf = _chunk("DIDF", struct.pack("<II", count, 0))
    grid_c = _chunk("GRID", struct.pack(f"<{count}I", *grid))
    dlen_c = _chunk("DLEN", struct.pack(f"<{count}I", *dlen))
    name_c = _chunk("NAME", names) if names else b""
    ofst_size = 8 + 4 * count
    data_base = 8 + len(didf) + len(grid_c) + len(dlen_c) + ofst_size + len(name_c)
    ofst_c = _chunk("OFST", struct.pack(f"<{count}I", *(data_base + o for o in body_off)))
    return _chunk("ZDIR", didf + grid_c + dlen_c + ofst_c + name_c) + body


def test_zal_index_roundtrip():
    a = _chunk("FMDL", _chunk("MODL", b"\x00" * 16))
    b = _chunk("FORM", _chunk("ANIM", b"\x01" * 8))
    z = _zal([("Skeleton", a), ("GFU_NudeTop", b)])
    es = zal_index(z)
    assert len(es) == 2
    assert es[0]["name"] == "Skeleton" and es[0]["tag"] == "FMDL" and es[0]["length"] == len(a)
    assert es[1]["name"] == "GFU_NudeTop" and es[1]["tag"] == "FORM" and es[1]["type"] == "ANIM"
    # the flag nibble 0x6 is stripped off the length
    assert es[0]["flag"] == 0x6


def test_zal_length_flag_masking():
    blob = b"\xde\xad\xbe\xef" * 4
    z = _zal([("", blob)])
    es = zal_index(z)
    assert es[0]["length"] == len(blob)          # low 28 bits survive the 0x6 flag
    assert es[0]["offset"] + es[0]["length"] <= len(z)


def test_iff_walk_and_model_summary():
    txc = _chunk("TXRC", struct.pack("<I", 1) + _chunk("TXRH", b"name\x00" * 2))
    txc2 = _chunk("TXRC", struct.pack("<I", 0))
    tgeo = _chunk("TGEO", _chunk("TGHD", b"\x00" * 32))
    tgin = _chunk("TGIN", b"\x00" * 8)
    modl = _chunk("MODL", txc + txc2 + tgeo + tgin)
    fmdl = _chunk("FMDL", modl)
    top = iff_chunks(fmdl)
    assert top[0]["tag"] == "FMDL" and top[0]["type"] == "MODL"
    s = model_summary(fmdl)
    assert s["tag"] == "FMDL" and s["texture_banks"] == 2
    assert s["geometry_chunks"] == 1 and s["instance_chunks"] == 1


def test_real_disc_inventory_if_present():
    iso = os.environ.get("GBOX_BMXXXX_ISO")
    if not iso or not os.path.exists(iso):
        import pytest
        pytest.skip("GBOX_BMXXXX_ISO not set (disc not required for the parser tests)")
    from gbox.bmxxxx_inventory import inventory
    m = inventory(Path(iso), source_sha256="0" * 64)
    assert m["image"]["disc_id"] == "GB3E51"
    assert m["fst_files"] > 300
    assert any(z["path"].endswith("models.zal") for z in m["zal_archives"])
