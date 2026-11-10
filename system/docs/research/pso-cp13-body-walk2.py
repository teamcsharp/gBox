"""CP13: walk every non-empty polygon list with _polys' own rules and report the first overrun."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox import ninja  # noqa: E402


def walk(pl: bytes, start: int) -> tuple[int, str, list]:
    p, trace = start, []
    while p + 4 <= len(pl):
        head = struct.unpack_from(">H", pl, p)[0]
        typ, flg = head & 0xFF, head >> 8
        trace.append((hex(p), hex(typ)))
        if typ == 0xFF:
            return p + 2, "end", trace
        if typ == 4:
            return p + 2, "cache", trace
        if typ == 5 or typ == 0 or 1 <= typ <= 7:
            p += 2
        elif typ in (8, 9):
            p += 4
        elif 0x10 <= typ <= 0x3A:
            p += 4 + struct.unpack_from(">H", pl, p + 2)[0] * 2
        elif 0x40 <= typ <= 0x4B:
            p += 4 + struct.unpack_from(">H", pl, p + 2)[0] * 2
        else:
            return p, f"unknown {typ:#x}", trace
        if p > len(pl):
            return p, "overrun", trace
    return p, "ran out", trace


def main():
    for name, path in (("daisy", r"D:\gBox\pso-ds\cp13\daisy_ssbu\body.nj"),
                       ("cloud", r"D:\gBox\pso-ds\cp13\cloud_ssbu\body.nj")):
        data = Path(path).read_bytes()
        size = struct.unpack_from("<I", data, 4)[0]
        pl = data[8:8 + size]
        nodes = ninja.tree_nodes(pl, 0, ">")
        print(f"== {name} payload {len(pl):#x}")
        for j, nd in enumerate(nodes):
            if not nd["model"]:
                continue
            _vl, plist = struct.unpack_from(">II", pl, nd["model"])
            end, verdict, trace = walk(pl, plist)
            if verdict != "end" or end > len(pl):
                print(f"  node {j}: plist {plist:#x} -> {end:#x} {verdict}; last {trace[-3:]}")
        print("  (only non-clean lists are printed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
