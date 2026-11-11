"""Parse the live GameCube memory card for the PSO character record and its technique array.

Card: D:\\gBox\\runtime\\dolphin\\Dolphin-x64\\User\\GC\\MemoryCardA.USA.raw (written on every area load).
1. read the directory entries (0x0040 and its backup 0x0840, 0x40 bytes each) and print any titled save,
2. scan the whole card for the character name in every plausible encoding and for the game code,
3. around each hit, report the byte neighbourhood and every 19-20 byte run of small values - the technique-level array.
"""
from pathlib import Path

CARD = Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw")
NAME = "BQF"


def read_card(path=CARD):
    return path.read_bytes()


def directory(data):
    rows = []
    for base in (0x0040, 0x0840):
        for index in range(127):
            offset = base + index * 0x40
            entry = data[offset:offset + 0x40]
            if len(entry) < 0x40:
                continue
            game = entry[0:4]
            filename = entry[8:40].split(b"\x00")[0]
            first, count = int.from_bytes(entry[0x3A:0x3C], "big"), int.from_bytes(entry[0x3C:0x3E], "big")
            if filename and count and all(32 <= b < 127 for b in game):
                rows.append({"offset": offset, "game": game.decode("ascii", "replace"),
                             "file": filename.decode("ascii", "replace"), "first": first, "blocks": count})
    return rows


def main():
    data = read_card()
    print(f"card {CARD} ({len(data)} bytes, {len(data) // 8192} blocks)")
    rows = directory(data)
    print(f"directory entries: {len(rows)}")
    for row in rows:
        print(f"  {row['game']} {row['file']:<32} first={row['first']} blocks={row['blocks']}")
    encodings = {"utf16-be": NAME.encode("utf-16-be"), "utf16-le": NAME.encode("utf-16-le"),
                 "ascii": NAME.encode("ascii")}
    for label, needle in encodings.items():
        hits, index = [], data.find(needle)
        while index >= 0 and len(hits) < 6:
            hits.append(index)
            index = data.find(needle, index + 1)
        print(f"{label}: {[hex(h) for h in hits]}")
    for code in (b"GPOE", b"GPO"):
        hits, index = [], data.find(code)
        while index >= 0 and len(hits) < 6:
            hits.append(index)
            index = data.find(code, index + 1)
        print(f"{code!r}: {[hex(h) for h in hits]}")
    # technique-array candidates in the whole card are too many; instead dump around each name hit
    for label, needle in encodings.items():
        index = data.find(needle)
        if index < 0:
            continue
        start = max(0, index - 0x40)
        chunk = data[start:start + 0x180]
        print(f"\ncontext around {label} at {index:#08x} (block {index // 8192}):")
        for row in range(0, len(chunk), 16):
            piece = chunk[row:row + 16]
            print(f"  {start + row:#08x}  {piece.hex(' ')}  "
                  f"{''.join(chr(b) if 32 <= b < 127 else '.' for b in piece)}")
        break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
