"""Look for structure in the encrypted save payload.

PSO keeps the file header in clear text and encrypts the data blocks. A save is mostly zeros (empty slots, unused character records), so an
XOR cipher with a repeating key would leave the *same* ciphertext pattern wherever the plaintext is zero, repeated at the key's period.
This measures exactly that: byte histogram, the most common 8-byte sequences, and the greatest common divisor of the distances between
their repeats. A strong period means a repeating key; no period at all means a stream cipher keyed per block.
"""
import sys
from collections import Counter
from math import gcd
from pathlib import Path

CHAR = Path(r"D:\gBox\pso-ds\memcard\PSO_CHARACTER.bin")
HEADER = 0x2000


def main():
    data = CHAR.read_bytes()
    print(f"file {len(data)} bytes")
    payload = data[HEADER:]
    print(f"payload after 0x{HEADER:X}: {len(payload)} bytes")
    histogram = Counter(payload)
    total = len(payload)
    top = histogram.most_common(8)
    print("byte histogram (top 8):", [(hex(b), round(n / total, 4)) for b, n in top])
    print(f"distinct byte values: {len(histogram)} (255 would be uniform noise)")

    windows = Counter()
    for index in range(0, len(payload) - 8, 8):
        windows[payload[index:index + 8]] += 1
    repeated = [(pattern, count) for pattern, count in windows.most_common(6) if count > 3]
    print(f"\nmost common 8-byte sequences (repeated > 3 times): {len(repeated)}")
    for pattern, count in repeated:
        positions = [index for index in range(0, len(payload) - 8, 8)
                     if payload[index:index + 8] == pattern]
        distances = [b - a for a, b in zip(positions, positions[1:])]
        divisor = 0
        for distance in distances:
            divisor = gcd(divisor, distance)
        active = sorted({d for d in distances if gcd(d, distances[0]) if distances})
        print(f"  {pattern.hex()} x{count} first at {positions[0]:#x} distances {active[:6]} gcd {divisor}")

    zero_run = 0
    best = 0
    for byte in payload:
        if byte == 0:
            zero_run += 1
            best = max(best, zero_run)
        else:
            zero_run = 0
    print(f"\nlongest run of zero bytes in the payload: {best}")
    print("a long zero run would mean the payload is NOT encrypted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
