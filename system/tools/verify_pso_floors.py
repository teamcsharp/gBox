"""Verify PsoV3's floor -> area/layout table against a decompressed `PsoV3.dol`.

    python tools/verify_pso_floors.py <PsoV3.dol> [--json]

`gbox/pso_floor_map.py` pins the two 36-entry tables `FUN_80207E88` reads (`0x804C8FC0` Episode 1, `0x804C9270`
Episode 2; `FUN_8030A6A8` picks between them) as (area/layout name pairs, layout count). This re-reads them from an
image and compares. Exit 0 only when both tables match.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox import pso_floor_map as F  # noqa: E402


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    report = F.verify(Path(argv[1]).read_bytes())
    if "--json" in argv:
        print(json.dumps(report, indent=2, default=str))
    else:
        mismatches = report["mismatches"]
        print(f"tables: EP1 floors 0-35, EP2 floors 0-35 ({len(F.EP1_FLOORS)} + {len(F.EP2_FLOORS)} entries)")
        print("mismatches:", mismatches[:5] if mismatches else "none")
        print("verdict:", "PASS - the image's own table is the pinned one" if report["ok"]
              else "FAIL - do not trust the pinned table for this image")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
