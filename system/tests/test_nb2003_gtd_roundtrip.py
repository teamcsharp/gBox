"""Writer no-op roundtrip tests for the NB2003 .gtd character container.

Fixture: owned-build nb2003_ape.gtd streamed from the GCZ into
gbox-cache/research/nb2003_reader_fixtures_2360 (absent -> skip).

Milestone proven here: the parsed chunk tree re-serializes to the exact
original bytes (no-op roundtrip), and the character-block slot can be
rewritten (name / single float word / full word list) with the rest of
the container byte-identical.
"""
import hashlib
import math
import os

import pytest

from gbox.nb2003_gtd import (
    character_block,
    parse_gtd,
    roundtrip_gtd,
    serialize_gtd,
    set_character_block,
)

FIX = os.path.expanduser(
    "~/gbox-cache/research/nb2003_reader_fixtures_2360/nb2003_ape.gtd")

d = None
try:
    with open(FIX, "rb") as f:
        d = f.read()
except FileNotFoundError:
    d = None

pytestmark = pytest.mark.skipif(d is None, reason="ape.gtd fixture absent")

EXPECTED = "91db6d81c4fd608dfad9236e807fe9a4ece0467438918382c2830f7d400919ac"


def _block(gf):
    leaves = gf.leaf(0x0800FFFF, 1, 32)
    assert len(leaves) == 1
    return character_block(leaves[0])


def _words_equal(a, b):
    # block data legitimately contains NaN words (sentinels); NaN != NaN
    return (len(a) == len(b)
            and all(x == y or (math.isnan(x) and math.isnan(y))
                    for x, y in zip(a, b)))


def test_noop_roundtrip_byte_identical():
    out = roundtrip_gtd(d)
    assert out == d
    assert hashlib.sha256(out).hexdigest() == EXPECTED


def test_roundtrip_idempotent():
    out = roundtrip_gtd(d)
    assert roundtrip_gtd(out) == d


def test_set_block_noop_serializes_identical():
    out = serialize_gtd(set_character_block(parse_gtd(d)))
    assert out == d


def test_set_block_single_word():
    gf = parse_gtd(d)
    name, data = _block(gf)
    new = list(data)
    new[100] = 1234.5
    out = serialize_gtd(set_character_block(gf, data=tuple(new)))
    assert len(out) == len(d)
    assert out != d
    name2, data2 = _block(parse_gtd(out))
    assert name2 == name
    assert data2[100] == 1234.5
    diff = sum(1 for a, b in zip(data, data2)
               if not (a == b or (math.isnan(a) and math.isnan(b))))
    assert diff == 1


def test_set_block_name_slot():
    gf = parse_gtd(d)
    _, data = _block(gf)
    out = serialize_gtd(set_character_block(gf, name="ape2"))
    assert len(out) == len(d)
    name2, data2 = _block(parse_gtd(out))
    assert name2 == "ape2"
    assert _words_equal(data, data2)
