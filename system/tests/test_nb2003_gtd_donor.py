"""Writer changed-donor test for the NB2003 .gtd character container.

Milestone: re-import one character's float data into a real target slot.
Donor: stride-17 float-pool decode of the owned-build nb2003_ape.dff
(published decoder ``gbox.nb2003_dff``). Target: the ape.gtd
character-block slot (name ``ape``, fixed 8207 float words).

Proven here:
* the donor decodes deterministically from the owned .dff (row mask from
  the published decoder: 150 full rows, 2566 real words);
* the packed donor (real words in pool order + 0xcdcdcdcd capacity
  padding to the fixed block size) differs from the original block,
  i.e. this is a *changed* donor, not a no-op;
* ``set_character_block`` + ``serialize_gtd`` keep container size,
  chunk alignment and every byte outside the block payload identical;
* the result re-parses to exactly the donor block, and round-trips
  stably.

Fixtures: owned-build bytes streamed from the GCZ into
gbox-cache/research/nb2003_reader_fixtures_2360 (absent -> skip).
"""
import hashlib
import math
import os
import struct

import pytest

from gbox.nb2003_dff import SENTINEL, decode_float_pool, read_dff
from gbox.nb2003_gtd import (
    character_block,
    parse_gtd,
    roundtrip_gtd,
    serialize_gtd,
    set_character_block,
)

GTD = os.path.expanduser(
    "~/gbox-cache/research/nb2003_reader_fixtures_2360/nb2003_ape.gtd")
DFF = os.path.expanduser(
    "~/gbox-cache/research/nb2003_reader_fixtures_2360/nb2003_ape.dff")

GTD_BYTES = None
DFF_BYTES = None
try:
    with open(GTD, "rb") as f:
        GTD_BYTES = f.read()
except FileNotFoundError:
    pass
try:
    with open(DFF, "rb") as f:
        DFF_BYTES = f.read()
except FileNotFoundError:
    pass

pytestmark = pytest.mark.skipif(
    GTD_BYTES is None or DFF_BYTES is None,
    reason="ape.gtd / ape.dff fixtures absent")

EXPECTED_GTD = "91db6d81c4fd608dfad9236e807fe9a4ece0467438918382c2830f7d400919ac"
BLOCK_WORDS = 8207          # fixed character-block word count (ape.gtd)
DONOR_REAL = 2566           # real float words in ape.dff mesh0 pos pool


def _words_equal(a, b):
    # block data legitimately contains NaN words; NaN != NaN in Python
    return (len(a) == len(b)
            and all(x == y or (math.isnan(x) and math.isnan(y))
                    for x, y in zip(a, b)))


def _block(gf):
    leaves = gf.leaf(0x0800FFFF, 1, 32)
    assert len(leaves) == 1
    return character_block(leaves[0])


def _donor():
    """Stride-17 decoded donor float words, packed to block size."""
    meshes = read_dff(DFF_BYTES)
    m = [x for x in meshes if x.kind == "pos"][0]
    words = struct.unpack_from(f"<{m.pool_words}f", DFF_BYTES, m.pool_off)
    pool = decode_float_pool(list(words))
    real = [w for r in pool.rows for w, mk in zip(r.words, r.mask) if mk]
    real += [w for w in pool.tail if w != SENTINEL]
    assert len(real) == pool.real_words
    return real + [SENTINEL] * (BLOCK_WORDS - len(real)), pool


def _payload_region(node):
    """Byte range of the leaf payload in the container bytes."""
    start = node.offset + 12
    return start, start + len(node.payload)


def test_original_block_layout_documented():
    gf = parse_gtd(GTD_BYTES)
    name, data = _block(gf)
    assert name == "ape"
    assert len(data) == BLOCK_WORDS
    # native capacity slots sit early in the block, not at the tail
    sent = [i for i, w in enumerate(data) if w == SENTINEL]
    assert len(sent) == 7
    assert sent == [4, 5, 6, 7, 8, 9, 10]


def test_donor_decodes_from_owned_dff():
    donor, pool = _donor()
    assert pool.stride == 17
    assert pool.n_full == 150
    assert pool.real_words == DONOR_REAL
    assert pool.sentinel_words == 1352
    assert len(donor) == BLOCK_WORDS
    assert sum(1 for w in donor if w == SENTINEL) == BLOCK_WORDS - DONOR_REAL
    # changed donor: not the original block content
    _, orig = _block(parse_gtd(GTD_BYTES))
    assert not _words_equal(orig, donor)


def test_changed_donor_size_and_alignment_invariant():
    donor, _ = _donor()
    gf = parse_gtd(GTD_BYTES)
    node = gf.leaf(0x0800FFFF, 1, 32)[0]
    out = serialize_gtd(set_character_block(gf, data=tuple(donor)))
    assert len(out) == len(GTD_BYTES)
    assert hashlib.sha256(out).hexdigest() != EXPECTED_GTD
    # bytes outside the block payload region are untouched
    start, end = _payload_region(node)
    assert out[:start] == GTD_BYTES[:start]
    assert out[end:] == GTD_BYTES[end:]


def test_changed_donor_reparse_exact():
    donor, _ = _donor()
    gf = parse_gtd(GTD_BYTES)
    node = gf.leaf(0x0800FFFF, 1, 32)[0]
    bstart = node.offset + 12
    bend = bstart + len(node.payload)
    out = serialize_gtd(set_character_block(gf, data=tuple(donor)))
    gf2 = parse_gtd(out)
    assert gf2.count == gf.count
    assert gf2.payload_size == gf.payload_size
    assert gf2.footer == gf.footer
    name2, data2 = _block(gf2)
    assert name2 == "ape"
    assert _words_equal(data2, donor)
    # every node whose byte span does NOT overlap the changed block
    # region is byte-identical to the original

    def all_nodes(ns, acc):
        for n in ns:
            acc.append(n)
            all_nodes(n.children, acc)
    a, b = [], []
    all_nodes(gf.nodes, a)
    all_nodes(gf2.nodes, b)
    assert [x.offset for x in a] == [x.offset for x in b]
    for x, y in zip(a, b):
        xs, xe = x.offset, x.offset + 12 + len(x.payload)
        if xs < bend and xe > bstart:
            continue
        assert x.payload == y.payload, f"node @{x.offset:#x} changed"


def test_changed_donor_roundtrip_stable():
    donor, _ = _donor()
    out = serialize_gtd(set_character_block(parse_gtd(GTD_BYTES),
                                            data=tuple(donor)))
    assert roundtrip_gtd(out) == out
