"""Do the player's ESL tables name texture ids that exist in imagepackhd?

`bio4/etc/emleon*.esl` are 8,160-byte per-character tables. If any of their 32-bit values equals an archive name in `imagepackhd`, that is
the missing link between the player and a surface that can be swapped - and the ids in the directory are sparse (`0000003c`, `1e003030`,
`4400050e`), so a match would be unmistakable.
"""
import os
import struct
import sys

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "gBox_alt/switch/romfs/010099A00BC1E000")
ETC = os.path.join(ROOT, "bio4", "etc")
PACKS = os.path.join(ROOT, "bio4", "imagepackhd")


def archive_ids() -> set[int]:
    ids = set()
    for name in os.listdir(PACKS):
        if name.endswith(".pack.fen") and len(name) == 17:
            try:
                ids.add(int(name[:8], 16))
            except ValueError:
                pass
    return ids


def main() -> int:
    have = archive_ids()
    print(f"archives: {len(have)}")
    for name in ("emleon00.esl", "emleon01.esl", "emleon02.esl"):
        path = os.path.join(ETC, name)
        if not os.path.isfile(path):
            continue
        data = open(path, "rb").read()
        values = [struct.unpack_from("<I", data, i)[0] for i in range(0, len(data) - 3, 4)]
        hits = [v for v in values if v in have and v > 0x20]
        print(f"{name}: {len(data)} bytes, {len(values)} u32 values, {len(hits)} that name an archive")
        if hits:
            print("   hits:", [hex(v) for v in hits[:10]])
        small = sorted({v for v in values if 0 < v < 0x100})
        print("   small values (candidate local texture ids):", small[:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
