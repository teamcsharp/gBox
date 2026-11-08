"""Decode the RE5 skin map's TEX header: where the surface starts and what dimensions/format it holds.

Measured so far: an archive map entry is zlib-compressed and decompresses to a `TEX\\0` container
(`54 45 58 00`), e.g. 1,400,384 raw bytes for Rebecca's body base map. The payload size does not divide as a plain
BC1/RGBA surface, so the header must be carrying dimensions, a mip count or a swizzle - this prints what is there and
checks the round numbers against the payload size instead of guessing.
"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import mt_arc, skin_swap

ROOT = os.path.join(os.path.expanduser("~"), "gBox_alt/switch/romfs/010018100CD46000",
                    "nativeNXx64/ImgNX/Archive")
CANDIDATES = (256, 512, 1024, 2048, 4096, 8192)


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "uPl07RebeccaNormal.arc"
    kind = sys.argv[2] if len(sys.argv) > 2 else "BM"
    data = open(os.path.join(ROOT, name), "rb").read()
    arc = mt_arc.parse(data)
    groups = skin_swap.material_groups(arc)
    entry = (groups.get(skin_swap.body_group(groups)) or {}).get(kind)
    if entry is None:
        print(f"{name}: no {kind} in the body group")
        return 1
    raw = zlib.decompress(entry.data)
    print(f"{name} {kind}: entry tag={entry.tag:#010x} compressed={entry.size} raw={len(raw)}")
    print("first 80 bytes:")
    for i in range(0, min(80, len(raw)), 16):
        chunk = raw[i:i + 16]
        print(f"  {i:03d}  {chunk.hex(' ')}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)}")

    print("u32 values in the first 64 bytes that look like dimensions:")
    for off in range(0, min(64, len(raw) - 3), 2):
        v = struct.unpack_from("<I", raw, off)[0]
        if v in CANDIDATES:
            print(f"  +{off:#04x} u32 {v}")
        h = struct.unpack_from("<H", raw, off)[0]
        if h in CANDIDATES:
            print(f"  +{off:#04x} u16 {h}")

    print("payload size versus mip-chained surfaces (header assumed 16..128 bytes):")
    for header in (16, 24, 32, 40, 48, 64, 80, 128):
        payload = len(raw) - header
        for w in CANDIDATES:
            for h in CANDIDATES:
                for bpp, label in ((0.5, "BC1"), (1.0, "BC3/BC5"), (1.5, "BC7"), (2.0, "RGBA16"), (4.0, "RGBA8")):
                    base = w * h * bpp
                    mips = base * 4 / 3
                    if abs(payload - base) <= 8 or abs(payload - mips) <= 8:
                        print(f"  header {header:>3}: {w}x{h} {label} base={int(base)} mips={int(mips)} payload={payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
