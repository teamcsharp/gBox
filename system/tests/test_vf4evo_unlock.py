import hashlib
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_pkg_module(pkg_name, pkg_dir, mod_name, file_name):
    """Load a module from the workspace package without importing its heavy __init__."""
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(pkg_dir)]
    sys.modules.setdefault(pkg_name, pkg)
    spec = importlib.util.spec_from_file_location(pkg_name + "." + mod_name, pkg_dir / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vf = _load_pkg_module("gbox_ws", ROOT / "gbox", "vf4evo_unlock", "vf4evo_unlock.py")
gu = _load_pkg_module("gbox_ws", ROOT / "gbox", "game_unlocks", "game_unlocks.py")


def test_revision_pin_is_a_full_sha256():
    assert len(vf.EXECUTABLE_SHA256) == 64
    assert vf.EXECUTABLE_SHA256 == vf.EXECUTABLE_SHA256.lower()
    int(vf.EXECUTABLE_SHA256, 16)


def test_profile_gate_reports_research_pending_not_verified():
    gate = vf.profile_gate()
    assert gate["scope"]
    assert gate["blockers"]
    assert gate["next"]
    assert "runtime-verified" in gate["reason"]
    assert vf.HYPOTHESES["H1"]["status"] == "unverified_hypothesis"


def test_revision_guard_refuses_a_foreign_buffer():
    res = vf.apply_candidate_unlocks(bytes(4096))
    assert res["applied"] is False
    assert res["reason"] == "revision-mismatch"
    assert res["patches"] == 0


def test_candidate_patches_stay_inside_the_documented_surface():
    rf = vf.LOCK_SURFACE["release_flag_tbl"]
    buf = bytes(rf["file_offset"] + rf["size"])
    patches = vf.plan_patches(buf)
    assert len(patches) == rf["size"] // 4 == 24
    for p in patches:
        assert rf["file_offset"] <= p["offset"] < rf["file_offset"] + rf["size"]
        assert p["patched"] == "ffffffff"
        assert p["hypothesis"] == "H1"


def test_apply_candidate_unlocks_is_deterministic_when_the_pin_matches():
    rf = vf.LOCK_SURFACE["release_flag_tbl"]
    buf = bytes(rf["file_offset"] + rf["size"])
    pin = hashlib.sha256(buf).hexdigest()
    first = vf.apply_candidate_unlocks(buf, expected_sha256=pin)
    second = vf.apply_candidate_unlocks(buf, expected_sha256=pin)
    assert first["applied"] is True and second["applied"] is True
    assert first["patches"] == 24
    assert first["buffer"] == second["buffer"]
    rf = vf.LOCK_SURFACE["release_flag_tbl"]
    assert first["buffer"][rf["file_offset"]:rf["file_offset"] + rf["size"]] == b"\xff" * rf["size"]
    assert first["buffer"][:rf["file_offset"]] == buf[:rf["file_offset"]]


def test_inventory_records_string_evidence_only():
    summary = vf.inventory_summary()
    assert set(summary) == set(vf.CATEGORIES)
    for cat, s in summary.items():
        assert s["total"] >= 1
        for e in vf.INVENTORY[cat]:
            assert e["status"] == "unknown"
            assert e["evidence"]["kind"] in ("ascii_string_in_owned_executable", "no_ascii_string_match")


def test_game_unlocks_registers_vf4evo_as_an_unverified_branch():
    src = (ROOT / "gbox" / "game_unlocks.py").read_text(encoding="utf-8")
    assert "vf4evo_unlock" in src
    idx = src.index("vf4evo_unlock.GAME_ID")
    window = src[idx:idx + 1200]
    assert "'verified': False" in window
    assert "research_pending" in src


def test_profile_for_returns_pending_research_for_vf4evo():
    profile = gu.profile_for({"game_id": vf.GAME_ID, "platform": vf.PLATFORM})
    assert profile["verified"] is False
    assert profile["status"] == "pending_research"
    assert profile["profile"] is None
    assert profile["scope"]
    assert profile["blockers"]


def test_pre_launch_reports_research_pending_and_applies_nothing():
    ctx = types.SimpleNamespace()
    out = gu.pre_launch({"game_id": vf.GAME_ID, "platform": vf.PLATFORM}, ctx)
    assert out["state"] == "research_pending"
    assert out["applied"] is False
    assert out["next"]
