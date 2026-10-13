"""Two-tier cache (gbox/cache_tiers.py): two temp dirs stand in for the NVMe (hot) and the HDD (cold)."""
import json
import os
import time
import types

import pytest
from fastapi.testclient import TestClient

from gbox import built_mods, cache_tiers, catalog, filemods
from gbox.config import HOST_OS, Config


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def _no_active_tiers(monkeypatch):
    monkeypatch.setattr(cache_tiers, "ACTIVE", None)
    yield
    if cache_tiers.ACTIVE is not None:
        cache_tiers.ACTIVE.stop()


def make(tmp_path, cap=10**9, idle_s=60.0, open_check=None, **kw):
    hot, cold = tmp_path / "nvme" / "gbox-cache", tmp_path / "hdd" / "gbox-cache"
    hot.mkdir(parents=True)
    cold.mkdir(parents=True)
    clock = Clock()
    t = cache_tiers.Tiers(hot, cold, cap, idle_s=idle_s, probes=[], open_check=open_check or (lambda roots: []),
                          clock=clock, data_dir=tmp_path / "data", **kw)
    return t, clock


def game(root, gid="g1", size=300_000):
    """A staged game folder, a base copy, and a mod hard-linked onto the base (the filemods layout)."""
    (root / gid).mkdir(parents=True)
    (root / gid / "disc.iso").write_bytes(b"I" * size)
    base = root / "modbase" / gid
    (base / "sub").mkdir(parents=True)
    (base / "sub" / "data.bin").write_bytes(b"D" * 200_000)
    (base / ".gbox-base-complete").write_text("src")
    mod = root / "mods" / gid / "m1"
    (mod / "sub").mkdir(parents=True)
    os.link(base / "sub" / "data.bin", mod / "sub" / "data.bin")
    (mod / "patched.bin").write_bytes(b"P" * 1000)
    (mod / ".gbox-mod.json").write_text(json.dumps({"name": "m1", "game_id": gid, "built": 1.0}))
    return root


def parts(gid="g1"):
    return (gid, f"modbase/{gid}", f"mods/{gid}")


def trash_empty(root):
    d = root / ".gbox-tiers" / "trash"
    return not d.exists() or not any(d.iterdir())


# ------------------------------------------------------------------------------------------------ moves

def test_demotion_leaves_a_symlink_and_hard_links_survive(tmp_path):
    t, _ = make(tmp_path)
    game(t.hot)
    rec = t.demote("g1")
    assert rec["op"] == "demote" and rec["bytes"] == cache_tiers.tree_size(t.cold, list(parts())) > 500_000
    for p in parts():
        assert os.path.islink(t.hot / p) and t.where(p) == "cold"
        assert (t.cold / p).is_dir() and not os.path.islink(t.cold / p)
    assert (t.hot / "g1" / "disc.iso").read_bytes() == b"I" * 300_000          # old paths keep working
    assert os.path.samefile(t.cold / "modbase/g1/sub/data.bin", t.cold / "mods/g1/m1/sub/data.bin")
    assert t.tier("g1") == "cold" and t.usage(fresh=True)["units"] == {}
    assert trash_empty(t.hot) and not list(t.journal_dir.glob("*.json"))


def test_promotion_on_access_brings_the_unit_back(tmp_path, monkeypatch):
    t, _ = make(tmp_path)
    game(t.hot)
    t.demote("g1")
    monkeypatch.setattr(cache_tiers, "ACTIVE", t)
    busy = []
    with cache_tiers.job_scope("cast_swap", {"game": {"game_id": "g1", "title": "Game"}, "name": "x"}):
        busy.append(t.busy_reason())
        assert all(t.where(p) == "hot" for p in parts())
    assert busy == ["1 job(s) running on this node"] and t.busy_reason() is None
    assert os.path.samefile(t.hot / "modbase/g1/sub/data.bin", t.hot / "mods/g1/m1/sub/data.bin")
    assert not any(os.path.lexists(t.cold / p) for p in parts())              # one copy: the cold one went to trash
    assert t.purge_trash() >= 1 and trash_empty(t.cold)
    assert (t.hot / "g1" / "disc.iso").read_bytes() == b"I" * 300_000


def test_registry_execute_promotes_units_its_input_names(tmp_path, monkeypatch):
    from gbox.registry import Ctx, execute
    t, _ = make(tmp_path)
    game(t.hot)
    t.demote("g1")
    monkeypatch.setattr(cache_tiers, "ACTIVE", t)
    execute("echo_artifact", {"message": "g1"}, Ctx(Config(data_dir=tmp_path / "data")))
    assert t.tier("g1") == "hot"


def test_launch_waits_only_for_a_quick_promotion(tmp_path, monkeypatch):
    t, clock = make(tmp_path, promote_wait_s=60)
    game(t.hot)
    t.demote("g1")
    t.cold_rate = 1000.0                                  # 500 KB at 1 KB/s: too slow to wait for
    out = t.promote_for("launch_game", {"game": {"game_id": "g1"}})
    assert out == [{"unit": "g1", "queued": True}] and t.tier("g1") == "cold" and "g1" in t._queue
    t.cold_rate = 80e6
    out = t.promote_for("launch_game", {"game": {"game_id": "g1"}})
    assert out[0]["op"] == "promote" and t.tier("g1") == "hot"


def test_a_launched_cold_game_moves_up_when_idle_and_pushes_out_an_older_one(tmp_path):
    t, clock = make(tmp_path, cap=1_000_000, idle_s=60)
    game(t.hot, "old", size=400_000)
    game(t.hot, "g1", size=400_000)
    t.demote("g1")
    t.state["warm_done"] = 1
    t.touch("old", at=clock.t - 10_000)
    t.cold_rate = 1000.0
    assert t.promote_for("launch_game", {"game": {"game_id": "g1"}}) == [{"unit": "g1", "queued": True}]
    with t.busy():                                        # the session plays from the HDD
        clock.t += 30
    assert t.tick()["waiting"]
    clock.t += 120                                        # idle again
    out = t.tick()
    assert out["promoted"] == ["g1"] and out["demoted"] == ["old"]
    assert t.tier("g1") == "hot" and t.tier("old") == "cold"


def test_new_writes_land_on_hot_and_mixed_units_move_whole(tmp_path):
    t, _ = make(tmp_path)
    game(t.hot)
    t.demote("g1")
    (t.hot / "dc" / "g1").mkdir(parents=True)              # a writer creates a part that did not exist: on the NVMe
    (t.hot / "dc" / "g1" / "disc.gdi").write_text("gdi")
    assert t.tier("g1") == "mixed"
    t.promote("g1")
    assert t.tier("g1") == "hot"
    t.demote("g1")
    assert t.where("dc/g1") == "cold" and (t.hot / "dc/g1/disc.gdi").read_text() == "gdi"


# ------------------------------------------------------------------------------------------------ idle gating, guards

def test_idle_gating_and_lru_and_cap(tmp_path):
    t, clock = make(tmp_path, cap=1_000_000, idle_s=60)
    for i, gid in enumerate(("old", "mid", "new")):
        game(t.hot, gid, size=400_000)
        t.touch(gid, at=clock.t - 1000 + i * 10)           # old < mid < new
    t.state["warm_done"] = 1
    with t.busy():                                        # a job: nothing moves
        assert t.tick()["waiting"].startswith("1 job")
    assert "quiet for" in t.tick()["waiting"]             # just after the job: still waiting
    t.probes.append(lambda: "1 game session(s) on this node")
    clock.t += 120
    assert "session" in t.tick()["waiting"]
    t.probes.clear()
    clock.t += 120
    out = t.tick()
    # 3 x ~601 KB = 1.8 MB over a 1 MB cap: demote LRU until under 0.9 MB -> the two oldest go
    assert out["demoted"] == ["old", "mid"]
    assert t.tier("new") == "hot" and t.usage()["total"] <= 1_000_000 * cache_tiers.LOW_WATER


def test_recently_used_unit_is_not_demoted(tmp_path):
    t, clock = make(tmp_path, cap=100_000, idle_s=60)
    game(t.hot, "busy1")
    game(t.hot, "cold1")
    t.state["warm_done"] = 1
    clock.t += 1000
    t.touch("cold1", at=clock.t - 500)
    t.touch("busy1", at=clock.t - 5)                       # API traffic named it seconds ago
    out = t.tick()
    assert out["demoted"] == ["cold1"] and t.tier("busy1") == "hot"


def test_open_file_guard(tmp_path):
    held = []
    t, clock = make(tmp_path, open_check=lambda roots: held)
    game(t.hot)
    held.append("pid 42: /x/g1/disc.iso")
    with pytest.raises(cache_tiers.Cancelled):
        t.demote("g1")
    assert t.tier("g1") == "hot" and not any(os.path.lexists(t.cold / p) for p in parts())
    held.clear()
    assert t.demote("g1") and t.tier("g1") == "cold"


def test_demotion_gives_way_when_the_unit_is_asked_for(tmp_path):
    t, _ = make(tmp_path)
    game(t.hot)
    calls = []

    def cancel():
        calls.append(1)
        if len(calls) == 3:
            t.touch("g1")                                 # e.g. an API request names the game mid-copy
    with pytest.raises(cache_tiers.Cancelled):
        t.demote("g1", cancel=cancel)
    assert t.tier("g1") == "hot" and not any(os.path.lexists(t.cold / p) for p in parts())
    assert not list(t.journal_dir.glob("*.json"))


def test_pinned_set_is_never_moved(tmp_path):
    t, clock = make(tmp_path, cap=1000)
    (t.hot / "characters" / "aya").mkdir(parents=True)
    (t.hot / "characters" / "aya" / "model.glb").write_bytes(b"M" * 50_000)
    (t.hot / "environments" / "stage").mkdir(parents=True)
    (t.hot / "environments" / "stage" / "scene.glb").write_bytes(b"E" * 50_000)
    (t.hot / catalog.STAGE_DB).write_text("{}")
    t.state["warm_done"] = 1
    clock.t += 10_000
    out = t.tick()
    assert out.get("demoted") == [] and t.where("characters") == "hot" and t.where("environments") == "hot"
    u = t.usage()
    assert u["pinned"] >= 100_000 and u["units"] == {}
    assert any("pinned data alone" in w for w in t.status()["warnings"])
    with pytest.raises(ValueError):
        t.set_pin("characters", True)


def test_keep_on_fast_drive_pin(tmp_path):
    t, clock = make(tmp_path, cap=1000)
    game(t.hot)
    t.demote("g1")
    t.state["warm_done"] = 1
    clock.t += 10_000
    t.set_pin("g1", True)
    t.tick()                                              # idle: the pinned game comes back and stays
    assert t.tier("g1") == "hot"
    clock.t += 10_000
    t.tick()
    assert t.tier("g1") == "hot"


# ------------------------------------------------------------------------------------------------ crash safety

class Crash(BaseException):
    pass


def test_crash_during_copy_rolls_back(tmp_path):
    t, _ = make(tmp_path)
    game(t.hot)
    # the state a power cut leaves: journal in "copying", a partial copy on the cold disk
    mid = "20261013-000000-abcdef"
    t._journal({"id": mid, "op": "demote", "unit": "g1", "parts": list(parts()), "phase": "copying", "aside": False})
    partial = t.cold / ".gbox-tiers" / "incoming" / mid / "g1"
    partial.mkdir(parents=True)
    (partial / "disc.iso").write_bytes(b"I" * 10)
    t2, _ = make_again(t)
    assert t2.recover() == ["g1: demote rolled back"]
    assert t2.tier("g1") == "hot" and (t2.hot / "g1/disc.iso").stat().st_size == 300_000
    assert not os.path.lexists(t2.cold / "g1") and not list(t2.journal_dir.glob("*.json"))
    t2.purge_trash()
    assert not (t2.cold / ".gbox-tiers" / "incoming" / mid).exists()


def make_again(t):
    return cache_tiers.Tiers(t.hot, t.cold, t.cap, idle_s=t.idle_s, probes=[], open_check=lambda r: [], clock=t.clock), None


def test_crash_mid_switch_of_a_demotion_rolls_forward(tmp_path, monkeypatch):
    t, _ = make(tmp_path)
    game(t.hot)
    real = cache_tiers.Tiers._swap_to_link
    n = []

    def flaky(self, p, mid, i):
        if n:
            raise Crash()                                  # power cut after the first part switched
        n.append(p)
        return real(self, p, mid, i)
    monkeypatch.setattr(cache_tiers.Tiers, "_swap_to_link", flaky)
    with pytest.raises(Crash):
        t.demote("g1")
    monkeypatch.setattr(cache_tiers.Tiers, "_swap_to_link", real)
    states = {p: t.where(p) for p in parts()}
    assert sorted(states.values()) == ["cold", "hot", "hot"]           # half switched: each part readable somewhere
    t2, _ = make_again(t)
    assert t2.recover() == ["g1: demote finished"]
    assert all(t2.where(p) == "cold" for p in parts()) and trash_empty(t2.hot)
    assert (t2.hot / "mods/g1/m1/patched.bin").read_bytes() == b"P" * 1000


def test_crash_between_unlink_and_rename_of_a_promotion(tmp_path, monkeypatch):
    t, _ = make(tmp_path)
    game(t.hot)
    t.demote("g1")
    monkeypatch.setattr(cache_tiers, "_exchange", lambda a, b: False)   # the non-atomic fallback path
    real_rename = os.rename
    hits = []

    def rename(a, b):
        if str(b) == str(t.hot / "modbase" / "g1") and not hits:
            hits.append(1)
            raise Crash()                                  # the symlink is gone, the copy not yet renamed in
        return real_rename(a, b)
    monkeypatch.setattr(cache_tiers.os, "rename", rename)
    with pytest.raises(Crash):
        t.promote("g1")
    monkeypatch.setattr(cache_tiers.os, "rename", real_rename)
    assert t.where("modbase/g1") == "unlinked"            # neither link nor folder at the hot path ...
    t2, _ = make_again(t)
    t2.recover()                                          # ... but the staged copy is complete: renamed in
    assert all(t2.where(p) == "hot" for p in parts())
    assert os.path.samefile(t2.hot / "modbase/g1/sub/data.bin", t2.hot / "mods/g1/m1/sub/data.bin")
    assert not any(os.path.lexists(t2.cold / p) for p in parts())


def test_late_write_during_the_switch_is_carried_over(tmp_path, monkeypatch):
    t, _ = make(tmp_path)
    game(t.hot)
    real = cache_tiers.Copier.verify

    def verify_then_write(self):
        real(self)
        if self.src_root == t.hot:                         # a writer slips in after the last delta pass
            (t.hot / "mods/g1/m1/late.txt").write_text("late")
    monkeypatch.setattr(cache_tiers.Copier, "verify", verify_then_write)
    rec = t.demote("g1")
    assert rec["late"] == 1 and (t.hot / "mods/g1/m1/late.txt").read_text() == "late"
    assert (t.cold / "mods/g1/m1/late.txt").read_text() == "late"


# ------------------------------------------------------------------------------------------------ migration

def cold_layout(cold, hot):
    game(cold, "g1")
    game(cold, "g2")
    (cold / "characters" / "aya").mkdir(parents=True)
    (cold / "characters" / "aya" / "meta.json").write_text('{"slug": "aya"}')
    (cold / "characters_build" / "cast").mkdir(parents=True)
    (cold / "characters_build" / "cast" / "x.bin").write_bytes(b"x")
    (cold / "lcs_re").mkdir()
    (cold / "lcs_re" / "notes.txt").write_text("re")
    sep = os.sep
    (cold / catalog.STAGE_DB).write_text(json.dumps({f"{cold}{sep}g1{sep}disc.iso": {"sha1": "ab", "ident": [300000, 5]}}))


def test_migration_from_an_all_cold_layout(tmp_path):
    t, clock = make(tmp_path)
    cold_layout(t.cold, t.hot)
    t.data_dir.mkdir(parents=True)
    (t.data_dir / "built_mods_index.json").write_text(json.dumps({"version": 1, "root": str(t.cold / "mods"), "mods": {}}))
    out = t.migrate()
    assert out["linked"] == 2 * 3 + 1 + 1 + 1             # 2 games x 3 parts, characters, characters_build/cast, lcs_re
    for gid in ("g1", "g2"):
        assert t.tier(gid) == "cold" and (t.hot / gid / "disc.iso").stat().st_size == 300_000
    assert t.where("characters") == "cold" and (t.hot / "characters_build").is_dir() \
        and not os.path.islink(t.hot / "characters_build") and t.where("characters_build/cast") == "cold"
    db = json.loads((t.hot / catalog.STAGE_DB).read_text())
    assert list(db) == [str(t.hot / "g1" / "disc.iso")]
    assert (t.cold / (catalog.STAGE_DB + cache_tiers.MIGRATED)).exists()          # the original is kept, renamed
    assert json.loads((t.data_dir / "built_mods_index.json").read_text())["root"] == str(t.hot / "mods")
    assert t.migrate()["linked"] == 0                     # idempotent
    # the pinned library comes over first, verified; the cold original is kept aside
    assert t.pinned_pending() == ["characters"]
    t.tick()
    assert t.where("characters") == "hot" and (t.hot / "characters/aya/meta.json").exists()
    assert (t.cold / ("characters" + cache_tiers.MIGRATED) / "aya" / "meta.json").exists()
    assert t.pinned_pending() == []
    # LRU times come from the folders' mtimes; the warm-up promotes the newest units within half the cap
    assert {"g1", "g2", "lcs_re", "characters_build/cast"} <= set(t.state["units"])


def test_migration_warm_up_promotes_most_recent_within_budget(tmp_path):
    t, clock = make(tmp_path, cap=2_000_000, warm_fraction=0.5)
    cold_layout(t.cold, t.hot)
    t.migrate()
    t.touch("g1", at=clock.t - 5000)
    t.touch("g2", at=clock.t - 4000)                       # newer
    clock.t += 10_000
    out = t.tick()                                        # pinned library first, then (idle) the warm-up
    assert out["pinned"][0]["unit"] == "characters"
    assert "g2" in out["warmed"] and t.tier("g2") == "hot"
    assert t.tier("g1") == "cold"                          # 2 x 600 KB would pass the 1 MB budget
    assert t.state.get("warm_done")


def test_first_migration_moves_a_conflicting_hot_leftover_aside(tmp_path):
    t, _ = make(tmp_path)
    game(t.cold, "g1")
    (t.hot / "g1").mkdir()
    (t.hot / "g1" / "leftover.bin").write_bytes(b"L")
    (t.hot / "n64-rom").mkdir()                             # hot-only leftovers stay where they are
    out = t.migrate()
    assert out["conflicts"][0]["path"] == "g1" and out["conflicts"][0]["kept"] == "cold"
    assert t.where("g1") == "cold" and Path_exists(out["conflicts"][0]["hot_copy"], "leftover.bin")
    assert t.where("n64-rom") == "hot"
    # later starts: the hot copy is authoritative, a cold duplicate is only reported
    (t.cold / "n64-rom").mkdir()
    out = t.migrate()
    assert out["conflicts"] == [{"path": "n64-rom", "kept": "hot", "at": t.clock()}] and t.where("n64-rom") == "hot"


def Path_exists(d, name):
    return os.path.exists(os.path.join(d, name))


def test_missing_cold_mount_is_never_created(tmp_path):
    t, _ = make(tmp_path)
    game(t.hot)
    os.rmdir(t.cold)
    os.rmdir(t.cold.parent)
    assert "error" in t.migrate() and not t.cold.exists()
    assert t.demote("g1") is None and t.tick() == {"skipped": "cold dir not available"} and not t.cold.exists()


# ------------------------------------------------------------------------------------------------ the rest of gBox

def test_other_modules_work_through_a_demoted_unit(tmp_path, monkeypatch):
    t, _ = make(tmp_path)
    game(t.hot)
    (t.hot / "mods/g1/m1/preview.png").write_bytes(b"png")
    t.demote("g1")
    monkeypatch.setattr(cache_tiers, "ACTIVE", t)
    cfg = types.SimpleNamespace(cache=t.hot)
    d = filemods.mod_dir(cfg, "g1", "m1")                  # resolves into the cold tier: still inside the game
    assert (d / ".gbox-mod.json").exists()
    assert [m["name"] for m in filemods.list_mods(cfg, "g1")] == ["m1"]
    assert [r["name"] for r in built_mods.scan(t.hot / "mods")] == ["m1"]
    assert built_mods.image_path(cfg, "g1", "m1", "preview.png").read_bytes() == b"png"
    conf = Config(data_dir=tmp_path / "data", cache_dir=t.hot)
    r = catalog.stage_begin(t.hot / "mods" / "g1" / "m1" / "patched.bin", "g1", conf)
    assert isinstance(r, dict) and r.get("in_cache") and r["dst"] == str(t.hot / "mods/g1/m1/patched.bin")
    assert not (t.hot / "g1" / "patched.bin").exists()     # not copied next to the staged game


def test_eviction_never_touches_pinned_bases_mods_or_cold_data(tmp_path):
    t, _ = make(tmp_path)
    game(t.hot, "g1")
    game(t.hot, "g2")
    (t.hot / "dc" / "g2").mkdir(parents=True)              # a demoted part inside an evictable container
    (t.hot / "dc" / "g2" / "disc.gdi").write_bytes(b"G" * 10)
    t.demote("g2")
    assert os.path.islink(t.hot / "dc" / "g2")
    (t.hot / "characters" / "aya").mkdir(parents=True)
    (t.hot / "characters" / "aya" / "m.glb").write_bytes(b"C" * 100_000)
    os.utime(t.hot / "characters" / "aya" / "m.glb", (1, 1))
    evicted = catalog.evict(t.hot, 0)
    assert evicted == [str(t.hot / "g1" / "disc.iso")]
    assert (t.hot / "characters/aya/m.glb").exists() and (t.hot / "modbase/g1/sub/data.bin").exists()
    assert (t.cold / "g2" / "disc.iso").exists() and (t.hot / "mods/g1/m1/patched.bin").exists()
    assert (t.cold / "dc" / "g2" / "disc.gdi").exists()


def test_demotion_keeps_stat_keyed_hashes_valid(tmp_path, monkeypatch):
    """The HDD stores mtimes at 100 ns: sidecar rows and stage db idents follow, so nothing is re-hashed."""
    t, _ = make(tmp_path)
    game(t.hot)
    st = os.stat(t.hot / "mods/g1/m1/patched.bin")
    import hashlib
    sha = hashlib.sha256(b"P" * 1000).hexdigest()
    (t.hot / "mods/g1/.m1.sha256.json").write_text(json.dumps({"patched.bin": [st.st_mtime_ns, 1000, sha]}))
    iso = t.hot / "g1" / "disc.iso"
    catalog._db_set(t.hot, str(iso), {"sha1": "x", "ident": [300_000, os.stat(iso).st_mtime_ns]})
    real = cache_tiers.Copier._copy_file

    def coarse(self, rel, st, allow_link):                # what ntfs-3g does to a nanosecond mtime
        real(self, rel, st, allow_link)
        m = self.man[rel]
        if not m.get("link"):
            ns = (st.st_mtime_ns // 100) * 100 - 100
            os.utime(self.dst_root / rel, ns=(ns, ns))
            m["dmtime"] = ns
    monkeypatch.setattr(cache_tiers.Copier, "_copy_file", coarse)
    monkeypatch.setattr(cache_tiers.Copier, "_dir_times", lambda self: None)
    t.demote("g1")
    rows = json.loads((t.cold / "mods/g1/.m1.sha256.json").read_text())
    assert rows["patched.bin"][0] == os.stat(t.cold / "mods/g1/m1/patched.bin").st_mtime_ns != st.st_mtime_ns
    assert catalog._db_load(t.hot)[str(iso)]["ident"] == [300_000, os.stat(t.cold / "g1/disc.iso").st_mtime_ns]


def test_keys_in_and_touch_request(tmp_path):
    t, clock = make(tmp_path)
    game(t.hot, "78ab9efa2e310db4")
    (t.hot / "characters_build" / "aya").mkdir(parents=True)
    assert t.keys_in({"game": {"game_id": "78ab9efa2e310db4"}, "n": 3}) == {"78ab9efa2e310db4"}
    assert t.keys_in({"rom": str(t.hot / "mods" / "78ab9efa2e310db4" / "m1" / "x.iso")}) == {"78ab9efa2e310db4"}
    assert t.keys_in({"character": "aya"}) == {"characters_build/aya"}
    assert t.keys_in({"slug": "characters"}) == set()     # pinned data is not a unit
    clock.t += 50
    assert t.touch_request("/api/modfiles/78ab9efa2e310db4/m1", b"x=1") == {"78ab9efa2e310db4"}
    assert t.state["units"]["78ab9efa2e310db4"]["atime"] == clock.t


def test_unit_keys_never_leave_the_roots(tmp_path, monkeypatch):
    for k in ("g1", "characters_build/aya", "78ab9efa2e310db4"):
        assert cache_tiers.safe_key(k)
    for k in ("..", "a/b", "x\\y", "C:x", "characters_build/..", "", "a\x00b", None):
        assert not cache_tiers.safe_key(k)
    t, _ = make(tmp_path)
    monkeypatch.setattr(cache_tiers, "ACTIVE", t)
    t.touch("..")
    cache_tiers.touch("nope", queue=True)                 # an API call naming a game that is not cached
    assert t.state["units"] == {} and not t._queue
    with pytest.raises(ValueError):
        t.promote("../etc")
    with pytest.raises(ValueError):
        t.demote("characters")


# ------------------------------------------------------------------------------------------------ API

def test_status_endpoint_and_pin(tmp_path):
    hot, cold = tmp_path / "nvme", tmp_path / "hdd"
    cold.mkdir()
    game(cold, "g1")
    (cold / "characters" / "aya").mkdir(parents=True)
    (cold / "characters" / "aya" / "meta.json").write_text("{}")
    cfg = Config(data_dir=tmp_path / "data", cache_dirs={HOST_OS: str(hot)}, cold_cache_dirs={HOST_OS: str(cold)},
                 hot_cache_limit_gb={HOST_OS: 1})
    from gbox.server import create_app
    app = create_app(cfg)
    c = TestClient(app)
    h = {"authorization": f"Bearer {cfg.token()}"}
    t = cache_tiers.ACTIVE
    assert t is not None and t.hot == hot and t.tier("g1") == "cold"     # migrated at start-up
    s = c.get("/api/cache/tiers", headers=h).json()
    assert s["enabled"] and s["hot"]["cap"] == 1024**3 and s["units"]["cold"] == 1
    assert {"unit", "tier", "size", "last_used", "pin"} <= set(s["top"][0])
    r = c.post("/api/cache/tiers/pin", json={"unit": "g1", "pin": True}, headers=h).json()
    assert r["pin"] and t.state["units"]["g1"]["pin"]
    assert c.post("/api/cache/tiers/pin", json={"unit": "characters"}, headers=h).status_code == 400
    before = t.state["units"]["g1"].get("atime")
    t.clock = lambda: 2e12
    c.get("/api/mods/built/g1/m1/image/x.png", headers=h)     # any API path naming the game marks it used
    assert t.state["units"]["g1"]["atime"] == 2e12 != before


def test_single_tier_nodes_are_unchanged(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    assert cache_tiers.install(cfg) is None and cache_tiers.ACTIVE is None
    from gbox.server import create_app
    c = TestClient(create_app(cfg))
    s = c.get("/api/cache/tiers", headers={"authorization": f"Bearer {cfg.token()}"}).json()
    assert s == {"enabled": False, "cache": str(tmp_path / "cache"), "cap": int(20 * 1024**3)}


linux_only = pytest.mark.skipif(not cache_tiers.IS_LINUX, reason="renameat2 and /proc are Linux")


@linux_only
def test_atomic_exchange_of_folder_and_symlink(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "f").write_text("data")
    os.symlink(str(tmp_path / "elsewhere"), tmp_path / "link")
    assert cache_tiers._exchange(tmp_path / "link", tmp_path / "real")
    assert os.path.islink(tmp_path / "real") and (tmp_path / "link" / "f").read_text() == "data"


@linux_only
def test_real_open_file_scan_blocks_demotion(tmp_path):
    t, _ = make(tmp_path, open_check=cache_tiers.open_files_under)
    game(t.hot)
    with open(t.hot / "g1" / "disc.iso", "rb"):
        assert cache_tiers.open_files_under([t.hot / "g1"])
        with pytest.raises(cache_tiers.Cancelled):
            t.demote("g1")
    assert not cache_tiers.open_files_under([t.hot / "g1"])
    assert t.demote("g1") and t.tier("g1") == "cold"
