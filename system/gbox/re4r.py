"""Resident Evil 4 (2023 remake, Steam app 2050650, PC): REFramework install, live bridge, extraction and loose-file mods.

Why REFramework and not Ghidra/a debugger: re4.exe is protected by Denuvo Anti-Tamper (DRM; the code sections are
virtualised/encrypted and change every run), so a disassembly of the exe is mostly the protector, and gBox never
attaches a debugger to it or touches the DRM. RE Engine games instead expose their whole type database (every class,
field and method of the game, the "TDB") to managed code; REFramework (praydog, MIT) loads as dinput8.dll, reads that
database and runs Lua on the game thread. gBox's bridge (adapters/reframework/gbox_bridge.lua) is a small Lua script
that takes commands through files (REFramework scripts have no sockets) - so every read/write goes through the game's
own objects by type path, no raw addresses. Ghidra's role here: the type dump (op=dump_types -> JSON) and non-protected
DLLs, not the exe.

Safety: refuses to touch anything when an anti-cheat component is in the install (none ships with RE4 2023: checked
for EasyAntiCheat/BattlEye/etc.). Offline single-player only; nothing here touches online features. Every file gBox
adds to the game folder is recorded in a manifest (runtime/re4r/manifest.json) with a backup of anything it would
overwrite, so op=revert_all / op=uninstall put the folder back exactly. Live value changes are remembered by the bridge
(first original per path) and restored by op=revert_all.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

APPID = 2050650
TITLE = "Resident Evil 4 (2023)"
EXE = "re4.exe"
MESH_EXT, TEX_EXT, MDF_EXT = ".221108797", ".143221013", ".32"
RF_TAG = "nightly-01424-d1461375aee4ec3f313170f8eaad12064eb542d9"
RF_URL = f"https://github.com/praydog/REFramework-nightly/releases/download/{RF_TAG}/REFramework.zip"
RF_SHA256 = "f035f1da6c9b199ef8348256abfd6bacef4a903485f75d9ab73be5249ae2b14c"
TOOLS = {   # name: (url, sha256)   official releases only (see LICENSES-THIRD-PARTY.md)
    "ree-pak-cli.exe": ("https://github.com/eigeen/ree-pak-rs/releases/download/v0.7.2/ree-pak-cli.exe",
                        "bc4e561194a74faa3dbac06bd4ca0039eff85d047a8075c67895047212723101"),
    "RE4_STM_Release.list": ("https://raw.githubusercontent.com/Ekey/REE.PAK.Tool/ad05ce82c9e7412b95d410ae46be44416b23bef4/"
                             "Projects/RE4_STM_Release.list",
                             "9ce8f66b62e152f5ee6267f653a2b06d4af768ce8da134be0e4abed8312cd78b"),
    "texconv.exe": ("https://github.com/microsoft/DirectXTex/releases/download/may2026/texconv.exe",
                    "dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06"),
    "RE-Mesh-Editor.zip": ("https://github.com/NSACloud/RE-Mesh-Editor/archive/622daa75b41ec622c3444ecb44ef31a651692687.zip",
                           "4169aabec3a6bf0f41179477260ee0b1a1c0523c860c8a76b3d088eade66e3c3"),
}
ANTICHEAT = re.compile(r"(?i)easyanticheat|battleye|beservice|beclient|\beac_|anticheat|anti-cheat|xigncode|nprotect|"
                       r"gameguard|vanguard|equ8|ricochet|faceit")
# files REFramework itself creates in the game folder at runtime (removed on uninstall when they weren't there before)
RF_RUNTIME = re.compile(r"(?i)^(re\d?_fw_config\.txt|re\d?_framework_log\.txt|reframework_[\w.]*\.(txt|dmp)|"
                        r"il2cpp_dump\.json|ref_ui\.ini|imgui\.ini|_storage_)$")
BRIDGE_SRC = Path(__file__).resolve().parent.parent / "adapters" / "reframework" / "gbox_bridge.lua"
BRIDGE_REL = "reframework/autorun/gbox_bridge.lua"
CONFIG_KEYS = {"LooseFileLoader_Enabled": "true", "REFrameworkConfig_MenuOpen": "false",
               "REFrameworkConfig_RememberMenuState": "false"}


# ------------------------------------------------------------------ locating the game

def steam_root(cfg=None) -> Path | None:
    if cfg is not None and getattr(cfg, "steam_root", None):
        return Path(cfg.steam_root)
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                return Path(winreg.QueryValueEx(k, "SteamPath")[0])
        except OSError:
            return None
    return None


def game_dir(cfg=None) -> Path:
    from .catalog import parse_vdf
    root = steam_root(cfg)
    if not root:
        raise FileNotFoundError("Steam is not installed on this PC")
    lf = root / "steamapps" / "libraryfolders.vdf"
    libs = [Path(v["path"]) for v in parse_vdf(lf.read_text(errors="replace")).get("libraryfolders", {}).values()
            if isinstance(v, dict) and "path" in v]
    for lib in libs:
        acf = lib / "steamapps" / f"appmanifest_{APPID}.acf"
        if acf.is_file():
            st = parse_vdf(acf.read_text(errors="replace"))["AppState"]
            d = lib / "steamapps" / "common" / st["installdir"]
            if (d / EXE).is_file():
                return d
    raise FileNotFoundError(f"{TITLE} (Steam app {APPID}) is not installed in any Steam library on this PC")


def anticheat_scan(gd: Path) -> list[str]:
    hits = []
    for p in gd.rglob("*"):
        rel = p.relative_to(gd).as_posix()
        if rel.lower().startswith(("natives/", "reframework/")):
            continue
        if ANTICHEAT.search(p.name):
            hits.append(rel)
    return hits


def safety(gd: Path) -> dict:
    hits = anticheat_scan(gd)
    return {"anticheat": hits, "ok": not hits,
            "drm": "Denuvo Anti-Tamper (DRM, not anti-cheat): gBox never attaches a debugger to re4.exe nor touches the DRM",
            "online": "no competitive online mode; gBox mods are offline single-player only and touch no online feature"}


def _check_safe(gd: Path):
    s = safety(gd)
    if not s["ok"]:
        raise PermissionError(f"anti-cheat files in the install ({s['anticheat']}): gBox does not touch this game")


# ------------------------------------------------------------------ process

def game_process(gd: Path | None = None):
    import psutil
    for p in psutil.process_iter(["name", "exe", "pid"]):
        if (p.info["name"] or "").lower() == EXE:
            if gd is None or not p.info["exe"] or Path(p.info["exe"]).parent.resolve() == gd.resolve():
                return p
    return None


def stop_game(gd: Path | None = None, timeout: float = 15) -> dict:
    """Ask the game window to close (WM_CLOSE), then end the process if it doesn't."""
    p = game_process(gd)
    if not p:
        return {"stopped": False, "running": False}
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as w
        u = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def cb(h, _):
            pid = w.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == p.pid and u.IsWindowVisible(h):
                u.PostMessageW(h, 0x0010, 0, 0)            # WM_CLOSE
            return True
        u.EnumWindows(cb, 0)
    try:
        p.wait(timeout)
        how = "closed"
    except Exception:                                      # noqa: BLE001 - psutil.TimeoutExpired
        p.kill()
        p.wait(10)
        how = "killed"
    return {"stopped": True, "how": how, "pid": p.pid}


# ------------------------------------------------------------------ runtime downloads

def runtime(cfg) -> Path:
    d = Path(cfg.runtime) / "re4r"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _fetch(url: str, sha: str, dst: Path) -> Path:
    if dst.is_file() and _sha(dst.read_bytes()) == sha:
        return dst
    import httpx
    data = httpx.get(url, follow_redirects=True, timeout=300).content
    if _sha(data) != sha:
        raise RuntimeError(f"download of {url} does not match the pinned sha256; not using it")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return dst


def reframework_dll(cfg) -> bytes:
    z = _fetch(RF_URL, RF_SHA256, Path(cfg.runtime) / "reframework" / "-".join(RF_TAG.split("-")[:2]) / "REFramework.zip")
    with zipfile.ZipFile(z) as zf:
        return zf.read("dinput8.dll")


def tool_path(cfg, name: str) -> Path:
    d = Path(cfg.runtime) / "re_engine"
    url, sha = TOOLS[name]
    p = _fetch(url, sha, d / name)
    if name == "RE-Mesh-Editor.zip":
        addon = d / "blender_scripts" / "addons" / "RE_Mesh_Editor"
        if not (addon / "__init__.py").is_file():
            with zipfile.ZipFile(p) as zf:
                for n in zf.namelist():
                    rel = n.split("/", 1)[1] if "/" in n else ""
                    if not rel or n.endswith("/"):
                        continue
                    out = addon / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(zf.read(n))
        return d / "blender_scripts"
    return p


# ------------------------------------------------------------------ manifest: every file gBox puts in the game folder

class Manifest:
    def __init__(self, cfg, gd: Path):
        self.cfg, self.gd = cfg, gd
        self.path = runtime(cfg) / "manifest.json"
        self.backup = runtime(cfg) / "backup"
        try:
            self.m = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.m = {}
        self.m.setdefault("files", {})
        self.m.setdefault("mods", {})
        self.m["game_dir"] = str(gd)

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.m, indent=1))
        tmp.replace(self.path)

    def put(self, rel: str, data: bytes, owner: str):
        rel = rel.replace("\\", "/")
        dst = self.gd / rel
        e = self.m["files"].get(rel)
        if dst.exists() and e is None:                     # never overwrite a file gBox didn't write: back it up first
            b = self.backup / rel
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, b)
            e = {"backup": str(b)}
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        self.m["files"][rel] = {**(e or {}), "sha256": _sha(data), "owner": owner, "size": len(data), "t": time.time()}

    def remove_owner(self, owner_pred) -> list[str]:
        gone = []
        for rel, e in list(self.m["files"].items()):
            if not owner_pred(e.get("owner", "")):
                continue
            dst = self.gd / rel
            if dst.exists():
                dst.unlink()
            if e.get("backup") and Path(e["backup"]).is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(e["backup"], dst)              # put the original back
                Path(e["backup"]).unlink()
            self.m["files"].pop(rel)
            gone.append(rel)
            _prune_dirs(dst.parent, self.gd)
        return gone


def _prune_dirs(d: Path, stop: Path):
    d, stop = d.resolve(), stop.resolve()
    while d != stop and stop in d.parents:
        try:
            d.rmdir()                                      # only empty folders gBox created
        except OSError:
            return
        d = d.parent


# ------------------------------------------------------------------ REFramework install / uninstall

def _config_file(gd: Path) -> Path:
    for n in ("re4_fw_config.txt", "re2_fw_config.txt"):
        if (gd / n).is_file():
            return gd / n
    return gd / "re2_fw_config.txt"                       # the universal nightly build names it this for every game


def _patch_config(gd: Path):
    f = _config_file(gd)
    lines = f.read_text().splitlines() if f.is_file() else []
    keys = dict(CONFIG_KEYS)
    out = []
    for ln in lines:
        k = ln.split("=", 1)[0]
        if k in keys:
            ln = f"{k}={keys.pop(k)}"
        out.append(ln)
    out += [f"{k}={v}" for k, v in keys.items()]
    f.write_text("\n".join(out) + "\n")


def framework_state(cfg, gd: Path) -> dict:
    man = Manifest(cfg, gd)
    dll = gd / "dinput8.dll"
    ours = man.m["files"].get("dinput8.dll")
    return {"installed": dll.is_file() and bool(ours) and _sha(dll.read_bytes()) == ours["sha256"],
            "dll_present": dll.is_file(), "bridge_present": (gd / BRIDGE_REL).is_file(),
            "version": man.m.get("framework", {}).get("tag"), "loose_files": _loose_enabled(gd)}


def _loose_enabled(gd: Path) -> bool:
    f = _config_file(gd)
    return f.is_file() and "LooseFileLoader_Enabled=true" in f.read_text()


def install(cfg, gd: Path) -> dict:
    _check_safe(gd)
    if game_process(gd):
        raise RuntimeError("the game is running: close it first (the DLL is loaded at start)")
    man = Manifest(cfg, gd)
    if "framework" not in man.m:
        man.m["framework"] = {"pre_top": sorted(p.name for p in gd.iterdir()), "installed": time.time()}
    man.m["framework"]["tag"] = RF_TAG
    man.put("dinput8.dll", reframework_dll(cfg), "framework")
    man.put(BRIDGE_REL, BRIDGE_SRC.read_bytes(), "framework")
    _patch_config(gd)
    (gd / "reframework" / "data" / "gbox").mkdir(parents=True, exist_ok=True)
    man.save()
    return {"installed": True, "reframework": RF_TAG, "bridge": BRIDGE_REL, "config": _config_file(gd).name,
            "files": [r for r, e in man.m["files"].items() if e["owner"] == "framework"]}


def update_bridge(cfg, gd: Path) -> dict:
    """Copy the current bridge script in (REFramework reloads scripts on 'Reset scripts' or the next start)."""
    man = Manifest(cfg, gd)
    man.put(BRIDGE_REL, BRIDGE_SRC.read_bytes(), "framework")
    man.save()
    return {"bridge": BRIDGE_REL, "sha256": man.m["files"][BRIDGE_REL]["sha256"]}


def uninstall(cfg, gd: Path) -> dict:
    """Remove every gBox mod file and REFramework itself; restore anything they replaced."""
    if game_process(gd):
        raise RuntimeError("the game is running: close it first")
    man = Manifest(cfg, gd)
    mods = man.remove_owner(lambda o: o.startswith("mod:"))
    for m in man.m["mods"].values():
        m["enabled"] = False
    fw = man.remove_owner(lambda o: o == "framework")
    pre = set(man.m.get("framework", {}).get("pre_top", []))
    extra = []
    for p in gd.iterdir():
        if p.name not in pre and (RF_RUNTIME.match(p.name) or p.name == "reframework"):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            extra.append(p.name)
    man.m.pop("framework", None)
    man.save()
    return {"uninstalled": True, "mod_files_removed": mods, "framework_files_removed": fw, "runtime_files_removed": extra}


# ------------------------------------------------------------------ bridge client

class Bridge:
    def __init__(self, gd: Path):
        self.dir = gd / "reframework" / "data" / "gbox"

    def state(self) -> dict:
        f = self.dir / "state.json"
        try:
            st = json.loads(f.read_text())
            st["age_s"] = round(time.time() - f.stat().st_mtime, 2)
            return st
        except (OSError, ValueError):
            return {}

    def alive(self) -> bool:
        return self.state().get("age_s", 1e9) < 6

    def run(self, ops: list[dict], timeout: float = 10) -> list[dict]:
        self.dir.mkdir(parents=True, exist_ok=True)
        seq = int(time.time() * 1000)
        tmp, req = self.dir / "req.tmp", self.dir / "req.json"
        tmp.write_text(json.dumps({"seq": seq, "ops": ops}))
        for i in range(50):
            try:
                os.replace(tmp, req)
                break
            except PermissionError:                        # the game is reading it this instant
                time.sleep(0.02)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                r = json.loads((self.dir / "resp.json").read_text())
                if r.get("seq") == seq:
                    return r["results"]
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        raise TimeoutError("the REFramework bridge did not answer (game not running, still loading, paused in a menu "
                           "that stops the game thread, or REFramework/bridge not installed)")

    def one(self, op: str, timeout: float = 10, **kw):
        r = self.run([{"op": op, **kw}], timeout)[0]
        if not r.get("ok"):
            raise RuntimeError(r.get("error"))
        return r.get("value")


# ------------------------------------------------------------------ extraction (paks -> files -> Blender -> glTF)

BLENDER_SCRIPT = Path(__file__).resolve().parent.parent / "adapters" / "reframework" / "re_blender.py"


def paks(gd: Path) -> list[Path]:
    """Base pak, then its patches in order (later patches override earlier files)."""
    def n(p):
        m = re.search(r"patch_(\d+)\.pak$", p.name)
        return int(m.group(1)) if m else -1
    return sorted([p for p in gd.glob("re_chunk_000.pak*") if p.suffix == ".pak"], key=n)


def extract_root(cfg) -> Path:
    return Path(cfg.runtime) / "re_engine" / "extract" / "re4r"


def unpack(cfg, gd: Path, pattern: str) -> list[Path]:
    """Files whose path matches the regex, from the base pak + every patch (newest wins), into the extract cache."""
    cli, lst = tool_path(cfg, "ree-pak-cli.exe"), tool_path(cfg, "RE4_STM_Release.list")
    out = extract_root(cfg)
    out.mkdir(parents=True, exist_ok=True)
    for p in paks(gd):
        r = subprocess.run([str(cli), "unpack", "-p", str(lst), "-i", str(p), "-o", str(out), "-f", pattern, "--override",
                            "--skip-unknown"], capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError(f"ree-pak-cli failed on {p.name}: {(r.stderr or r.stdout)[-400:]}")
    rx = re.compile(pattern)
    return sorted(f for f in out.rglob("*") if f.is_file() and rx.search(f.relative_to(out).as_posix()))


def blender_exe(cfg) -> str:
    """RE Mesh Editor is slow on Blender 5.1+ (upstream bug): prefer the newest 4.2-5.0 build, else gBox's Blender."""
    best = None
    for d in getattr(cfg, "blender_search", []) or []:
        for exe in Path(d).glob("*/*/blender.exe"):
            m = re.search(r"blender-(\d+)\.(\d+)\.(\d+)", exe.parent.name)
            if m and (4, 2) <= (int(m.group(1)), int(m.group(2))) <= (5, 0):
                v = tuple(int(x) for x in m.groups())
                if best is None or v > best[0]:
                    best = (v, str(exe))
    if best:
        return best[1]
    from . import provision
    b = provision.find_blender(cfg)
    if not b:
        raise FileNotFoundError("no Blender on this PC (blender_search)")
    return b


def run_blender(cfg, job: dict, work: Path, timeout: float = 1800) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    scripts = tool_path(cfg, "RE-Mesh-Editor.zip")
    job = {"cache": str(Path(cfg.runtime) / "re_engine" / "texture_cache"), **job}
    jf = work / f"job_{job['mode']}.json"
    jf.write_text(json.dumps(job, indent=1))
    rf = jf.with_suffix(".result.json")
    rf.unlink(missing_ok=True)
    env = {**os.environ, "BLENDER_USER_SCRIPTS": str(scripts)}
    p = subprocess.run([blender_exe(cfg), "-b", "--factory-startup", "--python", str(BLENDER_SCRIPT), "--", str(jf)],
                       capture_output=True, text=True, timeout=timeout, env=env)
    (work / f"blender_{job['mode']}.log").write_text((p.stdout or "") + "\n" + (p.stderr or ""))
    if not rf.is_file():
        raise RuntimeError(f"Blender ({job['mode']}) crashed: {(p.stdout or '')[-600:]}")
    r = json.loads(rf.read_text())
    if not r.get("ok"):
        raise RuntimeError(f"Blender ({job['mode']}): {r.get('error')}")
    return r


# ------------------------------------------------------------------ characters (pak paths) and collection export

# key: (name, aliases, [mesh paths without .mesh.221108797]) - the parts the game assembles (Leon: body, face, hair, scalp;
# Ashley: body, jacket, face, hair, scalp). mod_build parts=[i] indexes this list.
CHARACTERS = {
    "leon": ("Leon S. Kennedy (RE4 2023)", ["Leon", "Leon Kennedy", "RE4 remake Leon", "RE4R Leon"],
             ["_chainsaw/character/ch/cha0/cha000/00/cha000_00", "_chainsaw/character/ch/cha0/cha000/10/cha000_10",
              "_chainsaw/character/ch/cha0/cha000/20/cha000_20", "_chainsaw/character/ch/cha0/cha000/21/cha000_21"]),
    "ashley": ("Ashley Graham (RE4 2023)", ["Ashley", "Ashley Graham", "RE4 remake Ashley", "RE4R Ashley"],
               ["_chainsaw/character/ch/cha1/cha100/00/cha100_00", "_chainsaw/character/ch/cha1/cha100/01/cha100_01",
                "_chainsaw/character/ch/cha1/cha100/10/cha100_10",
                "_chainsaw/character/ch/cha1/cha100/20/cha100_20", "_chainsaw/character/ch/cha1/cha100/21/cha100_21"]),
}


def roster() -> list[dict]:
    return [{"key": k, "slug": f"re4r_{k}", "name": n, "aliases": a, "kind": "character"} for k, (n, a, _m) in CHARACTERS.items()]


def character_meshes(cfg, gd: Path, key: str) -> list[Path]:
    if key not in CHARACTERS:
        raise KeyError(f"no RE4 (2023) character {key!r}; have {sorted(CHARACTERS)}")
    parts = CHARACTERS[key][2]
    folders = sorted({p.rsplit("/", 2)[0] for p in parts})        # .../cha000: meshes, materials and textures
    rx = "|".join(re.escape(f) + "/" for f in folders)
    unpack(cfg, gd, rx)
    root = extract_root(cfg) / "natives" / "stm"
    out = [root / f"{p}.mesh{MESH_EXT}" for p in parts]
    return [p for p in out if p.is_file()]


def export_character(cfg, gd: Path, key: str, work: Path, max_tex: int = 2048) -> dict:
    meshes = character_meshes(cfg, gd, key)
    if not meshes:
        raise FileNotFoundError(f"{key}: no mesh files found in the paks")
    out = work / f"re4r_{key}.glb"
    r = run_blender(cfg, {"mode": "export", "meshes": [str(m) for m in meshes], "out": str(out), "max_tex": max_tex}, work)
    return r | {"glb": out, "meshes": [m.relative_to(extract_root(cfg)).as_posix() for m in meshes]}


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook (runs on the control plane): the Windows worker exports the model, this fetches it."""
    from .characters import _api
    j = _api(ctx, "POST", "/api/jobs", json={"tool": "re4r", "input": {"op": "export", "character": e["key"]},
                                             "require_os": "windows"})
    t0 = time.time()
    while j.get("state") in ("queued", "running") and time.time() - t0 < 1800:
        time.sleep(2)
        j = _api(ctx, "GET", f"/api/jobs/{j['id']}")
    if j.get("state") != "succeeded":
        raise RuntimeError(f"re4r export on the Windows PC: {j.get('error') or j.get('state')}")
    res = j["output"]["result"]
    glb = work / f"{e['slug']}.glb"
    glb.write_bytes(_api(ctx, "GET", f"/api/artifacts/{res['artifact']}", timeout=600))
    return {"files": [glb], "tool": "gbox.re4r (ree-pak-cli + RE Mesh Editor in Blender)", "source_files": res["meshes"],
            "notes": "REFramework-free extraction from the operator's own re_chunk_000 paks; albedo textures, full rig"}


# ------------------------------------------------------------------ loose-file mods (natives/ overrides)

def mods_root(cfg) -> Path:
    d = runtime(cfg) / "mods"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mod_files(cfg, name: str) -> list[str]:
    d = mods_root(cfg) / name
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and p.name != "mod.json")


def enable_mod(cfg, gd: Path, name: str) -> dict:
    _check_safe(gd)
    d = mods_root(cfg) / name
    if not (d / "mod.json").is_file():
        raise FileNotFoundError(f"no gBox mod {name!r} (have {[p.name for p in mods_root(cfg).iterdir() if p.is_dir()]})")
    man = Manifest(cfg, gd)
    if not _loose_enabled(gd):
        _patch_config(gd)
    files = mod_files(cfg, name)
    for rel in files:
        man.put(rel, (d / rel).read_bytes(), f"mod:{name}")
    man.m["mods"][name] = json.loads((d / "mod.json").read_text()) | {"enabled": True, "files": files, "t": time.time()}
    man.save()
    return {"mod": name, "enabled": True, "files": files,
            "note": "loose files load when the game starts (REFramework loose file loader): restart the game to see it"}


def disable_mod(cfg, gd: Path, name: str | None = None) -> dict:
    man = Manifest(cfg, gd)
    gone = man.remove_owner(lambda o: o == f"mod:{name}" if name else o.startswith("mod:"))
    for k, m in man.m["mods"].items():
        if name in (None, k):
            m["enabled"] = False
    man.save()
    return {"disabled": name or "all", "files_removed": gone}


def build_mesh_mod(cfg, gd: Path, name: str, key: str, work: Path, edited: Path | None = None,
                   original: Path | None = None, scale: float | None = None, only: list[str] | None = None,
                   xy_only: bool = False, parts: list[int] | None = None) -> dict:
    """Replacement meshes for character parts, as loose files under natives/stm/... (the paks are never touched).
    parts: indexes into CHARACTERS[key] meshes (0 body, 1 face, 2 hair, 3 scalp); default: every part (edited model)
    or the body (scale). A scale uses one pivot for all parts (the first part's bottom centre: a head grows from the neck)."""
    meshes = character_meshes(cfg, gd, key)
    parts = parts or ([0] if scale is not None else list(range(len(meshes))))
    d = mods_root(cfg) / name
    shutil.rmtree(d, ignore_errors=True)
    built, pivot = [], None
    for i in parts:
        src = meshes[i]
        rel = src.relative_to(extract_root(cfg)).as_posix()
        job = {"mode": "build", "meshes": [str(src)], "out": str(d / rel)}
        if scale is not None:
            job |= {"scale": scale, "only": only or [], "xy_only": xy_only, "pivot": pivot}
        else:
            job |= {"edited": str(edited), "original": str(original)}
        r = run_blender(cfg, job, work)
        pivot = pivot or r.get("pivot")
        if scale is None and not r.get("changed_parts"):
            (d / rel).unlink(missing_ok=True)              # untouched part: don't ship an identical copy
            continue
        built.append({"file": rel, **{k: r.get(k) for k in ("changed_parts", "moved", "replaced", "size")}})
    if not built:
        raise ValueError("the edited model has no changes against the original export (nothing to build)")
    meta = {"name": name, "game": TITLE, "appid": APPID, "character": key, "replaces": [b["file"] for b in built],
            "built": time.time(), "source": str(edited) if edited else f"scale {scale} {only or ''} parts {parts}"}
    (d / "mod.json").write_text(json.dumps(meta, indent=1))
    return {"mod": name, "files": built, "pivot": pivot}


def build_texture_mod(cfg, gd: Path, name: str, tex_rel: str, png: Path, work: Path) -> dict:
    """PNG -> the game's .tex (same DXGI format, full mip chain) as a loose-file mod. RE4 keeps the high mips in a
    streaming copy (natives/stm/streaming/...): the new texture is written to both paths."""
    tex_rel = tex_rel.replace("\\", "/").lower()
    tail = tex_rel.split("natives/stm/", 1)[-1].removeprefix("streaming/")
    base, stream = f"natives/stm/{tail}", f"natives/stm/streaming/{tail}"
    root = extract_root(cfg)
    if not (root / base).is_file():
        unpack(cfg, gd, re.escape(tail) + "$")
    ref = root / stream if (root / stream).is_file() else root / base
    if not ref.is_file():
        raise FileNotFoundError(f"{tail} is not in the game's paks")
    d = mods_root(cfg) / name
    shutil.rmtree(d, ignore_errors=True)
    rels = [base] + ([stream] if (root / stream).is_file() else [])
    r = run_blender(cfg, {"mode": "tex", "tex": str(ref), "png": str(png), "outs": [str(d / x) for x in rels],
                          "texconv": str(tool_path(cfg, "texconv.exe"))}, work)
    (d / "mod.json").write_text(json.dumps({"name": name, "game": TITLE, "appid": APPID, "replaces": rels,
                                            "built": time.time(), "source": str(png)}, indent=1))
    return {"mod": name, "files": rels, "format": r.get("format"), "size": r.get("size")}


# ------------------------------------------------------------------ live profile (type paths through the bridge)

PLAYER = "singleton:chainsaw.CharacterManager/getPlayerContextRef()"
# stat: candidate paths, first that resolves wins (game updates rename members; op=probe reports which work)
STATS = {
    "hp": [PLAYER + "/get_HitPoint()/CurrentHitPoint", PLAYER + "/get_HitPoint()/<CurrentHitPoint>k__BackingField"],
    "max_hp": [PLAYER + "/get_HitPoint()/DefaultHitPoint", PLAYER + "/get_HitPoint()/CurrentMaximumHitPoint"],
    "invincible": [PLAYER + "/get_HitPoint()/Invincible", PLAYER + "/get_HitPoint()/IsInvincible"],
    "money": ["singleton:chainsaw.InventoryManager/CurrPTAS"],
    "spinels": ["singleton:chainsaw.InGameShopManager/CurrSpinelCount"],
    "position": [PLAYER + "/get_Position()", PLAYER + "/get_BodyGameObject()/get_Transform()/get_Position()"],
    "time_scale": ["singleton:chainsaw.CharacterManager/TimeScale"],
}
SETTABLE = {"hp", "max_hp", "invincible", "money", "spinels", "time_scale"}
# behaviour hooks (flag-guarded in the bridge; revert_all turns them all off)
HOOKS = {
    "infinite_ammo": ("chainsaw.CsInventoryController.useWeapon", {"skip": True},
                      "weapon/ammo use is skipped: magazines and grenades are not consumed"),
    "unlimited_items": ("chainsaw.gui.inventory.CsInventory.operation(chainsaw.gui.inventory.ReduceItemCountOperation)",
                        {"skip": True}, "inventory item counts never go down (healing items, ammo boxes)"),
    "no_recoil": ("chainsaw.CameraRecoilParam.init", {"skip": True}, "camera recoil is never set up"),
}
# Lua run on the game thread (bridge `lua` op) for things that need several calls
LUA_INVENTORY = r"""
local scene = sdk.call_native_func(sdk.get_native_singleton("via.SceneManager"), sdk.find_type_definition("via.SceneManager"), "get_CurrentScene")
local eq = scene:call("findComponents(System.Type)", sdk.typeof("chainsaw.PlayerEquipment"))
eq = eq and eq[0]
if not eq then return {error = "no PlayerEquipment (not in game?)"} end
local inv = eq:call("get_InventoryController()")
local items = inv:call("getInventoryItems")
local out = {}
local n = items and items:call("get_Count") or 0
for i = 0, n - 1 do
  local e = items:call("get_Item", i)
  local row = {slot = i}
  local it = nil
  pcall(function() it = e:call("get_Item") end)
  if it == nil then pcall(function() it = e:get_field("_Item") end) end
  pcall(function() row.id = e:call("get_ItemId") end)
  pcall(function() row.count = it:call("get_CurrentItemCount") end)
  pcall(function() row.ammo = it:call("get_CurrentAmmo") end)
  pcall(function() row.type = it:get_type_definition():get_full_name() end)
  out[#out + 1] = row
end
local w = eq:call("getEquipWeaponItem()")
local ew = {}
if w then
  pcall(function() ew.id = w:call("get_ItemId") end)
  pcall(function() ew.ammo = w:call("get_CurrentAmmo") end)
  pcall(function() ew.type = w:get_type_definition():get_full_name() end)
end
return {items = out, equipped = ew}
"""
LUA_TELEPORT = r"""
local ctx = resolve("singleton:chainsaw.CharacterManager/getPlayerContextRef()")
local go = ctx:call("get_BodyGameObject")
local tr = go:call("get_Transform")
local pos = tr:call("get_Position")
local x, y, z = P.x, P.y, P.z
if P.relative then x, y, z = pos.x + x, pos.y + y, pos.z + z end
local cc = go:call("getComponent(System.Type)", sdk.typeof("via.physics.CharacterController"))
tr:call("set_Position", Vector3f.new(x, y, z))
if cc then pcall(function() cc:call("warp") end) end
local after = tr:call("get_Position")
return {before = {x = pos.x, y = pos.y, z = pos.z}, after = {x = after.x, y = after.y, z = after.z}}
"""


def _first(b: Bridge, key: str):
    errs = []
    for p in STATS[key]:
        r = b.run([{"op": "get", "path": p}])[0]
        if r.get("ok") and r.get("value") is not None:
            return p, r["value"]
        errs.append(r.get("error"))
    raise RuntimeError(f"{key}: none of {STATS[key]} resolved ({errs[-1] if errs else ''})")


def stats(b: Bridge) -> dict:
    vals = b.run([{"op": "get_many", "paths": {k: v[0] for k, v in STATS.items()}}])[0].get("value") or {}
    out = {}
    for k, v in vals.items():
        if isinstance(v, dict) and "error" in v:
            try:
                out[k] = _first(b, k)[1]
            except RuntimeError as e:
                out[k] = {"unavailable": str(e)[:160]}
        else:
            out[k] = v
    return out


def set_stat(b: Bridge, key: str, value) -> dict:
    if key not in SETTABLE:
        raise ValueError(f"settable: {sorted(SETTABLE)} (or op=set path=<type path>)")
    path, _cur = _first(b, key)
    r = b.one("set", path=path, value=value)
    return {"key": key, "path": path, **r, "verified": r.get("after") == value}


def _hook(b: Bridge, key: str, on: bool) -> dict:
    sig, opts, what = HOOKS[key]
    r = b.one("hook", sig=sig, **(opts if on else {"skip": False, "clear_ret": True}))
    return {key: on, "hook": r, "effect": what}


# ------------------------------------------------------------------ the tool

def _steam_eula_pending() -> bool:
    root = steam_root()
    try:
        tail = (root / "logs" / "console_log.txt").read_text(errors="replace")[-6000:]
    except (OSError, TypeError):
        return False
    lines = [ln for ln in tail.splitlines() if f"AppID {APPID}" in ln]
    return bool(lines) and "waiting for user response to ShowEula" in lines[-1]


def launch(cfg, gd: Path, wait: float = 120) -> dict:
    """Start through Steam (Steam's own launch path, DRM untouched) and wait for the process."""
    p = game_process(gd)
    if p:
        return {"running": True, "already": True, "pid": p.pid}
    os.startfile(f"steam://rungameid/{APPID}")            # noqa: S606 - constant URL
    t0 = time.time()
    while time.time() - t0 < wait:
        p = game_process(gd)
        if p:
            return {"running": True, "pid": p.pid, "seconds": round(time.time() - t0, 1)}
        if _steam_eula_pending():
            return {"running": False, "blocked": "Steam is showing Capcom's EULA for this game: the operator has to accept "
                                                 "it in Steam once (gBox never accepts agreements on their behalf)"}
        time.sleep(1)
    return {"running": False, "error": "the game did not start within the wait time"}


def _types_search(b: Bridge, query: str, limit: int) -> dict:
    rx = re.compile(query, re.I)
    hits = []
    files = sorted((b.dir / "tdb").glob("types_*.json"))
    if not files:
        raise FileNotFoundError("no type dump yet: run re4r op=dump_types (game running) first")
    for f in files:
        for t in json.loads(f.read_text()):
            if rx.search(t["name"]):
                hits.append({"type": t["name"], "parent": t.get("parent"), "fields": len(t.get("fields", [])),
                             "methods": len(t.get("methods", []))})
            else:
                ms = [m for m in t.get("methods", []) if rx.search(m[0])] + [x for x in t.get("fields", []) if rx.search(x[0])]
                if ms:
                    hits.append({"type": t["name"], "members": ms[:12]})
            if len(hits) >= limit:
                return {"hits": hits, "truncated": True}
    return {"hits": hits}


def run_op(cfg, inp, ctx=None) -> dict:
    gd = game_dir(cfg)
    op, b = inp.op, Bridge(gd)
    prog = ctx.progress if ctx else (lambda *a: None)
    if op == "status":
        p = game_process(gd)
        st = b.state()
        man = Manifest(cfg, gd)
        out = {"game": TITLE, "game_dir": str(gd), "safety": safety(gd), "framework": framework_state(cfg, gd),
               "running": bool(p), "pid": p.pid if p else None, "bridge_alive": b.alive(),
               "bridge_state": {k: st.get(k) for k in ("tick", "changed", "freezes", "watch", "age_s")} if st else None,
               "mods": {k: {"enabled": m.get("enabled"), "replaces": m.get("replaces")} for k, m in man.m["mods"].items()},
               "available_mods": [d.name for d in mods_root(cfg).iterdir() if (d / "mod.json").is_file()],
               "eula_pending": _steam_eula_pending()}
        if p and b.alive():
            try:
                out["player"] = stats(b)
            except Exception as e:                         # noqa: BLE001 - title screen etc.
                out["player"] = {"unavailable": str(e)[:200]}
        return out
    if op == "install":
        return install(cfg, gd)
    if op == "uninstall":
        return uninstall(cfg, gd)
    if op == "update_bridge":
        return update_bridge(cfg, gd)
    if op == "launch":
        if not framework_state(cfg, gd)["installed"]:
            install(cfg, gd)
        return launch(cfg, gd, wait=inp.wait or 120)
    if op == "stop":
        return stop_game(gd)
    if op == "export":                                     # model -> glb artifact (characters op=extract calls this)
        work = runtime(cfg) / "work" / f"export_{inp.character}"
        shutil.rmtree(work, ignore_errors=True)
        prog(10, f"Unpacking {inp.character} from the game's paks")
        r = export_character(cfg, gd, inp.character, work)
        data = Path(r.pop("glb")).read_bytes()
        if ctx:
            ctx.artifact(f"re4r_{inp.character}.glb", data, "model/gltf-binary", character=inp.character)
        return r | {"artifact": _sha(data), "bytes": len(data)}
    if op == "mods":
        man = Manifest(cfg, gd)
        return {"available": {d.name: json.loads((d / "mod.json").read_text()) for d in mods_root(cfg).iterdir()
                              if (d / "mod.json").is_file()}, "installed": man.m["mods"]}
    if op == "mod_enable":
        return enable_mod(cfg, gd, inp.name)
    if op == "mod_disable":
        return disable_mod(cfg, gd, inp.name or None)
    if op == "mod_build":
        name = inp.name or f"{inp.character}_{int(time.time())}"
        work = runtime(cfg) / "work" / f"build_{name}"
        work.mkdir(parents=True, exist_ok=True)
        if inp.texture:                                    # texture mod: png -> tex
            return build_texture_mod(cfg, gd, name, inp.texture, Path(inp.png or inp.path), work)
        if inp.scale:
            return build_mesh_mod(cfg, gd, name, inp.character, work, scale=inp.scale, only=inp.items or None,
                                  xy_only=inp.xy_only, parts=inp.parts or None)
        edited = Path(inp.path) if inp.path else None
        if inp.artifact and ctx:
            from .characters import _api
            edited = work / "edited.glb"
            edited.write_bytes(_api(ctx, "GET", f"/api/artifacts/{inp.artifact}", timeout=600))
        if not edited:
            raise ValueError("mod_build needs path=<edited .glb> or artifact=<sha256> (a collection entry / Blender variant), "
                             "or scale=<factor> [items=[material names]], or texture=<natives/... .tex path> png=<file>")
        orig = work / "original.glb"
        if not orig.is_file():
            r = export_character(cfg, gd, inp.character, work)
            Path(r["glb"]).replace(orig)
        return build_mesh_mod(cfg, gd, name, inp.character, work, edited=edited, original=orig, parts=inp.parts or None)
    if op == "revert_all":
        out = {}
        if game_process(gd) and b.alive():
            out["live"] = b.one("revert_all")
        if inp.scope in ("all", "files"):
            out["files"] = disable_mod(cfg, gd, None)
        return out or {"live": "game not running: nothing live to revert"}
    if op == "types":
        return _types_search(b, inp.query, inp.limit or 60)
    # ---- live ops: need the running game + bridge
    if not game_process(gd):
        raise RuntimeError(f"{TITLE} is not running (re4r op=launch, or launch it from gBox)")
    if not b.alive():
        raise RuntimeError("the gBox bridge is not answering: REFramework not installed (op=install, then restart the "
                           "game), or the game is still loading")
    if op == "stats":
        return stats(b)
    if op == "probe":                                      # which profile paths resolve on this game version
        out = {k: [{"path": p, **b.run([{"op": "get", "path": p}])[0]} for p in paths] for k, paths in STATS.items()}
        out["hook_types"] = b.one("find_types", names=sorted({v[0].split("(")[0].rsplit(".", 1)[0] for v in HOOKS.values()}))
        return out
    if op == "set":
        return b.one("set", path=inp.path, value=inp.value) if inp.path else set_stat(b, inp.key, inp.value)
    if op in HOOKS:
        return _hook(b, op, inp.on)
    if op == "freeze":
        if inp.key in HOOKS:
            return _hook(b, inp.key, inp.on)
        if inp.key == "health":                            # HP held at max every frame (+ the game's invincible flag)
            hp_p = _first(b, "hp")[0]
            r = [b.one("freeze", path=hp_p, value=_first(b, "max_hp")[1], on=inp.on)]
            try:
                r.append(b.one("freeze", path=_first(b, "invincible")[0], value=True, on=inp.on))
            except RuntimeError:
                pass
            return {"health": inp.on, "freezes": r}
        path = inp.path or (_first(b, inp.key)[0] if inp.key in STATS else None)
        if not path:
            raise ValueError(f"freeze key: health | {' | '.join(HOOKS)} | {' | '.join(sorted(SETTABLE))}, or path=")
        return b.one("freeze", path=path, value=inp.value, on=inp.on)
    if op == "inventory":
        return b.one("lua", code=LUA_INVENTORY)
    if op == "teleport":
        if len(inp.position) != 3:
            raise ValueError("teleport needs position=[x, y, z] (relative=true to move by that much)")
        x, y, z = (float(v) for v in inp.position)
        code = f"local P = {{x={x}, y={y}, z={z}, relative={str(inp.relative).lower()}}}\n" + LUA_TELEPORT
        return {"teleport": b.one("lua", code=code)}
    if op == "get":
        return {"path": inp.path, "value": b.one("get", path=inp.path)}
    if op == "call":
        return {"path": inp.path, "method": inp.method,
                "value": b.one("call", path=inp.path, method=inp.method, args=inp.args)}
    if op == "fields":
        return b.one("fields", path=inp.path, inherited=inp.inherited)
    if op == "type_info":
        return b.one("type_info", name=inp.name, limit=inp.limit or 400)
    if op == "find_types":
        return {"found": b.one("find_types", names=inp.items)}
    if op == "lua":
        return {"value": b.one("lua", code=inp.code, timeout=30)}
    if op == "changes":
        return b.one("changes")
    if op == "dump_types":
        seeds = inp.items
        if not seeds:
            f = Path(cfg.runtime) / "re_engine" / "re4_typenames_raw.txt"
            seeds = [ln for ln in f.read_text().splitlines() if ln.startswith(("chainsaw.", "app.", "share."))] if f.is_file() else []
        seeds = seeds or ["chainsaw.CharacterManager", "chainsaw.InventoryManager", "chainsaw.PlayerBaseContext"]
        r = b.one("dump_types", seeds=seeds, max=inp.limit or 60000, restart=True)
        t0, s = time.time(), {}
        while time.time() - t0 < (inp.wait or 900):
            s = b.one("dump_status")
            prog(min(95, 5 + s.get("count", 0) / 600), f"type dump: {s.get('count')} types, {s.get('queued')} queued")
            if s.get("done"):
                break
            time.sleep(2)
        return {"started": r, "status": s, "folder": str(b.dir / "tdb")}
    raise ValueError(f"unknown op {op}")


def seeds_from_exe(gd: Path, out: Path) -> int:
    """Type names visible as plain strings in re4.exe (a file read, no process access): seeds for op=dump_types."""
    d = (gd / EXE).read_bytes()
    names = sorted({m.group().decode() for m in re.finditer(
        rb"(?<![\w.])(?:chainsaw|app|via|share|soundlib|System)\.[A-Za-z0-9_.`<>+\[\],]{2,200}(?=\x00)", d)})
    out.write_text("\n".join(names))
    return len(names)


try:
    from pydantic import BaseModel

    from .models import Permission as P
    from .registry import tool

    class RE4RIn(BaseModel):
        op: str = "status"
        key: str = ""              # set/freeze: hp | max_hp | money | spinels | invincible | time_scale | health | infinite_ammo..
        value: object = None       # set / freeze value
        on: bool = True
        path: str = ""             # type path (get/set/call/fields/freeze), or a file (mod_build: edited .glb)
        method: str = ""           # call: method name or full signature, e.g. recovery(System.Int32)
        args: list = []            # call: arguments
        name: str = ""             # type_info: type name | mod_*: mod name
        items: list[str] = []      # find_types: names | dump_types: seeds | mod_build scale: material names to scale
        query: str = ""            # types: regex over the type dump
        code: str = ""             # lua: Lua run on the game thread (helpers: resolve, ser, assign, remember)
        position: list[float] = [] # teleport
        relative: bool = False
        character: str = "leon"    # export / mod_build: leon | ashley
        artifact: str = ""         # mod_build: edited model (sha256 of a collection .glb)
        texture: str = ""          # mod_build: natives/stm/... .tex path to replace
        png: str = ""              # mod_build: the new texture image
        scale: float = 0.0         # mod_build: scale the part (test / simple variant)
        xy_only: bool = False
        parts: list[int] = []      # mod_build: indexes into CHARACTERS[character] (Leon: 0 body 1 face 2 hair 3 scalp)
        scope: str = "live"        # revert_all: live | files | all
        inherited: bool = False
        limit: int = 0
        wait: float = 0

    class RE4ROut(BaseModel):
        result: dict

    def _check(cfg):
        if sys.platform != "win32":
            return "Resident Evil 4 (2023) runs on the Windows PC"
        try:
            game_dir(cfg)
        except Exception as e:                             # noqa: BLE001
            return str(e)
        return None

    @tool("re4r", "1.0", RE4RIn, RE4ROut, capabilities=["runtime", "mod", "extract", "analyze"], platforms=["windows"],
          permissions=[P.EXECUTE, P.INSTALL, P.MEMORY_WRITE], timeout_s=3600, check=_check, artifacts=["re4r_*.glb"],
          side_effects=["install/uninstall: adds/removes REFramework (dinput8.dll) + the gBox bridge in the game folder "
                        "(manifest + backups)", "set/freeze/hooks: change the running game (revert_all restores)",
                        "mod_enable/mod_disable: add/remove loose files under natives/ (revert_all scope=files)"])
    def re4r_tool(inp: RE4RIn, ctx):
        """Resident Evil 4 (2023, Steam) on this PC through REFramework + gBox's Lua bridge."""
        return {"result": run_op(ctx.config, inp, ctx)}
except ImportError:                                        # pragma: no cover - standalone use
    pass
