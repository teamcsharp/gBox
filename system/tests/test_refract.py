"""Meta Quest through Refract (gbox/refract.py): the ownership gate, the quest library scan, the private package copy,
the issue #38 loader fix (gbox/vendor/refract, run as a separate process like the installer runs it) and the input map."""
import hashlib
import json
import struct
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from gbox import adapters, launch_failures, refract, systems
from gbox.config import Config, QuestConfig, QuestOwnership
from gbox.registry import ToolUnavailable

PKG = "com.Armature.VR4"
VENDOR = Path(refract.__file__).resolve().parent / "vendor" / "refract"


def quest_config(tmp_path, **quest):
    return Config(data_dir=tmp_path / "data", quest=QuestConfig(root={"windows": str(tmp_path / "refract")},
                                                                workers=["QUESTPC"], **quest))


def declared(**over):
    return QuestOwnership(**({"title": "Resident Evil 4 VR", "declared_by": "mx1001", "declared_at": "2026-10-27",
                              "statement": "I own the game."} | over))


def library_json(path: Path, games: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"games": games, "jobs": [], "settings": {}}), encoding="utf-8")
    return path


def vr4_zip(path: Path, apk=b"apk-bytes", main=b"main-obb" * 64, patch=b"patch-obb" * 32, second_apk=None) -> Path:
    """The layout of the operator's com.Armature.VR4 v203 zip (the APK stored twice, byte-identical)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{PKG}/", b"")
        z.writestr(f"{PKG}/main.203.{PKG}.obb", main)
        z.writestr(f"{PKG}/patch.203.{PKG}.obb", patch)
        z.writestr(f"{PKG}/VR4-Android-Shipping-arm64.apk", second_apk if second_apk is not None else apk)
        z.writestr(f"{PKG}.apk", apk)
    return path


# ------------------------------------------------------------------------------------------------ ownership

def test_without_declaration_or_meta_record_the_game_is_refused(tmp_path):
    cfg = quest_config(tmp_path)
    assert refract.ownership(cfg, PKG, library=tmp_path / "none.json") == {"owned": False}
    with pytest.raises(refract.OwnershipRequired) as e:
        refract.require_owned(cfg, PKG, "Resident Evil 4 VR", "QUESTPC", library=tmp_path / "none.json")
    text = str(e.value)
    assert f'[quest.owned."{PKG}"]' in text and "declared_by" in text and "sign into Meta in Refract on QUESTPC" in text
    assert refract.NOT_A_FAILURE_RX.search(text)


@pytest.mark.parametrize("missing", ["declared_by", "declared_at"])
def test_a_declaration_needs_who_and_when(tmp_path, missing):
    cfg = quest_config(tmp_path, owned={PKG: declared(**{missing: "  "})})
    assert refract.declaration(cfg, PKG) is None
    assert not refract.ownership(cfg, PKG, library=tmp_path / "none.json")["owned"]


def test_the_operator_declaration_is_used_for_that_package_only(tmp_path):
    cfg = quest_config(tmp_path, owned={PKG: declared()})
    found = refract.ownership(cfg, PKG, library=tmp_path / "none.json")
    assert found == {"owned": True, "via": "declaration", "title": "Resident Evil 4 VR", "declared_by": "mx1001",
                     "declared_at": "2026-10-27", "statement": "I own the game."}
    assert not refract.ownership(cfg, "com.other.game", library=tmp_path / "none.json")["owned"]


def test_refracts_meta_sign_in_record_counts_only_when_owned_and_from_meta(tmp_path):
    cfg = quest_config(tmp_path)
    lib = tmp_path / "appdata" / "Refract" / "library.json"
    library_json(lib, [{"id": "2637179839719680", "name": "Resident Evil 4", "package": PKG, "owned": True,
                        "source": "meta"}])
    found = refract.ownership(cfg, PKG, library=lib)
    assert found["owned"] and found["via"] == "meta" and found["meta_id"] == "2637179839719680"
    for row in ({"owned": False, "source": "meta"}, {"owned": True, "source": "import"}, {"owned": "true", "source": "meta"}):
        library_json(lib, [{"package": PKG, **row}])
        assert not refract.ownership(cfg, PKG, library=lib)["owned"], row
    library_json(lib, [{"package": "com.other.game", "owned": True, "source": "meta"}])
    assert not refract.ownership(cfg, PKG, library=lib)["owned"]
    lib.write_text("{not json", encoding="utf-8")
    assert not refract.ownership(cfg, PKG, library=lib)["owned"]
    assert refract.meta_library_path({"APPDATA": "X:/AppData/Roaming"}) == Path("X:/AppData/Roaming/Refract/library.json")


def test_prepare_refuses_before_any_setup_or_download(tmp_path, monkeypatch):
    monkeypatch.setattr(refract, "HOST_OS", "windows")
    monkeypatch.setattr(refract.platform, "node", lambda: "QUESTPC")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    from gbox import storage_policy
    monkeypatch.setattr(storage_policy, "system_drive", lambda *a, **k: "Q:")
    monkeypatch.setattr(refract, "setup", lambda *a, **k: pytest.fail("setup ran for an unconfirmed game"))
    ad = refract.RefractAdapter(quest_config(tmp_path), {"title": "Resident Evil 4 VR", "launch": {"package": PKG}})
    with pytest.raises(refract.OwnershipRequired):
        ad.prepare(source=tmp_path / "game.zip")
    assert ad.prepared is None


def test_the_owner_flag_goes_only_to_the_confirmed_package(tmp_path):
    lay = refract.Layout(tmp_path / "refract")
    package = {"package": PKG, "obb_dir": str(tmp_path / "obb")}
    args = refract.native_args(lay, tmp_path / "apps" / PKG, package, {"owned": True, "via": "declaration"})
    assert args.count("--prop") == 1 and f"debug.refract.platform.owned.{PKG}=1" in args
    assert args[args.index("--data") + 1] == str(lay.data)
    assert f"/sdcard/Android/obb/{PKG}={tmp_path / 'obb'}" in args
    with pytest.raises(refract.OwnershipRequired):
        refract.native_args(lay, tmp_path / "apps" / PKG, package, {"owned": False})
    pose = refract.pose_args(QuestConfig())
    assert pose[pose.index("--host") + 1] == "127.0.0.1" and Path(pose[4]).parent == VENDOR


# ------------------------------------------------------------------------------------------------ PCs and routing

def test_quest_games_route_to_refract_on_windows_only(tmp_path, monkeypatch):
    game = {"platform": "quest", "launch": {"kind": "refract", "package": PKG}}
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    assert isinstance(adapters.for_game(game, quest_config(tmp_path)), refract.RefractAdapter)
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    with pytest.raises(ToolUnavailable, match="Windows x64 worker"):
        adapters.for_game(game, quest_config(tmp_path))


def test_only_the_listed_worker_off_the_system_drive_sets_quest_games_up(tmp_path, monkeypatch):
    from gbox import storage_policy
    monkeypatch.setattr(refract, "HOST_OS", "windows")
    monkeypatch.setattr(storage_policy, "system_drive", lambda *a, **k: "Q:")
    cfg = quest_config(tmp_path)
    assert refract.check_node(cfg, "questpc") == tmp_path / "refract"
    with pytest.raises(ToolUnavailable, match="set up only on QUESTPC"):
        refract.check_node(cfg, "JAYBUILTFINALE")
    monkeypatch.setattr(storage_policy, "system_drive", lambda *a, **k: Path(tmp_path).drive.upper())
    with pytest.raises(storage_policy.SystemDriveRefused, match="off this PC's system drive"):
        refract.check_node(cfg, "QUESTPC")
    monkeypatch.setattr(refract, "HOST_OS", "linux")
    with pytest.raises(ToolUnavailable, match="Windows x64"):
        refract.check_node(cfg, "QUESTPC")


def test_platform_names_and_failure_reports():
    assert systems.classify("Meta Quest")[:2] == ("quest", None)
    assert launch_failures.PLATFORM_ADAPTER["quest"] == "refract"
    assert launch_failures.adapter_for({"platform": "quest"}) == "refract"
    assert refract.NOT_A_FAILURE_RX.search("Refract setup for Resident Evil 4 VR is still running on i9-NUC (x, 40%)")


def test_repo_config_defines_the_quest_library_and_worker():
    from gbox.config import load
    cfg = load(Path(refract.__file__).resolve().parents[1] / "gbox.toml")
    lib = cfg.library("quest")
    assert lib.kind == "quest" and lib.paths["windows"].endswith("/Emulation/Occulus")
    assert cfg.quest.workers == ["i9-NUC"] and cfg.preferred_launch_workers["quest"] == "i9-NUC"
    assert "JAYBUILTFINALE" not in cfg.quest.workers


# ------------------------------------------------------------------------------------------------ the quest library

def test_scan_lists_one_quest_entry_per_package_zip_or_folder(tmp_path):
    root = tmp_path / "Occulus"
    root.mkdir()
    vr4_zip(root / f"{PKG} v203 {PKG}.zip")
    folder = root / "com.example.Game"
    (folder / "com.example.Game").mkdir(parents=True)
    (folder / "game.apk").write_bytes(b"apk")
    (folder / "com.example.Game" / "main.7.com.example.Game.obb").write_bytes(b"obb")
    with zipfile.ZipFile(root / "notes.zip", "w") as z:
        z.writestr("readme.txt", "no package here")
    vr4_zip(root / "broken.zip", second_apk=b"a different apk")
    entries, problems = refract.scan_refract(root, "quest")
    by = {e.rel_path: e for e in entries}
    assert set(by) == {f"{PKG} v203 {PKG}.zip", "com.example.Game"}
    vr4 = by[f"{PKG} v203 {PKG}.zip"]
    from gbox.catalog import _gid
    assert vr4.game_id == _gid("quest", vr4.rel_path) and vr4.platform == "quest" and vr4.title == "Resident Evil 4 VR"
    assert vr4.library == "quest" and vr4.system == "Meta Quest" and vr4.format == "quest_zip"
    assert vr4.launch == {"kind": "refract", "package": PKG, "version_code": 203, "container": "zip", "apk": f"{PKG}.apk",
                          "obb": [f"{PKG}/main.203.{PKG}.obb", f"{PKG}/patch.203.{PKG}.obb"]}
    assert by["com.example.Game"].launch["package"] == "com.example.Game"
    assert len(problems) == 1 and "broken.zip" in problems[0] and "several different APKs" in problems[0]


def test_one_apk_copy_is_chosen_when_meta_stored_it_twice():
    members = [(f"{PKG}/VR4-Android-Shipping-arm64.apk", 10, 7), (f"{PKG}/main.203.{PKG}.obb", 5, 1)]
    assert refract.select_members(members)["apk"] == f"{PKG}/VR4-Android-Shipping-arm64.apk"
    with pytest.raises(ValueError, match="several versions"):
        refract.select_members(members + [(f"{PKG}/patch.204.{PKG}.obb", 5, 2)])
    assert refract.select_members([("x/readme.txt", 1, 1)]) is None


# ------------------------------------------------------------------------------------------------ the package copy

def test_private_copy_of_apk_and_obbs_leaves_the_library_zip_untouched(tmp_path):
    (tmp_path / "share").mkdir()
    source = vr4_zip(tmp_path / "share" / "vr4.zip")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    lay = refract.Layout(tmp_path / "refract")
    launch = {"package": PKG}
    seen = []
    info = refract.stage_package(lay, launch, source, lambda pct, msg: seen.append(pct))
    dest = lay.packages / PKG / "203"
    assert Path(info["apk"]) == dest / f"{PKG}.apk" and (dest / f"{PKG}.apk").read_bytes() == b"apk-bytes"
    assert (dest / "obb" / f"main.203.{PKG}.obb").read_bytes() == b"main-obb" * 64
    assert info["obb_dir"] == str(dest / "obb") and seen and max(seen) <= 100
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    receipt = json.loads((dest / refract.PACKAGE_RECEIPT).read_text())
    assert receipt["verified"] == {f"{PKG}.apk": "crc32", f"{PKG}/main.203.{PKG}.obb": "crc32",
                                   f"{PKG}/patch.203.{PKG}.obb": "crc32"}
    again = refract.stage_package(lay, launch, source, lambda *a: pytest.fail("copied again"))
    assert again == info


def test_a_damaged_member_is_never_kept(tmp_path):
    source = tmp_path / "vr4.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as z:
        z.writestr(f"{PKG}.apk", b"A" * 4096)
        z.writestr(f"main.203.{PKG}.obb", b"B" * 4096)
    data = bytearray(source.read_bytes())
    data[data.index(b"B" * 64) + 100] ^= 0xFF                 # flip one byte of the stored OBB, keep its CRC
    source.write_bytes(bytes(data))
    lay = refract.Layout(tmp_path / "refract")
    with pytest.raises(zipfile.BadZipFile):
        refract.stage_package(lay, {"package": PKG}, source)
    assert not (lay.packages / PKG / "203" / "obb" / f"main.203.{PKG}.obb").exists()


def test_archive_members_cannot_escape_the_install_folder(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Refract-1.0.2-win64/ok.txt", "ok")
        z.writestr("../escape.txt", "no")
    with pytest.raises(ToolUnavailable, match="unsafe archive member"):
        refract.extract_single_folder(archive, tmp_path / "out", "Refract-1.0.2-win64", "test")
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "out").exists()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("one/a.txt", "a")
        z.writestr("two/b.txt", "b")
    with pytest.raises(ToolUnavailable, match="unexpected archive layout"):
        refract.extract_single_folder(archive, tmp_path / "out", None, "test")


def test_sysroot_needs_what_issue_39_lost(tmp_path):
    root = tmp_path / "sysroot"
    for d in ("system/lib64", "apex/com.android.runtime", "apex/com.android.art", "system/bin"):
        (root / d).mkdir(parents=True)
    for i in range(60):
        (root / "system" / "lib64" / f"lib{i}.so").write_bytes(b"\x7fELF")
    (root / "refract_symlinks.txt").write_text("")
    assert not refract.sysroot_ok(root)                        # no linker64: games die "cannot load interpreter"
    (root / "system" / "bin" / "linker64").write_bytes(b"\x7fELF")
    assert refract.sysroot_ok(root)


# ------------------------------------------------------------------------------------------------ background setup

def test_setup_outliving_the_job_keeps_running_and_the_next_launch_joins_it(tmp_path):
    gate = threading.Event()
    calls = []

    def slow(update):
        calls.append(1)
        update(40, "Copying main.203.com.Armature.VR4.obb")
        gate.wait(10)
        return {"ready": True}
    lines = []
    with pytest.raises(refract.SetupStillRunning, match="still running on QUESTPC"):
        refract.run_setup("k1", slow, lambda pct, msg: lines.append(msg), time.monotonic() + 46, "RE4 VR", "QUESTPC")
    gate.set()
    assert refract.run_setup("k1", slow, lambda *a: None, None, "RE4 VR", "QUESTPC") == {"ready": True}
    assert calls == [1]                                         # joined, not started twice
    assert "k1" not in refract._SETUPS

    def broken(update):
        raise ToolUnavailable("download failed")
    with pytest.raises(ToolUnavailable, match="download failed"):
        refract.run_setup("k2", broken, lambda *a: None, None, "RE4 VR", "QUESTPC")
    assert "k2" not in refract._SETUPS                          # a failed setup is retried by the next launch


# ------------------------------------------------------------------------------------------------ the session

class FakeProc:
    """Stands in for the three Refract processes: no real program starts, nothing real is killed."""
    def __init__(self, args, **kw):
        self.args, self.kw, self.code, self._handle = args, kw, None, 0
        self.pid = 40000 + len(FakeProc.started)
        FakeProc.started.append(self)
        if FakeProc.native_exit is not None and "refract_native.exe" in str(args[0]):
            self.code = FakeProc.native_exit

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.code


@pytest.fixture
def fake_session(tmp_path, monkeypatch):
    FakeProc.started, FakeProc.native_exit = [], None
    monkeypatch.setattr(refract.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(adapters, "keep_offscreen", lambda *a, **k: None)
    monkeypatch.setattr(adapters, "_kill_tree", lambda proc: setattr(proc, "code", proc.code if proc.code is not None else 1) if proc else None)
    from gbox import graphics
    monkeypatch.setattr(graphics, "prefer_gpu", lambda exe: True)      # no registry writes from tests
    monkeypatch.setattr(refract.RefractAdapter, "_listening", staticmethod(lambda proc, port: True))
    monkeypatch.setattr(refract.RefractAdapter, "_ports_busy", lambda self: [])
    monkeypatch.setattr(refract.RefractAdapter, "viewer_window", lambda self: None)
    lay = refract.Layout(tmp_path / "refract")
    ad = refract.RefractAdapter(quest_config(tmp_path), {"title": "Resident Evil 4 VR", "launch": {"package": PKG}})
    ad.boot_timeout_s = 5
    ad.prepared = {"layout": lay, "title": "Resident Evil 4 VR",
                   "package": {"package": PKG, "version_code": 203, "obb_dir": str(lay.packages / PKG / "203" / "obb")},
                   "install": {"app": str(lay.apps / PKG), "libcxx_rebind": {"libovrplatformloader.so": {"rebound": 21}}},
                   "ownership": {"owned": True, "via": "declaration", "declared_by": "mx1001"}}
    return ad


def test_a_session_starts_pose_server_viewer_and_game_and_ends_them_together(fake_session, monkeypatch):
    ad = fake_session
    monkeypatch.setattr(refract.RefractAdapter, "viewer_stats",
                        lambda self: {"game_fps": 72, "shown_fps": 72, "transport": "GPU shared"})
    detail = ad.launch_game()
    pose, viewer, native = FakeProc.started
    assert "pose_input_server.py" in pose.args[4] and pose.args[pose.args.index("--host") + 1] == "127.0.0.1"
    assert viewer.args[0].endswith("refract_viewer.exe") and viewer.args[viewer.args.index("--title") + 1] == "Resident Evil 4 VR"
    assert f"debug.refract.platform.owned.{PKG}=1" in native.args and "--data" in native.args
    assert native.kw["env"]["REFRACT_CPU"] == "digitalis" and native.kw["env"]["REFRACT_JAVA_HOME"].endswith("jdk")
    assert detail["pid"] == viewer.pid and detail["local_window"] and detail["fps"] == 72
    assert detail["ownership"]["declared_by"] == "mx1001" and detail["credit"] == refract.CREDIT
    assert ad.proc.pid == viewer.pid and ad.proc.poll() is None and ad.query_runtime()["running"]
    out = ad.stop_game()
    assert out["stopped"] and all(p.code is not None for p in FakeProc.started) and ad.proc.poll() is not None


def test_a_game_that_dies_while_booting_reports_its_log_and_leaves_nothing_running(fake_session):
    ad = fake_session
    FakeProc.native_exit = 139
    ad.prepared["layout"].logs.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Refract Native exited with code 139"):
        ad.launch_game()
    assert all(p.code is not None for p in FakeProc.started)


def test_a_setup_that_ate_the_job_time_never_boots_the_game_past_the_job(fake_session):
    ad = fake_session
    ad.deadline = time.monotonic() + 30                        # less than boot time + margin left
    with pytest.raises(refract.SetupStillRunning, match="finished on .+ Start the game again") as e:
        ad.launch_game()
    assert FakeProc.started == [] and refract.NOT_A_FAILURE_RX.search(str(e.value))


def test_a_failed_setup_leaves_its_logs_for_the_launch_failure_report(tmp_path):
    cfg = quest_config(tmp_path)
    logs = refract.Layout(refract.root(cfg)).logs
    logs.mkdir(parents=True)
    (logs / "setup-ext4.log").write_text("$ pip install ext4==1.2.4\nexit 1\nerror: crcmod build failed\n")
    tail = refract.RefractAdapter(cfg).log_tail()
    assert "== setup-ext4.log" in tail and "crcmod build failed" in tail


def test_no_frames_within_the_boot_time_is_a_failed_launch(fake_session, monkeypatch):
    ad = fake_session
    ad.boot_timeout_s = 1
    monkeypatch.setattr(refract.RefractAdapter, "viewer_stats", lambda self: {"title": "x", "transport": "waiting for game"})
    with pytest.raises(RuntimeError, match="sent no frames"):
        ad.launch_game()
    assert all(p.code is not None for p in FakeProc.started)


# ------------------------------------------------------------------------------------------------ input and stats

def test_pad_names_become_refract_udp_commands():
    assert refract.input_commands({"a", "r2", "lup", "lright"}) == [
        "hold right a 0.15", "hold right trigger 0.15", "stick left 1 1 0.15"]
    assert refract.input_commands({"up", "select"}) == []         # d-pad / select: no Quest equivalent
    assert refract.input_commands({"lup", "ldown"}) == []         # opposite directions cancel


def test_viewer_title_stats():
    title = ("Resident Evil 4 VR \u2013 Refract Viewer  |  game 72 fps, shown 71 fps (GPU shared)  |  right-drag look, "
             "click trigger, wheel hand distance  |  F1 stats, F2 screenshot")
    assert refract.parse_viewer_title(title) | {"title": ""} == {"title": "", "game_fps": 72, "shown_fps": 71,
                                                                 "transport": "GPU shared"}
    assert "game_fps" not in refract.parse_viewer_title("Resident Evil 4 VR \u2013 Refract Viewer")


# ------------------------------------------------------------------------------------------------ issue #38 fix

TEXT, PLT, GOTPLT = 0x1000, 0x800, 0x3000


def _stub(pc, got):
    delta = ((got & ~0xFFF) - (pc & ~0xFFF)) >> 12
    lo12 = got & 0xFFF
    return (0x90000010 | (delta & 3) << 29 | ((delta >> 2) & 0x7FFFF) << 5, 0xF9400211 | (lo12 // 8) << 10,
            0x91000210 | lo12 << 10, 0xD61F0220)


def elf(defined=("_ZNSt6__ndk112basic_stringIcEED2Ev", "_ZNKSt6__ndk16__treeIiE4findEv"), local=("_ZN3Foo3barEv",),
        imported=("puts",), new_delete=False, bad_first=False) -> bytes:
    """A minimal AArch64 shared library: .dynsym/.dynstr, .rela.plt JUMP_SLOTs, a standard .plt, .text, .dynamic."""
    names = [*defined, *local, *imported, *(["_Znwm"] if new_delete else [])]
    dynstr, offs = b"\0", {}
    for n in names:
        offs[n] = len(dynstr)
        dynstr += n.encode() + b"\0"
    syms, plt_syms = [bytes(24)], []
    for i, n in enumerate([*defined, *local]):
        syms.append(struct.pack("<IBBHQQ", offs[n], 0x12, 0, 5, TEXT + 0x10 * i, 4))   # GLOBAL FUNC in .text
        plt_syms.append(len(syms) - 1)
    for n in imported:
        syms.append(struct.pack("<IBBHQQ", offs[n], 0x12, 0, 0, 0, 0))
        plt_syms.append(len(syms) - 1)
    if new_delete:
        syms.append(struct.pack("<IBBHQQ", offs["_Znwm"], 0x12, 0, 0, 0, 0))
    rela, plt = b"", bytes(0x20)
    for slot, symidx in enumerate(plt_syms):
        got = GOTPLT + 0x18 + 8 * slot
        rela += struct.pack("<QQq", got, symidx << 32 | 1026, 0)
        words = _stub(PLT + 0x20 + 16 * slot, got)
        if bad_first and slot == 0:
            words = (0xD503245F,) + words[:3]                    # a BTI landing pad first: not the expected stub
        plt += struct.pack("<4I", *words)
    shstr = b"\0.dynsym\0.dynstr\0.rela.plt\0.plt\0.text\0.dynamic\0.got.plt\0.shstrtab\0"
    name = {n: shstr.index(n.encode() + b"\0") for n in
            (".dynsym", ".dynstr", ".rela.plt", ".plt", ".text", ".dynamic", ".got.plt", ".shstrtab")}
    body = {0x200: b"".join(syms), 0x400: dynstr, 0x600: rela, PLT: plt, TEXT: bytes(0x100),
            0x2000: struct.pack("<qQqQ", 3, GOTPLT, 0, 0), GOTPLT: bytes(0x18 + 8 * len(plt_syms)), 0x3800: shstr}
    sections = [bytes(64)]
    for sec, (off, typ, flags, link, ent) in {".dynsym": (0x200, 11, 2, 2, 24), ".dynstr": (0x400, 3, 2, 0, 0),
                                              ".rela.plt": (0x600, 4, 2, 1, 24), ".plt": (PLT, 1, 6, 0, 16),
                                              ".text": (TEXT, 1, 6, 0, 0), ".dynamic": (0x2000, 6, 3, 2, 16),
                                              ".got.plt": (GOTPLT, 1, 3, 0, 8), ".shstrtab": (0x3800, 3, 0, 0, 0)}.items():
        sections.append(struct.pack("<IIQQQQIIQQ", name[sec], typ, flags, off, off, len(body[off]), link, 0, 8, ent))
    header = struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + bytes(9), 3, 183, 1, 0, 0, 0x4000, 0, 64, 56,
                         0, 64, len(sections), len(sections) - 1)
    out = bytearray(0x4000)
    out[:64] = header
    for off, data in body.items():
        out[off:off + len(data)] = data
    return bytes(out) + b"".join(sections)


def rebind(path: Path, *extra) -> dict:
    run = subprocess.run([sys.executable, "-I", str(VENDOR / "private_libcxx.py"), *extra, str(path)],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)[0]


def test_private_libcxx_stubs_point_at_the_librarys_own_definitions(tmp_path):
    lib = tmp_path / "libovrplatformloader.so"
    lib.write_bytes(elf())
    dry = rebind(lib, "--dry-run")
    assert dry["eligible"] and dry["applied"] == 0 and lib.read_bytes() == elf()
    assert [p["symbol"] for p in dry["patches"]] == ["_ZNSt6__ndk112basic_stringIcEED2Ev", "_ZNKSt6__ndk16__treeIiE4findEv"]
    done = rebind(lib)
    assert done["applied"] == 2
    data = lib.read_bytes()
    for slot, target in ((0, TEXT), (1, TEXT + 0x10)):
        pc = PLT + 0x20 + 16 * slot
        assert struct.unpack_from("<I", data, pc)[0] == 0x14000000 | ((target - pc) >> 2 & 0x3FFFFFF)
    for slot in (2, 3):                                         # Foo::bar (not libc++) and an import stay as built
        pc = PLT + 0x20 + 16 * slot
        assert struct.unpack_from("<4I", data, pc) == _stub(pc, GOTPLT + 0x18 + 8 * slot)
    again = rebind(lib)
    assert again["applied"] == 0 and len(again["already"]) == 2  # idempotent


def test_libraries_that_use_operator_new_or_odd_stubs_are_left_alone(tmp_path):
    shared = tmp_path / "libc++_shared.so"
    shared.write_bytes(elf(new_delete=True))
    report = rebind(shared)
    assert not report["eligible"] and "operator new/delete" in report["reason"] and shared.read_bytes() == elf(new_delete=True)
    odd = tmp_path / "libodd.so"
    odd.write_bytes(elf(bad_first=True))
    report = rebind(odd)
    assert report["applied"] == 1 and report["skipped"][0]["reason"].startswith("PLT entry is not the expected")
    text = tmp_path / "libnotelf.so"
    text.write_text("INPUT(-lc)")
    assert rebind(text)["eligible"] is False


def test_installer_fork_needs_the_refract_release_folder(tmp_path):
    run = subprocess.run([sys.executable, "-I", str(VENDOR / "install_apk.py"), str(tmp_path / "game.apk"),
                          "--refract-root", str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert run.returncode != 0 and "--refract-root must name a Refract release folder" in run.stderr
    head = (VENDOR / "install_apk.py").read_text(encoding="utf-8")[:2500]
    assert "Based on Refract: https://github.com/MIXIDtheSilly/Refract" in head and "issues/38" in head
    assert (VENDOR / "LICENSE").read_text(encoding="utf-8").lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    assert "Section 7(b)" in (VENDOR / "NOTICE").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="the pose server reads XInput through ctypes.windll")
def test_pose_server_fork_listens_on_loopback_only():
    psutil = pytest.importorskip("psutil")
    proc = subprocess.Popen([refract.python(), "-I", "-u", str(VENDOR / "pose_input_server.py"), "--port", "0",
                             "--control-port", "0"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline, rows = time.monotonic() + 15, []
        while time.monotonic() < deadline and not rows:
            rows = [c for c in psutil.net_connections(kind="tcp") if c.pid == proc.pid and c.status == psutil.CONN_LISTEN]
            time.sleep(0.2)
        assert rows and all(c.laddr.ip == "127.0.0.1" for c in rows)
    finally:
        proc.kill()
        proc.wait(10)
