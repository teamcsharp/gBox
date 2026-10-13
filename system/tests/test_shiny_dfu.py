"""Shiny's WAD1.DFU archive (gbox.shiny_dfu): both name hashes against names the owned discs answer to, reading
(packed entries, entries straddling WAD1 / WAD1_B), in-place replacement plans and the table checks."""
import struct
import zlib

import pytest

from gbox import shiny_dfu as D
from matrix_synth import make_dfu, make_iso
from gbox.defjam_inventory import Iso

SEEDS = (22313, 2067, 674)


class Disc:
    """files / size / read like gbox.chd.ChdDisc."""

    def __init__(self, parts: dict):
        self.blobs = parts
        self.files = {k: (100 + i * 1000, len(v)) for i, (k, v) in enumerate(parts.items())}

    def size(self, n):
        return len(self.blobs[n])

    def read(self, n, off=0, size=None):
        b = self.blobs[n]
        size = len(b) - off if size is None else size
        assert 0 <= off and off + size <= len(b)
        return b[off:off + size]


def test_name_hashes_match_the_owned_tables():
    # rows the owned discs' tables hold for these names (ETM SLUS_204.54, PoN SLUS_212.73)
    assert D.name_hash("Animation\\AnimList.txt", SEEDS) == 0x0CB4474A
    assert D.name_hash("Actors\\ActorHeadersV4.Bin", SEEDS) == 0x100A3663
    assert D.name_hash("actors/ActorHeadersV4.BIN", SEEDS) == 0x100A3663          # case and slash insensitive
    assert D.name_hash("Fonts\\Matrix.ftx", SEEDS) == 0x062E4B43
    assert D.name_hash("common\\misc\\ActorHeadersV11.Bin", SEEDS, "pon") == 3303543266
    assert D.name_hash("levels\\_global.rmp_5", SEEDS, "pon") == 958883721            # hashed as ps2\levels\...
    assert D.name_hash("levels\\b5_lobby.lvl_3", SEEDS, "pon") == 0x30C8481C
    assert D.name_hash("levels\\b5_lobby.lvl_3", SEEDS, "etm") != 0x30C8481C


@pytest.mark.parametrize("variant", ["etm", "pon"])
def test_read_packed_and_split_entries(variant):
    files = {"actors\\a.dcn": b"A" * 5000, "Animation\\AnimList.txt": b"one.asb\ntwo.asb\n" * 50,
             "levels\\big.lvl_3": bytes(range(256)) * 40}
    w1, w2 = make_dfu(files, variant, packed={"Animation\\AnimList.txt"}, split=6000)
    assert w2                                              # the last entry straddles into WAD1_B
    d = D.Dfu(Disc({"WAD1.DFU": w1, "WAD1_B.DFU": w2}), variant)
    assert d.count == 3 and d.base == 0x800 and d.seeds == SEEDS
    for name, blob in files.items():
        assert d.read(name) == blob
    e = d.entry("Animation\\AnimList.txt")
    assert e.compressed and e.size == len(files["Animation\\AnimList.txt"])
    assert len(d.spans(d.entry("levels\\big.lvl_3"))) == 2
    assert "nothing\\here" not in d


def test_replace_plan_patches_in_place_and_refuses_overflow():
    files = {"actors\\a.dcn": bytes(range(256)) * 64, "actors\\b.dcn": b"B" * 3000}
    w1, w2 = make_dfu(files, packed={"actors\\a.dcn"})
    disc = Disc({"WAD1.DFU": w1, "WAD1_B.DFU": w2})
    d = D.Dfu(disc)
    new = bytes(20000)                                     # compresses far below the slot
    plan = d.replace_plan("actors\\a.dcn", new)
    img = bytearray(w1)
    for part, off, blob in plan["patches"]:
        assert part == "WAD1.DFU"
        img[off:off + len(blob)] = blob
    d2 = D.Dfu(Disc({"WAD1.DFU": bytes(img), "WAD1_B.DFU": w2}))
    assert d2.read("actors\\a.dcn") == new and d2.read("actors\\b.dcn") == files["actors\\b.dcn"]
    row = struct.unpack_from("<4I", bytes(img), 0x18 + 16 * plan["entry"].index)
    assert row[1] == plan["packed"] and row[3] == len(new)
    with pytest.raises(D.DfuError):
        d.replace_plan("actors\\b.dcn", b"C" * 3001)        # raw entry: must keep its size
    with pytest.raises(D.DfuError):
        d.replace_plan("actors\\a.dcn", bytes(__import__("os").urandom(40000)))   # incompressible: no room
    abs_ = D.image_patches(disc, plan)
    assert abs_[0][0] == disc.files["WAD1.DFU"][0] * 2048 + plan["patches"][0][1]


def test_table_checks():
    w1, w2 = make_dfu({"x": b"1" * 100, "y": b"2" * 100})
    bad = bytearray(w1)
    a, b = struct.unpack_from("<I", bad, 0x18)[0], struct.unpack_from("<I", bad, 0x28)[0]
    struct.pack_into("<I", bad, 0x18, b)
    struct.pack_into("<I", bad, 0x28, a)                    # unsorted
    with pytest.raises(D.DfuError):
        D.Dfu(Disc({"WAD1.DFU": bytes(bad), "WAD1_B.DFU": w2}))
    bad = bytearray(w1)
    struct.pack_into("<I", bad, 0x18 + 8, 10 ** 7)          # offset past the end
    with pytest.raises(D.DfuError):
        D.Dfu(Disc({"WAD1.DFU": bytes(bad), "WAD1_B.DFU": w2}))
    bad = bytearray(w1)
    struct.pack_into("<I", bad, 0, 10 ** 6)                 # count
    with pytest.raises(D.DfuError):
        D.Dfu(Disc({"WAD1.DFU": bytes(bad), "WAD1_B.DFU": w2}))
    with pytest.raises(D.DfuError):
        D.Dfu(Disc({"OTHER.BIN": b""}))
    w1, w2 = make_dfu({"z": b"zz" * 300}, packed={"z"})
    bad = bytearray(w1)
    e = D.Dfu(Disc({"WAD1.DFU": w1, "WAD1_B.DFU": w2})).entry("z")
    bad[0x800 + e.offset:0x800 + e.offset + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(D.DfuError):
        D.Dfu(Disc({"WAD1.DFU": bytes(bad), "WAD1_B.DFU": w2})).read("z")


def test_works_on_an_iso9660_image(tmp_path):
    w1, w2 = make_dfu({"Actors\\ModelHeadersV4.Bin": b"actors\\x.dcn".ljust(80, b"\0")})
    p = tmp_path / "d.iso"
    p.write_bytes(make_iso({"WAD1.DFU": w1, "WAD1_B.DFU": w2}))
    d = D.Dfu(Iso(p))
    assert d.read("Actors\\ModelHeadersV4.Bin").startswith(b"actors\\x.dcn")
    assert zlib.crc32(d.raw(d.entries[0])) == zlib.crc32(b"actors\\x.dcn".ljust(80, b"\0"))
