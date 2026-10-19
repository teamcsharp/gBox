"""Tests for gbox/re4r.py: RE4 (2023) REFramework bridge — infinite-ammo hook and stats plumbing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gbox.re4r as r4r


class FakeBridge:
    """Minimal stand-in for r4r.Bridge used by the pure-Python parts."""

    def __init__(self):
        self.calls: list[dict] = []

    def one(self, op: str, timeout: float = 10, **kw) -> dict:
        self.calls.append({"op": op, **kw})
        if op == "get":
            return {"ok": True, "value": 42}
        if op == "get_many":
            return [{"value": {k: 42 for k in (kw.get("paths") or {})}}]
        if op == "lua":
            return {"ok": True, "value": {}}
        if op == "find_types":
            return {"found": True}
        if op == "dump_status":
            return {"done": True, "count": 10}
        return {"ok": True}

    def run(self, ops: list[dict], timeout: float = 10) -> list[dict]:
        for op in ops:
            self.one(op["op"], timeout, **{k: v for k, v in op.items() if k != "op"})
        return [{"ok": True, "value": 42}]

    def alive(self) -> bool:
        return True

    @property
    def dir(self):
        return Path("/tmp")


# ---- HOOKS table -----------------------------------------------------------

def test_infinite_ammo_hook_is_present():
    assert "infinite_ammo" in r4r.HOOKS, "infinite_ammo hook must be in HOOKS"
    hook = r4r.HOOKS["infinite_ammo"]
    assert isinstance(hook, tuple) and len(hook) == 3
    sig, opts, what = hook
    assert "useWeapon" in sig, f"hook signature should target useWeapon, got {sig!r}"
    assert opts == {"skip": True}
    assert "magazine" in what.lower() or "ammo" in what.lower()


def test_existing_hooks_unchanged():
    for key in ("unlimited_items", "no_recoil"):
        assert key in r4r.HOOKS, f"{key} hook must still exist"


# ---- STATS / SETTABLE -------------------------------------------------------

def test_stats_keys():
    expected = {"hp", "max_hp", "invincible", "money", "spinels", "position", "time_scale"}
    assert expected.issubset(set(r4r.STATS)), f"missing stat keys: {expected - set(r4r.STATS)}"


def test_settable_keys():
    expected = {"hp", "max_hp", "invincible", "money", "spinels", "time_scale"}
    assert expected == set(r4r.SETTABLE)


# ---- _first helper ----------------------------------------------------------

def test_first_resolves_first_candidate():
    b = FakeBridge()
    # STATS["hp"] has two candidates; _first should return the first path
    path, val = r4r._first(b, "hp")
    assert path == r4r.STATS["hp"][0]
    assert val == 42


def test_first_raises_when_none_resolve():
    class FailingBridge:
        def __init__(self):
            self.calls = []

        def run(self, ops, timeout=10):
            for op in ops:
                self.calls.append(op)
            return [{"ok": False, "error": "type not found"}]

        def one(self, op, timeout=10, **kw):
            self.calls.append(op)
            return {"ok": False, "error": "type not found"}

        def alive(self):
            return True

    b = FailingBridge()
    try:
        r4r._first(b, "hp")
        assert False, "_first should raise RuntimeError when no candidate resolves"
    except RuntimeError as e:
        assert "hp" in str(e)


# ---- stats() -----------------------------------------------------------------

def test_stats_uses_get_many():
    b = FakeBridge()
    # stats() calls get_many once and returns the per-key dict
    result = b.run([{"op": "get_many", "paths": {k: v[0] for k, v in r4r.STATS.items()}}])
    out = r4r.stats.__wrapped__(b) if hasattr(r4r.stats, "__wrapped__") else None
    # Instead, verify stats() calls get_many via the bridge's call log
    out = r4r.stats(b)
    assert isinstance(out, dict)
    get_many_calls = [c for c in b.calls if c["op"] == "get_many"]
    assert len(get_many_calls) == 1
    paths = get_many_calls[0].get("paths")
    assert paths, "get_many must carry a paths mapping"
    for key in ("hp", "max_hp", "money", "spinels"):
        assert key in paths, f"stats() must request {key} via get_many"


# ---- _hook -------------------------------------------------------------------

def test_hook_on_calls_lua_with_skip():
    b = FakeBridge()
    result = r4r._hook(b, "infinite_ammo", True)
    assert isinstance(result, dict)
    # the bridge should have been asked to toggle the hook
    assert b.calls, "_hook must call the bridge"


def test_hook_off_calls_lua():
    b = FakeBridge()
    r4r._hook(b, "infinite_ammo", False)
    assert b.calls


# ---- CHARACTERS / roster -----------------------------------------------------

def test_roster_returns_characters():
    roster = r4r.roster()
    assert isinstance(roster, list) and len(roster) >= 1
    for entry in roster:
        assert "key" in entry and "slug" in entry and "name" in entry
        assert entry["kind"] == "character"


def test_character_meshes_raises_for_unknown():
    try:
        r4r.character_meshes(None, None, "unknown_character")
        assert False, "should raise for unknown character"
    except KeyError as e:
        assert "character" in str(e).lower() or "re4r" in str(e).lower()


# ---- anticheat_scan (pure filesystem) ----------------------------------------

def test_anticheat_scan_clean_dir(tmp_path):
    gd = tmp_path / "game"
    gd.mkdir()
    (gd / "re4.exe").write_text("x" * 10)
    hits = r4r.anticheat_scan(gd)
    assert hits == [], f"clean dir should have no anticheat hits: {hits}"


def test_anticheat_scan_detects_eac(tmp_path):
    gd = tmp_path / "game"
    gd.mkdir()
    eac = gd / "EasyAntiCheat"
    eac.mkdir()
    (eac / "EACInit.exe").write_text("x")
    hits = r4r.anticheat_scan(gd)
    assert len(hits) >= 1, f"should detect EasyAntiCheat: {hits}"


def test_anticheat_scan_skips_natives_and_reframework(tmp_path):
    gd = tmp_path / "game"
    (gd / "natives").mkdir(parents=True)
    (gd / "natives" / "eac.dll").write_text("x")   # inside natives/ — skipped
    (gd / "reframework").mkdir()
    (gd / "reframework" / "battleye.dll").write_text("x")  # inside reframework/ — skipped
    hits = r4r.anticheat_scan(gd)
    assert hits == [], f"natives/ and reframework/ must be skipped: {hits}"


# ---- RF_RUNTIME regex --------------------------------------------------------

def test_rf_runtime_matches_framework_files():
    for name in ("re4_fw_config.txt", "re4_framework_log.txt", "reframework_foo.txt",
                 "il2cpp_dump.json", "ref_ui.ini", "imgui.ini", "_storage_"):
        assert r4r.RF_RUNTIME.match(name), f"{name} should match RF_RUNTIME"


def test_rf_runtime_rejects_normal_files():
    for name in ("re4.exe", "game.dat", "README.md", "steam_appid.txt"):
        assert not r4r.RF_RUNTIME.match(name), f"{name} should NOT match RF_RUNTIME"


# ---- paks ---------------------------------------------------------------------

def test_paks_sorts_naturally(tmp_path):
    """paks() globs re_chunk_000.pak and re_chunk_000_pak_N.pak; verify natural sort order."""
    gd = tmp_path / "game"
    gd.mkdir()
    (gd / "re_chunk_000.pak").write_text("x")
    (gd / "re_chunk_000_pak_1.pak").write_text("x")
    (gd / "re_chunk_000_pak_10.pak").write_text("x")
    (gd / "re_chunk_000_pak_2.pak").write_text("x")
    paks = r4r.paks(gd)
    names = [p.name for p in paks]
    # natural sort: base pak first, then patch_1, patch_2, patch_10
    assert names == ["re_chunk_000.pak", "re_chunk_000_pak_1.pak",
                     "re_chunk_000_pak_2.pak", "re_chunk_000_pak_10.pak"], f"got {names}"


# ---- seeds_from_exe ----------------------------------------------------------

def test_seeds_from_exe_finds_type_names(tmp_path):
    gd = tmp_path / "game"
    gd.mkdir()
    # minimal "exe" with embedded type-name strings
    payload = b"\x00" + b"chainsaw.CharacterManager" + b"\x00" + b"app.GameManager" + b"\x00" + b"random_string" + b"\x00"
    (gd / "re4.exe").write_bytes(payload)
    out = tmp_path / "seeds.txt"
    n = r4r.seeds_from_exe(gd, out)
    assert n >= 2, f"should find at least 2 type names, got {n}"
    content = out.read_text()
    assert "chainsaw.CharacterManager" in content
    assert "app.GameManager" in content
    assert "random_string" not in content
