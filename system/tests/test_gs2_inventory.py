"""gs2_inventory: owned-source manifest for Resident Evil Survivor 2 - Code: Veronica (PS2 Europe)."""
import json
import os
from pathlib import Path

from gbox.gs2_inventory import afs_pairs, boot_name, classify, collect, sniff

DISC = Path(os.environ.get("GBOX_GS2_DISC", "/home/ehm_eckx/gbox-cache/ps2/5ec1d297cb44b3ea/disc.iso"))


def test_boot_name_variants():
    assert boot_name("BOOT2 = cdrom0:\\SLES_506.50;1\nVER = 1.02\nVMODE = PAL") == "SLES_506.50"
    assert boot_name("BOOT2=cdrom0:FOO.BAR;1") == "FOO.BAR"
    assert boot_name("VER = 1.00") is None


def test_classify():
    assert classify("/ROOT/DATA.CNF", 10) == "cnf"
    assert classify("/ROOT/CHR/CLAIRE.AFS", 4096) == "afs"
    assert classify("/ROOT/NOEXT", 1) == "other"


def test_afs_pairs_interleaved_variant():
    # SYSTEM.AFS-style header: 'AFS\0', N=2, pairs (off,size)
    head = b"AFS\x00" + (2).to_bytes(4, "little") + \
        (0x800).to_bytes(4, "little") + (11192).to_bytes(4, "little") + \
        (0x83000).to_bytes(4, "little") + (444).to_bytes(4, "little")
    assert afs_pairs(head) == [(0x800, 11192), (0x83000, 444)]


def test_sniff():
    assert sniff(b"\x01\x02\x03\x04MDL\x00\x00") == "mdl"
    assert sniff(b"TIM2\x00\x05\x04\x00CDCD") == "tim2"
    assert sniff(b"MPAC\x04\x00\x00\x00\xec\x00") == "mpac"
    assert sniff(b"\x00" * 12) == "zero"


def test_collect_manifest():
    if not DISC.exists():
        import pytest
        pytest.skip(f"disc not staged: {DISC}")
    m = collect(DISC, "0" * 64)
    for key in ("boot", "boot_sha256", "boot_size", "disc_iso_sha256", "file_count",
                "top_level", "ext_counts", "containers", "afs"):
        assert key in m, key
    assert m["boot"] == "SLES_506.50"
    assert m["boot_size"] > 0
    assert len(m["boot_sha256"]) == 64
    sys = m["afs"]["SYSTEM.AFS"]
    assert len(sys["mdl"]) == 87 and len(sys["skin"]) == 5 and len(sys["tim2"]) == 5
    assert m["afs"]["MRY.AFS"]["kinds"]["mpac"] == 135
    # every archive entry extent stays inside its archive (validated by afs_pairs users)
    assert m["file_count"] == 31
