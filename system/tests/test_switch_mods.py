"""Switch builds as LayeredFS overlays (gbox.switch_mods, docs/switch-mods.md): a build is only its changed RomFS files,
linked into Eden's load/<title id>/ and selected through [DisabledAddOns]; edits land in place with backups; an in-game
swap restarts the title in the same session; the audit turns old full copies into overlays. Temp dirs and a fake Eden
config only: no emulator, no NSP content (a tiny PFS0 with a ticket name gives the title id)."""
import base64
import json
import struct
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import adapters, built_mods, filemods, provision, server, switch_mods as SM
from gbox.config import Config

RE5, RE6 = "010018100CD46000", "01002A000CD48000"
GID = "52d15709be0fda1a"                        # the catalog id of the Spark's RE5 Switch NSP
CREATE = {"title_id": RE5, "game_title": "Resident Evil 5", "base": "Resident Evil 5.nsp"}
ARM64_MAPS = [                                   # Eden's HostMemory arena once a game booted (see test_switch_linux)
    "1200000000-1208000000 rw-p 00000000 00:00 0 ",
    "1208000000-1210000000 r-xp 00000000 00:01 123 /memfd:HostMemory (deleted)",
    "1210000000-5200000000 rw-p 00000000 00:00 0 ",
]


def cfg(tmp_path) -> Config:
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")


def nsp(path: Path, tid: str = RE5) -> Path:
    """A tiny PFS0 container whose ticket names the title id (the NCAs are irrelevant here)."""
    names = [f"{tid.lower()}0000000000000003.tik", "a.nca"]
    table = b"".join(n.encode() + b"\0" for n in names)
    entries, offset, name_at = b"", 0, 0
    for n in names:
        entries += struct.pack("<QQII", offset, 3, name_at, 0)
        offset, name_at = offset + 3, name_at + len(n) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<4sIII", b"PFS0", len(names), len(table), 0) + entries + table + b"nca" * len(names))
    return path


def overlay(c, name: str, files=None) -> Path:
    files = files or {"arc/pl/pl00.arc": b"A" * 16}
    return Path(SM.write_files(c, GID, name, {k: {"bytes": v} for k, v in files.items()}, create=CREATE)["dir"])


# --- Eden's [DisabledAddOns] (frontend_common/config.cpp) ----------------------------------------------------------------

def test_disabled_addons_section_is_edens_own_layout_and_keeps_the_rest_of_the_file():
    other = 0x0100000000000000
    text = ("[UI]\ntheme=dark\n\n[DisabledAddOns]\n1\\title_id\\default=false\n1\\title_id=%d\n"
            "1\\disabled\\1\\d\\default=false\n1\\disabled\\1\\d=Update\n1\\disabled\\size=1\nsize=1\n\n"
            "[Renderer]\nbackend=1\n" % other)
    table = SM.read_disabled(text)
    assert table == {other: ["Update"]}
    table[int(RE5, 16)] = ["b", "a~1"]
    out = SM.write_disabled(text, table)
    assert out.startswith("[UI]\ntheme=dark\n\n[DisabledAddOns]\n") and out.endswith("\n\n[Renderer]\nbackend=1\n")
    assert SM.read_disabled(out) == table
    lines = out.split("\n")
    # the keys ReadDisabledAddOnValues walks, each with its \default=false twin (a missing twin reads as the default)
    for want in ("1\\title_id=%d" % other, "2\\title_id\\default=false", "2\\title_id=%d" % int(RE5, 16),
                 "2\\disabled\\1\\d\\default=false", "2\\disabled\\1\\d=b", '2\\disabled\\2\\d="a~1"',
                 "2\\disabled\\size=2", "size=2"):
        assert want in lines                          # '~' is one of Eden's special characters: written quoted
    fresh = SM.write_disabled("", {int(RE5, 16): ["x"]})
    assert fresh.startswith("[DisabledAddOns]\n") and fresh.endswith("size=1\n")


def test_a_value_marked_default_reads_as_edens_default_and_a_missing_twin_keeps_the_value():
    kv = {"size": "2", "1\\title_id\\default": "true", "1\\title_id": "5", "1\\disabled\\size": "1",
          "1\\disabled\\1\\d": "x", "2\\title_id": "7", "2\\disabled\\size": "2", "2\\disabled\\1\\d": '"q;r"',
          "2\\disabled\\2\\d\\default": "true", "2\\disabled\\2\\d": "ignored"}
    assert SM.parse_disabled(kv) == {7: ["q;r"]}


def test_selection_disables_every_other_mod_folder_and_keeps_the_operators_entries(tmp_path):
    e = SM.eden(cfg(tmp_path))
    e.config.parent.mkdir(parents=True)
    e.config.write_text("[DisabledAddOns]\n1\\title_id\\default=false\n1\\title_id=%d\n1\\disabled\\1\\d\\default=false\n"
                        "1\\disabled\\1\\d=Update\n1\\disabled\\size=1\nsize=1\n" % int(RE5, 16))
    pv = e.cache / "game_list" / f"{RE5}.pv.txt"
    pv.parent.mkdir(parents=True)
    pv.write_text("cached add-on column")
    r = SM.set_title_disabled(e, RE5, ["a", "b", "mine"], "a")
    assert r["disabled"] == ["Update", "b", "mine"] and r["changed"] and not pv.exists()   # like the Add-Ons tab
    r = SM.set_title_disabled(e, RE5, ["a", "b", "mine"], None)                             # the original game
    assert sorted(r["disabled"]) == ["Update", "a", "b", "mine"]
    assert not SM.set_title_disabled(e, RE5, ["a", "b", "mine"], None)["changed"]
    assert SM.read_disabled(e.config.read_text())[int(RE5, 16)] == r["disabled"]


def test_a_crlf_config_with_a_bom_keeps_both(tmp_path):
    e = SM.eden(cfg(tmp_path))
    e.config.parent.mkdir(parents=True)
    e.config.write_bytes(b"\xef\xbb\xbf[UI]\r\ntheme=dark\r\n")
    SM.set_title_disabled(e, RE5, ["a"], None)
    raw = e.config.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf[UI]\r\ntheme=dark\r\n") and b"\r\n[DisabledAddOns]\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")


# --- builds: in place, backups, pending edits, copies ----------------------------------------------------------------

def test_edits_rewrite_only_the_named_files_in_place_with_backups_and_revert(tmp_path):
    c = cfg(tmp_path)
    first = SM.write_files(c, GID, "re5_chris", {"arc/pl/pl00.arc": {"bytes": b"one"}}, create=CREATE)
    folder = Path(first["dir"])
    assert (folder / "romfs/arc/pl/pl00.arc").read_bytes() == b"one" and not first["pending"]
    meta = SM.read_meta(folder)
    assert meta["layeredfs"]["title_id"] == RE5 and meta["files"] == ["romfs/arc/pl/pl00.arc"]
    assert meta["history"][-1]["files"][0] | {} == {"path": "romfs/arc/pl/pl00.arc", "change": "new", "was": "base",
                                                     "size": 3}
    second = SM.write_files(c, GID, "re5_chris", {"romfs/arc/pl/pl00.arc": {"bytes": b"two"},
                                                  "arc/em/em10.arc": {"b64": base64.b64encode(b"enemy").decode()}})
    rows = {f["path"]: f for f in SM.read_meta(folder)["history"][-1]["files"]}
    assert (folder / "romfs/arc/pl/pl00.arc").read_bytes() == b"two" and rows["romfs/arc/em/em10.arc"]["change"] == "new"
    assert rows["romfs/arc/pl/pl00.arc"]["change"] == "replaced"
    assert (folder / rows["romfs/arc/pl/pl00.arc"]["backup"]).read_bytes() == b"one"       # the replaced file is kept
    assert [p.name for p in (c.cache / "mods" / GID).iterdir()] == ["re5_chris"]          # never a second build
    SM.write_files(c, GID, "re5_chris", {"arc/pl/pl00.arc": {"patch": [{"offset": "0x1", "hex": "5a"}]}})
    assert (folder / "romfs/arc/pl/pl00.arc").read_bytes() == b"tZo"
    out = SM.revert(c, GID, "re5_chris")                                                  # the last edit
    assert (folder / "romfs/arc/pl/pl00.arc").read_bytes() == b"two" and out["reverted"]
    SM.revert(c, GID, "re5_chris", edit=second["edit"], paths=["arc/em/em10.arc"])        # it came from the game:
    assert not (folder / "romfs/arc/em/em10.arc").exists()                                # it leaves the overlay
    SM.write_files(c, GID, "re5_chris", {"arc/pl/pl00.arc": {"remove": True}})
    assert not (folder / "romfs").exists() and SM.read_meta(folder)["files"] == []        # the game's own file again
    assert SM.read_meta(folder)["file_changes"] == []
    with pytest.raises(ValueError, match="not a Switch LayeredFS build"):
        SM.write_files(c, GID, "unknown", {"arc/x": {"bytes": b"x"}})


def test_an_edit_of_a_running_build_waits_node_locally_and_lands_at_the_restart(tmp_path):
    c = cfg(tmp_path)
    folder = overlay(c, "re5_chris", {"arc/pl/pl00.arc": b"old"})
    marker = (folder / SM.MARKER).read_bytes()
    r = SM.write_files(c, GID, "re5_chris", {"arc/pl/pl00.arc": {"bytes": b"new"}}, in_use=True)
    assert r["pending"] and (folder / "romfs/arc/pl/pl00.arc").read_bytes() == b"old"   # nothing under the running game
    assert (folder / SM.MARKER).read_bytes() == marker                                   # the collection sees no change
    assert not [f for f in filemods._files(folder) if f["path"].startswith(SM.PENDING)]  # never in the manifest
    assert SM.summary(folder)["pending"] == [r["edit"]]
    got = SM.apply_pending(folder)
    assert got["applied"] == [r["edit"]] and (folder / "romfs/arc/pl/pl00.arc").read_bytes() == b"new"
    assert not (folder / SM.PENDING).exists() and (folder / SM.BACKUP / r["edit"] / "romfs/arc/pl/pl00.arc").is_file()


def test_a_new_build_copies_only_the_overlay_folder(tmp_path):
    c = cfg(tmp_path)
    folder = overlay(c, "re5_chris")
    SM.write_files(c, GID, "re5_chris", {"arc/pl/pl00.arc": {"bytes": b"B" * 16}})           # a backup now exists
    SM.write_files(c, GID, "re5_chris", {"arc/pl/pl01.arc": {"bytes": b"P"}}, in_use=True)    # and a pending edit
    r = SM.copy_build(c, GID, "re5_chris", "re5_chris_v2")
    new = Path(r["dir"])
    assert (new / "romfs/arc/pl/pl00.arc").read_bytes() == b"B" * 16 and r["files"] == 1 and r["bytes"] == 16
    assert not (new / SM.BACKUP).exists() and not (new / SM.PENDING).exists()
    meta = SM.read_meta(new)
    assert meta["copied_from"]["build"] == "re5_chris" and meta["name"] == "re5_chris_v2" and len(meta["history"]) == 1
    assert r["pending_left_in_source"] and (folder / SM.PENDING).is_dir()
    with pytest.raises(ValueError, match="already exists"):
        SM.copy_build(c, GID, "re5_chris", "re5_chris_v2")
    with pytest.raises(ValueError, match="letters, digits"):
        SM.copy_build(c, GID, "re5_chris", "bad name")


def test_an_overlay_build_honours_the_no_builds_on_the_system_drive_policy(tmp_path, monkeypatch):
    from gbox import storage_policy

    def refuse(cfg, path, what, **kw):
        raise storage_policy.SystemDriveRefused(f"{what}: {path} is on C:")
    monkeypatch.setattr(storage_policy, "require_off_system", refuse)
    c = cfg(tmp_path)
    with pytest.raises(storage_policy.SystemDriveRefused, match="build re5_chris"):
        SM.write_files(c, GID, "re5_chris", {"arc/x": {"bytes": b"x"}}, create=CREATE)
    assert not (c.cache / "mods" / GID / "re5_chris").exists()


def test_paths_are_romfs_unless_they_name_an_overlay_folder():
    assert SM.norm_path("arc/pl/pl00.arc") == "romfs/arc/pl/pl00.arc"
    assert SM.norm_path("\\RomFS\\arc\\x.arc") == "romfs/arc/x.arc" and SM.norm_path("exefs/main") == "exefs/main"
    for bad in ("", "../x", "romfs", "a/./b", "C:/x", ".gbox-backup/x", "romfs/.gbox-pending/x"):
        with pytest.raises(ValueError):
            SM.norm_path(bad)


def test_the_games_own_file_from_an_extracted_romfs_swaps_a_slot(tmp_path):
    c = cfg(tmp_path)
    base = tmp_path / "dump" / "romfs"
    (base / "arc/pl").mkdir(parents=True)
    (base / "arc/pl/pl02.arc").write_bytes(b"sheva")
    r = SM.write_files(c, GID, "re5_swap", {"arc/pl/pl00.arc": {"romfs": "arc/pl/pl02.arc"}}, romfs_base=base,
                       create=CREATE)
    assert (Path(r["dir"]) / "romfs/arc/pl/pl00.arc").read_bytes() == b"sheva"
    assert SM.read_meta(r["dir"])["history"][-1]["files"][0]["from_romfs"] == "romfs/arc/pl/pl02.arc"
    with pytest.raises(ValueError, match="extracted RomFS"):
        SM.write_files(c, GID, "re5_swap", {"arc/pl/pl01.arc": {"romfs": "arc/pl/pl02.arc"}})


# --- the emulator's view: links and the selection --------------------------------------------------------------------

def test_starting_a_build_links_it_enables_it_and_disables_the_other_gbox_builds(tmp_path):
    c = cfg(tmp_path)
    e = SM.eden(c)
    rom = nsp(tmp_path / "lib" / "Resident Evil 5.nsp")
    overlay(c, "a")
    overlay(c, "b", {"arc/pl/pl01.arc": b"b"})
    foreign = e.title_dir(RE5) / "operator_mod"
    (foreign / "romfs").mkdir(parents=True)
    (foreign / "romfs" / "x").write_text("mine")
    r = SM.prepare_launch(c, e, GID, rom, "a")
    assert r["selection"] == "applied" and r["enabled"] == "a" and sorted(r["disabled"]) == ["b"]
    assert r["mode"] == "link" and SM._linked(e.title_dir(RE5) / "a") and r["foreign"] == ["operator_mod"]
    assert (e.title_dir(RE5) / "a" / "romfs/arc/pl/pl00.arc").read_bytes() == b"A" * 16    # through the link
    assert (foreign / "romfs" / "x").read_text() == "mine"                                 # never touched
    assert SM.read_disabled(e.config.read_text())[int(RE5, 16)] == ["b"]                   # the operator's mod stays on
    assert SM.selected(c, "eden", RE5)["build"] == "a"
    original = SM.prepare_launch(c, e, GID, rom, None)                                    # every gBox build off
    assert original["enabled"] is None and sorted(original["disabled"]) == ["a", "b"]
    assert SM.selected(c, "eden", RE5)["build"] is None
    edited = SM.write_files(c, GID, "a", {"arc/pl/pl00.arc": {"bytes": b"edited"}})       # an in-place edit shows
    assert (e.title_dir(RE5) / "a" / "romfs/arc/pl/pl00.arc").read_bytes() == b"edited" and not edited["pending"]


def test_operator_mod_folders_keep_the_state_the_operator_gave_them(tmp_path):
    """gBox only switches its own builds: a mod the operator installed by hand stays on or off as they set it, for a
    build start and for the original game alike."""
    c = cfg(tmp_path)
    e = SM.eden(c)
    rom = nsp(tmp_path / "lib" / "Resident Evil 5.nsp")
    overlay(c, "a")
    for name in ("mine_on", "mine_off"):
        (e.title_dir(RE5) / name / "romfs").mkdir(parents=True)
    SM.set_title_disabled(e, RE5, ["mine_off"], None)                     # the operator turned one of them off
    r = SM.prepare_launch(c, e, GID, rom, "a")
    assert r["enabled"] == "a" and sorted(r["foreign"]) == ["mine_off", "mine_on"]
    assert SM.read_disabled(e.config.read_text())[int(RE5, 16)] == ["mine_off"]
    SM.prepare_launch(c, e, GID, rom, None)
    assert sorted(SM.read_disabled(e.config.read_text())[int(RE5, 16)]) == ["a", "mine_off"]


def test_symlinks_work_like_junctions(tmp_path, monkeypatch):
    """The Spark links with symlinks (Windows PCs with junctions): same selection, pruning and cleanup."""
    import os
    probe = tmp_path / "probe"
    try:
        os.symlink(tmp_path, probe, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege on this host")
    SM._unlink(probe)
    monkeypatch.setattr(SM, "_make_link", lambda target, link: os.symlink(target, link, target_is_directory=True))
    c = cfg(tmp_path)
    e = SM.eden(c)
    monkeypatch.setattr(SM, "local_emulators", lambda cfg: [e])
    rom = nsp(tmp_path / "Resident Evil 5.nsp")
    overlay(c, "a")
    overlay(c, "b")
    r = SM.prepare_launch(c, e, GID, rom, "b")
    link = e.title_dir(RE5) / "b"
    assert r["mode"] == "link" and SM._linked(link) and SM._ours(c, link) and r["disabled"] == ["a"]
    assert (link / "romfs/arc/pl/pl00.arc").read_bytes() == b"A" * 16
    assert SM.prepare_launch(c, e, GID, rom, "b")["mode"] == "link"                       # an existing link is kept
    filemods.delete_build(c, GID, "b")
    assert not SM._linked(link)
    with pytest.raises(ValueError, match="not a Switch LayeredFS build"):
        SM.prepare_launch(c, e, GID, rom, "b")


def test_a_copy_stands_in_when_no_link_can_be_made(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    e = SM.eden(c)
    rom = nsp(tmp_path / "Resident Evil 5.nsp")
    overlay(c, "a")

    def no_links(target, link):
        raise OSError("no symlink privilege")
    monkeypatch.setattr(SM, "_make_link", no_links)
    r = SM.prepare_launch(c, e, GID, rom, "a")
    entry = e.title_dir(RE5) / "a"
    assert r["mode"] == "copy" and not SM._linked(entry) and (entry / SM.COPY_MARK).is_file()
    SM.write_files(c, GID, "a", {"arc/pl/pl00.arc": {"bytes": b"v2"}})
    SM.prepare_launch(c, e, GID, rom, "a")                                                # rebuilt at each start
    assert (entry / "romfs/arc/pl/pl00.arc").read_bytes() == b"v2"


def test_deleted_builds_and_unused_staged_copies_leave_the_load_folder(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    e = SM.eden(c)
    monkeypatch.setattr(SM, "local_emulators", lambda cfg: [e])
    rom = nsp(tmp_path / "Resident Evil 5.nsp")
    overlay(c, "a")
    overlay(c, "b")
    SM.prepare_launch(c, e, GID, rom, "a")
    assert (e.title_dir(RE5) / "b").is_dir()
    assert filemods.delete_build(c, GID, "b")["removed"] == ["b"]
    assert not SM._linked(e.title_dir(RE5) / "b") and not (e.title_dir(RE5) / "b").exists()
    staged = c.cache / "mods" / GID / "a~k1"                                              # a fetched newer copy
    staged.mkdir()
    (staged / filemods.STAGED_MARK).write_text("a")
    (staged / SM.MARKER).write_text(json.dumps(SM.read_meta(c.cache / "mods" / GID / "a") | {"name": "a~k1"}))
    assert SM.prepare_launch(c, e, GID, rom, "a~k1")["enabled"] == "a~k1"
    SM.prepare_launch(c, e, GID, rom, "a")
    assert not (e.title_dir(RE5) / "a~k1").exists() and (e.title_dir(RE5) / "a").is_dir()


def test_a_build_is_refused_for_another_title_a_shared_emulator_or_no_title_id(tmp_path):
    c = cfg(tmp_path)
    e = SM.eden(c)
    rom6 = nsp(tmp_path / "Resident Evil 6.nsp", RE6)
    overlay(c, "a")
    with pytest.raises(ValueError, match="made for title 010018100CD46000"):
        SM.prepare_launch(c, e, GID, rom6, "a")
    with pytest.raises(ValueError, match="not a Switch LayeredFS build"):
        SM.prepare_launch(c, e, GID, nsp(tmp_path / "re5.nsp"), "missing")
    shared = SM.Emu("yuzu", tmp_path / "nas" / "load", tmp_path / "nas" / "qt-config.ini", None, False, "on a share")
    with pytest.raises(ValueError, match="private to this PC"):
        SM.prepare_launch(c, shared, GID, nsp(tmp_path / "re5.nsp"), "a")
    skipped = SM.prepare_launch(c, shared, GID, nsp(tmp_path / "re5.nsp"), None)
    assert skipped["selection"] == "skipped" and not (tmp_path / "nas").exists()          # a shared install untouched
    (tmp_path / "noid.xci").write_bytes(b"not a pfs0")
    assert SM.prepare_launch(c, e, GID, tmp_path / "noid.xci", None)["selection"] == "skipped"


def test_yuzu_is_private_only_as_a_local_portable_folder(tmp_path):
    assert not SM.yuzu(Path("//nas/HyperSpin/emulators/yuzu/yuzu.exe")).private
    exe = tmp_path / "yuzu" / "yuzu.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    assert not SM.yuzu(exe).private and "portable" in SM.yuzu(exe).why
    (exe.parent / "user").mkdir()
    y = SM.yuzu(exe)
    assert y.private and y.load == exe.parent / "user" / "load" and y.config.name == "qt-config.ini"


# --- the old copy paths never copy a Switch container -------------------------------------------------------------------

def test_an_overlay_boots_the_base_file_and_build_image_never_copies_a_container(tmp_path):
    c = cfg(tmp_path)
    rom = nsp(tmp_path / "lib" / "Resident Evil 5.nsp")
    overlay(c, "a")
    assert filemods.launch_path(c, GID, rom, "a") == rom
    assert SM.overlay_of(c, GID, "a") == "a" and SM.overlay_of(c, GID, "") is None
    with pytest.raises(ValueError, match="LayeredFS"):
        filemods.build_image(c, GID, rom, "full_copy", {"@image": {"patch": []}})
    assert not (c.cache / "mods" / GID / "full_copy").exists()


def test_file_mod_on_a_switch_game_merges_into_the_overlay(tmp_path):
    c = cfg(tmp_path)
    ctx = SimpleNamespace(config=c, server=None, headers={}, job_id="j1")
    game = {"game_id": GID, "title": "Resident Evil 5", "platform": "switch", "serial": RE5}
    rom = nsp(tmp_path / "lib" / "Resident Evil 5.nsp")
    r = SM.file_mod_build(ctx, game, rom, "re5_mod", {"arc/pl/pl00.arc": {"bytes": b"x"}})
    SM.file_mod_build(ctx, game, rom, "re5_mod", {"arc/pl/pl01.arc": {"bytes": b"y"}})
    assert r["layeredfs"] and r["title_id"] == RE5
    assert SM.read_meta(r["dir"])["files"] == ["romfs/arc/pl/pl00.arc", "romfs/arc/pl/pl01.arc"]
    assert not list((c.cache / "mods" / GID).rglob("*.nsp"))


# --- the Eden adapter: selection before start, restart in the same session ------------------------------------------------

def _eden(tmp_path, monkeypatch):
    from gbox import memory_card_sessions
    c = cfg(tmp_path)
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    monkeypatch.setattr(provision, "ensure_switch_linux", lambda *a, **k: None)
    monkeypatch.setattr(adapters, "Display", lambda *a: SimpleNamespace(name=":99", w=1280, h=720, close=lambda: None))
    monkeypatch.setattr(adapters, "_proc_tree", lambda pid: [pid])
    monkeypatch.setattr(adapters, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(adapters.time, "sleep", lambda s: None)
    monkeypatch.setattr(memory_card_sessions, "launched", lambda ad: None)
    killed = []
    monkeypatch.setattr(adapters.os, "kill", lambda pid, sig: killed.append((pid, sig)))   # never a real process
    ad = adapters.SwitchLinuxAdapter(c)
    ad.nce, ad.game_id, ad.serial = True, GID, RE5
    monkeypatch.setattr(ad, "_maps", lambda pid: ARM64_MAPS)
    monkeypatch.setattr(ad, "_xdo", lambda *a: None)
    spawned, pids = [], iter(range(501, 600))

    def popen(argv, **kw):
        e = SM.eden(c)
        spawned.append({"argv": argv, "display": kw["env"]["DISPLAY"], "proc": ad.proc,
                        "disabled": SM.read_disabled(e.config.read_text()).get(int(RE5, 16)) if e.config.exists() else None,
                        "links": sorted(p.name for p in e.title_dir(RE5).iterdir()) if e.title_dir(RE5).is_dir() else []})
        return SimpleNamespace(pid=next(pids), poll=lambda: None)
    monkeypatch.setattr(adapters.subprocess, "Popen", popen)
    return c, ad, spawned, killed


def test_eden_writes_the_selection_before_it_starts_and_reports_it(tmp_path, monkeypatch):
    c, ad, spawned, _ = _eden(tmp_path, monkeypatch)
    rom = nsp(tmp_path / "lib" / "Resident Evil 5.nsp")
    overlay(c, "a")
    overlay(c, "b")
    ad.overlay_build = "a"
    out = ad.launch_game(str(rom))
    assert spawned[0]["disabled"] == ["b"] and spawned[0]["links"] == ["a", "b"]           # in place before Eden ran
    assert out["overlay"]["enabled"] == "a" and out["overlay"]["title_id"] == RE5 and out["ready"] == "guest_memory"
    assert "[Renderer]" in SM.eden(c).config.read_text()                                   # its own settings kept


def test_restart_title_switches_the_build_in_the_same_session_and_display(tmp_path, monkeypatch):
    c, ad, spawned, killed = _eden(tmp_path, monkeypatch)
    rom = nsp(tmp_path / "lib" / "Resident Evil 5.nsp")
    overlay(c, "a")
    overlay(c, "b", {"arc/pl/pl01.arc": b"old"})
    ad.overlay_build = "a"
    ad.launch_game(str(rom))
    display = ad.display
    SM.write_files(c, GID, "b", {"arc/pl/pl01.arc": {"bytes": b"new"}}, in_use=True)     # waits for the restart
    monkeypatch.setattr(adapters, "Display", lambda *a: pytest.fail("a restart keeps the session's display"))
    out = ad.restart_title(overlay="b")
    assert out["same_session"] and out["previous_pid"] == 501 and out["pid"] == 502 and out["ready"] == "guest_memory"
    assert ad.display is display and spawned[1]["display"] == ":99" and spawned[1]["argv"] == spawned[0]["argv"]
    assert isinstance(spawned[1]["proc"], adapters._EdenRestarting) and spawned[1]["proc"].poll() is None   # the pump
    assert spawned[1]["disabled"] == ["a"] and out["overlay"]["pending_applied"]           # sees a running game
    assert (c.cache / "mods" / GID / "b" / "romfs/arc/pl/pl01.arc").read_bytes() == b"new"
    assert [p for p, _ in killed] == [501] and ad.overlay_build == "b"
    back = ad.restart_title(overlay=None)                                                  # the original game
    assert back["overlay"]["enabled"] is None and sorted(back["overlay"]["disabled"]) == ["a", "b"]


def test_reset_restarts_in_place_and_a_bad_build_never_stops_the_game(tmp_path, monkeypatch):
    c, ad, spawned, killed = _eden(tmp_path, monkeypatch)
    rom = nsp(tmp_path / "lib" / "Resident Evil 5.nsp")
    overlay(c, "a")
    ad.overlay_build = "a"
    ad.launch_game(str(rom))
    with pytest.raises(ValueError, match="not a Switch LayeredFS build"):
        ad.restart_title(overlay="missing")
    assert killed == [] and ad.proc.pid == 501 and ad.overlay_build == "a"
    out = ad.reset()
    assert out["reset"] and out["same_session"] and out["ready"] == "booting" and out["overlay"]["enabled"] == "a"
    ad.debug = True
    with pytest.raises(adapters.Unsupported, match="GDB stub"):
        ad.restart_title()


def test_apply_live_edits_the_running_build_and_restarts_the_title_in_one_action(tmp_path, monkeypatch):
    from gbox import tools
    c, ad, spawned, _ = _eden(tmp_path, monkeypatch)
    rom = nsp(tmp_path / "lib" / "Resident Evil 5.nsp")
    folder = overlay(c, "a", {"arc/pl/pl00.arc": b"chris"})
    ad.overlay_build = "a"
    ad.launch_game(str(rom))
    gd = {"game_id": GID, "title": "Resident Evil 5", "platform": "switch", "serial": RE5, "mod": "a",
          "_rom_path": str(rom)}
    monkeypatch.setitem(tools.SESSIONS, "w-1", (ad, gd))
    tracked = []
    monkeypatch.setattr(tools, "track_emulator", lambda cfg, sid, pid, add=True: tracked.append((sid, pid)))
    ctx = SimpleNamespace(config=c, server=None, headers={}, job_id="j1", progress=lambda *a: None)
    out = SM.apply_live(ctx, SM.SwitchModsIn(op="apply_live", session_id="w-1",
                                             changes={"arc/pl/pl00.arc": {"bytes": b"wesker"}}))
    assert out["same_session"] and out["build"] == "a" and out["edit"]["pending"]          # staged: the game ran it
    assert (folder / "romfs/arc/pl/pl00.arc").read_bytes() == b"wesker"                    # landed while Eden was down
    assert out["restart"]["overlay"]["pending_applied"] == [out["edit"]["edit"]]
    assert tracked == [("w-1", 502)] and out["session_detail"]["pid"] == 502 and gd["mod"] == "a"
    original = SM.apply_live(ctx, SM.SwitchModsIn(op="apply_live", session_id="w-1", build=""))
    assert original["build"] == "" and ad.overlay_build is None and spawned[-1]["disabled"] == ["a"]
    with pytest.raises(ValueError, match="not running on this worker"):
        SM.apply_live(ctx, SM.SwitchModsIn(op="apply_live", session_id="w-gone"))


def test_session_op_reset_reports_the_restarted_emulators_pid(tmp_path, monkeypatch):
    from gbox import tools
    from gbox.mercs import warm_boot

    class Ad:
        name = "eden"

        def __init__(self):
            self.proc = SimpleNamespace(pid=10, poll=lambda: None)

        def reset(self):
            self.proc = SimpleNamespace(pid=11, poll=lambda: None)
            return {"reset": True}
    monkeypatch.setitem(tools.SESSIONS, "w-1", (Ad(), {"game_id": GID}))
    tracked = []
    monkeypatch.setattr(tools, "track_emulator", lambda cfg, sid, pid, add=True: tracked.append((sid, pid)))
    monkeypatch.setattr(warm_boot, "cancel", lambda *a, **k: None)
    out = tools.session_op(tools.SessionIn(session_id="w-1", op="reset"), SimpleNamespace(config=cfg(tmp_path)))
    assert out["result"]["session_detail"] == {"pid": 11} and tracked == [("w-1", 11)]
    store = _Store({"w-1": {"session_id": "w-1", "state": "running", "detail": {"pid": 10, "display": ":99"}}})
    tools._session_accept(store, tools.SessionOut(**out), "tester")
    assert store.docs["w-1"]["detail"] == {"pid": 11, "display": ":99"}


class _Store:
    def __init__(self, sessions):
        import threading
        self.docs, self.lock, self.audits = dict(sessions), threading.RLock(), []

    def get(self, kind, key):
        return self.docs.get(key)

    def put(self, kind, key, doc):
        self.docs[key] = doc

    def audit(self, *a):
        self.audits.append(a)


def test_apply_live_bookkeeping_moves_the_session_onto_the_build():
    store = _Store({"w-1": {"session_id": "w-1", "state": "running", "mod": "a", "launch_mod": "a~k", "staged_mod": "a~k",
                            "collection_mod": "a", "live_mod": "x", "detail": {"pid": 501, "display": ":99"}}})
    SM._accept(store, SM.SwitchModsOut(result={"op": "apply_live", "session_id": "w-1", "same_session": True,
                                               "build": "b", "launch_mod": "b",
                                               "session_detail": {"pid": 502, "overlay": {"enabled": "b"}}}), "tester")
    doc = store.docs["w-1"]
    assert doc["mod"] == "b" and not {"launch_mod", "staged_mod", "collection_mod", "live_mod"} & set(doc)
    assert doc["detail"] == {"pid": 502, "display": ":99", "overlay": {"enabled": "b"}} and store.audits
    SM._accept(store, SM.SwitchModsOut(result={"op": "status"}), "tester")              # anything else: untouched
    assert store.docs["w-1"]["mod"] == "b"


# --- the control plane: a swap on a Switch session -------------------------------------------------------------------------

def _enclosed(fn, name):
    return dict(zip(fn.__code__.co_freevars, fn.__closure__))[name]


@pytest.fixture
def swap(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    app = server.create_app(c)
    store = app.state.store
    store.upsert_catalog([{"game_id": GID, "title": "Resident Evil 5", "platform": "switch", "source_paths": [],
                           "format": "nsp"}])
    store.put("worker", "w", {"id": "w", "name": "lilspark", "os": "linux", "last_seen": time.time()})
    store.put("session", "w-live", {"session_id": "w-live", "game_id": GID, "state": "running", "adapter": "eden",
                                    "mod": "a", "started": 1})
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/sessions/{sid}/swap")
    session_swap = _enclosed(_enclosed(route.endpoint, "swap_job").cell_contents, "session_swap").cell_contents
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    calls = []

    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp), kwargs.get("worker")))
        if tool == "switch_mods":
            return {"result": {"op": "apply_live", "launch_mod": inp["build"], "notes": ["Eden has no save states."]}}
        if tool == "prepare_mod":
            return {"ready": True, "mod": inp["mod"]}
        if tool == "launch_game":
            store.put("session", "w-new", {"session_id": "w-new", "game_id": GID, "state": "running",
                                           "mod": inp.get("mod", ""), "adapter": "yuzu"})
            return {"session_id": "w-new"}
        if tool == "session_op" and inp["op"] == "stop_game":
            return {"ended": True}
        pytest.fail("unexpected tool " + tool)
    _enclosed(session_swap, "_run_job").cell_contents = run
    return store, session_swap, calls, c


def test_a_swap_on_an_eden_session_restarts_the_title_in_the_same_session(swap):
    store, session_swap, calls, c = swap
    overlay(c, "b")
    out = session_swap("w-live", "b", "", "tester")
    assert out["session_id"] == "w-live" and out["in_place"] and out["launch_mod"] == "b" and not out["state_loaded"]
    assert calls == [("switch_mods", {"op": "apply_live", "session_id": "w-live", "game_id": GID, "build": "b"}, "w")]
    assert store.get("session", "w-live")["state"] == "running"
    calls.clear()
    assert session_swap("w-live", "", "", "tester")["in_place"]                          # back to the original game
    assert calls[0][1]["build"] == ""


def test_an_older_full_copy_build_on_an_eden_session_is_relaunched_not_restarted_in_place(swap):
    store, session_swap, calls, c = swap
    _full_copy(c, "re5_full")
    out = session_swap("w-live", "re5_full", "", "tester")
    assert [t for t, _, _ in calls][:2] == ["prepare_mod", "launch_game"] and out["session_id"] == "w-new"
    assert "keep_session" not in next(i for t, i, _ in calls if t == "launch_game")


def test_a_swap_on_a_yuzu_session_relaunches_without_a_moment_and_closes_the_old_copy_first(swap):
    store, session_swap, calls, c = swap
    store.put("worker", "w", store.get("worker", "w") | {"os": "windows", "name": "i9-NUC"})
    store.put("session", "w-live", store.get("session", "w-live") | {"adapter": "yuzu"})
    out = session_swap("w-live", "b", "", "tester", keep_state=True, keep_old=True)
    tools_called = [t for t, _, _ in calls]
    assert "state_transfer" not in tools_called and tools_called[:2] == ["prepare_mod", "launch_game"]
    launch = next(i for t, i, _ in calls if t == "launch_game")
    assert "keep_session" not in launch and launch["mod"] == "b"                          # never beside (one Yuzu)
    assert out["session_id"] == "w-new" and any("no save states" in n for n in out["notes"])
    assert {"eden", "yuzu"} <= server.RELAUNCH_BESIDE_UNSAFE


# --- the disk audit ----------------------------------------------------------------------------------------------------

def _full_copy(c, name, marker_extra=None, staged_of=None) -> Path:
    folder = c.cache / "mods" / GID / name
    nsp(folder / "Resident Evil 5.nsp")
    (folder / "Resident Evil 5.nsp").write_bytes((folder / "Resident Evil 5.nsp").read_bytes() + b"\0" * 4096)
    if staged_of:
        (folder / filemods.STAGED_MARK).write_text(staged_of)
    (folder / SM.MARKER).write_text(json.dumps({"name": name, "game_id": GID, "image": "Resident Evil 5.nsp",
                                                "files": [], "built": 1} | (marker_extra or {})))
    return folder


def test_the_audit_lists_full_copies_converts_them_on_request_and_deletes_only_on_purge(tmp_path):
    c = cfg(tmp_path)
    full = _full_copy(c, "re5_full")                                              # made by build_image, no changes
    patched = _full_copy(c, "re5_patched", {"files": ["@image"], "file_changes": [
        {"path": "Resident Evil 5.nsp", "change": "patched", "patches": [{"offset": 16, "length": 2}]}]})
    staged = _full_copy(c, "re5_full~abc", staged_of="re5_full")                  # a staged copy of it
    tree = c.cache / "mods" / GID / "re5_tree"                                    # an extracted RomFS tree
    (tree / "romfs/arc/pl").mkdir(parents=True)
    (tree / "romfs/arc/pl/pl00.arc").write_bytes(b"changed")
    (tree / "romfs/arc/pl/pl01.arc").write_bytes(b"as shipped")
    (tree / SM.MARKER).write_text(json.dumps({"name": "re5_tree", "game_id": GID, "serial": RE5,
                                              "files": ["romfs/arc/pl/pl00.arc"]}))
    overlay(c, "re5_overlay")
    rep = SM.audit(c, switch_ids=[GID])
    by = {i["id"]: i for i in rep["items"]}
    ids = {n: f"mods/{GID}/{n}" for n in ("re5_full", "re5_patched", "re5_full~abc", "re5_tree")}
    assert by[ids["re5_full"]]["kind"] == "container_copy" and by[ids["re5_full"]]["convertible"] == "empty_overlay"
    assert by[ids["re5_full"]]["bytes"] > 4096 and by[ids["re5_full"]]["title_id"] == RE5
    assert by[ids["re5_patched"]]["convertible"] is False and "byte patches" in by[ids["re5_patched"]]["reason"]
    assert by[ids["re5_full~abc"]]["kind"] == "staged_copy" and by[ids["re5_full~abc"]]["convertible"] == "quarantine"
    assert by[ids["re5_tree"]]["convertible"] == "overlay"
    assert [k["path"] for k in by[ids["re5_tree"]]["keep"]] == ["romfs/arc/pl/pl00.arc"]
    assert [o["build"] for o in rep["overlays"]] == ["re5_overlay"] and rep["totals"]["convertible"] == 3
    before = sorted(p.as_posix() for p in (c.cache / "mods").rglob("*"))
    dry = SM.convert(c, switch_ids=[GID])
    assert dry["dry_run"] and len(dry["converted"]) == 3 and dry["skipped"][0]["id"] == ids["re5_patched"]
    assert sorted(p.as_posix() for p in (c.cache / "mods").rglob("*")) == before   # a dry run changes nothing
    done = SM.convert(c, dry_run=False, switch_ids=[GID])
    assert len(done["converted"]) == 3 and "purge" in done["next"]
    assert SM.is_overlay(SM.read_meta(full)) and not list(full.glob("*.nsp"))     # same name, now an overlay
    assert SM.read_meta(full)["converted_from"]["kind"] == "container_copy"
    assert (tree / "romfs/arc/pl/pl00.arc").read_bytes() == b"changed" and not (tree / "romfs/arc/pl/pl01.arc").exists()
    assert not staged.exists() and (patched / "Resident Evil 5.nsp").is_file()     # not convertible: untouched
    moved = sorted(p for p in (c.cache / "mods" / GID).iterdir() if p.name.startswith(SM.QUARANTINE))
    assert len(moved) == 3 and all((m / (SM.MARKER + ".full-copy")).is_file() for m in moved)
    assert sum(1 for m in moved if (m / "Resident Evil 5.nsp").is_file()) == 2      # nothing deleted yet
    assert not any(r["name"].startswith(SM.QUARANTINE) for r in built_mods.scan(c.cache / "mods"))
    listed = SM.purge(c)
    assert not listed["confirm"] and len(listed["would_delete"]) == 3 and all(m.exists() for m in moved)
    gone = SM.purge(c, confirm=True)
    assert len(gone["deleted"]) == 3 and not any(m.exists() for m in moved) and not gone["errors"]
    assert SM.is_overlay(SM.read_meta(full)) and SM.is_overlay(SM.read_meta(tree))
    forced = SM.convert(c, items=[ids["re5_patched"]], dry_run=False, force_empty=True)
    assert forced["converted"][0]["action"] == "empty_overlay" and SM.is_overlay(SM.read_meta(patched))


def test_a_3ds_build_with_a_romfs_folder_is_not_a_switch_copy(tmp_path):
    c = cfg(tmp_path)
    citra = c.cache / "mods" / "3ds0000000000001" / "merc3d_skin"                    # Citra layers romfs/ too
    (citra / "romfs" / "arc").mkdir(parents=True)
    (citra / "romfs" / "arc" / "pl.arc").write_bytes(b"x")
    (citra / SM.MARKER).write_text(json.dumps({"name": "merc3d_skin", "title_id": "0004000000046700"}))
    assert SM.audit(c, switch_ids={GID: RE5})["items"] == []
    tree = c.cache / "mods" / GID / "re5_tree"                                    # a Switch game's tree: its catalog
    (tree / "romfs").mkdir(parents=True)                                          # serial gives the title id
    (tree / "romfs" / "a.arc").write_bytes(b"x")
    (tree / SM.MARKER).write_text(json.dumps({"name": "re5_tree", "files": ["romfs/a.arc"]}))
    rows = SM.audit(c, switch_ids={GID: RE5})["items"]
    assert [(r["kind"], r["title_id"], r["convertible"]) for r in rows] == [("romfs_tree", RE5, "overlay")]


def test_the_audit_reports_cache_and_export_copies_without_converting_them(tmp_path):
    c = cfg(tmp_path)
    nsp(c.cache / GID / "Resident Evil 5.nsp")                                    # an old launch-cache copy
    nsp(c.data_dir / "exports" / "Resident Evil 5 - mine" / "Resident Evil 5.nsp")
    rep = SM.audit(c, switch_ids=[GID])
    kinds = {i["kind"]: i for i in rep["items"]}
    assert set(kinds) == {"cache_copy", "export"} and not kinds["cache_copy"]["convertible"]
    assert "exports folder" in kinds["export"]["reason"] and rep["totals"]["convertible"] == 0


# --- character replacement on a Switch title --------------------------------------------------------------------------------

def test_a_switch_writer_edits_the_active_build_in_place_and_the_session_restarts(tmp_path):
    c = cfg(tmp_path)
    folder = overlay(c, "re5_chris")
    calls = []

    def api(ctx, method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/api/sessions":
            return [{"session_id": "w-1", "game_id": GID, "state": "running", "mod": "re5_chris", "adapter": "eden"}]
        if path.endswith("/swap"):
            return {"id": "swap-job"}
        raise AssertionError(path)
    SM.register_writer(RE5, lambda ctx, game, inp, meta: {
        "changes": {"arc/pl/pl00.arc": {"bytes": meta["slug"].encode()}}, "kind": "character",
        "slots": [{"slot": "player", "donor": meta["slug"]}]})
    try:
        ctx = SimpleNamespace(config=c, job_id="j9", server="http://plane", headers={})
        game = {"game_id": GID, "title": "Resident Evil 5", "platform": "switch", "serial": RE5}
        out = SM.character_use(ctx, api, {"slug": "wesker", "name": "Wesker"}, game,
                               SimpleNamespace(session_id="w-1", mod_name="", launch=False))
    finally:
        SM.WRITERS.pop(RE5, None)
    assert out["status"] == "restarting" and out["mod"] == "re5_chris" and out["swap_job"] == "swap-job"
    assert (folder / "romfs/arc/pl/pl00.arc").read_bytes() == b"wesker" and SM.read_meta(folder)["kind"] == "character"
    assert ("POST", "/api/sessions/w-1/swap", {"mod": "re5_chris", "keep_state": True}) in calls
    assert [p.name for p in (c.cache / "mods" / GID).iterdir()] == ["re5_chris"]


def test_without_a_switch_writer_the_repair_request_names_the_overlay_route(tmp_path, monkeypatch):
    from gbox import char_coverage
    c = cfg(tmp_path)
    monkeypatch.setattr(char_coverage, "no_writer", lambda ctx, api, meta, game, need, inp: {
        "status": "missing", "missing": need, "request": {"number": 7}})
    game = {"game_id": GID, "title": "Resident Evil 5", "platform": "switch", "serial": RE5}
    out = SM.character_use(SimpleNamespace(config=c, job_id="j", server="", headers={}), lambda *a, **k: [],
                           {"slug": "wesker", "name": "Wesker"}, game,
                           SimpleNamespace(session_id="", mod_name="", launch=False))
    assert out["status"] == "missing" and out["request"] == {"number": 7}
    assert out["switch_overlay"]["layeredfs"] and out["switch_overlay"]["title_id"] == RE5
    assert "LayeredFS" in out["missing"]["have"] and not (c.cache / "mods").exists()
