"""PSO save-card parser, with the layout read off the actual bytes.

Measured on D:\\gBox\\runtime\\dolphin\\Dolphin-x64\\User\\GC\\MemoryCardA.USA.raw:

  directory entries   start at 0x20C0, 0x40 bytes each (backup copy at 0x40C0, i.e. +0x2000)
  entry +0x00         u32 game code ("GPOE")
  entry +0x04         u16 company ("8P")
  entry +0x06         u8 banner format, u8 icon count
  entry +0x08         32-byte file name ("PSO_SYSTEM", "PSO_CHARACTER", ...)
  entry +0x36         u16 first block, BIG endian
  entry +0x38         u16 block count, BIG endian

Measured entries: PSO_SYSTEM block 14 x3, PSO_CHARACTER block 17 x11, PSO_GUILDCARD block 28 x10.

This extracts each PSO file to D:\\gBox\\pso-ds\\memcard\\ and, for the character file, reports every run of 19-20 small values - the
technique-level array - so the save can be used to confirm the in-RAM layout (CP9).
"""
import struct
import sys
from pathlib import Path

CARD = Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw")
DIRECTORY = 0x20C0
ENTRY = 0x40
BLOCK = 0x2000
OUT = Path(r"D:\gBox\pso-ds\memcard")
MAX_LEVEL = 30


def entries(data):
    rows = []
    for index in range(127):
        offset = DIRECTORY + index * ENTRY
        entry = data[offset:offset + ENTRY]
        if len(entry) < ENTRY:
            break
        name = entry[0x08:0x28].split(b"\x00")[0]
        first = struct.unpack(">H", entry[0x36:0x38])[0]
        blocks = struct.unpack(">H", entry[0x38:0x3A])[0]
        if not name or first in (0, 0xFFFF) or blocks == 0:
            continue
        rows.append({"index": index, "game": entry[0x00:0x04].decode("latin-1", "replace"),
                     "company": entry[0x04:0x06].decode("latin-1", "replace"),
                     "name": name.decode("latin-1", "replace"),
                     "first_block": first, "blocks": blocks,
                     "offset": first * BLOCK, "size": blocks * BLOCK})
    return rows


def small_runs(blob, minimum=16):
    runs = []
    index = 0
    while index < len(blob):
        run = []
        while index + len(run) < len(blob) and blob[index + len(run)] <= MAX_LEVEL:
            run.append(blob[index + len(run)])
            if len(run) > 24:
                break
        if len(run) >= minimum and sum(1 for v in run if v) >= 2:
            runs.append((index, list(run)))
        index += max(1, len(run))
    return runs


def main():
    data = CARD.read_bytes()
    print(f"card: {len(data)} bytes")
    rows = entries(data)
    print(f"directory entries: {len(rows)}")
    OUT.mkdir(parents=True, exist_ok=True)
    for row in rows:
        blob = data[row["offset"]:row["offset"] + row["size"]]
        target = OUT / f"{row['name']}.bin"
        target.write_bytes(blob)
        print(f"  {row['name']:<16} block {row['first_block']:3d} x {row['blocks']:3d}  "
              f"{len(blob):7d} bytes -> {target.name}")
    character = next((row for row in rows if row["name"] == "PSO_CHARACTER"), None)
    if character is None:
        print("no PSO_CHARACTER entry")
        return 2
    blob = data[character["offset"]:character["offset"] + character["size"]]
    runs = small_runs(blob)
    print(f"\nPSO_CHARACTER: {len(blob)} bytes, {len(runs)} candidate technique runs "
          f"(runs of >=16 values all <= {MAX_LEVEL})")
    for offset, run in runs[:15]:
        text = " ".join(f"{value:02d}" for value in run)
        print(f"  +0x{offset:05X}  len {len(run):2d}  non-zero {sum(1 for v in run if v):2d}  :: {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
