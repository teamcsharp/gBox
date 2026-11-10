"""CP13: call ninja.NJ's own `_polys` per polygon list and report which one overruns."""
import struct
import sys
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox import ninja  # noqa: E402

BODY = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\gBox\pso-ds\cp13\cloud_ssbu\body.nj")


def main():
    data = BODY.read_bytes()
    size = struct.unpack_from("<I", data, 4)[0]
    payload = data[8:8 + size]
    nodes = ninja.tree_nodes(payload, 0, ">")
    nj = object.__new__(ninja.NJ)
    nj.e, nj.d = ">", payload
    nj.vbuf, nj.tris, nj.plcache, nj.bones, nj.tex = {}, {}, {}, [], 0
    for j, nd in enumerate(nodes):
        if not nd["model"]:
            continue
        vlist, plist = struct.unpack_from(">II", payload, nd["model"])
        first = struct.unpack_from(">H", payload, plist)[0] if plist + 2 <= len(payload) else None
        if first == 0xFF:
            continue                                  # empty list: not a suspect
        nj.tris, nj.plcache = {}, {}
        try:
            nj._polys(plist)
        except Exception as exc:                      # noqa: BLE001
            print(f"node {j}: plist {plist:#x} FAILED with {type(exc).__name__}: {exc}")
            # walk it with a bound check to show where it leaves the buffer
            p, last = plist, []
            while p + 4 <= len(payload):
                head = struct.unpack_from(">H", payload, p)[0]
                typ = head & 0xFF
                last.append((hex(p), hex(typ)))
                if typ == 0xFF or typ == 4:
                    break
                if typ in (5, 0) or 1 <= typ <= 7:
                    p += 2
                elif typ in (8, 9):
                    p += 4
                elif 0x10 <= typ <= 0x3A or 0x40 <= typ <= 0x4B:
                    p += 4 + struct.unpack_from(">H", payload, p + 2)[0] * 2
                else:
                    last.append(("unknown", hex(typ)))
                    break
                if p > len(payload):
                    print(f"   walk left the payload at {p:#x} (len {len(payload):#x}); last chunks {last[-4:]}")
                    break
            continue
        else:
            print(f"node {j}: plist {plist:#x} ok ({len(nj.tris)} texture buckets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
