"""List every printable text run in the character save, so the current character's name and the record layout become visible.

The old character was called BQF but this save does not contain that name, so the current one has a different name. Names, section labels
and item strings are plain ASCII in a PSO save, so listing the runs locates the records by their text instead of assuming an offset.
"""
import sys
from pathlib import Path

CHAR = Path(r"D:\gBox\pso-ds\memcard\PSO_CHARACTER.bin")


def main():
    data = CHAR.read_bytes()
    print(f"file {len(data)} bytes")
    print("non-zero fraction:",
          round(sum(1 for b in data if b) / len(data), 3))
    runs = []
    current = []
    start = 0
    for index, byte in enumerate(data):
        if 32 <= byte < 127:
            if not current:
                start = index
            current.append(chr(byte))
        else:
            if len(current) >= 3:
                runs.append((start, "".join(current)))
            current = []
    if len(current) >= 3:
        runs.append((start, "".join(current)))
    print(f"text runs of 3+ characters: {len(runs)}")
    for offset, text in runs[:60]:
        print(f"  +0x{offset:05X}  {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
