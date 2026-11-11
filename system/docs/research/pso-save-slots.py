"""Infer the character-slot structure from the save's empty space.

The payload has a 10,828-byte zero run and 157 data regions. If the file is a fixed-size slot array, that zero run starts on a slot boundary,
and the same per-slot layout repeats. This reports the long zero runs, tests which candidate slot sizes divide their offsets, and prints
the bytes at each candidate boundary so the record header can be recognised.
"""
import sys
from pathlib import Path

CHAR = Path(r"D:\gBox\pso-ds\memcard\PSO_CHARACTER.bin")
HEADER = 0x2000


def zero_runs(payload, minimum=512):
    out = []
    start = None
    for index, byte in enumerate(payload):
        if byte == 0:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= minimum:
                out.append((start, index, index - start))
            start = None
    if start is not None and len(payload) - start >= minimum:
        out.append((start, len(payload), len(payload) - start))
    return out


def main():
    data = CHAR.read_bytes()
    payload = data[HEADER:]
    runs = zero_runs(payload)
    print(f"zero runs >= 512 bytes: {len(runs)}")
    for start, end, length in runs:
        print(f"  +0x{start:05X}..0x{end:05X}  {length:6d} bytes  "
              f"(start % 0x2000 = {start % 0x2000:#x}, % 0x5000 = {start % 0x5000:#x})")
    print(f"\npayload size {len(payload):#x} bytes; "
          f"as 4 slots = {len(payload) // 4:#x} each; as 3 = {len(payload) // 3:#x}")
    for size in (0x2000, 0x4000, 0x5000, 0x6000, 0x8000):
        print(f"\ncandidate slot size {size:#06x} ({len(payload) // size} slots):")
        for index in range(min(6, len(payload) // size)):
            offset = index * size
            head = payload[offset:offset + 24]
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in head)
            non_zero = sum(1 for b in payload[offset:offset + size] if b)
            print(f"  slot {index} @0x{offset:05X}: {non_zero:6d}/{size} non-zero  | {head.hex(' ')}  | {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
