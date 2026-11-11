"""Map the character save's structure: which regions hold data and which are empty slots.

The payload is not encrypted - 13.5% zero bytes and one 10,828-byte zero run - so the file is a sequence of character records separated by
empty space. This prints every contiguous non-zero region with its offset and size, and the printable text inside each, which is how the
live character record is located without a guessed offset.
"""
import sys
from pathlib import Path

CHAR = Path(r"D:\gBox\pso-ds\memcard\PSO_CHARACTER.bin")
MIN_REGION = 128


def regions(payload, minimum=MIN_REGION):
    out = []
    start = None
    for index, byte in enumerate(payload):
        if byte:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= minimum:
                out.append((start, index))
            start = None
    if start is not None and len(payload) - start >= minimum:
        out.append((start, len(payload)))
    return out


def main():
    data = CHAR.read_bytes()
    payload = data[0x2000:]
    print(f"payload {len(payload)} bytes at file offset 0x2000")
    found = regions(payload)
    print(f"data regions (non-zero, >= {MIN_REGION} bytes): {len(found)}")
    for start, end in found:
        blob = payload[start:end]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in blob[:60])
        print(f"\n  +0x{start:05X}..0x{end:05X}  {end - start:6d} bytes  |  {text}")
        runs = []
        current = []
        run_start = 0
        for index, byte in enumerate(blob):
            if 32 <= byte < 127:
                if not current:
                    run_start = index
                current.append(chr(byte))
            else:
                if len(current) >= 4:
                    runs.append((start + run_start, "".join(current)))
                current = []
        if len(current) >= 4:
            runs.append((start + run_start, "".join(current)))
        for offset, text in runs[:12]:
            print(f"      +0x{offset:05X}  {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
