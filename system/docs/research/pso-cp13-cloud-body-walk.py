"""CP13: why the Cloud body does not parse - walk its polygon chunks with bounds checks."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import ninja  # noqa: E402

BODY = Path(r"D:\gBox\pso-ds\cp13\cloud_ssbu\body.nj")


def main():
    data = BODY.read_bytes()
    size = struct.unpack_from("<I", data, 4)[0]
    payload = data[8:8 + size]
    print(f"body {len(data)} bytes, NJCM payload {len(payload)}")
    nodes = ninja.tree_nodes(payload, 0, ">")
    print(f"nodes {len(nodes)}")
    bad = 0
    for j, nd in enumerate(nodes):
        if not nd["model"]:
            continue
        vlist, plist = struct.unpack_from(">II", payload, nd["model"])
        p, chunks = plist, []
        while p + 4 <= len(payload):
            head = struct.unpack_from(">H", payload, p)[0]
            typ, flg = head & 0xFF, head >> 8
            chunks.append((p, typ, flg))
            if typ == 0xFF:
                break
            if typ in (8, 9):
                p += 4
            elif 0x10 <= typ <= 0x3A:
                p += 4 + struct.unpack_from(">H", payload, p + 2)[0] * 2
            elif 0x40 <= typ <= 0x4B:
                p += 4 + struct.unpack_from(">H", payload, p + 2)[0] * 2
            elif typ in (0, 4, 5) or 1 <= typ <= 7:
                p += 2
            else:
                chunks.append(("unknown", typ))
                break
        if p > len(payload):
            bad += 1
            if bad <= 3:
                print(f"node {j}: plist {plist:#x} ran to {p:#x} (payload {len(payload):#x}); last chunks {chunks[-3:]}")
    print(f"nodes whose polygon walk overruns: {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
