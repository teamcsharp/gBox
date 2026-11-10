"""Verify RE5's grenade class table against a decompressed `main` image.

    python tools/verify_re5_classes.py <main.bin> [--json]

`main.bin` is `hactool -t nso --uncompressed=main.bin main` output (the NSO header kept, so virtual address =
file offset - 0x100), e.g. after `python -m gbox.switch_extract exefs <nsp> <program.nca> <out> --keys prod.keys`.

`gbox/mercs/native/re5_ebffdb22/classes.py` pins the DTIs the item factory takes for the three grenade classes:
uWp06 hand `main+0x1D714C8`, uWp07 incendiary `main+0x1D71500`, uWp08 flash `main+0x1D71538` (the last is the DTI
the live-verified native flash already uses, which is the cross-check that makes the block trustworthy). This
re-runs the game's own MtDTI registration block and compares. Exit 0 only when every pinned value matches.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox.mercs.native.re5_ebffdb22 import classes as C  # noqa: E402


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    image = Path(argv[1]).read_bytes()
    try:
        report = C.verify(image)
    except ImportError:
        print("capstone is required for this check (pip install capstone)")
        return 2
    report["pinned"] = {k: {"name": v.name, "dti": hex(v.dti), "item": hex(v.item),
                            "size": None if v.size is None else hex(v.size)}
                        for k, v in C.CLASSES.items()}
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        print("pinned:")
        for kind, row in report["pinned"].items():
            print(f"  {kind:<11} {row['name']:<6} dti {row['dti']:<12} item {row['item']:<7} size {row['size']}")
        print("derived:")
        for name, row in report["derived"].items():
            print(f"  {name:<6} dti {row['dti']:<12} item {row['item']:<7} size {row['size']}"
                  f" parent {row['parent']} id {row['id']}")
        print("mismatches:", report["mismatches"] or "none")
        print("verdict:", "PASS - the image's initialiser builds the pinned DTIs"
              if report["ok"] else "FAIL - do not trust the pinned table for this image")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
