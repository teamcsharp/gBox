"""CP13: compare a clean body (Daisy) with the failing one (Cloud) node by node."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import ninja  # noqa: E402

BODIES = {
    "daisy": Path(r"D:\gBox\pso-ds\cp13\daisy_ssbu\body.nj"),
    "cloud": Path(r"D:\gBox\pso-ds\cp13\cloud_ssbu\body.nj"),
}


def chunks(payload: bytes, start: int, limit: int = 40) -> tuple[list, int]:
    p, out = start, []
    while p + 4 <= len(payload) and len(out) < limit:
        head = struct.unpack_from(">H", payload, p)[0]
        typ = head & 0xFF
        out.append((hex(p), hex(typ)))
        if typ == 0xFF:
            return out, p + 2
        if typ in (8, 9):
            p += 4
        elif 0x10 <= typ <= 0x3A:
            p += 4 + struct.unpack_from(">H", payload, p + 2)[0] * 2
        elif 0x40 <= typ <= 0x4B:
            p += 4 + struct.unpack_from(">H", payload, p + 2)[0] * 2
        elif typ in (0, 4, 5) or 1 <= typ <= 7:
            p += 2
        else:
            out.append(("unknown", hex(typ)))
            break
    return out, p


def main():
    for name, path in BODIES.items():
        data = path.read_bytes()
        size = struct.unpack_from("<I", data, 4)[0]
        payload = data[8:8 + size]
        nodes = ninja.tree_nodes(payload, 0, ">")
        print(f"== {name}: {len(data)} bytes, payload {len(payload)}, nodes {len(nodes)}")
        for j in (0, 1, 39, 40):
            if j >= len(nodes):
                continue
            nd = nodes[j]
            model = nd["model"]
            if not model:
                print(f"  node {j}: no model")
                continue
            vlist, plist = struct.unpack_from(">II", payload, model)
            vl_types, _ = chunks(payload, vlist, limit=8)
            pl_types, pl_end = chunks(payload, plist, limit=8)
            print(f"  node {j}: model {model:#x} vlist {vlist:#x} plist {plist:#x} "
                  f"flags {nd['flags']:#x} | vtypes {[t for _, t in vl_types]} | "
                  f"ptypes {[t for _, t in pl_types]} end {pl_end:#x} (payload {len(payload):#x})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
