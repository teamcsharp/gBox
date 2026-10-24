"""A .xci must be routed to the Switch card reader, not refused as an unknown disc."""
from __future__ import annotations

import pytest

from gbox.formats import disc, nsw, xci


def _card(payload: bytes, at: int = 0x100) -> bytes:
    b = bytearray(b"\x00" * 0x7100)
    b[0:4] = b"XCI0"
    b[0x7000] = 0x01                      # NCSD slot present -> plaintext partition table
    b[at:at + len(payload)] = payload
    return bytes(b)


def test_xci_is_listed_through_the_card_reader(monkeypatch, tmp_path):
    payload = b"PAYLOAD!"
    p = tmp_path / "Card.xci"
    p.write_bytes(_card(payload))

    class _E:
        name = "main"
        offset = 0x100
        size = len(payload)
        sha256 = "0" * 64

    class _Info:
        partitions = []
        hfs0 = {"update": [_E()]}
        ncas = []
        warnings = []

    monkeypatch.setattr(nsw, "list_xci", lambda path: _Info())
    L = disc.listing(str(p))
    assert L.kind == "xci"
    assert [f["path"] for f in L.files] == ["update/main"]
    assert L.files[0]["size"] == len(payload)
    assert L.files[0]["head"] == payload


def test_xci_without_a_plaintext_header_names_the_prerequisite(tmp_path):
    p = tmp_path / "Encrypted.xci"
    p.write_bytes(b"\x18\x64\xf7\x4b" + b"\x00" * 0x2000)
    with pytest.raises(ValueError) as exc:
        disc.listing(str(p))
    msg = str(exc.value)
    assert "not a disc image, ROM, archive or folder gBox can list" not in msg
    assert "Encrypted.xci" in msg
    assert "layout=" in msg


def test_owned_card_header_classifies_consistently():
    src = ("/mnt/gbox/hyperspin/Arcade/collections/Nintendo Switch/roms/"
           "Crash Team Racing - Nitro Fueled.xci")
    import os
    if not os.path.exists(src):
        pytest.skip("owned share not mounted")
    with open(src, "rb") as fh:
        head = fh.read(0x7040)
    card = xci.classify(head, os.path.getsize(src), src)
    if head[0:4] == b"XCI0":
        assert card.layout == "standard"
        assert card.partition_table_readable
    else:
        assert card.layout != "standard"
        assert not card.partition_table_readable
