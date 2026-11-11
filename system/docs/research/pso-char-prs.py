"""Try PRS decompression on the character save payload.

The payload is not a flat record and not encrypted: it holds 157 compact high-entropy chunks with a 10,828-byte zero gap, which is what
compressed character data looks like. gBox already parses PSO's PRS-compressed ItemPMT, so the same decompressor is applied at several
candidate offsets; a chunk decompresses into something with long zero runs and printable text if the guess is right.
"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import psotext                                            # noqa: E402

CHAR = Path(r"D:\gBox\pso-ds\memcard\PSO_CHARACTER.bin")
HEADER = 0x2000
OUT = r"D:\gBox\pso-ds\char-prs-out.bin"


def describe(blob, label):
    zeros = blob.count(0)
    printable = sum(1 for b in blob if 32 <= b < 127)
    return (f"{label}: {len(blob)} bytes, zeros {zeros} ({zeros / max(1, len(blob)):.1%}), "
            f"printable {printable} ({printable / max(1, len(blob)):.1%})")


def main():
    data = CHAR.read_bytes()
    payload = data[HEADER:]
    print(describe(payload, "raw payload"))
    candidates = [0, 0x40, 0x100, 0x200, 0x400, 0x1000, 0x2000, 0x4000, 0x8000]
    best = None
    for offset in candidates:
        chunk = payload[offset:]
        try:
            out = psotext.prs_decompress(chunk)
        except Exception as exc:                                  # noqa: BLE001
            print(f"  offset 0x{offset:05X}: failed ({type(exc).__name__}: {str(exc)[:60]})")
            continue
        line = describe(out, f"offset 0x{offset:05X}")
        print("  " + line)
        if out and (best is None or len(out) > len(best[1])):
            best = (offset, out)
    if best is None:
        print("no offset decompressed")
        return 2
    offset, out = best
    print(f"\nlargest result from offset 0x{offset:05X}: {len(out)} bytes -> {OUT}")
    Path(OUT).write_bytes(out)
    text = "".join(chr(b) if 32 <= b < 127 else "." for b in out[:200])
    print("first 200 bytes as text:")
    print(" ", text)
    for token in (b"BQF", b"PSO", b"HUmar", b"FOmarl"):
        print(f"  contains {token.decode()}: {token in out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
