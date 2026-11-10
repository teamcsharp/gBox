
"""Focused checks for the owned-build inventory of Resident Evil - Survivor (PSX)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbox.res_survivor_inventory import (DEFAULT_CHD, build_inventory, sha256_file)

EXPECTED_SOURCE_SHA256 = "2a3cb809b891c8642aefe33d1f1fd95c03c6d2a610fd0687db2663b496464be3"
EXPECTED_SOURCE_BYTES = 177454189


def test_source_identity():
    p = Path(os.environ.get("RES_SURVIVOR_CHD", DEFAULT_CHD))
    assert p.is_file(), p
    assert p.stat().st_size == EXPECTED_SOURCE_BYTES
    assert sha256_file(p) == EXPECTED_SOURCE_SHA256


def test_iso_manifest():
    inv = build_inventory()
    assert inv["source"]["sha256"] == EXPECTED_SOURCE_SHA256
    assert inv["source"]["bytes"] == EXPECTED_SOURCE_BYTES
    assert inv["iso"]["volume_id"], inv["iso"]
    assert inv["member_count"] == len(inv["members"]) >= 100
    assert all(m["size"] > 0 for m in inv["members"])
    assert sum(c["count"] for c in inv["counted_assets"].values()) == inv["member_count"]
    assert inv["byte_order"].startswith("little-endian")


def test_boot_executable_identified():
    inv = build_inventory()
    boot = inv["boot"]
    assert boot["system_cnf"], "SYSTEM.CNF not found in owned disc"
    assert boot["name"], "boot executable not identified"
    assert len(boot["sha256"] or "") == 64, boot
    assert boot["size"] > 0 and boot["extent"] >= 0


if __name__ == "__main__":
    fails = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            try:
                _fn()
                print("PASS", _name)
            except Exception as exc:
                fails += 1
                print("FAIL", _name, type(exc).__name__, exc)
    raise SystemExit(1 if fails else 0)
