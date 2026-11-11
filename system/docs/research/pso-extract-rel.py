"""List and extract files from the PSO GameCube image through gcz.GCZ (random access) and the GC FST.

FST layout (GameCube boot header): u32 fst_offset at 0x424, u32 fst_size at 0x428. Each entry is 12 bytes:
u32 type_and_name_offset (u8 type: 1 file / 0 dir, u24 name offset into the string table), u32 offset_or_parent, u32 size.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox.gcz import GCZ                                            # noqa: E402


def parse_fst(image) -> list[dict]:
    header = image.read(0, 0x440)
    fst_offset = int.from_bytes(header[0x424:0x428], "big")
    entry_count = int.from_bytes(image.read(fst_offset + 8, 4), "big")
    raw = image.read(fst_offset, entry_count * 12 + 0x10000)
    strings = fst_offset + entry_count * 12
    string_table = image.read(strings, 0x10000)
    entries = []
    for index in range(entry_count):
        row = raw[index * 12:(index + 1) * 12]
        kind = row[0]
        name_off = int.from_bytes(row[1:4], "big")
        offset = int.from_bytes(row[4:8], "big")
        size = int.from_bytes(row[8:12], "big")
        end = string_table.find(b"\x00", name_off)
        name = string_table[name_off:end].decode("latin-1") if end > name_off else ""
        # GameCube FST: type 1 is a directory, 0 is a file (the root entry is a directory).
        entries.append({"index": index, "dir": kind == 1, "name": name, "offset": offset, "size": size,
                        "parent": offset if kind == 1 else None})
    return entries


def paths(entries) -> dict[int, str]:
    out: dict[int, str] = {}
    for entry in entries:
        if entry["index"] == 0:
            out[0] = ""
            continue
        parent = out.get(entry["parent"], "")
        out[entry["index"]] = f"{parent}/{entry['name']}" if parent else entry["name"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
    ap.add_argument("--match", default="forest")
    ap.add_argument("--extract", default="", help="full path to extract, or a name fragment; empty lists only")
    ap.add_argument("--out", default=r"D:\gBox\pso-ds\rel")
    args = ap.parse_args()
    with GCZ(args.image) as image:
        print("image size:", image.file_size)
        entries = parse_fst(image)
        names = paths(entries)
        matches = [(i, names[i], e["offset"], e["size"]) for i, e in enumerate(entries)
                   if not e["dir"] and args.match.lower() in names.get(i, "").lower() and names.get(i, "").lower().endswith(".rel")]
        print(f"rel entries matching {args.match!r}: {len(matches)}")
        for item in matches[:20]:
            print("  ", item[1], item[3], "bytes")
        if args.extract:
            pick = next((m for m in matches if m[1].lower().endswith(args.extract.lower())), None) or \
                   next((m for m in matches if args.extract.lower() in m[1].lower()), None)
            if not pick:
                print("no match for", args.extract)
                return 1
            data = image.read(pick[2], pick[3])
            out = Path(args.out) / Path(pick[1]).name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            print("wrote", out, len(data), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
