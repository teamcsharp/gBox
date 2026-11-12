"""Focused tests for the Capcom Generations owned-build inventory module.

Verifies the manifest entry path (DEE header + decoded TIM geometry), the
slot-map iteration from EXE slot tables (regression: iterating a
{slot: path} dict with enumerate() yielded int keys), and target/alternate
selection in build_inventory.  Fully self-contained: fixtures are
synthesized via the published gbox.capcom_dee writer primitives.
"""

import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import capcom_dee as dee  # noqa: E402
from gbox import capcom_inventory as inv  # noqa: E402


_CLUT_BLOCK = bytes.fromhex("0c0200000000e0010001010000805a6b1c08420800805a6b42081c0800805a6b1e02420800805a6b42081e0200805a6b1c1b420800805a6b1e00420800809452140000800080801310210a0200801c085a6b420800801e025a6b420800805a6b1e021e00008042081e005a6b008042081e025a6b0080de7b807b4208008042081c081c08008042081c085a6b008042084208420800805a6b807b420800805a6b8013420800805a6b1021420800805a6b0a02420800805a6b9452420800805a6b1400420800805a6b0e0042081e0294521e000a021c08945214001021807b94521400102180130e009452807b42085a6b1e02de7b807b1c0880131c1b10210a02945214001e000e009c730080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008000800080008042085a6b1e02de7b807b1c0880131c1b10210a02945214001e000e009c73ff7f")  # real CLUT block (524 B) from 1943/43CHAR7.DEE TIM, owned dump


def _make_tim(width=8, height=8):
    """Synthesize a minimal PSX TIM in the real owned DEE block layout.

    Lead header + CLUT block come from the owned 1943/43CHAR7.DEE TIM
    (4bpp + CLUT, STP transparency); the image block is a small 8x8 4bpp sheet.
    """
    pixel = b"\x11" * (width * height // 2)
    return struct.pack("<2I", 0x10, 0x08) + _CLUT_BLOCK + \
        struct.pack("<I4H", 12 + len(pixel), 0, 0, width, height) + pixel

def _make_dee(tim):
    return dee.dee_pack(tim)


def test_asset_entry_compressed_tim(tmp_path):
    tim = _make_tim()
    p = tmp_path / "1943_OBJ01.DEE"
    p.write_bytes(_make_dee(tim))
    entry = inv.asset_entry(str(p), "1943/OBJ01.DEE")
    assert entry["size"] == 12 + len(dee.dee_compress(tim))
    assert len(entry["sha256"]) == 64
    assert entry["compressed"] is True
    assert entry["raw_len"] == len(tim)
    assert entry["word"] == 0x00400001
    assert entry["tim"] == {
        "width": 8, "height": 8, "bpp": 4,
        "has_clut": True, "clut_size": 12 + 256 * 2, "tim_len": len(tim),
    }


def test_asset_entry_uncompressed_raw_tim(tmp_path):
    tim = _make_tim()
    p = tmp_path / "MENU_WARN2.DEE"
    p.write_bytes(tim)
    entry = inv.asset_entry(str(p), "MENU/WARN2.DEE")
    assert entry["compressed"] is False
    assert entry["tim"]["width"] == 8 and entry["tim"]["bpp"] == 4


def test_asset_entry_non_tim_payload(tmp_path):
    p = tmp_path / "MENU_S14.DEE"
    p.write_bytes(_make_dee(b"\x00" * 64))  # compressed, not a TIM
    entry = inv.asset_entry(str(p), "MENU/S14.DEE")
    assert entry["compressed"] is True
    assert entry["tim"] is None


def test_slot_map_iteration_regression(tmp_path, monkeypatch):
    # Regression: slot_table() returns {slot_index: iso_path}; the old
    # enumerate(labels) loop iterated int keys and crashed on rsplit.
    monkeypatch.setattr("gbox.capcom_slots.slot_table",
                        lambda exe: {0: "1943/CHAR.DEE", 1: "1943/OBJ01.DEE"})
    for name in ("P1943.EXE", "P1942.EXE", "P1943K.EXE"):
        (tmp_path / name).write_bytes(b"PS-X EXE" + b"\x00" * 100)
    maps = inv.slot_map_from_exes(str(tmp_path))
    assert len(maps) == 3
    m = maps["P1943.EXE"]
    assert m["1943/OBJ01.DEE"] == 1
    assert m["OBJ01.DEE"] == 1  # basename fallback
    assert m["1943/CHAR.DEE"] == 0


def test_build_inventory_target_and_decoded(tmp_path, monkeypatch):
    dee_dir = tmp_path / "dee"
    exe_dir = tmp_path / "exe"
    dee_dir.mkdir()
    exe_dir.mkdir()
    tim = _make_tim()
    (dee_dir / "1943_OBJ01.DEE").write_bytes(_make_dee(tim))
    (dee_dir / "1943_CHAR.DEE").write_bytes(_make_dee(tim))
    for name in ("P1943.EXE",):
        (exe_dir / name).write_bytes(b"PS-X EXE" + b"\x00" * 100)
    monkeypatch.setattr("gbox.capcom_slots.slot_table",
                        lambda exe: {0: "1943/CHAR.DEE", 1: "1943/OBJ01.DEE"})
    out = inv.build_inventory(str(dee_dir), str(exe_dir))
    assert out["asset_count"] == 2
    assert out["decoded_count"] == 2
    assert out["source_sha256"] == inv.CHD_SHA256
    assert out["target"]["sha256"] is not None
    assert out["target"]["tim"]["width"] == 8
    assert out["target"]["slot"] == 1
    assert out["alternate"]["slot"] == 0
    # Each ISO path also gets a basename alias -> 4 entries.
    assert out["slot_tables"] == {"P1943.EXE": 4}


DEE_DIR = os.environ.get(
    "CAPCOM_GEN_DEE_DIR",
    "/home/ehm_eckx/.hermes/cache/scratch/capcom_gen/dee",
)


@pytest.mark.skipif(not os.path.isdir(DEE_DIR),
                    reason="owned dump not present")
def test_real_dump_decodes(tmp_path):
    # Against the real dump: 54 DEE files, 52 decode to TIM geometry
    # (S14 and S14K are compressed non-TIM payloads; WARN2 is a raw TIM).
    import shutil
    for name in sorted(os.listdir(DEE_DIR)):
        if name.lower().endswith(".dee"):
            shutil.copy(os.path.join(DEE_DIR, name), tmp_path / name)
    entries = [inv.asset_entry(str(tmp_path / n), inv._iso_path_from_name(n))
               for n in sorted(os.listdir(tmp_path))]
    assert len(entries) == 54
    assert sum(1 for e in entries if e["tim"]) == 52
    warn2 = next(e for e in entries if e["iso_path"] == "MENU/WARN2.DEE")
    assert warn2["compressed"] is False and warn2["tim"] is not None
    obj01 = next(e for e in entries if e["iso_path"] == "1943/OBJ01.DEE")
    assert obj01["sha256"].startswith("5c33dc9c")


SCRATCH = "/home/ehm_eckx/.hermes/cache/scratch/capcom_gen"

_EXE_FILES = ("P1943.EXE", "P1942.EXE", "P1943K.EXE")


@pytest.mark.skipif(
    not (os.path.isdir(os.path.join(SCRATCH, "dee"))
         and all(os.path.isfile(os.path.join(SCRATCH, e)) for e in _EXE_FILES)),
    reason="owned dump and game EXEs not present",
)
def test_real_dump_build_inventory():
    # build_inventory end-to-end against the owned dump: 54 assets, 52
    # decode to TIM geometry, non-empty slot maps from all three game
    # EXEs, target 1943/OBJ01.DEE on P1943.EXE slot 1 with decoded TIM.
    out = inv.build_inventory(os.path.join(SCRATCH, "dee"), SCRATCH)
    assert out["asset_count"] == 54
    assert out["decoded_count"] >= 52
    assert set(out["slot_tables"]) == set(_EXE_FILES)
    assert all(v >= 20 for v in out["slot_tables"].values())
    t = out["target"]
    assert t["iso_path"] == "1943/OBJ01.DEE" and t["slot"] == 1
    assert t["sha256"].startswith("5c33dc9c")
    assert t["tim"] and t["tim"]["width"] == 512 and t["tim"]["bpp"] == 4
    a = out["alternate"]
    assert a["iso_path"] == "1943/CHAR.DEE" and a["slot"] == 0
    assert out["source_sha256"] == inv.CHD_SHA256
