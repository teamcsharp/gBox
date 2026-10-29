"""Focused writer tests: no-op ARC roundtrip + changed donor retarget on uPl00LeonUsa slot."""

import hashlib
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import re6
from gbox.re6_models import CHARACTERS, Mod

ISO = Path(os.environ.get("RE6_ISO", "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Resident Evil 6.iso"))


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _leon_arc_from_iso(iso: str, tmp: Path) -> tuple[re6.Arc, bytes]:
    """Extract uPl00LeonUsa.arc from the owned ISO into tmp. Returns (Arc, original_bytes)."""
    c = CHARACTERS["leon"]
    stem = c["arc"].format(part="", costume="Usa")
    x = re6.XDVD(iso)
    try:
        data = x.read(f"/nativeXenon/arc/X360/{stem}.arc")
    finally:
        x.close()
    dst = tmp / "nativeXenon" / "arc" / "X360" / f"{stem}.arc"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return re6.Arc(data), data


@pytest.mark.skipif(not ISO.exists(), reason="owned RE6 ISO not mounted")
def test_noop_arc_roundtrip(tmp_path):
    """Extract Leon Usa ARC -> rebuild -> byte-identical. The writer's no-op proof."""
    a, orig = _leon_arc_from_iso(str(ISO), tmp_path)
    assert len(a.entries) == 89, f"expected 89 entries, got {len(a.entries)}"
    # Rebuild with no changes
    out = a.build()
    assert _sha(out) == _sha(orig), "no-op ARC rebuild must be byte-identical"
    # Verify the mod entry is present and unchanged
    mods = [e for e in a.entries if e["ext"] == "mod"]
    assert mods, "no mod entries found in uPl00LeonUsa.arc"
    body_mod = mods[0]
    m = Mod(a.get(body_mod))
    assert _sha(a.get(body_mod)) == "ecfd8ad529b56a8300572dabe40ccbd28865824aaced38e51d66289d5178d356"


@pytest.mark.skipif(not ISO.exists(), reason="owned RE6 ISO not mounted")
def test_changed_donor_retarget(tmp_path):
    """Retarget a synthetic donor model onto the uPl00LeonUsa slot. The changed model must differ from the
    original, and unrelated ARC entries must remain intact."""
    a, orig = _leon_arc_from_iso(str(ISO), tmp_path)
    mods = [e for e in a.entries if e["ext"] == "mod"]
    body_mod = mods[0]
    m_orig = Mod(a.get(body_mod))
    orig_sha = _sha(a.get(body_mod))

    # Build a synthetic donor: a single rigid triangle on bone 0, different from the original
    from gbox.re6_models import write_body
    W = m_orig.world()
    p0 = W[0][3, :3]
    P = np.array([p0, p0 + np.array([0.1, 0, 0]), p0 + np.array([0, 0.1, 0])])
    N = np.array([[0, 1.0, 0]] * 3)
    UV = np.zeros((3, 2))
    T = np.array([[0, 1, 2]])
    B = np.zeros(3, int)
    prims = [{"pos": P, "nrm": N, "uv": UV, "tris": T, "J": B[:, None]}]
    new_bytes = write_body(m_orig, prims, 0, m_orig.prims[0]["mesh_id"], m_orig.prims[0]["draw"],
                           m_orig.prims[0].get("group", 0), None)
    new_sha = _sha(new_bytes)
    assert new_sha != orig_sha, "changed donor must differ from original"

    # Rebuild the ARC with the changed mod
    a.put(body_mod["name"], "mod", new_bytes)
    out = a.build()
    assert len(out) > 0, "rebuilt ARC must be non-empty"

    # Read back: the mod entry must be the changed one
    a2 = re6.Arc(out)
    e2 = a2.find(body_mod["name"], "mod")
    m2 = Mod(a2.get(e2))
    assert _sha(a2.get(e2)) == new_sha, "read-back mod must match the changed donor"

    # Unrelated entries must be intact: check that the ARC still has the same number of entries
    # and that a non-mod entry is byte-identical
    assert len(a2.entries) == len(a.entries), "entry count must be preserved"
    non_mod = [e for e in a.entries if e["ext"] != "mod"]
    if non_mod:
        e0 = non_mod[0]
        assert a2.get(e0) == a.get(e0), "unrelated ARC entry must be unchanged"
