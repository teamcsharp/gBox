"""decomp_me / ida / n64recomp (#90) with fakes: no network, no IDA, no N64Recomp, no real ROM."""
import json
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import decomp_tools as dt
from gbox.config import Config
from gbox.registry import ToolUnavailable


def ctx(cfg, server=None):
    arts = {}
    return SimpleNamespace(config=cfg, job_id="job1", worker="w", server=server, headers={}, arts=arts,
                           progress=lambda *a: None, artifact=lambda name, data, mt="", **p: arts.__setitem__(name, data))


# --- decomp.me ----------------------------------------------------------------------------------

def test_decomp_me_defaults_to_dry_run_and_builds_the_real_api_requests(tmp_path):
    c = ctx(Config(data_dir=tmp_path))
    out = dt.decomp_me(dt.DecompMeIn(op="submit", platform="n64", compiler="ido7.1", compiler_flags="-O2 -mips2",
                                     diff_label="func_80001234", target_asm="glabel func_80001234\njr $ra\nnop\n"), c)
    req = out["request"]
    assert out["dry_run"] and not out["public"]
    assert req["method"] == "POST" and req["url"] == "https://decomp.me/api/scratch"
    assert req["json"]["diff_label"] == "func_80001234" and req["json"]["compiler"] == "ido7.1"
    assert dt.decomp_me_request(c.config, dt.DecompMeIn(op="fetch", slug="AbC12"))["url"].endswith("/scratch/AbC12")
    assert dt.decomp_me_request(c.config, dt.DecompMeIn(op="compilers"))["url"].endswith("/api/compiler")
    assert dt.decomp_me_request(c.config, dt.DecompMeIn(op="list", params={"platform": "n64"}))["params"] == \
        {"page_size": 20, "platform": "n64"}


@pytest.mark.parametrize("inp,msg", [
    (dict(op="submit", target_asm=""), "target_asm"),
    (dict(op="submit", target_asm="x"), "platform"),
    (dict(op="fetch", slug="../admin"), "slug"),
    (dict(op="nuke"), "op:"),
])
def test_decomp_me_validates_before_any_request(inp, msg):
    with pytest.raises(ValueError, match=msg):
        dt.decomp_me_request(Config(), dt.DecompMeIn(**inp))


def test_decomp_me_network_is_opt_in(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(dt, "_dm_send", lambda req: sent.append(req) or (201, {"slug": "Zx9", "claim_token": "t"}))
    inp = dt.DecompMeIn(op="submit", preset=42, target_asm="glabel f\n", dry_run=False)
    with pytest.raises(PermissionError, match="opt-in"):
        dt.decomp_me(inp, ctx(Config(data_dir=tmp_path)))
    assert not sent
    out = dt.decomp_me(inp, ctx(Config(data_dir=tmp_path, decomp_me_enabled=True)))
    assert out["public"] and out["data"]["url"] == "https://decomp.me/scratch/Zx9" and out["data"]["claim_token"] == "t"
    assert dt.decomp_me(dt.DecompMeIn(op="status"), ctx(Config()))["data"]["enabled"] is False


def test_decomp_me_names_the_cloudflare_challenge(monkeypatch):
    import httpx

    class R:
        status_code, headers, text, content = 403, {"content-type": "text/html; charset=UTF-8"}, "<title>Just a moment", b"x"
    monkeypatch.setattr(httpx, "request", lambda *a, **k: R())
    with pytest.raises(ToolUnavailable, match="Cloudflare"):
        dt._dm_send({"method": "GET", "url": "https://decomp.me/api/compiler"})

    class Empty:
        status_code, headers, text, content = 200, {}, "", b""
    monkeypatch.setattr(httpx, "request", lambda *a, **k: Empty())
    with pytest.raises(RuntimeError, match="instead of JSON"):
        dt._dm_send({"method": "GET", "url": "https://api.decomp.dev/compiler"})


# --- IDA ------------------------------------------------------------------------------------------

def test_ida_check_hook_explains_install_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "ida_search_roots", lambda cfg: [])
    for v in ("IDA_HOME", "IDADIR"):
        monkeypatch.delenv(v, raising=False)
    why = dt.ida_check(Config(data_dir=tmp_path))
    assert "not installed" in why and "ida_home" in why and "never installs" in why


def test_ida_found_from_ida_home(tmp_path, monkeypatch):
    home = tmp_path / "IDA Professional 9.1"
    home.mkdir()
    (home / dt.IDA_NAMES[1]).write_bytes(b"MZ")
    assert dt.find_idat(Config(ida_home=str(home))) == home / dt.IDA_NAMES[1]
    assert dt.ida_check(Config(ida_home=str(home))) is None


def test_ida_command_keeps_database_and_log_in_the_work_folder(tmp_path):
    cmd = dt.ida_command(Path("idat64"), tmp_path / "in.elf", tmp_path / "s.py", tmp_path / "db", tmp_path / "ida.log", "mipsb")
    assert cmd[:2] == ["idat64", "-A"] and f"-o{tmp_path / 'db'}" in cmd and "-pmipsb" in cmd and cmd[-1].endswith("in.elf")


def test_ida_analyze_copies_the_binary_and_returns_analyze_binary_shape(tmp_path, monkeypatch):
    home = tmp_path / "ida"
    home.mkdir()
    (home / dt.IDA_NAMES[0]).write_bytes(b"MZ")
    src = tmp_path / "game" / "SLUS_123.45"
    src.parent.mkdir()
    src.write_bytes(b"\x7fELF" + b"\0" * 60)
    seen = {}

    def fake_run(cmd, cwd, env, **kw):
        seen["cmd"], seen["cwd"] = cmd, cwd
        Path(env["GBOX_IDA_OUT"]).write_text(json.dumps({
            "program": {"name": "SLUS_123.45", "language": "mipsl:LE:32:ida", "image_base": "00100000", "sha256": ""},
            "functions": [{"name": "main", "entry": "00100008", "size": 64, "source": "IMPORTED"}],
            "strings": [{"addr": "00200000", "value": "hello"}]}))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(dt.subprocess, "run", fake_run)
    c = ctx(Config(data_dir=tmp_path / "data", ida_home=str(home)))
    out = dt.ida(dt.IdaIn(binary_path=str(src), processor="mipsl"), c)
    assert out["functions"] == 1 and out["strings"] == 1 and out["program"]["name"] == "SLUS_123.45"
    assert seen["cmd"][-1] != str(src) and Path(seen["cmd"][-1]).parent == Path(seen["cwd"])   # a copy, not the original
    assert sorted(p.name for p in src.parent.iterdir()) == ["SLUS_123.45"]                     # nothing written beside it
    assert dt._ida_validate(dt.IdaOut(**out), c.arts) == []
    with pytest.raises(ValueError, match="-o"):
        dt.ida(dt.IdaIn(binary_path=str(src), extra_args=["-oC:/elsewhere"]), c)


def test_ida_export_script_is_valid_python():
    compile(dt.IDA_EXPORT_PY, "gbox_ida_export.py", "exec")


# --- N64Recomp ------------------------------------------------------------------------------------

def fake_rom(entry=0x80000400, size=0x200000):
    rom = bytearray(size)
    rom[:4] = b"\x80\x37\x12\x40"
    struct.pack_into(">I", rom, 8, entry)
    return bytes(rom)


ANALYSIS = {"program": {"name": "boot.elf"}, "functions": [
    {"name": "entry", "entry": "80000400", "size": 0x50, "source": "IMPORTED"},
    {"name": "FUN_80000450", "entry": "ram:80000450", "size": 0x22, "source": "DEFAULT"},   # trimmed to 0x20
    {"name": "overlap", "entry": "80000460", "size": 0x10, "source": "DEFAULT"},             # inside the previous
    {"name": "odd", "entry": "80000502", "size": 0x10, "source": "DEFAULT"},                 # unaligned
    {"name": "far", "entry": "80400000", "size": 0x10, "source": "DEFAULT"},                 # outside the boot segment
    {"name": "entry", "entry": "80000600", "size": 0x8, "source": "DEFAULT"},                # duplicate name
]}


def test_boot_functions_are_aligned_sorted_unique_and_inside_the_segment():
    fns, notes = dt.boot_functions(ANALYSIS, 0x80000400)
    assert [(f["name"], hex(f["vram"]), f["size"]) for f in fns] == [
        ("entry", "0x80000400", 0x50), ("FUN_80000450", "0x80000450", 0x20), ("entry_2", "0x80000600", 8)]
    assert "2 functions skipped" in notes[0]
    toml = dt.syms_toml(fns, 0x80000400, 0x100000)
    assert "rom = 0x00001000" in toml and "vram = 0x80000400" in toml and '{ name = "entry_2", vram = 0x80000600, size = 0x8 }' in toml


def test_config_toml_keeps_paths_inside_the_work_folder():
    t = dt.config_toml(0x80000400, {"uses_mips3_float_mode": True}, {"stubs": ["osSyncPrintf"]})
    assert "entrypoint = 0x80000400" in t and 'rom_file_path = "rom.z64"' in t and "uses_mips3_float_mode = true" in t
    assert '[patches]\nstubs = ["osSyncPrintf"]' in t
    for bad in ({"rom_file_path": "C:/roms/game.z64"}, {"output_func_path": "../../x"}):
        with pytest.raises(ValueError, match="inside the work folder"):
            dt.config_toml(0x80000400, bad)


def _recomp_env(tmp_path):
    exe = tmp_path / "N64Recomp" / "build" / ("N64Recomp.exe" if dt.sys.platform == "win32" else "N64Recomp")
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    rom = tmp_path / "roms" / "Game (USA).v64"
    rom.parent.mkdir()
    z = fake_rom()
    rom.write_bytes(bytes(b for i in range(0, len(z), 2) for b in (z[i + 1], z[i])))     # byte-swapped .v64
    an = tmp_path / "analysis.json"
    an.write_text(json.dumps(ANALYSIS))
    return Config(data_dir=tmp_path / "data", n64recomp_path=str(exe.parent.parent)), exe, rom, an


def test_n64recomp_check_hook_and_discovery(tmp_path, monkeypatch):
    monkeypatch.delenv("N64RECOMP", raising=False)
    monkeypatch.setattr(dt.shutil, "which", lambda n: None)
    cfg, exe, _, _ = _recomp_env(tmp_path)
    assert dt.find_n64recomp(cfg) == exe and dt.n64recomp_check(cfg) is None
    assert "never downloads or builds it" in dt.n64recomp_check(Config(data_dir=tmp_path, n64recomp_path=str(tmp_path / "nope")))


def test_n64recomp_run_writes_a_work_folder_and_never_touches_the_rom(tmp_path, monkeypatch):
    cfg, exe, rom, an = _recomp_env(tmp_path)
    rom_bytes = rom.read_bytes()
    calls = []

    def fake_run(cmd, cwd, **kw):
        calls.append((cmd, cwd))
        (Path(cwd) / "RecompiledFuncs" / "funcs_0.c").write_text("// recompiled")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")
    monkeypatch.setattr(dt.subprocess, "run", fake_run)
    c = ctx(cfg)
    out = dt.n64recomp(dt.N64RecompIn(op="run", rom_path=str(rom), analysis_path=str(an), name="game"), c)["result"]
    work = Path(out["work"])
    assert calls == [([str(exe), "config.toml"], str(work))]
    assert out["state"] == "recompiled" and out["rom_unchanged"] and out["functions"] == 3 and out["outputs"] == ["funcs_0.c"]
    assert (work / "rom.z64").read_bytes()[:4] == b"\x80\x37\x12\x40" and rom.read_bytes() == rom_bytes
    assert 'symbols_file_path = "syms.toml"' in (work / "config.toml").read_text()
    assert json.loads(c.arts["n64recomp.json"])["entrypoint"] == "0x80000400"
    listed = dt.n64recomp(dt.N64RecompIn(op="list"), c)["result"]["work"]
    assert [w["name"] for w in listed] == ["game"]
    assert dt.n64recomp(dt.N64RecompIn(op="status"), c)["result"]["work_count"] == 1


def test_n64recomp_dry_run_and_missing_analysis(tmp_path, monkeypatch):
    cfg, exe, rom, an = _recomp_env(tmp_path)
    monkeypatch.setattr(dt.subprocess, "run", lambda *a, **k: pytest.fail("dry_run must not run N64Recomp"))
    out = dt.n64recomp(dt.N64RecompIn(op="run", rom_path=str(rom), analysis_path=str(an), dry_run=True), ctx(cfg))["result"]
    assert out["state"] == "prepared" and Path(out["work"], "syms.toml").is_file()
    with pytest.raises(ValueError, match="re_study"):
        dt.n64recomp(dt.N64RecompIn(op="run", rom_path=str(rom)), ctx(cfg))
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"functions": [{"name": "x", "entry": "80400000", "size": 4}]}))
    with pytest.raises(ValueError, match="boot segment"):
        dt.n64recomp(dt.N64RecompIn(op="run", rom_path=str(rom), analysis_path=str(empty)), ctx(cfg))


def test_n64recomp_failure_raises_with_the_log(tmp_path, monkeypatch):
    cfg, exe, rom, an = _recomp_env(tmp_path)
    monkeypatch.setattr(dt.subprocess, "run", lambda cmd, cwd, **k: subprocess.CompletedProcess(cmd, 3, "", "bad config"))
    with pytest.raises(RuntimeError, match="bad config"):
        dt.n64recomp(dt.N64RecompIn(op="run", rom_path=str(rom), analysis_path=str(an)), ctx(cfg))
