"""Verify PsoV3's object-class registry against a decompressed `PsoV3.dol`.

    python tools/verify_pso_classes.py <PsoV3.dol> [--json]

`gbox/pso_class_registry.py` pins the 240-slot class-name table at `0x805D3138` (148 named in this build). This
re-reads it from an image and compares. Exit 0 only when every slot matches.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox import pso_class_registry as R  # noqa: E402


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    report = R.verify(Path(argv[1]).read_bytes())
    if "--json" in argv:
        print(json.dumps(report, indent=2, default=str))
    else:
        named = sum(1 for t in R.CLASS_NAMES if t)
        print(f"table {R.TABLE_ADDRESS:#x}: {R.SLOTS} slots, {named} named")
        print("four walked lobby doors:",
              [R.label(k) for k in (0x46, 0x47, 0x48, 0x49)])
        print("mismatches:", report["mismatches"][:5] if report["mismatches"] else "none")
        print("verdict:", "PASS - the image's own table is the pinned one" if report["ok"]
              else "FAIL - do not trust the pinned table for this image")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
