"""Dump the PSO directory entries from the live memory card to locate the real save block."""
from pathlib import Path

CARD = Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw")


def main():
    data = CARD.read_bytes()
    for offset in (0x20C0, 0x2100, 0x2140, 0x40C0):
        entry = data[offset:offset + 0x40]
        print(f"entry {offset:#08x}:")
        for row in range(0, 0x40, 16):
            piece = entry[row:row + 16]
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in piece)
            print(f"  +{row:02x}  {piece.hex(' ')}  {text}")
        print("  time:", entry[0x28:0x2C].hex(),
              " image_off:", int.from_bytes(entry[0x2C:0x30], "big"),
              " icon_fmt:", int.from_bytes(entry[0x30:0x32], "big"),
              " perm:", entry[0x34:0x38].hex(),
              " copy:", int.from_bytes(entry[0x38:0x3A], "big"),
              " first:", int.from_bytes(entry[0x3A:0x3C], "big"),
              " blocks:", int.from_bytes(entry[0x3C:0x3E], "big"))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
