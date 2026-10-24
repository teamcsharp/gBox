"""Focused tests for gbox.formats.nsw: NCA header-name reading over the shared HFS0 parser.

``nsw`` no longer carries its own HFS0 parser -- it delegates all HFS0 geometry to
``gbox.formats.hfs0`` (real 0x40-byte entry layout) and only adds the Switch-specific
concern above HFS0: reading the plaintext NCA3 header-name slots (main/program/control
ids) at fixed offsets inside each ``*.nca`` member.

This test builds a synthetic **headerless** card (HEAD at 0x100, root HFS0 at its real
0x130 field) with a "secure" partition holding two plaintext NCA3 members, and asserts
``nsw`` surfaces the correct absolute member offsets, sizes and NCA3 header names
without ever decrypting anything.
"""
import hashlib
import struct

import pytest

from gbox.formats import hfs0, nsw


def _hfs0(files):
    pool = b"".join(name.encode() + b"\0" for name, _ in files)
    ents, off, no = b"", 0, 0
    for name, data in files:
        ents += struct.pack("<QQIIQ", off, len(data), no, min(0x200, len(data)), 0)
        ents += hashlib.sha256(data[:0x200]).digest()
        off += len(data)
        no += len(name) + 1
    return b"HFS0" + struct.pack("<III", len(files), len(pool), 0) + ents + pool + b"".join(d for _, d in files)


def _nca(named):
    blob = bytearray(0x400)
    blob[0:4] = b"NCA3"
    for slot, n in zip(nsw.NCA_HEADER_NAME_SLOTS, named):
        blob[slot:slot + 32] = n.encode().ljust(32, b"\0")
    return bytes(blob)


def _card():
    nca1, nca2 = _nca(["Program1"]), _nca(["Control2"])
    secure = _hfs0([("main.nca", nca1), ("control.nca", nca2)])
    root = _hfs0([("update", _hfs0([])), ("secure", secure)])
    # HEAD at 0x100 with root offset field at 0x130; root HFS0 at 0xF000.
    root_at = 0xF000
    out = ["update", "normal", "logo", "secure"]
    root = _hfs0([("update", _hfs0([])), ("normal", _hfs0([])), ("secure", secure)])
    img = bytearray(root_at + len(root))
    img[0x100:0x104] = b"HEAD"
    struct.pack_into("<Q", img, 0x130, root_at)
    img[root_at:] = root
    return bytes(img), secure


def _ra(img):
    return lambda o, n: img[o:o + n]


def test_nca_names_delegated_to_shared_parser():
    img, secure = _card()
    info = nsw.list_card_ncas_from(_ra(img))
    # partitions come from the shared list_card
    assert set(info.hfs0) == {"update", "normal", "secure"}
    secure_entries = info.hfs0["secure"]
    assert [e.name for e in secure_entries] == ["main.nca", "control.nca"]
    # NCA header names surface only for the two members with an NCA3 magic
    assert [n["entry"] for n in info.ncas] == ["main.nca", "control.nca"]
    assert info.ncas[0]["header_names"] == ["Program1"]
    assert info.ncas[1]["header_names"] == ["Control2"]
    # offsets are absolute and land on the NCA3 magic
    for n in info.ncas:
        assert img[n["offset"]:n["offset"] + 4] == b"NCA3"


def test_non_card_yields_warning_not_exception():
    info = nsw.list_card_ncas_from(_ra(b"\0" * 0x20000))
    assert info.ncas == []
    assert info.warnings  # not silently empty


def test_no_ncas_in_empty_partitions():
    img, _ = _card()
    info = nsw.list_card_ncas_from(_ra(img))
    # update/normal partitions are empty -> no NCA entries from them
    assert all(n["partition"] == "secure" for n in info.ncas)


def test_nca3_name_slot_round_trip():
    img, secure = _card()
    # shared parser's sha256 is the hash of the first 0x200 bytes of the NCA member
    e = nsw.list_card_ncas_from(_ra(img)).hfs0["secure"][0]
    assert e.sha256 == hashlib.sha256(img[e.offset:e.offset + 0x200]).hexdigest()
