"""CP9: the cipher on the real card - a round trip over the actual PSO_CHARACTER body.

The card's character payload is 90,048 bytes of encoded data. `decode(encode(body, seed), seed) == body` for any seed is the
self-consistency check that matters before the live seed is known: it proves the transcribed pipeline (ring, permutation,
word cipher) is invertible on real data, not just on synthetic buffers.
"""
import pathlib

import pytest

from gbox import pso_memcard as M, pso_save_cipher as C

CARD = pathlib.Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw")


@pytest.fixture(scope="module")
def character_body() -> bytes:
    if not CARD.is_file():
        pytest.skip("the memory card is not on this machine")
    card = M.read(str(CARD))
    entry = next((e for e in M.saves(card) if e["name"] == "PSO_CHARACTER"), None)
    if entry is None:
        pytest.skip("this card has no PSO_CHARACTER save")
    data = card[entry["first_block"] * M.BLOCK: entry["first_block"] * M.BLOCK + entry["bytes"]]
    return data[0x40:]


def test_the_character_body_is_the_measured_size(character_body):
    assert len(character_body) == 90048                    # 90,112 bytes minus the 0x40 header


@pytest.mark.parametrize("seed", [0, 1, 0x12345678, 0xDEADBEEF, 0xFFFFFFFF])
def test_the_real_body_round_trips_through_the_cipher(character_body, seed):
    encoded = C.encode(character_body, seed)
    assert encoded != character_body                      # it really transformed the data
    assert C.decode(encoded, seed) == character_body      # and exactly inverted itself


def test_two_seeds_produce_different_encodings(character_body):
    a = C.encode(character_body[:2048], 0x12345678)
    b = C.encode(character_body[:2048], 0x12345679)
    assert a != b
