"""Fast GameCube ISO file table reader: load the whole FST and string table once.

The first version seeked per character when reading names, which made listing a 1.4 GB image take minutes. Reading the string table into memory once
makes it instant.
"""
import struct
import sys
from pathlib import Path

ISO = Path(r"D:\gBox\pso-ds\disc\pso.iso")


def load(iso=ISO):
    """Return (entry_table, string_table) for the image, using the offsets measured on this disc."""
    with iso.open("rb") as handle:
        header = handle.read(0x460)
        fst_offset = struct.unpack(">I", header[0x424:0x428])[0]
        handle.seek(fst_offset)
        head = handle.read(12)
        count = struct.unpack(">III", head)[2] or 1          # the root directory's size field is the entry count
        handle.seek(fst_offset)
        blob = handle.read(count * 12 + 0x80000)
    table = blob[:count * 12]
    strings = blob[count * 12:]
    return table, strings


def cstr(blob, offset):
    end = blob.find(bytes([0]), offset)
    if end < 0:
        end = len(blob)
    return blob[offset:end].decode(chr(97)+chr(115)+chr(99)+chr(105)+chr(105), chr(114)+chr(101)+chr(112)+chr(108)+chr(97)+chr(99)+chr(101))


def entries(iso=ISO):
    """Every file as (path, offset, size) - directories are walked with an explicit stack."""
    table, strings = load(iso)
    count = len(table) // 12
    out = []
    stack = []                                                    # (end_index, name)
    for index in range(1, count):
        type_name, offset, size = struct.unpack(">III", table[index * 12:index * 12 + 12])
        while stack and stack[-1][0] <= index:
            stack.pop()
        name = cstr(strings, type_name & 0x00FFFFFF)
        path = "/".join([entry[1] for entry in stack] + [name])
        if type_name & 0x01000000:
            out.append((path + "/", None, None))
            stack.append((offset, name))
        else:
            out.append((path, offset, size))
    return out


def extract(path, out_path, iso=ISO):
    for candidate, offset, size in entries(iso):
        if candidate == path and offset is not None:
            with iso.open("rb") as handle:
                handle.seek(offset)
                Path(out_path).write_bytes(handle.read(size))
            return size
    return None


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    if command == "list":
        prefix = sys.argv[2] if len(sys.argv) > 2 else ""
        rows = [row for row in entries() if prefix.lower() in row[0].lower()]
        print(f"{len(rows)} entries matching {prefix!r}")
        for path, offset, size in rows[:80]:
            print(f"  {path}  {size if size is not None else ''}")
    elif command == "get":
        size = extract(sys.argv[2], sys.argv[3])
        print(f"{sys.argv[2]}: {size} bytes" if size else f"not found: {sys.argv[2]}")
    else:
        print(__doc__)
