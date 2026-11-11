"""Try to break the PSO save cipher with a measurable success test.

Two probes:

1. PERIOD - XOR the occupied slot with itself shifted by 2/4/8/16 bytes and count cancelled bytes. A short repeating key cancels a huge
   fraction instantly; a stream cipher cancels almost nothing.
2. STREAM - PSO's save encryption is documented as a per-word LCG XOR. This tries the usual 32-bit generators seeded from plausible header
   words, and scores each attempt by printable ratio plus the presence of known tokens (the character-name alphabet, "PSO", and the ASCII
   header that is already known to be plain text).

A candidate only counts as a hit if it produces a *long* printable run (>= 24 consecutive) or a known token - random output can reach 40%
printable but does not produce readable words.
"""
import struct
import sys
from pathlib import Path

CHAR = Path(r"D:\gBox\pso-ds\memcard\PSO_CHARACTER.bin")
SYSTEM = Path(r"D:\gBox\pso-ds\memcard\PSO_SYSTEM.bin")
HEADER = 0x2000
TOKENS = (b"BQF", b"PSO", b"Humar", b"HUmar", b"FOmarl")


def printable_run(blob):
    best = 0
    current = 0
    for byte in blob:
        if 32 <= byte < 127:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def period_test(payload, slot=0x5000):
    block = payload[:slot]
    print(f"period test on the first {len(block)} bytes:")
    for shift in (1, 2, 4, 8, 16, 32, 256):
        same = sum(1 for index in range(len(block) - shift) if block[index] == block[index + shift])
        print(f"  shift {shift:3d}: {same:6d} equal bytes ({same / (len(block) - shift):.1%})")


def lcg_bytes(seed, count, algorithm="41c64e6d"):
    out = bytearray(count)
    key = seed & 0xFFFFFFFF
    for index in range(count):
        key = (key * 0x41C64E6D + 0x3039) & 0xFFFFFFFF
        out[index] = (key >> 16) & 0xFF
    return bytes(out)


def score(blob, label):
    text = bytes(byte ^ 0 for byte in blob)
    long_run = printable_run(text)
    hits = [token.decode() for token in TOKENS if token in text]
    ratio = sum(1 for byte in text if 32 <= byte < 127) / max(1, len(text))
    decent = long_run >= 24 or hits
    if decent or ratio > 0.7:
        print(f"  {label}: run {long_run:3d} printable {ratio:.1%} tokens {hits} "
              f"{'<-- CANDIDATE' if decent else ''}")
    return (long_run, hits, ratio)


def stream_test(payload):
    print("\nstream-cipher attempts (LCG XOR, seeded from header words):")
    seeds = set()
    for offset in (0, 4, 8, 0xC, 0x10):
        seeds.add(struct.unpack(">I", payload[offset:offset + 4])[0])
        seeds.add(struct.unpack("<I", payload[offset:offset + 4])[0])
    seeds.add(0)
    seeds.add(0x12345678)
    best = (0, [], 0.0, None)
    sample = payload[:0x4000]
    for seed in seeds:
        stream = lcg_bytes(seed, len(sample))
        mixed = bytes(a ^ b for a, b in zip(sample, stream))
        result = score(mixed, f"seed {seed:#010x}")
        if result[0] > best[0]:
            best = (result[0], result[1], result[2], seed)
    print(f"  best: run {best[0]} tokens {best[1]} printable {best[2]:.1%} seed {best[3] if best[3] is None else hex(best[3])}")


def main():
    data = CHAR.read_bytes()
    payload = data[HEADER:]
    print(f"payload {len(payload)} bytes")
    period_test(payload)
    stream_test(payload)
    print("\ncontrol: a known-plaintext region (the file header) should score high")
    score(data[:0x40], "file header (plain)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
