"""Offline byte-level verification of gbox.re6_tool.apply_unlock / unlock_save.

Builds a synthetic 0x6000-byte save with a *valid* checksum, then exercises the
same code path unlock_save uses and asserts the acceptance properties from
docs/re6-unlock-checkpoint.md item #2:
  1. checksum is recalculated after a change and always matches the body,
  2. every intended unlock mask / category is applied,
  3. better existing progress is preserved (monotonic, never lowered),
  4. the upgrade is idempotent (second pass changes nothing).
Also verifies unlock_save refuses a corrupt-checksum image and keeps its backup.
"""
import json
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace

from gbox import re6_tool as R

T = R.unlock_template()
SAVE_LEN = 0x6000
TEMPLATE_SHA256 = "194cb5b71858f65feeb2b1703642ddc4ffde09b9a087119189b29b0ad7b83f11"


def fix_sum(d: bytearray) -> None:
    struct.pack_into(">I", d, 8, R._save_sum(bytes(d)))


def verify(save: bytearray, label: str) -> None:
    cur = struct.unpack_from(">I", save, 8)[0]
    want = R._save_sum(bytes(save))
    assert cur == want, f"{label}: checksum {cur:#x} != computed {want:#x}"


def seeded_save() -> bytearray:
    save = bytearray(SAVE_LEN)
    # Seed "better existing progress" BEFORE the unlock: skill points, a pre-set
    # campaign record (non-zero flags -> rec12 must NOT overwrite), a flags8 slot
    # already set, and a faster Mercenaries/region time.
    struct.pack_into(">I", save, 0x6F8, 999999)          # skill points
    struct.pack_into(">I", save, 0x164C, 0xBEEF)         # campaign record flags (rec12)
    save[0x164C + 4] = 0x99                              # better rank kept
    save[0x100F] = 3                                     # flags8 already > 0
    save[0x15F4:0x15F8] = bytes.fromhex("47c35000")      # float in a max32 region
    fix_sum(save)
    return save


def test_unlock_is_monotonic_and_applies_every_category():
    save = seeded_save()
    before = bytes(save)

    n = R.apply_unlock(save)
    fix_sum(save)  # unlock_save recomputes the checksum the same way
    verify(save, "after apply_unlock + fix_sum")
    assert n > 0

    # monotonic on payload only (offsets 12..end); the checksum word at 8..11 is
    # legitimately recomputed and may decrease.
    lowered = [i for i in range(12, SAVE_LEN) if save[i] < before[i]]
    assert not lowered, f"monotonicity violated at {len(lowered)} offsets (first {lowered[:8]})"
    assert struct.unpack_from(">I", save, 0x6F8)[0] == 999999, "skill points lowered"
    assert struct.unpack_from(">I", save, 0x164C)[0] == 0xBEEF, "rec12 overwrote existing campaign record"
    assert save[0x164C + 4] == 0x99, "rec12 overwrote better rank"
    assert save[0x100F] >= 3, "flags8 lowered"
    assert save[0x15F4:0x15F8] == bytes.fromhex("47c35000"), "max32 region lowered existing value"

    # every intended unlock mask / category is set
    assert struct.unpack_from(">I", save, 0xBC)[0] == 0xFFFFFFFF, "mUnlockFlag not set"
    assert struct.unpack_from(">I", save, 0x974)[0] == 0x3FF, "Mercenaries stage mask not set"
    assert struct.unpack_from(">I", save, 0x978)[0] == 0x3FFFFFFF, "Mercenaries character/costume mask not set"
    for off in T["flags8"]:
        assert save[int(off, 16)] >= 1, f"flags8 {off} not set"
    for r in T["regions"]:
        o, src, m = int(r["off"], 16), bytes.fromhex(r["hex"]), r["mode"]
        if m == "max8":
            assert all(save[o + i] >= b for i, b in enumerate(src)), f"max8 region {r['off']} not met"
        elif m == "max32":
            cnt = len(src) // 4
            cur = struct.unpack_from(f">{cnt}I", save, o)
            new = struct.unpack(f">{cnt}I", src)
            assert all(a >= b for a, b in zip(cur, new)), f"max32 region {r['off']} not met"


def test_unlock_is_idempotent():
    save = seeded_save()
    R.apply_unlock(save)
    fix_sum(save)
    n2 = R.apply_unlock(save)
    assert n2 == 0, f"second pass changed {n2} bytes"
    verify(save, "idempotent image")


def test_unlock_save_refuses_corrupt_checksum_then_accepts_valid(monkeypatch):
    save = seeded_save()
    rom = Path(tempfile.mkdtemp(prefix="re6_verify_"))
    sp = rom / R.SAVE_REL
    sp.parent.mkdir(parents=True)
    # corrupt the checksum word
    corr = bytearray(save)
    struct.pack_into(">I", corr, 8, (struct.unpack_from(">I", corr, 8)[0] ^ 0xFFFFFFFF) & 0xFFFFFFFF)
    assert struct.unpack_from(">I", corr, 8)[0] != R._save_sum(bytes(corr))
    sp.write_bytes(bytes(corr))
    monkeypatch.setattr(R, "save_path", lambda cfg: sp)
    monkeypatch.setattr(R, "save_backup", lambda cfg: rom / "save_backup" / "43430819")

    import pytest
    with pytest.raises(ValueError):
        R.unlock_save(SimpleNamespace())

    # a valid save is accepted and the backup is created exactly once
    sp.write_bytes(bytes(save))
    r1 = R.unlock_save(SimpleNamespace())
    assert r1["bytes_changed"] > 0 and not r1["already_unlocked"], r1
    verify(bytearray(sp.read_bytes()), "unlock_save output")
    r2 = R.unlock_save(SimpleNamespace())
    assert r2["already_unlocked"] and r2["bytes_changed"] == 0, r2
    assert (rom / "save_backup" / "43430819").exists()


def test_template_canonical_sha256_unchanged():
    digest = __import__("hashlib").sha256(
        json.dumps(T, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == TEMPLATE_SHA256, "RE6 template changed; unlock profile requires re-verification"
