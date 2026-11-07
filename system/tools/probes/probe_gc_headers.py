"""Are the parsed offsets real headers, or padding? Check files whose magic is known.

Round 61 concluded that 117 of 128 `.drs` entries were mispaired because they did not start `ca b6 be 20`. But that sequence
repeated four times looks like a fill pattern rather than a header, so the conclusion may be exactly backwards. This prints
the first bytes of files with known magics (`opening.bnr` starts BNR1) and of the disputed archives, and says whether the
region is a repeating 4-byte pattern.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox.gcdisc import GCDisc

ISO = os.path.expanduser("~/gBox_alt/re4-lab/gc/re4-d1.iso")
KEYS = ("opening.bnr", "font/common_p.fnt", "em/pl00.drs", "em/pl08.drs", "em/em10.drs", "St1/r100.das", "St1/r101.das")


def repeating_4(blob: bytes) -> bool:
    return len(blob) >= 8 and all(blob[i:i + 4] == blob[:4] for i in range(0, len(blob) - 3, 4))


def main() -> int:
    disc = GCDisc(ISO)
    for key in KEYS:
        entry = disc.files.get(key)
        if entry is None:
            print(f"{key}: not in the FST")
            continue
        offset, size = entry
        head = disc._r(offset, 64)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in head[:32])
        print(f"{key:20s} off {offset:>12} size {size:>9} head {head.hex()}")
        print(f"{'':20s} ascii [{text}] repeating-4: {repeating_4(head)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
