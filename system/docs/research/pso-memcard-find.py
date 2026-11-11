"""Locate PSO's save structures on the card by searching for their known strings.

Rather than assuming the directory layout, this searches the whole card for the game code and the PSO file names, then prints the 0x40 bytes
before each hit (where a GC directory entry keeps the name) plus the neighbourhood, so the real layout is read off the bytes.
"""
import struct
import sys
from pathlib import Path

CARD = Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw")


def main():
    data = CARD.read_bytes()
    print(f"card: {len(data)} bytes")
    for token in (b"GPOE8P", b"PSO_CHARACTER", b"PSO_SYSTEM", b"PSO_GUILDCARD", b"BQF"):
        positions = []
        start = 0
        while True:
            found = data.find(token, start)
            if found < 0:
                break
            positions.append(found)
            start = found + 1
            if len(positions) >= 8:
                break
        print(f"\n{token.decode('latin-1')}: {len(positions)} hit(s)")
        for offset in positions:
            block = offset // 0x2000
            print(f"  offset {offset:#08x} (block {block})")
            window = data[max(0, offset - 0x20):offset + 0x60]
            for row in range(0, len(window), 16):
                piece = window[row:row + 16]
                text = "".join(chr(b) if 32 <= b < 127 else "." for b in piece)
                print(f"    {max(0, offset - 0x20) + row:#08x}  {piece.hex(' '):<47}  {text}")
    # a directory-like entry: 0x40 bytes where bytes 0..8 are game+company and 6..38 a name
    print("\nscan for directory-shaped entries (game code in 0..4, printable name in 6..38):")
    found = 0
    for offset in range(0, min(len(data), 0x40000), 0x40):
        entry = data[offset:offset + 0x40]
        name = entry[6:38].split(b"\x00")[0]
        game = entry[0:4]
        if len(name) >= 4 and all(32 <= b < 127 for b in name) and game.isalpha():
            first = struct.unpack("<H", entry[0x36:0x38])[0]
            blocks = struct.unpack("<H", entry[0x38:0x3A])[0]
            print(f"  {offset:#08x} game {game.decode()} name {name.decode()} first {first} blocks {blocks}")
            found += 1
            if found >= 12:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
