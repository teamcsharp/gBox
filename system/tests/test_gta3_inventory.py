"""GTA III (PS2) exact-build inventory (gbox/gta3_inventory.py, #1405 stage 1).

A synthetic ISO9660 disc exercises the whole streamed walker/capture/manifest path with
monkeypatched identity hashes; the real-disc case (env GBOX_GTA3_ROM pointing at the owned
.7z or .iso) verifies the pinned SLUS-20062 build constants and skips otherwise.
"""
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import gta3_inventory as I

SECTOR = 2048


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _dir_rec(entries):
    """One ISO9660 directory sector: entries are (name, lba, size, is_dir)."""
    buf = bytearray(SECTOR)
    o = 0
    for name, lba, size, is_dir in entries:
        nb = name.encode("ascii")
        ln = 33 + len(nb) + (1 if (33 + len(nb)) % 2 else 0)
        buf[o] = ln
        struct.pack_into("<I", buf, o + 2, lba)
        struct.pack_into(">I", buf, o + 6, lba)
        struct.pack_into("<I", buf, o + 10, size)
        buf[o + 25] = 2 if is_dir else 0
        buf[o + 32] = len(nb)
        buf[o + 33:o + 33 + len(nb)] = nb
        o += ln
    return bytes(buf)


def _pvd(root_lba, root_size):
    buf = bytearray(SECTOR)
    buf[1:6] = b"CD001"
    struct.pack_into("<I", buf, 158, root_lba)
    struct.pack_into("<I", buf, 166, root_size)
    return bytes(buf)


def make_synthetic_iso(path: Path) -> dict:
    """A minimal GTA III-shaped disc: root (SYSTEM.CNF, SLUS_200.62, MODELS, ANIM), two IMG
    copies, a 4-entry DIR, and the four player entries. Returns {name: sector_padded_sha}."""
    cnf = b"BOOT2 = cdrom0:\\SLUS_200.62;1\r\nVER = 1.40\r\nVMODE = NTSC"
    slus = b"\x7fELF" + bytes([1, 1, 1]) + b"\0" * 11 + struct.pack("<H", 8) + b"\0" * 4 \
        + struct.pack("<I", 0x100000) + b"\0" * 24
    ped = b"PED!" + b"\0" * (SECTOR - 4)
    ents = {n: n.encode("ascii").ljust(2040, b".") for n in
            ("player.dff", "player.txd", "playerp.dff", "playerp.txd")}
    names = list(ents)
    dir_buf = bytearray(SECTOR)
    for i, n in enumerate(names):
        struct.pack_into("<II", dir_buf, i * 32, i, 1)
        dir_buf[i * 32 + 8:i * 32 + 8 + len(n)] = n.encode("ascii")

    img_pad = [d + b"\0" * (SECTOR - len(d)) for d in ents.values()]

    secs = {16: _pvd(18, SECTOR),
            18: _dir_rec([("SYSTEM.CNF;1", 100, len(cnf), False), ("SLUS_200.62;1", 101, len(slus), False),
                          ("MODELS;1", 102, SECTOR, True), ("ANIM;1", 103, SECTOR, True)]),
            100: cnf, 101: slus,
            102: _dir_rec([("GTA3.IMG;1", 110, 4 * SECTOR, False), ("GTA3.DIR;1", 105, SECTOR, False),
                           ("GTA3_1.IMG;1", 114, 4 * SECTOR, False)]),
            103: _dir_rec([("PED.IFP;1", 104, SECTOR, False)]),
            104: ped, 105: bytes(dir_buf)}
    secs.update({110 + i: s for i, s in enumerate(img_pad)})
    secs.update({114 + i: s for i, s in enumerate(img_pad)})
    with open(path, "wb") as f:
        for i in range(0, 120):
            f.write((secs.get(i, b"") + b"\0" * SECTOR)[:SECTOR])
    return {"SYSTEM.CNF": _sha(cnf), "SLUS_200.62": _sha(slus), "PED.IFP": _sha(ped),
            "DIR": _sha(bytes(dir_buf)),
            **{n: _sha(d + b"\0" * (SECTOR - len(d))) for n, d in ents.items()}}


def test_dir_stats_and_dir_records(tmp_path):
    names = ("player.dff", "player.txd", "playerp.dff")
    buf = bytearray(128)
    for i, n in enumerate(names):
        struct.pack_into("<II", buf, i * 32, i * 3, 3)
        buf[i * 32 + 8:i * 32 + 8 + len(n)] = n.encode("ascii")
    stats = I.dir_stats(bytes(buf))
    assert stats["count"] == 3
    assert stats["by_extension"] == {"dff": 2, "txd": 1}
    assert [e["offset_sectors"] for e in stats["entries"]] == [0, 3, 6]

    sec = _dir_rec([("PLAYER.DFF;1", 7, 12, False), ("MODELS;1", 9, SECTOR, True)])
    recs = list(I.dir_records(sec, ""))
    assert recs == [("PLAYER.DFF", 7, 12, False), ("MODELS", 9, SECTOR, True)]


def test_elf_info():
    b = b"\x7fELF" + bytes([1, 1, 1]) + b"\0" * 11 + struct.pack("<H", 8) + b"\0" * 4 \
        + struct.pack("<I", 0x00100460) + b"\0" * 24
    info = I.elf_info(b)
    assert info["e_machine"] == 8 and info["entry"] == "0x100460" and info["class"] == 32


def test_inventory_synthetic_disc_full_path(tmp_path, monkeypatch):
    """The streamed walk + capture + manifest runs end to end on a synthetic disc."""
    disc = tmp_path / "synthetic.iso"
    want = make_synthetic_iso(disc)
    monkeypatch.setattr(I, "ISO_SHA256", _sha(disc.read_bytes()))
    monkeypatch.setattr(I, "SOURCE_7Z_SHA256", "synthetic")
    monkeypatch.setattr(I, "STOCK_SHA256", {n: want[n] for n in I.PLAYER_ENTRIES})
    monkeypatch.setattr(I, "PED_IFP_SHA256", want["PED.IFP"])

    m = I.inventory(disc, tmp_path / "out")
    assert m["source"]["iso_bytes"] == 120 * SECTOR
    assert m["executable"]["e_machine"] == 8
    assert m["container"]["dir"]["entries"] == 4
    assert m["container"]["dir"]["by_extension"] == {"dff": 2, "txd": 2}
    assert m["container"]["player_entries"]["player.dff"]["copies"] == 2
    assert m["container"]["player_entries"]["player.dff"]["lba"] == 110
    assert (tmp_path / "out" / "manifest.json").is_file()
    assert (tmp_path / "out" / "SLUS_200.62").is_file()
    assert (tmp_path / "out" / "player.dff").read_bytes() == b"player.dff".ljust(2040, b".") + b"\0" * 8


def test_inventory_refuses_unknown_image(tmp_path, monkeypatch):
    """Any disc whose hash is not the pinned owned build is refused before use."""
    disc = tmp_path / "other.iso"
    make_synthetic_iso(disc)
    with pytest.raises(ValueError, match="not the owned"):
        I.inventory(disc)


@pytest.mark.skipif(not os.environ.get("GBOX_GTA3_ROM"), reason="GBOX_GTA3_ROM not set")
def test_inventory_owned_disc_pinned_constants(tmp_path):
    """Real-disc acceptance: the owned .7z/.iso must reproduce every pinned constant."""
    m = I.inventory(Path(os.environ["GBOX_GTA3_ROM"]), tmp_path / "real")
    assert m["source"]["iso_sha256"] == I.ISO_SHA256
    assert m["source"]["iso_bytes"] == I.ISO_BYTES
    assert m["executable"]["e_machine"] == 8
    assert m["container"]["dir"]["entries"] > 3000
    for n, h in I.STOCK_SHA256.items():
        assert m["container"]["player_entries"][n]["sha256"] == h
        assert m["container"]["player_entries"][n]["copies"] == 12
    assert m["container"]["animation"]["sha256"] == I.PED_IFP_SHA256
    assert "SLUS_200.62" in m["launch"]["boot"]
