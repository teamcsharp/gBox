"""gBox setup wizard (gBox.sh): scan this machine for what gBox needs, reuse what is already there, install or build
what is missing, write per-machine settings, troubleshoot, and start gBox. The server is standard library http.server;
gBox.sh installs gBox's Python packages first. UI: clients/wizard/index.html (http://127.0.0.1:8770).

It is also the guided installer of a decanted package (gbox/decant.py; "Install gBox.cmd" -> `python -m gbox.wizard`):
a clickable flow chart of nine steps over the visualizer, from checking the machine to starting gBox.

Settings go to gbox.local-<host>.toml next to gbox.toml (merged over it by config.load), never into the shared file.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # system/
UI = ROOT / "clients" / "wizard" / "index.html"
WIN = platform.system() == "Windows"
LOG: list[str] = []
TASKS: dict[str, str] = {}                                 # component -> running | ok | failed: ...


def log(msg: str):
    LOG.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    del LOG[:-800]


def _probe(url: str, timeout=2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except Exception:
        return False


def _cfg(config_path: Path):
    sys.path.insert(0, str(ROOT))
    from gbox import config
    return config.load(config_path)


def scan(config_path: Path) -> list[dict]:
    """Every component gBox can use: found (and where) or missing (and whether the wizard can install it)."""
    cfg = _cfg(config_path)
    from gbox import provision
    a = cfg.agent
    llm = a.get("llm_url", "http://127.0.0.1:11434/v1").replace("/v1", "")
    server = cfg.public_url or f"http://127.0.0.1:{cfg.api_port}"
    gpu = ""
    if shutil.which("nvidia-smi"):
        try:
            gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        except Exception:
            pass

    def item(cid, name, found, where="", installable=True, group="core", note=""):
        return {"id": cid, "name": name, "found": bool(found), "where": str(where or ""), "installable": installable,
                "group": group, "note": note, "task": TASKS.get(cid)}

    out = [
        item("python", "Python 3.11+", sys.version_info >= (3, 11), sys.executable, False),
        item("gbox", "gBox control plane", _probe(server + "/api/health"), server, True, "core",
             "reuse an existing control plane (e.g. your DGX Spark) or run one here"),
        item("gpu", "GPU", gpu, gpu or "no NVIDIA GPU found", False, "core"),
        item("docker", "Docker", shutil.which("docker"), shutil.which("docker"), False, "core", "needed for the containerized stack"),
        item("ollama", "Ollama (local LLM)", _probe(llm + "/api/tags"), llm, True, "ai"),
        item("searxng", "SearXNG (web search)", _probe(a.get("searx_url", "") + "/healthz") or _probe(a.get("searx_url", "")),
             a.get("searx_url"), True, "ai"),
        item("ffmpeg", "ffmpeg", shutil.which("ffmpeg"), shutil.which("ffmpeg"), True, "media"),
        item("retroarch", "RetroArch + cores", (cfg.runtime / ("retroarch-win" if WIN else "retroarch")).exists() or shutil.which("retroarch"),
             cfg.runtime, True, "emulators"),
        item("rpcs3", "RPCS3 (PS3)", (provision.rpcs3_home(cfg) / "rpcs3.exe").exists(), provision.rpcs3_home(cfg), WIN, "emulators",
             "" if WIN else "Windows nodes only"),
        item("jdk21", "JDK 21", provision.jdk21(cfg), provision.jdk21(cfg), True, "reverse"),
        item("ghidra", "Ghidra", provision.ghidra_home(cfg), provision.ghidra_home(cfg), True, "reverse"),
        item("blender", "Blender", provision.find_blender(cfg), provision.find_blender(cfg), False, "media",
             "install from blender.org, then set the search folder"),
        item("cargo", "Rust / cargo (Bevy)", shutil.which("cargo"), shutil.which("cargo"), False, "media", "install from rustup.rs"),
    ]
    for lib in cfg.libraries:
        root = lib.root()
        out.append(item(f"lib:{lib.id}", f"Library: {lib.id}", root and Path(root).exists(), root, False, "libraries"))
    return out


def _install(cid: str, config_path: Path):
    cfg = _cfg(config_path)
    from gbox import provision
    steps = {
        "ffmpeg": lambda: provision.ensure_ffmpeg(),
        "retroarch": lambda: provision.retroarch_exe(cfg),
        "rpcs3": lambda: provision.ensure_rpcs3(cfg, lambda p, m: log(f"rpcs3: {m}")),
        "jdk21": lambda: provision.ensure_jdk21(cfg),
        "ghidra": lambda: provision.ensure_ghidra(cfg),
        "all": lambda: provision.setup(cfg, log=log),
    }
    if cid == "ollama":
        cmd = (["winget", "install", "-e", "--id", "Ollama.Ollama", "--accept-package-agreements", "--accept-source-agreements"]
               if WIN else ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"])
        return _run(cmd)
    if cid == "searxng":
        return _run(["docker", "run", "-d", "--name", "gbox-searxng", "--restart", "unless-stopped", "-p", "8081:8080",
                     "searxng/searxng"])
    if cid == "gbox":
        return start_gbox(config_path)
    if cid == "stack":
        return _run(["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "up", "-d", "--build"])
    if cid not in steps:
        raise ValueError(f"no installer for {cid}")
    return steps[cid]()


def _run(cmd: list[str]):
    log("$ " + " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    for line in p.stdout:
        log(line.rstrip())
    if p.wait():
        raise RuntimeError(f"{cmd[0]} exited {p.returncode}")
    return {"ok": True}


def install(cid: str, config_path: Path):
    def work():
        TASKS[cid] = "running"
        log(f"== {cid}: start")
        try:
            r = _install(cid, config_path)
            TASKS[cid] = "ok"
            log(f"== {cid}: done {json.dumps(r, default=str)[:300]}")
        except Exception as e:
            TASKS[cid] = f"failed: {e}"
            log(f"== {cid}: FAILED {type(e).__name__}: {e}")
    threading.Thread(target=work, daemon=True).start()


def start_gbox(config_path: Path):
    """Run a control plane + local worker on this machine (standalone mode), detached."""
    args = [sys.executable, "-m", "gbox", "--config", str(config_path), "serve", "--worker"]
    kw = {"creationflags": 0x00000008 | 0x00000200} if WIN else {"start_new_session": True}   # detached / new group
    p = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    log(f"started gBox (pid {p.pid}): {' '.join(args)}")
    return {"pid": p.pid}


# ---- settings: per-machine overlay (gbox.local-<host>.toml) ----
def _toml(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_toml(x)}" for k, x in v.items()) + " }"
    return json.dumps(str(v))                              # a JSON string is a valid TOML basic string


def save_settings(config_path: Path, s: dict) -> Path:
    from gbox import config
    over = config.local_overlay(config_path)
    lines = ["# Written by the gBox setup wizard for this machine; merged over gbox.toml.", ""]
    libs = s.pop("libraries", None)
    for k, v in s.items():
        if v not in (None, "", [], {}):
            lines.append(f"{k} = {_toml(v)}")
    for lib in libs or []:
        lines += ["", "[[libraries]]"] + [f"{k} = {_toml(v)}" for k, v in lib.items() if v not in (None, "")]
    over.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"saved settings -> {over}")
    return over


def settings(config_path: Path) -> dict:
    cfg = _cfg(config_path)
    os_ = "windows" if WIN else "linux"
    return {"os": os_, "host": platform.node(), "config": str(config_path),
            "data_dir": str(cfg.data_dir), "public_url": cfg.public_url or "", "api_port": cfg.api_port,
            "runtime_dir": cfg.runtime_dirs.get(os_, ""), "cache_dir": cfg.cache_dirs.get(os_, ""),
            "llm_url": cfg.agent.get("llm_url"), "model": cfg.agent.get("model"), "searx_url": cfg.agent.get("searx_url"),
            "blender_search": cfg.blender_search,
            "libraries": [{"id": lib.id, "kind": lib.kind, "path": lib.paths.get(os_, "")} for lib in cfg.libraries]}


def apply_settings(config_path: Path, f: dict) -> Path:
    os_ = "windows" if WIN else "linux"
    cfg = _cfg(config_path)
    agent = dict(cfg.agent) | {k: f[k] for k in ("llm_url", "model", "searx_url") if f.get(k)}
    s = {"public_url": f.get("public_url"), "agent": agent, "blender_search": f.get("blender_search") or None,
         "runtime_dirs": cfg.runtime_dirs | ({os_: f["runtime_dir"]} if f.get("runtime_dir") else {}),
         "cache_dirs": cfg.cache_dirs | ({os_: f["cache_dir"]} if f.get("cache_dir") else {})}
    libs = []
    for lib in f.get("libraries") or []:
        old = next((x for x in cfg.libraries if x.id == lib["id"]), None)
        paths = (old.paths if old else {}) | {os_: lib["path"]}
        libs.append({"id": lib["id"], "kind": lib.get("kind", "files"), "paths": paths})
    if libs:
        s["libraries"] = libs
    return save_settings(config_path, s)


def doctor(config_path: Path) -> list[dict]:
    """Troubleshooting: the checks that explain most 'it doesn't work' reports."""
    cfg = _cfg(config_path)
    server = cfg.public_url or f"http://127.0.0.1:{cfg.api_port}"
    tokf = cfg.data_dir / "api_token"
    checks = [("config file readable", config_path.exists(), str(config_path)),
              ("data folder writable", os.access(cfg.data_dir if cfg.data_dir.exists() else cfg.data_dir.parent, os.W_OK), str(cfg.data_dir)),
              ("API token present", tokf.exists(), str(tokf)),
              ("control plane answers", _probe(server + "/api/health"), server)]
    if tokf.exists() and _probe(server + "/api/health"):
        try:
            req = urllib.request.Request(server + "/api/workers", headers={"authorization": "Bearer " + tokf.read_text().strip()})
            ws = json.loads(urllib.request.urlopen(req, timeout=5).read())
            checks.append(("workers online", any(w.get("online") for w in ws), ", ".join(w["name"] for w in ws if w.get("online"))))
        except Exception as e:
            checks.append(("token accepted by the control plane", False, str(e)))
    for lib in cfg.libraries:
        r = lib.root()
        checks.append((f"library {lib.id} reachable", bool(r and Path(r).exists()), str(r)))
    llm = cfg.agent.get("llm_url", "").replace("/v1", "")
    checks.append(("LLM endpoint (Ollama) answers", _probe(llm + "/api/tags"), llm))
    return [{"check": c, "ok": bool(ok), "detail": d} for c, ok, d in checks]


# ================================================================ guided installer (the flow chart)
# Nine steps, each a node the UI can open, run, redo or skip. The wizard process itself is standard library only (it runs
# before gBox's packages exist); everything that needs gBox runs in the installed venv as `python -m gbox.decant ...`.
# State lives in <package>/.tools/wizard-state.json so closing the browser (or the wizard) loses nothing.

PKG = ROOT.parent                                            # the unzipped package (Install gBox.cmd, system/) or the repo root
STATE_FILE = PKG / ".tools" / "wizard-state.json"
OS_ = "windows" if WIN else "linux"
STEPS = [("machine", "Check the machine"), ("folder", "Install folder"), ("runtime", "Python + gBox"),
         ("roms", "Your ROM folders"), ("emulators", "Emulators & cores"), ("toolkits", "Toolkits"),
         ("llm", "Local LLM"), ("mods", "Rebuild mods"), ("start", "Start gBox")]
BIG = 50 << 20                                               # downloads above this always ask first, one by one
_lock = threading.RLock()
STATE: dict = {}


def _blank_step() -> dict:
    return {"status": "idle", "progress": 0, "lines": [], "error": "", "data": {}, "t": 0}


def _load_state(api_port: int | None = None):
    global STATE
    try:
        STATE = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        STATE = {}
    STATE.setdefault("install_dir", str(PKG))
    STATE.setdefault("roms", [])
    STATE.setdefault("offline", False)
    STATE.setdefault("overlay", {})
    STATE.setdefault("steps", {})
    if api_port:
        STATE["api_port"] = api_port
    STATE.setdefault("api_port", 8765)
    for sid, _ in STEPS:
        STATE["steps"].setdefault(sid, _blank_step())
        if STATE["steps"][sid]["status"] == "running":       # the wizard was closed mid-step
            STATE["steps"][sid].update(status="failed", error="interrupted: the wizard was closed while this step ran")


def _save():
    with _lock:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(STATE, indent=1, default=str), encoding="utf-8")
        tmp.replace(STATE_FILE)


def S(step: str) -> dict:
    return STATE["steps"][step]


def say(step: str, msg: str):
    with _lock:
        for ln in str(msg).splitlines() or [""]:
            S(step)["lines"].append(ln.rstrip()[:400])
        del S(step)["lines"][:-400]
    log(f"[{step}] {msg}")


def prog(step: str, pct: float):
    S(step)["progress"] = max(0, min(100, round(pct, 1)))


def inst() -> Path:
    return Path(STATE.get("install_dir") or PKG)


def sysdir() -> Path:
    return inst() / "system"


def cfg_file() -> Path:
    return sysdir() / "gbox.toml"


def venv_py() -> Path:
    return inst() / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")


def overlay_file() -> Path:
    return sysdir() / f"gbox.local-{platform.node().lower()}.toml"


def write_overlay():
    """This PC's choices (merged over the package's standalone gbox.toml by config.load)."""
    ov = STATE["overlay"]
    lines = ["# Written by the gBox setup wizard for this PC; merged over gbox.toml.", ""]
    for k, v in ov.items():
        if k != "libraries" and v not in (None, "", [], {}):
            lines.append(f"{k} = {_toml(v)}")
    for lib in ov.get("libraries") or []:
        lines += ["", "[[libraries]]"] + [f"{k} = {_toml(v)}" for k, v in lib.items() if v not in (None, "")]
    overlay_file().write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env() -> dict:
    return {**os.environ, "PYTHONPATH": str(sysdir()), "GBOX_CONFIG": str(cfg_file()), "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8"}


NO_WINDOW = 0x08000000
BELOW = 0x00004000 if WIN else 0                          # BELOW_NORMAL_PRIORITY_CLASS: setup never competes with a game


def _stream(step: str, cmd: list, cwd: Path | None = None, env: dict | None = None, on_json=None) -> int:
    """Run a command, every output line into the step's console; JSON lines go to on_json (progress / results)."""
    say(step, "$ " + " ".join(str(c) for c in cmd))
    cwd = cwd or (sysdir() if sysdir().exists() else PKG)
    p = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), env=env or _env(),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         creationflags=(NO_WINDOW | BELOW) if WIN else 0)
    for line in p.stdout:
        line = line.rstrip()
        if on_json and line.startswith("{"):
            try:
                if on_json(json.loads(line)) is not False:
                    continue
            except ValueError:
                pass
        if line:
            say(step, line)
    return p.wait()


def _py(step: str, args: list, on_json=None) -> tuple[int, dict]:
    """python -m gbox.decant ... in the installed venv; returns (exit code, the {"result": ...} it printed)."""
    out = {}

    def take(o):
        if "result" in o:
            out.update(o["result"] if isinstance(o["result"], dict) else {"value": o["result"]})
            return True
        if on_json:
            return on_json(o)
        pr = o.get("progress")
        msg = o.get("log") or (pr.get("msg") if isinstance(pr, dict) else pr)
        if msg:
            say(step, str(msg))
            return True
        say(step, json.dumps(o)[:300])
        return True
    rc = _stream(step, [venv_py(), "-P", *args], on_json=take)
    return rc, out


def _uv() -> str | None:
    for c in (inst() / ".tools" / "uv" / "uv.exe", PKG / ".tools" / "uv" / "uv.exe", inst() / ".tools" / "uv" / "uv"):
        if c.exists():
            return str(c)
    return shutil.which("uv")


def _net() -> bool:
    return not STATE.get("offline")


def _head(url: str) -> int | None:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"user-agent": "gbox-setup"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return int(r.headers.get("content-length") or 0) or None
    except Exception:
        return None


def _download(step: str, url: str, dest: Path, lo: float = 0, hi: float = 100) -> Path:
    if not _net():
        raise RuntimeError("offline mode: point this step at a file you already have instead")
    dest.parent.mkdir(parents=True, exist_ok=True)
    say(step, f"downloading {url}")
    req = urllib.request.Request(url, headers={"user-agent": "gbox-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest.with_suffix(dest.suffix + ".part"), "wb") as f:
        total, got, t = int(r.headers.get("content-length") or 0), 0, 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            if total and time.time() - t > 0.5:
                t = time.time()
                prog(step, lo + (hi - lo) * got / total)
                S(step)["data"]["dl"] = {"url": url, "got": got, "total": total}
    dest.with_suffix(dest.suffix + ".part").replace(dest)
    S(step)["data"].pop("dl", None)
    say(step, f"saved {dest.name} ({got / 1e6:.1f} MB)")
    return dest


# ---- step 1: the machine

def _gpu() -> dict:
    if shutil.which("nvidia-smi"):
        try:
            row = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW if WIN else 0).stdout.strip().splitlines()[0]
            name, mem, drv = [x.strip() for x in row.split(",")]
            return {"name": name, "vram_gb": round(int(mem) / 1024, 1), "driver": drv, "vendor": "NVIDIA"}
        except Exception:
            pass
    if WIN:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | "
                                "Select-Object Name, AdapterRAM, DriverVersion | ConvertTo-Json"], capture_output=True, text=True,
                               timeout=20, creationflags=NO_WINDOW)
            rows = json.loads(r.stdout or "[]")
            rows = rows if isinstance(rows, list) else [rows]
            best = max(rows, key=lambda x: x.get("AdapterRAM") or 0) if rows else None
            if best:
                return {"name": best["Name"], "vram_gb": round((best.get("AdapterRAM") or 0) / 2**30, 1), "driver": best.get("DriverVersion"),
                        "vendor": "AMD" if "AMD" in best["Name"] or "Radeon" in best["Name"] else "Intel" if "Intel" in best["Name"] else "?",
                        "note": "VRAM as reported by Windows (capped at 4 GB for some cards)"}
        except Exception:
            pass
    return {}


def _ram_gb() -> float:
    if WIN:
        import ctypes

        class M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong),
                        ("e", ctypes.c_ulonglong)]
        m = M()
        m.l = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.total / 2**30, 1)
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return 0


def recommend_models(vram: float) -> dict:
    """The local models gBox uses, sized to the GPU: tools/chat + vision (Ollama names)."""
    if vram >= 14:
        tools = "gpt-oss:20b"
    elif vram >= 8:
        tools = "qwen3:8b"
    else:
        tools = "qwen3:4b"
    vision = "qwen2.5vl:7b" if vram >= 8 else "qwen2.5vl:3b"
    why = (f"{vram:g} GB VRAM: " + ("gpt-oss:20b fits (about 13 GB)" if tools == "gpt-oss:20b" else
           f"gpt-oss:20b needs about 14 GB, so {tools} for tools") + f"; {vision} for vision")
    return {"tools": tools, "vision": vision, "why": why, "recommended": {"tools": "gpt-oss:20b", "vision": "qwen2.5vl:7b"}}


def s_machine(p):
    st = "machine"
    say(st, "Looking at this PC…")
    win = {"system": platform.system(), "release": platform.release(), "version": platform.version(), "arch": platform.machine()}
    build = int((platform.version().split(".") + ["0", "0", "0"])[2] or 0) if WIN else 0
    prog(st, 20)
    gpu = _gpu()
    prog(st, 45)
    disk = shutil.disk_usage(inst() if inst().exists() else PKG)
    free = round(disk.free / 2**30, 1)
    ram = _ram_gb()
    prog(st, 65)
    say(st, "Checking the network (GitHub, libretro, Ollama)…")
    net = {u: _head(u) is not None or _probe(u, 6) for u in ("https://github.com", "https://buildbot.libretro.com", "https://ollama.com")}
    online = any(net.values())
    warn = []
    if WIN and build and build < 17763:
        warn.append("Windows 10 1809 or newer is needed (this is build %d)" % build)
    if not gpu:
        warn.append("no GPU found: emulators and the local LLM will be slow")
    if free < 20:
        warn.append(f"only {free} GB free on this drive: emulators + models want about 20 GB")
    if not online:
        warn.append("no network: the offline path uses files you already have")
        STATE["offline"] = True
    S(st)["data"] = {"windows": win, "build": build, "gpu": gpu, "ram_gb": ram, "cpu": os.cpu_count(), "free_gb": free,
                     "network": net, "online": online, "warnings": warn, "models": recommend_models(gpu.get("vram_gb") or 0)}
    say(st, f"{win['system']} {win['release']} (build {build or win['version']}), {os.cpu_count()} threads, {ram} GB RAM")
    say(st, f"GPU: {gpu.get('name', 'none')} {gpu.get('vram_gb', '')} GB VRAM" + (f", driver {gpu['driver']}" if gpu.get("driver") else ""))
    say(st, f"Disk: {free} GB free · network: {'online' if online else 'OFFLINE'}")
    for w in warn:
        say(st, "! " + w)


# ---- step 2: install folder

def s_folder(p):
    st = "folder"
    target = Path(os.path.expandvars(p.get("path") or STATE.get("install_dir") or str(PKG))).resolve()
    say(st, f"Install folder: {target}")
    target.mkdir(parents=True, exist_ok=True)
    probe = target / ".gbox-write-test"
    probe.write_text("ok")
    probe.unlink()
    free = round(shutil.disk_usage(target).free / 2**30, 1)
    if target != PKG.resolve():
        if (target / "system" / "gbox").exists() and not p.get("overwrite"):
            say(st, "gBox is already there: keeping it (redo with 'replace the code' to copy this package over it)")
        else:
            say(st, f"Copying gBox from {PKG} …")
            skip = shutil.ignore_patterns("__pycache__", "gbox-data", "*.pyc", "wizard-state.json", "uv-cache", "downloads", ".venv")
            for name in ("system", "Install gBox.cmd", "Start gBox.cmd", "README-FIRST.txt", "MANIFEST.md", "MANIFEST.json", "wheels", ".tools"):
                src = PKG / name
                if src.is_dir():
                    shutil.copytree(src, target / name, dirs_exist_ok=True, ignore=skip)
                elif src.is_file():
                    shutil.copy2(src, target / name)
            say(st, "Copied (the unzipped folder can be deleted once setup is done).")
    STATE["install_dir"] = str(target)
    S(st)["data"] = {"path": str(target), "free_gb": free, "package": str(PKG)}
    say(st, f"{free} GB free there")


# ---- step 3: Python runtime + gBox

def s_runtime(p):
    st = "runtime"
    import tomllib
    vpy, uv = venv_py(), _uv()
    wheels = next((d for d in (inst() / "wheels", PKG / "wheels") if d.is_dir()), None)
    offline = not _net()
    base = Path(getattr(sys, "_base_executable", None) or sys.executable)   # a venv's base interpreter, not the venv
    try:                                                     # the wizard's own Python lives in the package: use the copy
        rel = base.resolve().relative_to(PKG.resolve())      # that step 2 put into the install folder
        if (inst() / rel).exists():
            base = inst() / rel
    except ValueError:
        pass
    if not vpy.exists() or p.get("rebuild"):
        say(st, f"Creating the Python environment in {inst() / '.venv'} (Python {platform.python_version()})")
        rc = _stream(st, [uv, "venv", "--allow-existing", str(inst() / ".venv"), "--python", str(base)] if uv
                     else [str(base), "-m", "venv", str(inst() / ".venv")], cwd=inst())
        if rc:
            raise RuntimeError("could not create the virtual environment")
    prog(st, 25)
    deps = tomllib.loads((sysdir() / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    say(st, f"Installing gBox's packages: {', '.join(d.split('>')[0] for d in deps)}" + (" (offline: wheels folder only)" if offline else ""))
    if uv:
        cmd = [uv, "pip", "install", "--python", str(vpy), *deps] + (["--offline"] if offline else []) + (["--find-links", str(wheels)] if wheels else [])
    else:
        cmd = [str(vpy), "-m", "pip", "install", "--disable-pip-version-check", *deps] + (["--no-index"] if offline else []) + \
              (["--find-links", str(wheels)] if wheels else [])
    if _stream(st, cmd, cwd=inst()):
        raise RuntimeError("package install failed" + (": offline installs need the packages as wheels in a 'wheels' folder "
                                                       "next to Install gBox.cmd" if offline else ""))
    prog(st, 80)
    say(st, "Checking that gBox imports…")
    if _stream(st, [vpy, "-P", "-c", "import fastapi, uvicorn, pydantic, httpx, numpy, PIL, capstone; import gbox.server, gbox.worker; "
                    "print('gBox imports ok')"], cwd=sysdir()):
        raise RuntimeError("gBox does not import in the new environment (see above)")
    ov = STATE["overlay"]
    ov["api_port"] = STATE["api_port"]
    ov["runtime_dirs"] = {OS_: str(inst() / "runtime").replace("\\", "/")}
    ov["cache_dirs"] = {OS_: str(inst() / "cache").replace("\\", "/")}
    write_overlay()
    S(st)["data"] = {"venv": str(inst() / ".venv"), "python": platform.python_version(), "uv": bool(uv), "overlay": str(overlay_file())}
    say(st, f"Settings for this PC: {overlay_file().name} (control plane on 127.0.0.1:{STATE['api_port']})")


def _need_venv():
    if not venv_py().exists():
        raise RuntimeError("install the Python runtime first (step 3)")


# ---- step 4: ROM folders -> scan + match the recipes' games

def s_roms(p):
    st = "roms"
    _need_venv()
    folders = [f.strip() for f in (p.get("folders") if p.get("folders") is not None else STATE["roms"]) if f and f.strip()]
    if not folders:
        raise RuntimeError("add at least one ROM folder (the folders with your own game files)")
    bad = [f for f in folders if not Path(f).is_dir()]
    if bad:
        raise RuntimeError("not a folder: " + ", ".join(bad))
    STATE["roms"] = folders
    attract = lambda f: (Path(f) / "emulators").is_dir() and ((Path(f) / "romlists").is_dir() or (Path(f) / "collections").is_dir())
    STATE["overlay"]["libraries"] = [{"id": f"roms{i + 1}" if i else "roms", "kind": "attract" if attract(f) else "files",
                                      "paths": {OS_: f.replace("\\", "/")}} for i, f in enumerate(folders)]   # HyperSpin / Attract-Mode trees too
    write_overlay()
    say(st, f"Scanning {len(folders)} folder(s) and matching the mod recipes' games…")
    rc, res = _py(st, ["-m", "gbox.decant", "match", "--config", cfg_file()])
    if rc:
        raise RuntimeError("the scan failed (see above)")
    S(st)["data"] = res
    say(st, f"{res.get('scanned', 0)} games found; {res.get('games_owned', 0)} of the {res.get('games_needed', 0)} games the recipes need")
    for o in res.get("owned", [])[:40]:
        say(st, f"  ✓ {o.get('recipe_title')}  ←  {o.get('title')} ({o.get('how')})")


# ---- steps 5 + 6: emulators / toolkits (official downloads, one consent each, or files you have)

def _need(step: str) -> dict:
    rc, res = _py(step, ["-m", "gbox.decant", "need", "--config", cfg_file()] + (["--offline"] if not _net() else []))
    if rc:
        raise RuntimeError("could not work out what this PC needs (see above)")
    return res


def s_components(step: str, group: str, p: dict):
    _need_venv()
    act = p.get("action") or "plan"
    if act in ("get", "use"):
        item = p["item"]
        args = ["-m", "gbox.decant", "fetch", item, "--config", cfg_file()]
        if act == "use":
            args += ["--from", p.get("path") or ""]
        elif not _net():
            raise RuntimeError("offline mode: use 'I have this file' and point at an archive or folder you already have")

        def onj(o):
            if "progress" in o and isinstance(o["progress"], dict):
                if o["progress"].get("pct") is not None:
                    prog(step, o["progress"]["pct"])
                if o["progress"].get("msg"):
                    say(step, o["progress"]["msg"])
                return True
            return None
        rc, res = _py(step, args, on_json=onj)
        if rc or res.get("error"):
            raise RuntimeError(res.get("error") or f"{item}: failed (see above)")
        say(step, f"✓ {item}: {res.get('detail', 'ok')}")
        if res.get("overlay"):
            STATE["overlay"].update(res["overlay"])
            write_overlay()
    elif act == "bios":
        path = (p.get("path") or "").strip()
        if path and not Path(path).is_dir():
            raise RuntimeError(f"not a folder: {path}")
        STATE["overlay"]["retroarch_bios"] = {OS_: path.replace("\\", "/")} if path else {}
        write_overlay()
        say(step, f"BIOS folder: {path or '(none)'} (gBox copies what a core needs from there; it never downloads BIOS)")
    elif act == "blender":
        path = (p.get("path") or "").strip()
        if path and not Path(path).exists():
            raise RuntimeError(f"not found: {path}")
        STATE["overlay"]["blender_path" if path.lower().endswith(".exe") else "blender_search"] = path if path.lower().endswith(".exe") else [path]
        write_overlay()
        say(step, f"Blender: {path}")
    res = _need(step)
    items = [i for i in res.get("items", []) if i["group"] == group]
    S(step)["data"] = {"items": items, "bios": res.get("bios", []) if group == "emulators" else [], "offline": not _net()}
    missing = [i for i in items if not i["have"] and not i.get("optional")]
    say(step, f"{len(items) - len(missing)} of {len(items)} ready" + (f"; missing: {', '.join(i['name'] for i in missing)}" if missing else ""))
    if missing:                                              # still waiting on a download or a file you have
        S(step)["status_after"] = "waiting"


# ---- step 7: local LLM (Ollama)

OLLAMA = "http://127.0.0.1:11434"


def _ollama_exe() -> str | None:
    for c in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe", Path("C:/Program Files/Ollama/ollama.exe")):
        if c.exists():
            return str(c)
    return shutil.which("ollama")


def _ollama_models() -> list[dict] | None:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=4) as r:
            return json.loads(r.read()).get("models", [])
    except Exception:
        return None


def llm_data() -> dict:
    """What the llm step shows: Ollama state, every model installed on this PC, and whether the configured
    tools/vision models are among them. Refreshed live by the 'scan' action, so a model the operator just
    installed is detected (and becomes selectable in the wizard) without re-running the step."""
    vram = (S("machine")["data"].get("gpu") or {}).get("vram_gb") or 0
    rec = recommend_models(vram)
    models = _ollama_models()
    have = [m["name"] for m in models or []]
    agent = STATE["overlay"].get("agent") or {}
    want = [agent.get("model") or rec["tools"], agent.get("vision_model") or rec["vision"]]
    ready = models is not None and all(any(h == w or h == w + ":latest" for h in have) for w in want)
    return {"installed": bool(_ollama_exe()), "running": models is not None, "models": have, "recommend": rec,
            "chosen": agent, "want": want, "ready": ready, "vram_gb": vram,
            "sizes": {"gpt-oss:20b": "13 GB", "qwen3:8b": "5.2 GB", "qwen3:4b": "2.6 GB", "qwen2.5vl:7b": "6.0 GB",
                      "qwen2.5vl:3b": "3.2 GB"}}


def s_llm(p):
    st = "llm"
    act = p.get("action") or "plan"
    vram = (S("machine")["data"].get("gpu") or {}).get("vram_gb") or 0
    rec = recommend_models(vram)
    if act == "install":
        src = (p.get("path") or "").strip()
        if not src:
            src = str(_download(st, "https://ollama.com/download/OllamaSetup.exe", inst() / ".tools" / "downloads" / "OllamaSetup.exe"))
        say(st, "Running the Ollama installer (silent)…")
        if _stream(st, [src, "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], cwd=inst()):
            raise RuntimeError("the Ollama installer failed")
    if act in ("install", "start") or (act == "plan" and _ollama_models() is None and _ollama_exe()):
        exe = _ollama_exe()
        if exe and _ollama_models() is None:
            say(st, "Starting Ollama…")
            subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=(0x00000008 | 0x00000200 | NO_WINDOW) if WIN else 0)
            for _ in range(30):
                time.sleep(1)
                if _ollama_models() is not None:
                    break
    if act == "pull":
        name = p["model"]
        if not _net():
            raise RuntimeError("offline: copy the model folder (%USERPROFILE%\\.ollama\\models) from a PC that has it")
        say(st, f"Pulling {name} from the Ollama library…")
        req = urllib.request.Request(OLLAMA + "/api/pull", data=json.dumps({"model": name, "stream": True}).encode(),
                                     headers={"content-type": "application/json"})
        last = ""
        with urllib.request.urlopen(req, timeout=3600) as r:
            for line in r:
                o = json.loads(line or b"{}")
                if o.get("error"):
                    raise RuntimeError(o["error"])
                if o.get("total"):
                    prog(st, 100 * (o.get("completed") or 0) / o["total"])
                    S(st)["data"]["dl"] = {"url": name, "got": o.get("completed") or 0, "total": o["total"]}
                if o.get("status") and o["status"] != last:
                    last = o["status"]
                    say(st, f"{name}: {last}")
        S(st)["data"].pop("dl", None)
    if act == "use":
        STATE["overlay"]["agent"] = {"llm_url": OLLAMA + "/v1", "model": p.get("tools") or rec["tools"],
                                     "vision_model": p.get("vision") or rec["vision"], "searx_url": "http://127.0.0.1:8081",
                                     "tts_engine": "xtts", "voice_library": ""}
        write_overlay()
        say(st, f"gBox will use {STATE['overlay']['agent']['model']} (tools) and {STATE['overlay']['agent']['vision_model']} (vision)")
    S(st)["data"] = llm_data()
    d = S(st)["data"]
    say(st, ("Ollama is running" if d["running"] else "Ollama is installed but not running" if d["installed"] else
             "Ollama is not installed") + (f"; models here: {', '.join(d['models']) or 'none'}" if d["running"] else ""))
    if not d["ready"]:
        S(st)["status_after"] = "waiting"


# ---- step 8: rebuild mods from recipes (needs the control plane)

def _token() -> str:
    try:
        return (sysdir() / "gbox-data" / "api_token").read_text().strip()
    except OSError:
        return ""


def server_url() -> str:
    return f"http://127.0.0.1:{STATE['overlay'].get('api_port') or STATE['api_port']}"


def ensure_server(step: str) -> str:
    """This PC's control plane + local worker (gbox serve --worker), started detached if it isn't answering."""
    _need_venv()
    url = server_url()
    if not _probe(url + "/api/health"):
        logf = sysdir() / "gbox-data" / "serve.log"
        logf.parent.mkdir(parents=True, exist_ok=True)
        say(step, f"Starting gBox's control plane + worker on {url} (log: {logf})")
        p = subprocess.Popen([str(venv_py()), "-P", "-m", "gbox", "--config", str(cfg_file()), "serve", "--worker"], cwd=str(sysdir()),
                             env=_env(), stdout=open(logf, "ab"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=(0x00000200 | NO_WINDOW | BELOW) if WIN else 0, start_new_session=not WIN)
        STATE["server_pid"] = p.pid
        for _ in range(60):
            time.sleep(1)
            if _probe(url + "/api/health"):
                break
            if p.poll() is not None:
                raise RuntimeError(f"the control plane exited ({p.returncode}): see {logf}")
        else:
            raise RuntimeError(f"the control plane did not answer on {url}: see {logf}")
    for _ in range(40):                                      # its worker registers a moment later
        try:
            req = urllib.request.Request(url + "/api/workers", headers={"authorization": "Bearer " + _token()})
            if any(w.get("online") for w in json.loads(urllib.request.urlopen(req, timeout=5).read())):
                return url
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("the control plane runs but its worker never came online")


def s_mods(p):
    st = "mods"
    url = ensure_server(st)
    say(st, f"gBox is up on {url}: rebuilding from recipes (catalog, cheat DB, characters, swaps, mod cards)…")
    counts = {"n": 0}

    def onj(o):
        if "progress" in o:
            pr = o["progress"]
            msg = pr.get("msg") if isinstance(pr, dict) else pr
            if isinstance(pr, dict) and pr.get("pct") is not None:
                prog(st, pr["pct"])
            if msg:
                say(st, str(msg))
            return True
        for k in ("character", "swap"):
            if k in o:
                x = o[k]
                counts["n"] += 1
                say(st, f"{'✓' if x.get('status') in ('extracted', 'in_collection', 'built', 'ready') else '·'} {k}: "
                        f"{x.get('name') or x.get('character')} {('-> ' + x['game']) if x.get('game') else ''} = {x.get('status')}"
                        + (f" ({x['why']})" if x.get("why") else ""))
                return True
        if "step" in o:
            say(st, f"{o['step']}: {o['status']}" + (f" ({o['detail']})" if o.get("detail") else ""))
            return True
        return None
    args = ["-m", "gbox.decant", "rebuild", "--config", cfg_file(), "--server", url] + (["--only", p["only"]] if p.get("only") else [])
    rc, res = _py(st, args, on_json=onj)
    if rc:
        raise RuntimeError("the rebuild stopped (see above)")
    S(st)["data"] = res
    av = lambda xs, ok: sum(1 for x in xs if x.get("status") in ok)
    say(st, f"mod cards: {av(res.get('cards', []), ('added',))} added · characters: "
            f"{av(res.get('characters', []), ('extracted', 'in_collection'))} ready · swaps: {av(res.get('swaps', []), ('built', 'ready', 'built+launched'))} built")


# ---- step 9: start gBox

def _electron() -> Path | None:
    for c in (inst() / ".tools" / "electron" / "electron.exe", inst() / ".tools" / "electron" / "gBox.exe"):
        if c.exists():
            return c
    return None


def s_start(p):
    st = "start"
    act = p.get("action") or "plan"
    if act == "electron":
        src = (p.get("path") or "").strip()
        dest = inst() / ".tools" / "electron"
        if src and Path(src).is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            if not src:
                rel = json.loads(urllib.request.urlopen(urllib.request.Request(
                    "https://api.github.com/repos/electron/electron/releases?per_page=40", headers={"user-agent": "gbox-setup"}), timeout=30).read())
                tag = next(r["tag_name"] for r in rel if r["tag_name"].startswith("v38.") and not r.get("prerelease"))
                src = str(_download(st, f"https://github.com/electron/electron/releases/download/{tag}/electron-{tag}-win32-x64.zip",
                                    inst() / ".tools" / "downloads" / f"electron-{tag}-win32-x64.zip"))
            import zipfile
            say(st, f"Unpacking {Path(src).name}…")
            zipfile.ZipFile(src).extractall(dest)
        say(st, f"Desktop app runtime: {_electron()}")
    if act == "shortcut":
        target = inst() / "Start gBox.cmd"
        ps = ("$s=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'), "
              "(Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs'))){ $l=$s.CreateShortcut((Join-Path $d 'gBox.lnk')); "
              f"$l.TargetPath='{target}'; $l.WorkingDirectory='{inst()}'; $l.IconLocation='{sysdir() / 'assets' / 'brand' / 'gbox.ico'}'; "
              "$l.WindowStyle=7; $l.Save() }")
        _stream(st, ["powershell", "-NoProfile", "-Command", ps], cwd=inst())
        say(st, "Shortcuts: Desktop + Start menu (gBox)")
    if act == "browser":
        url = ensure_server(st)
        import webbrowser
        webbrowser.open(f"{url}/#token={_token()}")
        say(st, f"Opened {url} in the browser")
    if act == "app":
        exe = _electron()
        if not exe:
            raise RuntimeError("the desktop app runtime isn't installed yet (Get the desktop app), or use the browser")
        pid = STATE.pop("server_pid", None)                  # the app runs its own control plane in standalone mode
        if pid and _probe(server_url() + "/api/health"):
            say(st, f"Handing the control plane over to the desktop app (stopping pid {pid})")
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
            time.sleep(1.5)
        env = {k: v for k, v in _env().items() if k != "ELECTRON_RUN_AS_NODE"} | {
            "GBOX_STANDALONE_HOME": str(inst()), "GBOX_API_URL": server_url()}
        subprocess.Popen([str(exe), str(sysdir() / "clients" / "desktop")], cwd=str(exe.parent), env=env,
                         creationflags=0x00000008 | 0x00000200, close_fds=True)
        say(st, "gBox desktop app started")
    S(st)["data"] = {"electron": str(_electron() or ""), "url": server_url(), "running": _probe(server_url() + "/api/health"),
                     "install_dir": str(inst()), "start_cmd": str(inst() / "Start gBox.cmd")}
    if act == "plan":
        S(st)["status_after"] = "waiting"


RUNNERS = {"machine": s_machine, "folder": s_folder, "runtime": s_runtime, "roms": s_roms,
           "emulators": lambda p: s_components("emulators", "emulators", p), "toolkits": lambda p: s_components("toolkits", "toolkits", p),
           "llm": s_llm, "mods": s_mods, "start": s_start}


def run_step(step: str, params: dict):
    """Run (or redo) a step in the background; the UI polls /api/flow."""
    s = S(step)
    if s["status"] == "running":
        raise RuntimeError(f"{step} is already running")
    if params.get("action") == "skip":
        s.update(status="skipped", error="")
        _save()
        return
    s.update(status="running", error="", progress=0, t=time.time())
    s.pop("status_after", None)
    say(step, f"── {dict(STEPS)[step]} ──")

    def work():
        try:
            RUNNERS[step](params)
            s["status"] = s.pop("status_after", None) or "ok"
            s["progress"] = 100 if s["status"] == "ok" else s["progress"]
        except Exception as e:                               # noqa: BLE001 - every failure is shown with a retry
            s.update(status="failed", error=f"{e}")
            say(step, f"✗ {type(e).__name__}: {e}")
        finally:
            _save()
    threading.Thread(target=work, daemon=True).start()


def flow() -> dict:
    return {"steps": [{"id": sid, "title": t, **{k: v for k, v in S(sid).items() if k != "lines"}, "lines": S(sid)["lines"][-200:]}
                      for sid, t in STEPS],
            "install_dir": str(inst()), "package": str(PKG), "host": platform.node(), "os": OS_, "offline": STATE.get("offline"),
            "api_port": STATE["overlay"].get("api_port") or STATE["api_port"], "roms": STATE["roms"], "decanted": (ROOT / "decant").is_dir(),
            "manifest": (PKG / "MANIFEST.json").exists()}


def pick_folder(title: str = "Choose a folder", initial: str = "") -> str:
    """The native folder picker (the wizard runs on this PC)."""
    if not WIN:
        raise RuntimeError("type the folder path (the native picker is Windows-only)")
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.FolderBrowserDialog; "
          f"$f.Description = '{title.replace(chr(39), '')}'; $f.ShowNewFolderButton = $true; "
          + (f"$f.SelectedPath = '{initial.replace(chr(39), '')}'; " if initial else "")
          + "$w = New-Object System.Windows.Forms.Form -Property @{TopMost=$true}; "
          "if ($f.ShowDialog($w) -eq 'OK') { $f.SelectedPath }")
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True, timeout=600)
    return r.stdout.strip()


# ================================================================ HTTP

STATIC = {"/viz/": ROOT / "clients" / "web" / "viz", "/brand/": ROOT / "assets" / "brand"}
MIME = {".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        ".html": "text/html; charset=utf-8", ".css": "text/css", ".md": "text/markdown; charset=utf-8"}


class H(BaseHTTPRequestHandler):
    cfg_path: Path = ROOT / "gbox.toml"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _file(self, f: Path):
        b = f.read_bytes()
        self.send_response(200)
        self.send_header("content-type", MIME.get(f.suffix.lower(), "application/octet-stream"))
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urllib.parse.unquote(self.path.split("?")[0])
        try:
            if p == "/":
                return self._file(UI)
            if p == "/viz/vendor/three.module.js" and not (STATIC["/viz/"] / "vendor" / "three.module.js").exists():
                self.send_response(302)                              # not bundled: the visualizer's CDN copy
                self.send_header("location", "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js")
                self.end_headers()
                return
            for pre, base in STATIC.items():
                if p.startswith(pre):
                    f = (base / p[len(pre):]).resolve()
                    if f.is_relative_to(base.resolve()) and f.is_file():
                        return self._file(f)
                    return self._json({"error": "not found"}, 404)
            if p == "/manifest":
                for f in (PKG / "MANIFEST.md", inst() / "MANIFEST.md"):
                    if f.exists():
                        return self._file(f)
                return self._json({"error": "no manifest in this package"}, 404)
            if p == "/api/flow":
                return self._json(flow())
            if p == "/api/scan":
                return self._json(scan(self.cfg_path))
            if p == "/api/settings":
                return self._json(settings(self.cfg_path))
            if p == "/api/doctor":
                return self._json(doctor(self.cfg_path))
            if p == "/api/log":
                return self._json({"log": LOG[-300:], "tasks": TASKS})
            self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            if p.startswith("/api/flow/"):
                step = p.rsplit("/", 1)[-1]
                if step not in RUNNERS:
                    return self._json({"error": f"no step {step}"}, 404)
                if step == "llm" and body.get("action") == "scan":
                    # Light model refresh: the UI polls this while the llm step is open so a model the operator
                    # just installed is detected (and becomes selectable) without re-running the step.
                    if S("llm")["status"] != "running":
                        S("llm")["data"] = llm_data()
                        _save()
                    return self._json(flow())
                run_step(step, body)
                return self._json({"started": step})
            if p == "/api/offline":
                STATE["offline"] = bool(body.get("offline"))
                _save()
                return self._json({"offline": STATE["offline"]})
            if p == "/api/pick-folder":
                return self._json({"path": pick_folder(body.get("title") or "Choose a folder", body.get("initial") or "")})
            if p == "/api/settings":
                return self._json({"saved": str(apply_settings(self.cfg_path, body))})
            if p == "/api/install":
                install(body["id"], self.cfg_path)
                return self._json({"started": body["id"]})
            self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def serve(config_path: Path, port: int = 8770, open_browser: bool = True, api_port: int | None = None):
    H.cfg_path = Path(config_path).resolve()
    _load_state(api_port)
    _save()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)          # local only: the wizard can install software
    url = f"http://127.0.0.1:{port}/"
    log(f"wizard on {url} (config {H.cfg_path}, install folder {inst()})")
    print(f"gBox setup wizard: {url}", flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


def _selftest():
    assert _toml({"a": 1, "b": "x"}) == '{ a = 1, b = "x" }' and _toml([True, 2]) == "[true, 2]"
    assert _toml('C:\\path "q"') == '"C:\\\\path \\"q\\""'
    import tomllib
    assert tomllib.loads("v = " + _toml('C:\\path "q"'))["v"] == 'C:\\path "q"'
    assert recommend_models(24)["tools"] == "gpt-oss:20b" and recommend_models(8)["tools"] == "qwen3:8b"
    assert recommend_models(0)["vision"] == "qwen2.5vl:3b"
    print("wizard selftest ok")


def main(argv=None):
    """python -m gbox.wizard: the guided installer (stdlib only, so it runs before gBox's packages are installed)."""
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.wizard")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--api-port", type=int, default=None, help="the control plane port this install will use (default 8765)")
    ap.add_argument("--config", default=str(ROOT / "gbox.toml"))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    serve(Path(a.config), a.port, not a.no_browser, a.api_port)


if __name__ == "__main__":
    main()
