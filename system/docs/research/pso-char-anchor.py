"""Anchor the PSO character record: find the character's name in the save and read the layout around it.

The character file is 90,112 bytes. Its record should carry the character's name ("BQF"), so this finds every occurrence and prints the
surrounding bytes with both byte orders of the u16s, which is how the level/stats/technique fields get identified without guessing.
"""
import struct
import sys
from pathlib import Path

CHAR = Path(r"D:\gBox\pso-ds\memcard\PSO_CHARACTER.bin")


def main():
    data = CHAR.read_bytes()
    print(f"character file: {len(data)} bytes")
    print(f"first 64 bytes: {data[:64].hex(' ')}")
    print(f"as text: {''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:64])}")
    names = [b"BQF", b"bqf"]
    for token in names:
        start = 0
        count = 0
        while True:
            found = data.find(token, start)
            if found < 0 or count >= 4:
                break
            start = found + 1
            count += 1
            print(f"\n'{token.decode()}' at +0x{found:05X}:")
            lo = max(0, found - 0x20)
            window = data[lo:found + 0x40]
            for row in range(0, len(window), 16):
                piece = window[row:row + 16]
                text = "".join(chr(b) if 32 <= b < 127 else "." for b in piece)
                print(f"  {lo + row:#07x}  {piece.hex(' '):<47}  {text}")
        if count == 0:
            print(f"'{token.decode()}' not found")
    # every run of 17-21 bytes <= 30 with at least three non-zero, anywhere in the file
    print("\nruns of 17-21 small values (possible technique arrays), scanning the whole file:")
    found_runs = 0
    index = 0
    while index < len(data):
        run = []
        while index + len(run) < len(data) and data[index + len(run)] <= 30:
            run.append(data[index + len(run)])
            if len(run) > 21:
                break
        if len(run) >= 17 and sum(1 for v in run if v) >= 3:
            text = " ".join(f"{v:02d}" for v in run)
            print(f"  +0x{index:05X} len {len(run):2d} non-zero {sum(1 for v in run if v):2d} :: {text}")
            found_runs += 1
            if found_runs >= 10:
                break
        index += max(1, len(run))
    print(f"runs found: {found_runs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
