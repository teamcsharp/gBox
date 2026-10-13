"""gbox.pe2_inventory: Parasite Eve II STAGE0.HED/CDF archive + LZ codec (#559).

Synthetic fixtures for the parsers; the owned disc is read only when it is mounted (PE2_DISC env or the Spark path).
"""
import os
import random
import struct
from pathlib import Path

import pytest

from gbox import pe2_inventory as I

DISC = Path(os.environ.get("PE2_DISC", "/mnt/gbox/hyperspin/Arcade/collections/Sony Playstation/roms/"
                           "Parasite Eve II (USA) (Disc 1).chd"))


def _hed(pairs, recs=()):
    return I.build_hed([I.HedRecord(i, s, tuple(range(8))) for i, s in recs], pairs)


def test_hed_roundtrip_and_spans():
    pairs = [(0, 0), (1, 3), (10200, 3), (10201, 7)]
    raw = _hed(pairs, recs=[(1, 0x41B), (0x6A0002, 4344)])
    recs, got = I.parse_hed(raw + bytes(64))
    assert [(r.id, r.sector) for r in recs] == [(1, 0x41B), (0x6A0002, 4344)]
    assert got == pairs
    assert I.build_hed(recs, got, len(raw) + 64) == raw + bytes(64)
    sp = I.file_spans(got, 12)
    assert sp == {0: (0, 3), 1: (3, 0), 10200: (3, 4), 10201: (7, 5)}


def test_hed_rejects_bad_index():
    with pytest.raises(ValueError):
        I.parse_hed(struct.pack("<II", 5, 10) + struct.pack("<II", 6, 4) + b"\xff" * 4)    # backwards
    with pytest.raises(ValueError):
        I.parse_hed(struct.pack("<II", 5, 10))                                             # no terminator
    with pytest.raises(ValueError):
        I.build_hed([], [(1, 1)] * 10, size=16)


def test_file_classes():
    assert I.file_class(10200) == "Aya outfit model"
    assert I.file_class(10305) == "weapon"
    assert I.file_class(100300) == "room"
    assert I.file_class(40105) == "music"


@pytest.mark.parametrize("data", [b"", b"a", b"abababababababababababab" * 9, bytes(range(256)) * 3,
                                  bytes(random.Random(5).randrange(4) for _ in range(5000)),
                                  bytes(random.Random(6).randrange(256) for _ in range(3000))])
def test_lz_roundtrip(data):
    enc = I.lz_encode(data)
    out, nxt = I.lz_decode(enc)
    assert out == data
    assert nxt <= len(enc) + 1


def test_lz_streams_chain_like_the_exe():
    a, b = bytes(random.Random(1).randrange(8) for _ in range(4096)), bytes(range(200)) * 20
    blob = I.lz_encode(a) + I.lz_encode(b)
    x, n = I.lz_decode(blob)
    y, _ = I.lz_decode(blob, n)
    assert (x, y) == (a, b)


def test_lz_bounds():
    with pytest.raises(ValueError):
        I.lz_decode(b"\xff\xff")                          # literal runs past the data
    with pytest.raises(ValueError):
        I.lz_decode(I.lz_encode(bytes(5000)), limit=100)


def _chunk(t, flag, data, addr=0):
    body = struct.pack("<BBHIII", t, flag, 0, 0, addr, 0) + data
    n = max(1, (len(body) + 2047) // 2048)
    used = len(body) - (n - 1) * 2048
    body = bytearray(body.ljust(n * 2048, b"\0"))
    struct.pack_into("<HI", body, 2, used, n)
    return bytes(body)


def test_chunk_walk_payload_image_and_clut():
    strips = [bytes([k]) * 4096 for k in range(8)]
    img = b"".join(I.lz_encode(s) for s in strips)
    ent = struct.pack("<HHI", 0x180, 0x100, 16) + b"\xff\xff\0\0\0\0\0\0"
    clut = struct.pack("<4H", 0, 245, 1, 256) + bytes(8) + I.lz_encode(bytes(range(256)) * 2)
    blob = bytes(range(64)) * 50
    cdf = _chunk(2, 1, clut) + _chunk(1, 1, ent + img) + _chunk(0, 0xFF, I.lz_encode(blob), 0x80115770)
    ch = I.walk_file(cdf, 0, len(cdf) // 2048)
    assert [c.type for c in ch] == [2, 1, 0] and ch[-1].last and ch[-1].addr == 0x80115770
    assert I.decode_clut(I.payload(cdf, ch[0]))["data"] == bytes(range(256)) * 2
    blk = I.decode_image(I.payload(cdf, ch[1]))
    assert len(blk) == 1 and (blk[0]["x"], blk[0]["y"]) == (0x180, 0x100) and blk[0]["data"] == b"".join(strips)
    assert I.lz_decode(I.payload(cdf, ch[2]))[0] == blob


def test_chunk_walk_stops_on_garbage():
    cdf = _chunk(0, 1, b"x" * 100) + b"\x99" * 2048
    assert len(I.walk_file(cdf, 0, 2)) == 1
    assert I.read_chunk_header(b"\x09\x01\x00\x08" + bytes(12), 0) is None


@pytest.mark.skipif(not DISC.exists(), reason="owned PE2 disc 1 not mounted")
def test_owned_disc_inventory():
    rep = I.inventory(DISC)
    assert rep["disc"] == 1 and rep["matches_owned_disc1"]
    assert rep["hed_files"] == 864 and rep["cdf_sectors"] == 30041
    assert rep["aya_outfits"] == {1: 10400, 2: 10300, 3: 10200, 4: 10500, 5: 10600}
