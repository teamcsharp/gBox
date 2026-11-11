"""CP9: the save cipher's algebra - determinism, the permutation invariant and the encode/decode round trip."""
import pytest

from gbox import pso_save_cipher as C


def test_seed_ring_is_deterministic_and_sets_the_cursor():
    a, b = C.seed_ring(0x12345678), C.seed_ring(0x12345678)
    assert a == b
    assert a[0] == C.CURSOR
    # state[0x38]/[0x39] hold the seed *before* the four warm-up rounds, but they are inside the 55-word window, so
    # ::func:`ring_step` legitimately changes them - what must hold is that the seed reaches the ring at all:
    assert C.seed_ring(0x12345678)[0x38] != C.seed_ring(0x12345679)[0x38]
    assert C.seed_ring(1) != C.seed_ring(2)


def test_the_keystream_is_reproducible_and_seed_dependent():
    s1, s2 = C.seed_ring(7), C.seed_ring(7)
    keys1 = [C.next_key(s1) for _ in range(64)]
    keys2 = [C.next_key(s2) for _ in range(64)]
    assert keys1 == keys2
    s3 = C.seed_ring(8)
    assert [C.next_key(s3) for _ in range(64)] != keys1


def test_build_perm_is_a_permutation():
    state = C.seed_ring(0xDEADBEEF)
    perm = C.build_perm(state)
    assert sorted(perm) == list(range(256))


def test_permute_and_unpermute_invert():
    state = C.seed_ring(0xDEADBEEF)
    perm = C.build_perm(state)
    data = bytes(range(256)) * 3 + b"tail"                 # two whole blocks plus a partial one
    assert C.unpermute(C.permute(data, perm), perm) == data
    assert C.permute(data, perm) != data


def test_the_word_cipher_is_its_own_inverse():
    data = bytes((i * 37) & 0xFF for i in range(1024))
    assert C.word_cipher(C.word_cipher(data, C.seed_ring(5)), C.seed_ring(5)) == data


@pytest.mark.parametrize("seed", [0, 1, 0x12345678, 0xDEADBEEF, 0xFFFFFFFF])
def test_encode_then_decode_round_trips(seed):
    data = bytes((i * 101 + 7) & 0xFF for i in range(2048))
    assert C.decode(C.encode(data, seed), seed) == data


def test_a_wrong_seed_does_not_round_trip():
    data = bytes((i * 13) & 0xFF for i in range(512))
    encoded = C.encode(data, 0x12345678)
    assert C.decode(encoded, 0x12345679) != data
