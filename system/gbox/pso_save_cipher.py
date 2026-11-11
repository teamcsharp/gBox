"""The PSO save cipher, as code: the subtractive ring, its keystream, the byte permutation and the word cipher.

Transcribed from the game's assembly in CP9 (all of it verified against decompiles and disassembly kept under
`docs/research/pso-save-cipher*.txt`):

```
seed_ring(seed):  state[0x38] = state[0x39] = seed
                  0x36 times: idx = (0x15 * i) % 0x37; state[idx + 1] = a;  a, s = s - a, a
                  four ring rounds, then cursor = 0x37
ring_step:        24 times state[k + 1] -= state[k + 0x20]   (k = 1..24)
                  31 times state[k + 1] -= state[k - 0x17]   (k = 25..55)
next_key:         cur = state[0]; state[0] = cur + 1
                  if state[0] > 0x37: ring_step(); state[0] = 1
                  return state[state[0] + 1]
rand(n):          ((n & 0xffff) * (next_key() >> 16)) >> 16
build_perm:       Fisher-Yates over 0..255 using rand, returning the inverse table `B`
permute:          for each 256-byte block: dst[256k + B[j]] = src[256k + j]
word_cipher:      buf[i] = key_i - buf[i]                 (its own inverse, like a XOR)
```

The one input the file cannot supply is the **seed**: the game reads it from the selected save slot's descriptor
(`FUN_802019f8`, the 24-way per-slot initialiser) at runtime, so `decode` takes it as an argument.

Everything here is deterministic and pure except the ring state it builds itself; `decode` is the function the live seed read
feeds.
"""
from __future__ import annotations

import struct

M32 = 0xFFFFFFFF
STATE_WORDS = 0x3A          # the ring is 58 words in the assembly
CURSOR = 0x37
BLOCK = 256


def ring_step(state: list[int]) -> None:
    """One ring update: two subtractive passes over the 55-word window."""
    for k in range(1, 25):
        state[k + 1] = (state[k + 1] - state[k + 0x20]) & M32
    for k in range(25, 56):
        state[k + 1] = (state[k + 1] - state[k - 0x17]) & M32


def seed_ring(seed: int) -> list[int]:
    """The ring for a seed, with the four warm-up rounds applied and the cursor at 0x37."""
    state = [0] * STATE_WORDS
    state[0x38] = state[0x39] = seed & M32
    a, s = 1, seed & M32
    for i in range(0x36):
        idx = (0x15 * i) % 0x37
        state[idx + 1] = a
        a, s = (s - a) & M32, a
    for _ in range(4):
        ring_step(state)
    state[0] = CURSOR
    return state


def next_key(state: list[int]) -> int:
    """Advance the cursor and return the next 32-bit key (wrapping the ring when the cursor passes 0x37)."""
    state[0] = state[0] + 1
    if state[0] > CURSOR:
        ring_step(state)
        state[0] = 1
    return state[state[0] + 1]


def rand(state: list[int], n: int) -> int:
    """The bounded random the Fisher-Yates step uses: high half of the key scales `n`."""
    return (((n & 0xFFFF) * (next_key(state) >> 16)) >> 16)


def build_perm(state: list[int]) -> list[int]:
    """The 256-entry inverse permutation table B (the assembly's Fisher-Yates over the identity)."""
    a = list(range(BLOCK))
    b = [0] * BLOCK
    for i in range(BLOCK - 1, -1, -1):
        j = rand(state, i + 1)
        value = a[j]
        a[j] = a[i]
        b[value] = i
        a[i] = value
    return b


def permute(data: bytes, perm: list[int]) -> bytes:
    """Apply the byte permutation per 256-byte block; a trailing partial block is copied unchanged."""
    out = bytearray(data)
    whole = len(data) - len(data) % BLOCK
    for base in range(0, whole, BLOCK):
        for j in range(BLOCK):
            out[base + perm[j]] = data[base + j]
    return bytes(out)


def unpermute(data: bytes, perm: list[int]) -> bytes:
    """The inverse of :func:`permute` (for encoding): src[j] = dst[perm[j]]."""
    out = bytearray(data)
    whole = len(data) - len(data) % BLOCK
    for base in range(0, whole, BLOCK):
        for j in range(BLOCK):
            out[base + j] = data[base + perm[j]]
    return bytes(out)


def word_cipher(data: bytes, state: list[int]) -> bytes:
    """buf[i] = key_i - buf[i], little-endian u32 words; its own inverse, so the same call decodes and encodes."""
    out = bytearray(data)
    for i in range(len(data) // 4):
        key = next_key(state)
        value = struct.unpack_from("<I", data, 4 * i)[0]
        struct.pack_into("<I", out, 4 * i, (key - value) & M32)
    return bytes(out)


def decode(data: bytes, seed: int) -> bytes:
    """Decode a save block with a seed: un-permute (the permute above), then the word cipher."""
    state = seed_ring(seed)
    perm = build_perm(state)
    return word_cipher(permute(data, perm), state)


def encode(data: bytes, seed: int) -> bytes:
    """Encode with the same seed - the exact inverse order of :func:`decode`."""
    state = seed_ring(seed)
    perm = build_perm(state)
    return unpermute(word_cipher(data, state), perm)
