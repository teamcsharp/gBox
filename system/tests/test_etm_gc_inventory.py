"""GameCube archive byte order, bounded reads and offline inventory identity; no gameplay claims."""
import hashlib
import io
import os
from pathlib import Path
import struct

import pytest

from gbox import etm_gc_inventory as G, shiny_dfu as D
from test_shiny_dfu import Disc
from matrix_synth import make_dfu


def archive(files, *, endian=">", packed=(), split=None):
    one, two = make_dfu(files, packed=set(packed), split=split)
    if endian == ">":
        one = bytearray(one)
        count = struct.unpack_from("<I", one)[0]
        header = struct.unpack_from("<6I", one)
        rows = [struct.unpack_from("<4I", one, 0x18 + 16 * i) for i in range(count)]
        struct.pack_into(">6I", one, 0, *header)
        for i, row in enumerate(rows):
            struct.pack_into(">4I", one, 0x18 + 16 * i, *row)
        one = bytes(one)
    return Disc({"wad2.dfu": one, "wad2_b.dfu": two})


@pytest.mark.parametrize("endian", ["<", ">"])
def test_endian_named_parts_split_read_and_replacement(endian):
    files = {"actors\\a.dcn": b"A" * 5000, "z": b"xyz" * 3000}
    disc = archive(files, endian=endian, packed={"z"}, split=4000)
    dfu = D.Dfu(disc, endian=endian, parts=G.DFU_PARTS)
    assert len(dfu.spans(dfu.entry("actors\\a.dcn"))) == 2
    assert {name: dfu.read(name) for name in files} == files
    plan = dfu.replace_plan("z", b"y" * 3000)
    # The replacement directory belongs to the configured first part, with its native byte order.
    part, off, row = plan["patches"][-1]
    assert part == "wad2.dfu"
    assert struct.unpack(endian + "4I", row)[3] == 3000
    for part, off, data in plan["patches"]:
        blob = bytearray(disc.blobs[part]); blob[off:off + len(data)] = data
        disc.blobs[part] = bytes(blob)
    rebuilt = D.Dfu(disc, endian=endian, parts=G.DFU_PARTS)
    assert rebuilt.read("z") == b"y" * 3000
    assert rebuilt.read("actors\\a.dcn") == files["actors\\a.dcn"]


@pytest.mark.parametrize("kwargs", [
    {"endian": "="}, {"endian": "!"}, {"endian": "junk"},
    {"parts": ()}, {"parts": "wad2.dfu"}, {"parts": ("",)},
    {"parts": ("wad2.dfu", "wad2.dfu")}, {"parts": (1,)},
])
def test_bad_archive_options_fail_before_read(kwargs):
    class NoRead:
        def read(self, *args): pytest.fail("invalid options must fail before I/O")
    with pytest.raises(D.DfuError):
        D.Dfu(NoRead(), **kwargs)


@pytest.mark.parametrize("truncate_at", [0, 0x18, 0x800])
def test_short_part_reads_are_explicit_errors(truncate_at):
    disc = archive({"x": b"x" * 40})
    original = disc.read
    disc.read = lambda name, off, size: original(name, off, size)[:-1] if off == truncate_at else original(name, off, size)
    with pytest.raises(D.DfuError, match="short read"):
        dfu = D.Dfu(disc, endian=">", parts=G.DFU_PARTS)
        dfu.read("x")


def test_declared_size_limit_prevents_content_read():
    disc = archive({"x": b"x" * 10000}, packed={"x"})
    dfu = D.Dfu(disc, endian=">", parts=G.DFU_PARTS)
    disc.read = lambda *args: pytest.fail("oversize entry should not be read")
    with pytest.raises(D.DfuError, match="exceeds read limit"):
        dfu.read("x", max_size=100)


def test_inflate_stops_at_declared_output_size():
    disc = archive({"x": b"x" * 10000}, packed={"x"})
    raw = bytearray(disc.blobs["wad2.dfu"])
    struct.pack_into(">I", raw, 0x18 + 12, 100)  # stream actually expands to 10,000
    disc.blobs["wad2.dfu"] = bytes(raw)
    dfu = D.Dfu(disc, endian=">", parts=G.DFU_PARTS)
    with pytest.raises(D.DfuError, match="exceeds its size"):
        dfu.read("x")


@pytest.mark.parametrize("offset,size", [(-1, 1), (0, -1), (3, 2), (True, 1), (1, 1.5)])
def test_gc_file_read_never_crosses_file_boundary(offset, size):
    class Fake:
        files = {"part": (100, 4)}
        def _r(self, *args): pytest.fail("invalid range must not reach disc")
    with pytest.raises(G.FormatError, match="leaves the FST file"):
        G.GcDisc(Fake()).read("part", offset, size)


def test_gc_adapter_exact_read_and_absolute_patch_offsets():
    class Fake:
        files = {"part": (100, 4)}
        def _r(self, off, size):
            assert (off, size) == (101, 2)
            return b"ok"
    adapter = G.GcDisc(Fake())
    assert adapter.read("part", 1, 2) == b"ok"
    assert D.image_patches(adapter, {"patches": [("part", 1, b"ok")]}) == [(101, b"ok")]
    with pytest.raises(D.DfuError):
        D.image_patches(adapter, {"patches": [("part", -1, b"ok")]})
    adapter.disc._r = lambda *args: b"x"
    with pytest.raises(G.FormatError, match="short read"):
        adapter.read("part", 1, 2)


def fake_identity_disc(monkeypatch, *, section_offset=0x100, section_size=0x20, disc_number=1, revision=0):
    header = bytearray(0x440)
    header[:8] = b"GMXE70" + bytes([disc_number, revision])
    struct.pack_into(">I", header, 0x420, 0x1000)
    dol = bytearray(0x120)
    struct.pack_into(">I", dol, 0, section_offset)
    struct.pack_into(">I", dol, 0x90, section_size)
    monkeypatch.setattr(G, "DOL_SIZE", len(dol))
    monkeypatch.setattr(G, "DOL_SHA256", hashlib.sha256(dol).hexdigest())
    class Fake:
        game_id, title = "GMXE70", "Enter The Matrix"
        files = {"wad2.dfu": (0, 932722688), "wad2_b.dfu": (0, 0)}
        reads = []
        def _r(self, off, size):
            self.reads.append((off, size))
            assert size in (0x440, 0x100, 0x120)
            if off == 0: return bytes(header)
            assert off == 0x1000
            return bytes(dol[:size])
    return Fake()


def test_exact_identity_and_disc_revision(monkeypatch):
    assert G.identify(fake_identity_disc(monkeypatch))["exact_build"]
    for number, revision in [(0, 0), (1, 1)]:
        assert not G.identify(fake_identity_disc(monkeypatch, disc_number=number, revision=revision))["exact_build"]


@pytest.mark.parametrize("offset,size", [(0, 0x120), (0x100, 0xffffffff), (0x100, 0x10), (0, 0)])
def test_invalid_dol_extent_never_allocates_untrusted_size(monkeypatch, offset, size):
    disc = fake_identity_disc(monkeypatch, section_offset=offset, section_size=size)
    assert not G.identify(disc)["exact_build"]
    assert disc.reads == [(0, 0x440), (0x1000, 0x100)]


@pytest.mark.parametrize("failure", ["identity", "archive"])
def test_inventory_closes_disc_on_failure(monkeypatch, failure):
    class Fake:
        f = io.BytesIO()
    disc = Fake()
    monkeypatch.setattr(G, "GCDisc", lambda path: disc)
    monkeypatch.setattr(G, "identify", lambda d: {"exact_build": failure != "identity"})
    monkeypatch.setattr(G, "GcDisc", lambda d: d)
    def bad(*args, **kwargs): raise D.DfuError("invalid table")
    monkeypatch.setattr(G, "Dfu", bad)
    with pytest.raises(G.FormatError): G.inventory("unused")
    assert disc.f.closed


OWNED = Path(os.environ.get("GBOX_ETM_GC_DISC2", "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Enter the Matrix (USA) (Disc 2).gcz"))


@pytest.mark.skipif(not OWNED.is_file(), reason="owned Enter the Matrix GC Disc 2 unavailable")
def test_owned_inventory_exact_headers_and_honest_capabilities(monkeypatch):
    opened = []
    real = G.GCDisc
    def track(path):
        disc = real(path); opened.append(disc); return disc
    monkeypatch.setattr(G, "GCDisc", track)
    result = G.inventory(OWNED)
    assert all(d.f.closed for d in opened)
    assert result["identity"]["exact_build"]
    assert result["identity"]["dol_sha256"] == "4348709361c1c5eae482bd87f5df85d96b82125fd5e3533ed6c1332434b7b58f"
    assert result["archive"]["entries"] == 5874
    assert result["archive"]["duplicate_hashes"] == 3
    assert result["models"] == 288 and result["actors"] == 387
    assert result["model_names_resolved"] == 0
    assert result["capabilities"] == {"archive_inventory": True, "character_extraction": False, "character_replacement": False, "gameplay_verified": False}


@pytest.mark.skipif(not OWNED.is_file(), reason="owned Enter the Matrix GC Disc 2 unavailable")
def test_owned_header_bytes_match_independent_receipts():
    disc = G.GCDisc(OWNED)
    try:
        dfu = D.Dfu(G.GcDisc(disc), endian=">", parts=G.DFU_PARTS)
        for name, size, digest in [
            (G.MODEL_HEADERS, 288 * 0x50, "41ae2707a12e3f8de808c76b265ed64aabf6f46c8c67ccc520bb1987b17c663e"),
            (G.ACTOR_HEADERS, 404 * 0x60, "e83c834e940298f27ac7f5dfab73d4bf7cb84a2e9e2a5ee4edf92288bdbf8977"),
        ]:
            data = dfu.read(name, max_size=size)
            assert len(data) == size and hashlib.sha256(data).hexdigest() == digest
    finally:
        disc.f.close()



def test_part_gap_is_not_silently_concatenated():
    disc = archive({"x": b"x"})
    with pytest.raises(D.DfuError, match="missing middle"):
        D.Dfu(disc, endian=">", parts=("wad2.dfu", "missing.dfu", "wad2_b.dfu"))


@pytest.mark.parametrize("offset", [-1, True, 1.5, "1"])
def test_patch_coordinates_fail_closed(offset):
    disc = Disc({"WAD1.DFU": b"1234"})
    with pytest.raises(D.DfuError):
        D.image_patches(disc, {"patches": [("WAD1.DFU", offset, b"x")]})


@pytest.mark.parametrize("unit", [True, 0, 2, "1"])
def test_unsupported_offset_units_fail_closed(unit):
    disc = Disc({"WAD1.DFU": b"1234"}); disc.offset_unit = unit
    with pytest.raises(D.DfuError, match="offset unit"):
        D.image_patches(disc, {"patches": [("WAD1.DFU", 0, b"x")]})
