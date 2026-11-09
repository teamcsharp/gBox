"""Focused tests for the NB2003 .gtd character-container reader.

Fixture: owned-build ape.gtd streamed from the GCZ into
gbox-cache/research/nb2003_reader_fixtures_2360 (absent -> skip).
"""
import os
import struct

import pytest

from gbox.nb2003_gtd import SENTINEL, character_block, parse_gtd

FIX = os.path.expanduser(
    "~/gbox-cache/research/nb2003_reader_fixtures_2360/nb2003_ape.gtd")

d = None
try:
    with open(FIX, "rb") as f:
        d = f.read()
except FileNotFoundError:
    d = None

pytestmark = pytest.mark.skipif(d is None, reason="ape.gtd fixture absent")


def _gf():
    return parse_gtd(d)


def test_prefix_and_footer():
    gf = _gf()
    assert len(d) == 32936
    assert (gf.count, gf.payload_size) == (22, 32924)
    assert 8 + gf.payload_size + 4 == len(d)
    assert gf.footer == 0x0800FFFF


def test_exact_chunk_tree():
    gf = _gf()
    root = gf.nodes
    assert [(n.offset, n.type, n.subtype, n.size) for n in root] == [
        (0x0008, 0x0800FFFF, 1, 4),
        (0x0018, 1, 0x15, 0x8074),
        (0x8098, 0x0800FFFF, 3, 0),
    ]
    c2 = root[1]
    assert c2.payload == d[0x0024:0x8098]
    assert [(n.offset, n.type, n.subtype, n.size) for n in c2.children] == [
        (0x0024, 0x0800FFFF, 1, 0x805C),
        (0x808C, 0xFF67261B, 3, 0),
    ]
    blk = c2.children[0]
    assert len(blk.payload) == 0x805C


def test_character_block_name_and_data():
    gf = _gf()
    leaves = gf.leaf(0x0800FFFF, 1, 32)
    assert len(leaves) == 1
    name, data = character_block(leaves[0])
    assert name == "ape"
    assert len(data) == 8207
    sent = sum(1 for w in data if w == SENTINEL)
    assert sent == 7


def test_container_exact_fill():
    gf = _gf()
    c2 = gf.nodes[1]
    o, sz = c2.offset + 12, c2.size
    assert o + sz - (c2.children[-1].offset + 12 + c2.children[-1].size) == 0
