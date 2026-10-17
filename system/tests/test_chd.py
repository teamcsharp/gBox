"""CHD v5 CD reader (gbox.chd): a synthetic cdzl / cdlz / self / uncompressed image round trip, the map's Huffman
tree, the cdfl (FLAC) path, bounds errors, and the owned Enter the Matrix CHD when it is reachable."""
import os
import struct
from pathlib import Path

import pytest

from gbox import chd
from matrix_synth import _BitWriter, make_chd, make_iso

OWNED = Path(os.environ.get("GBOX_ETM_PS2_CHD") or
             "//10.89.1.125/HyperSpin Attraction/Arcade/collections/Sony Playstation 2/roms/USA/Enter the Matrix (USA).chd")


def _files():
    return {"SYSTEM.CNF": b"BOOT2 = cdrom0:\\TEST_000.01;1\nVER = 1.00\n", "HELLO.TXT": b"hello matrix" * 400,
            "ZERO.BIN": bytes(40000), "BIG.BIN": bytes(range(256)) * 300}


def test_synthetic_chd_reads_the_iso_back(tmp_path):
    iso = make_iso(_files())
    p = tmp_path / "disc.chd"
    p.write_bytes(make_chd(iso))
    d = chd.ChdDisc(p)
    counts = d.chd.codec_counts()
    assert counts.get("cdzl") == 1 and counts.get("cdlz", 0) >= 1 and counts.get("self", 0) >= 1
    assert counts.get("none") == 1
    assert d.track_type == "MODE1" and d.frames == len(iso) // 2048
    for name, blob in _files().items():
        assert d.read(name) == blob
    assert d.read("HELLO.TXT", 6, 7) == b"matrixh"
    out = d.write_iso(tmp_path / "out.iso")
    assert out.read_bytes() == iso
    assert not (tmp_path / "out.iso.part").exists()


def test_read_bounds_and_header_errors(tmp_path):
    p = tmp_path / "disc.chd"
    p.write_bytes(make_chd(make_iso(_files())))
    d = chd.ChdDisc(p)
    with pytest.raises(chd.ChdError):
        d.read("HELLO.TXT", 4790, 20)
    with pytest.raises(chd.ChdError):
        d.sector(10 ** 6)
    with pytest.raises(chd.ChdError):
        chd.header(b"NOTACHD!" + bytes(116))
    bad = bytearray(p.read_bytes())
    struct.pack_into(">I", bad, 12, 4)                    # version 4 -> refused (psxdisc reads v4)
    with pytest.raises(chd.ChdError):
        chd.header(bytes(bad[:124]))


def test_huffman_rle_tree_and_canonical_codes():
    bw = _BitWriter()
    lens = [1, 2, 3, 3] + [0] * 12
    for n in lens[:4]:
        if n == 1:
            bw.put(1, 4)
            bw.put(1, 4)                                  # escaped 1
        else:
            bw.put(n, 4)
    bw.put(1, 4)
    bw.put(0, 4)
    bw.put(12 - 3, 4)                                     # run of 12 zero lengths
    # canonical codes (longest first): len 3 -> 000, 001; len 2 -> 01; len 1 -> 1
    for code, n in ((1, 1), (1, 2), (0, 3), (1, 3)):
        bw.put(code, n)
    bits = chd._Bits(bw.bytes())
    h = chd._Huffman(bits)
    assert [h.decode(bits) for _ in range(4)] == [0, 1, 2, 3]


def test_flac_cdfl_constant_frames():
    # two FLAC frames of 2352 stereo samples each (CONSTANT 0 subframes), then the zlib subcode: what chdman wrote
    # for an all-zero system-area hunk of the owned discs
    src = bytes.fromhex("fff8791800092f760000000000003587fff8791801092f1d000000000000382363601805a360e40200")
    pcm, used = chd.flac_cd(src, 8 * 2352 // 4)
    assert pcm == bytes(8 * 2352) and src[used:] == bytes.fromhex("63601805a360e40200")


@pytest.mark.skipif(not OWNED.exists(), reason="owned Enter the Matrix CHD not reachable")
def test_owned_etm_chd_lists_the_disc():
    d = chd.ChdDisc(OWNED)
    assert d.chd.h["sha1"] == "0d5fb09505041295ac665cf53f4d391386adfa46"
    assert d.pvd[40:72].strip() == b"SLUS_20454"
    assert d.read("SYSTEM.CNF").startswith(b"BOOT2 = cdrom0:\\SLUS_204.54;1")
    assert d.size("WAD1.DFU") == 1007788032 and d.size("WAD1_B.DFU") == 1425079296
