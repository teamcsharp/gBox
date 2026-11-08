"""Decompress an RE5 skin map and work out what the uncompressed surface is."""
import os
import sys
import zlib

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import mt_arc, skin_swap

ROOT = os.path.join(os.path.expanduser("~"), "gBox_alt/switch/romfs/010018100CD46000",
                    "nativeNXx64/ImgNX/Archive")


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "uPl07RebeccaNormal.arc"
    data = open(os.path.join(ROOT, name), "rb").read()
    arc = mt_arc.parse(data)
    groups = skin_swap.material_groups(arc)
    body = skin_swap.body_group(groups)
    print(f"body group {body!r}")
    for kind, entry in sorted((groups.get(body) or {}).items()):
        raw = zlib.decompress(entry.data)
        g = entry.tag
        print(f"  {kind:2s} compressed={entry.size:>8} raw={len(raw):>9} tag={g:#010x} head={raw[:16].hex()}")
        for w, h in ((1024, 1024), (2048, 1024), (1024, 2048), (512, 512), (2048, 2048), (4096, 4096)):
            for mult, label in ((1.0, "rgba8"), (0.5, "bc1"), (1.0, "bc3"), (2.0, "bc5")):
                if int(w * h * mult) == len(raw):
                    print(f"      fits {w}x{h} {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
