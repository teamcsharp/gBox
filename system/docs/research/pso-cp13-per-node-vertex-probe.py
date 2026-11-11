"""CP13: per-node probe for the vertex lists (Bayonetta's failure is a u32 overrun, i.e. the vertex side)."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox import ninja  # noqa: E402

BODY = Path(sys.argv[1])


def main():
    data = BODY.read_bytes()
    size = struct.unpack_from("<I", data, 4)[0]
    payload = data[8:8 + size]
    nodes = ninja.tree_nodes(payload, 0, ">")
    nj = object.__new__(ninja.NJ)
    nj.e, nj.d = ">", payload
    nj.vbuf, nj.tris, nj.plcache, nj.bones, nj.tex = {}, {}, {}, [], 0
    fails = 0
    for j, nd in enumerate(nodes):
        if not nd["model"]:
            continue
        vlist, plist = struct.unpack_from(">II", payload, nd["model"])
        if vlist:
            nj.vbuf = {}
            try:
                nj._vertices(vlist, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], j)
            except Exception as exc:                       # noqa: BLE001
                fails += 1
                print(f"node {j}: vlist {vlist:#x} FAILED {type(exc).__name__}: {exc}")
                p, last = vlist, []
                while p + 4 <= len(payload) and len(last) < 12:
                    head = struct.unpack_from(">I", payload, p)[0]
                    typ, sz = head & 0xFF, head >> 16
                    last.append((hex(p), hex(typ), hex(sz)))
                    if typ == 0xFF:
                        break
                    if typ < 0x20 or typ > 0x32:
                        p += 4 + sz * 4
                    else:
                        p += 4 + sz * 4
                print(f"   first chunks {last[:6]} end {p:#x} (payload {len(payload):#x})")
        if plist:
            nj.tris, nj.plcache = {}, {}
            try:
                nj._polys(plist)
            except Exception as exc:                       # noqa: BLE001
                fails += 1
                print(f"node {j}: plist {plist:#x} FAILED {type(exc).__name__}: {exc}")
    print(f"failing lists: {fails}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
