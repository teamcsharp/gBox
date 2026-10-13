"""decomp.me / IDA Pro / N64Recomp integrations: three op-based native gBox tools.

- `decompme`: REST client for the decomp.me API. Read ops (scratch fetch, search,
  compiler list) work with or without a token; the API serves empty bodies for
  token-gated routes, and mutations (create/claim/update/fork/compile) require a
  GitHub OAuth token via config `decompme_token` or the DECOMPME_TOKEN env var.
  Every mutation publishes source publicly, so the tool declares it as a side effect.
- `ida_pro`: locate the operator's IDA Pro, run headless auto-analysis exports
  (functions/strings, same shape as analyze_binary), and start/stop the
  ida-pro-mcp plugin (mrexodia/ida-pro-mcp) so REA's IDA provider can drive the
  same database through `rea_env.REA_IDA_MCP_CONFIG`.
- `n64recomp`: toolchain detection, a pinned shallow source build of
  Mr-Wiseguy/N64Recomp into this node's runtime, and ROM -> Rust mod project
  generation through the upstream recompiler. The RT64 frontend stays a manual
  step on Windows (VS + Vulkan SDK); the backend crate builds anywhere cargo works.

None of these tools touch the live game library or an operator PC unless a job is
explicitly dispatched there. All state lives under cfg.runtime and the job artifacts.
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

from .config import HOST_OS
from .models import Permission as P
from .registry import ToolUnavailable, tool

ROOT = Path(__file__).resolve().parent.parent

N64RECOMP_REPO = "https://github.com/Mr-Wiseguy/N64Recomp"
IDA_MCP_PORT = 13337

# Headless function/string census for `ida_pro analyze`, run by IDA as
#   idat64 -A -B -S"gbox_export.idc <out.json>" <binary>
# Same JSON shape as adapters/ghidra/ExportAnalysis.java so downstream gBox
# consumers treat both headless analyzers interchangeably.
IDA_EXPORT_IDC = r'''#include <idc.idc>

static esc(s) {
    auto out, i, c;
    out = "";
    for (i = 0; i < strlen(s); i = i + 1) {
        c = substr(s, i, i + 1);
        if (c == "\"") out = out + "\\\"";
        else if (c == "\\") out = out + "\\\\";
        else if (c == "\n") out = out + "\\n";
        else if (c == "\r") out = out + "\\r";
        else if (c == "\t") out = out + "\\t";
        else out = out + c;
    }
    return out;
}

static main() {
    auto out, f, ea, end, name, seg, seg_end, istr;
    out = fopen(ARGV[1], "wb");
    if (out == 0) {
        warning("gbox_export: cannot open output file");
        return;
    }
    fputs("{\"functions\":[", out);
    f = 0;
    ea = get_next_func(0);
    while (ea != BADADDR) {
        name = get_func_name(ea);
        end = get_func_attr(ea, FUNCATTR_END);
        if (f == 1) fputs(",", out);
        fputs("{\"name\":\"", out);
        fputs(esc(name), out);
        fputs("\",\"start\":", out);
        fputs(ltoa(ea, 10), out);
        fputs(",\"end\":", out);
        fputs(ltoa(end, 10), out);
        fputs("}", out);
        f = 1;
        ea = get_next_func(ea);
    }
    fputs("],\"strings\":[", out);
    f = 0;
    seg = get_first_seg();
    while (seg != BADADDR) {
        ea = get_seg_start(seg);
        seg_end = get_seg_end(seg);
        while (ea != BADADDR && ea < seg_end) {
            if (GetStringType(ea) >= 0) {
                istr = GetString(ea, -1, ASCSTR_C);
                if (strlen(istr) > 0) {
                    if (f == 1) fputs(",", out);
                    fputs("{\"addr\":", out);
                    fputs(ltoa(ea, 10), out);
                    fputs(",\"value\":\"", out);
                    fputs(esc(istr), out);
                    fputs("\"}", out);
                    f = 1;
                }
            }
            ea = next_head(ea, seg_end);
        }
        seg = get_next_seg(seg);
    }
    fputs("],\"program\":{\"name\":\"", out);
    fputs(esc(get_root_filename()), out);
    fputs("\",\"processor\":\"", out);
    fputs(esc(inf_get_procname()), out);
    fputs("\",\"min_ea\":", out);
    fputs(ltoa(get_min_ea(), 10), out);
    fputs(",\"max_ea\":", out);
    fputs(ltoa(get_max_ea(), 10), out);
    fputs("}}", out);
    fclose(out);
}
'''


# --- decomp.me ------------------------------------------------------------------------------

def _decompme_token(cfg) -> str | None:
    return os.environ.get("DECOMPME_TOKEN") or getattr(cfg, "decompme_token", None)


def _dm_request(ctx, method: str, path: str, params: dict | None = None,
                body: dict | None = None, token: str | None = None):
    """One decomp.me API round-trip with honest token-gating errors."""
    base = getattr(ctx.config, "decompme_base_url", "https://api.decomp.dev").rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    headers = {"accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    try:
        response = httpx.request(method, url, params=params, json=body, headers=headers, timeout=120)
    except httpx.HTTPError as exc:
        raise ToolUnavailable(f"decomp.me unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"decomp.me {method} {path} -> HTTP {response.status_code}: {(response.text or '')[:400]}")
    if not (response.content or b"").strip():
        if not token:
            raise RuntimeError(
                "decomp.me returned an empty response; this endpoint requires a token. "
                "Set decompme_token in gbox.toml (local overlay) or the DECOMPME_TOKEN env var.")
        raise RuntimeError(f"decomp.me returned an empty response for {method} {path}")
    try:
        return json.loads(response.content)
    except ValueError:
        return {"_raw": response.text[:4000], "status": response.status_code}


class DecompMeIn(BaseModel):
    op: str  # scratch | search | compilers | create | claim | update | fork | compile
    slug: str = ""
    params: dict = {}
    payload: dict = {}


class DecompMeOut(BaseModel):
    op: str
    status: str
    data: dict
    token_used: bool


@tool("decompme", "1.0", DecompMeIn, DecompMeOut, capabilities=["reverse-engineering", "decompilation", "network"],
      platforms=["windows", "linux", "darwin"], permissions=[P.READ, P.EXECUTE, P.NETWORK],
      side_effects=["create/claim/update/fork/compile publish decompiled source publicly on decomp.me"],
      timeout_s=600)
def decompme(inp: DecompMeIn, ctx):
    """decomp.me API: fetch/search scratches, list compilers; create/claim/update/fork/compile a scratch with a token.

    Read ops: op=scratch (GET /scratch/{slug}), op=search (GET /scratch with params
    like platform=n64, preset=zelda64, compiler=ido-7.1), op=compilers.
    Write ops (token required, source becomes public): create (payload: platform,
    compiler, name, target_func, source_code, context), claim, update (PATCH payload),
    fork, compile (payload: compiler, compiler_flags, source_code, context).
    """
    token = _decompme_token(ctx.config)
    op = inp.op.lower()
    mutating = op in ("create", "claim", "update", "fork", "compile")
    if mutating and not token:
        raise RuntimeError(
            f"decomp.me op {op} publishes code publicly and needs a token: set decompme_token or DECOMPME_TOKEN.")
    ctx.progress(5, f"decomp.me {op} {'with token' if token else 'anonymous'}")
    if op == "scratch":
        data = _dm_request(ctx, "GET", f"scratch/{inp.slug}", token=token)
    elif op == "search":
        data = _dm_request(ctx, "GET", "scratch", params=inp.params or None, token=token)
    elif op == "compilers":
        data = _dm_request(ctx, "GET", "compilers", token=token)
    elif op == "create":
        data = _dm_request(ctx, "POST", "scratch", body=inp.payload, token=token)
    elif op in ("claim", "fork", "compile"):
        data = _dm_request(ctx, "POST", f"scratch/{inp.slug}/{op}", body=inp.payload, token=token)
    elif op == "update":
        data = _dm_request(ctx, "PATCH", f"scratch/{inp.slug}", body=inp.payload, token=token)
    else:
        raise ValueError(f"unknown op {inp.op!r}; use scratch, search, compilers, create, claim, update, fork, compile")
    ctx.progress(100, "decomp.me answered")
    return {"op": op, "status": "ok", "data": data, "token_used": bool(token)}


# --- IDA Pro --------------------------------------------------------------------------------

def _ida_search_roots(cfg) -> list[Path]:
    roots = []
    if getattr(cfg, "ida_home", None):
        roots.append(Path(cfg.ida_home))
    if HOST_OS == "windows":
        for base in ("C:/Program Files", "C:/Program Files (x86)"):
            if Path(base).exists():
                roots.append(Path(base))
    else:
        roots.append(Path.home())
        roots.append(Path("/opt"))
    roots.append(cfg.runtime)
    return roots


def _ida_home(cfg) -> Path | None:
    if getattr(cfg, "ida_home", None) and Path(cfg.ida_home).is_dir():
        return Path(cfg.ida_home)
    names = ("ida64.exe", "idat64.exe", "ida.exe", "idat.exe") if HOST_OS == "windows" else ("ida64", "idat64", "ida", "idat")
    for root in _ida_search_roots(cfg):
        # two levels deep covers C:/Program Files/IDA Professional 9.1/ida64.exe and /opt/ida-9.1/ida64
        for depth in (0, 1, 2):
            pattern = "/".join(["*"] * depth + ["IDA*"]) if depth else "IDA*"
            for d in root.glob(pattern) if depth else root.glob("IDA*"):
                if d.is_dir():
                    for n in names:
                        if (d / n).is_file():
                            return d
    # runtime copy: runtime/ida/ida64
    for n in names:
        p = cfg.runtime / "ida" / n
        if p.is_file():
            return p.parent
    return None


def _ida_binary(cfg, prefer_headless: bool = False) -> Path:
    home = _ida_home(cfg)
    if not home:
        raise ToolUnavailable(
            "IDA Pro not found on this node; set ida_home in gbox.toml or install IDA into the runtime dir")
    order = (("idat64.exe", "idat.exe", "ida64.exe", "ida.exe") if HOST_OS == "windows"
             else ("idat64", "idat", "ida64", "ida"))
    if not prefer_headless:
        order = (("ida64.exe", "ida.exe", "idat64.exe", "idat.exe") if HOST_OS == "windows"
                 else ("ida64", "ida", "idat64", "idat"))
    for name in order:
        p = home / name
        if p.is_file():
            return p
    raise ToolUnavailable(f"no IDA executable in {home}")


def _ida_user_dir() -> Path:
    """IDA user directory holding ida_mcp/config.toml (mrexodia/ida-pro-mcp convention)."""
    if HOST_OS == "windows" and os.environ.get("APPDATA"):
        d = Path(os.environ["APPDATA"]) / "Hex-Rays" / "IDA Pro"
    else:
        d = Path.home() / ".idapro"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_mcp_config(user_dir: Path, port: int) -> Path:
    d = user_dir / "ida_mcp"
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / "config.toml"
    cfg.write_text(
        f"[ida_mcp]\nhost = \"127.0.0.1\"\nport = {port}\ncheck_port = false\napi_key = \"\"\n", encoding="utf-8")
    return cfg


def _port_open(port: int, timeout_s: float) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _analyze_command(binary: Path, binary_path: str, out: Path, idc: Path) -> list[str]:
    return [str(binary), "-A", "-B", f'-S"{idc} {out}"', binary_path]


class IdaIn(BaseModel):
    op: str  # locate | analyze | mcp_start | mcp_status | mcp_stop
    binary_path: str = ""
    port: int = IDA_MCP_PORT
    wait_s: float = 60.0


class IdaOut(BaseModel):
    op: str
    result: dict


@tool("ida_pro", "1.0", IdaIn, IdaOut, capabilities=["reverse-engineering", "analysis", "ida"],
      platforms=["windows", "linux"], permissions=[P.READ, P.EXECUTE, P.FILE_MUTATION],
      side_effects=["launches/stops IDA Pro on this node", "writes ida_mcp/config.toml in the IDA user dir"],
      artifacts=["analysis.json"], timeout_s=3600)
def ida_pro(inp: IdaIn, ctx):
    """IDA Pro on this node: locate the install, run headless auto-analysis, and manage the ida-pro-mcp server for REA.

    op=locate: report ida_home, executable and user dir. op=analyze: headless
    auto-analysis of binary_path exporting functions/strings as analysis.json
    (same shape as analyze_binary). op=mcp_start: ensure ida_mcp/config.toml is
    configured, launch IDA on binary_path and wait for the MCP port; the returned
    rea_env_hint plugs into config.rea_env so the REA bridge can drive this
    database. op=mcp_status: probe the port and report the PID file.
    op=mcp_stop: terminate the IDA process gBox started (PID file in runtime).
    """
    op = inp.op.lower()
    if op == "locate":
        home = _ida_home(ctx.config)
        return {"op": op, "result": {"ida_home": str(home) if home else None,
                                     "binary": str(_ida_binary(ctx.config)) if home else None,
                                     "user_dir": str(_ida_user_dir())}}
    if op == "analyze":
        binary = _ida_binary(ctx.config, prefer_headless=True)
        work = Path(tempfile.mkdtemp())
        idc = work / "gbox_export.idc"
        idc.write_text(IDA_EXPORT_IDC, encoding="utf-8")
        out = work / "analysis.json"
        cmd = _analyze_command(binary, inp.binary_path, out, idc)
        ctx.progress(5, f"IDA analyzing {inp.binary_path}")
        r = subprocess.run(cmd, timeout=3500, capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode or not out.is_file():
            raise RuntimeError(f"IDA analysis failed ({r.returncode}): {(r.stdout + r.stderr)[-1500:]}")
        data = out.read_bytes()
        analysis = json.loads(data)
        ctx.artifact("analysis.json", data, "application/json", binary=inp.binary_path, tool="ida")
        return {"op": op, "result": {"functions": len(analysis["functions"]),
                                     "strings": len(analysis["strings"]), "program": analysis["program"]}}
    if op == "mcp_start":
        binary = _ida_binary(ctx.config)  # GUI-capable executable hosts the plugin server
        port = inp.port or IDA_MCP_PORT
        pidfile = ctx.config.runtime / "ida_mcp.pid"
        if _port_open(port, 0.5):
            return {"op": op, "result": {"pid": None, "port": port,
                                         "note": "ida-pro-mcp already listening; reuse it",
                                         "rea_env_hint": _rea_hint(port)}}
        config_file = _write_mcp_config(_ida_user_dir(), port)
        args = [str(binary), "-c"]
        if inp.binary_path:
            args.append(inp.binary_path)
        env = os.environ.copy()
        env["IDA_MCP_PORT"] = str(port)
        proc = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "DETACHED_PROCESS",
                                                      getattr(subprocess, "CREATE_NO_WINDOW", 0)) or 0)
        deadline = time.monotonic() + max(5.0, inp.wait_s)
        while time.monotonic() < deadline:
            if _port_open(port, 0.5):
                ctx.config.runtime.mkdir(parents=True, exist_ok=True)
                pidfile.write_text(str(proc.pid), encoding="utf-8")
                ctx.progress(100, f"ida-pro-mcp listening on {port}")
                return {"op": op, "result": {"pid": proc.pid, "port": port,
                                             "config": str(config_file), "rea_env_hint": _rea_hint(port)}}
            if proc.poll() is not None:
                raise RuntimeError(f"IDA exited early with code {proc.returncode}; is ida-pro-mcp installed?")
            time.sleep(1.0)
        raise TimeoutError(f"ida-pro-mcp did not open port {port} within {inp.wait_s}s; install the plugin and retry")
    if op == "mcp_status":
        pidfile = ctx.config.runtime / "ida_mcp.pid"
        return {"op": op, "result": {"listening": _port_open(inp.port, 0.5), "port": inp.port,
                                     "pid": pidfile.read_text().strip() if pidfile.is_file() else None,
                                     "config": str(_ida_user_dir() / "ida_mcp" / "config.toml")}}
    if op == "mcp_stop":
        pidfile = ctx.config.runtime / "ida_mcp.pid"
        pid = pidfile.read_text().strip() if pidfile.is_file() else None
        if pid and pid.isdigit():
            subprocess.run(["taskkill", "/PID", pid, "/F"] if HOST_OS == "windows" else ["kill", pid],
                           capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            pidfile.unlink(missing_ok=True)
        return {"op": op, "result": {"stopped": pid}}
    raise ValueError("unknown op; use locate, analyze, mcp_start, mcp_status, mcp_stop")


def _rea_hint(port: int) -> dict:
    """Best-effort REA provider config for this IDA MCP server (streamable HTTP)."""
    return {"REA_IDA_MCP_CONFIG": json.dumps({"type": "http", "url": f"http://127.0.0.1:{port}/mcp"})}


# --- N64Recomp ------------------------------------------------------------------------------

def _toolchain() -> dict:
    out = {}
    for name in ("git", "cargo", "cmake"):
        out[name] = shutil.which(name)
    out["vulkan_sdk"] = os.environ.get("VULKAN_SDK") or None
    if HOST_OS == "windows":
        out["msvc"] = bool(shutil.which("cl") or os.environ.get("VSINSTALLDIR") or shutil.which("cmake")
                           and os.environ.get("VCToolsInstallDir"))
    return out


def _repo(cfg) -> Path:
    return cfg.runtime / "n64recomp" / "N64Recomp"


def _repo_ready(cfg) -> bool:
    return (_repo(cfg) / "Cargo.toml").is_file()


def _generate_command(repo: Path, rom: str, config_toml: Path) -> list[str]:
    cargo = shutil.which("cargo") or "cargo"
    return [cargo, "run", "--release", "--manifest-path", str(repo / "Cargo.toml"),
            "--", "--rom", rom, "--config", str(config_toml)]


class N64RecompIn(BaseModel):
    op: str  # toolchain | provision | generate | status
    rom: str = ""                # generate: owned ROM path (.z64/.v64/.n64)
    name: str = "gbox-recomp"    # generate: mod project name
    project_dir: str = ""        # generate: output dir (default: runtime/n64recomp/mods/<name>)


class N64RecompOut(BaseModel):
    op: str
    result: dict


@tool("n64recomp", "1.0", N64RecompIn, N64RecompOut, capabilities=["reverse-engineering", "recompilation", "n64", "build"],
      platforms=["windows", "linux"], permissions=[P.READ, P.EXECUTE, P.INSTALL, P.NETWORK, P.FILE_MUTATION],
      side_effects=["clones and builds the N64Recomp source tree into this node's runtime",
                    "generates a Rust mod project from a ROM on this node"],
      artifacts=["n64recomp.json"], timeout_s=3600)
def n64recomp(inp: N64RecompIn, ctx):
    """N64Recomp (Mr-Wiseguy) source build and ROM -> Rust mod project generation on this node.

    op=toolchain: report git/cargo/cmake/Vulkan/MSVC availability.
    op=provision: shallow-clone N64Recomp into runtime/n64recomp and cargo build --release
    the backend; the RT64 frontend stays a manual step (VS + Vulkan SDK on Windows).
    op=generate: run the upstream recompiler on an owned ROM to emit a Rust mod project.
    op=status: read this node's build/generate receipts.
    """
    op = inp.op.lower()
    if op == "toolchain":
        return {"op": op, "result": _toolchain()}
    if op == "provision":
        tc = _toolchain()
        missing = [k for k in ("git", "cargo") if not tc.get(k)]
        if missing:
            raise ToolUnavailable(f"n64recomp provision needs: {', '.join(missing)}")
        repo = _repo(ctx.config)
        if not (repo / ".git").is_dir():
            ctx.progress(5, "cloning N64Recomp (shallow)")
            r = subprocess.run(["git", "clone", "--depth", "1", N64RECOMP_REPO, str(repo)],
                               capture_output=True, text=True, timeout=600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode:
                raise RuntimeError(f"git clone failed: {(r.stderr or r.stdout)[-1000:]}")
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=30).stdout.strip()
        ctx.progress(40, "cargo build --release (backend)")
        r = subprocess.run([tc["cargo"], "build", "--release", "--manifest-path", str(repo / "Cargo.toml")],
                           capture_output=True, text=True, timeout=3000,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        receipt = {"op": "provision", "repo": N64RECOMP_REPO, "sha": sha, "path": str(repo),
                   "backend": "built" if r.returncode == 0 else f"failed: {(r.stderr or '')[-600:]}",
                   "frontend": "manual (Windows: cmake + MSVC + Vulkan SDK for RT64)",
                   "toolchain": tc, "at": time.time()}
        (ctx.config.runtime / "n64recomp").mkdir(parents=True, exist_ok=True)
        receipt_path = ctx.config.runtime / "n64recomp" / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
        ctx.artifact("n64recomp.json", json.dumps(receipt, indent=1).encode(), "application/json")
        if r.returncode:
            raise RuntimeError(f"cargo build failed: {(r.stderr or r.stdout)[-1500:]}")
        ctx.progress(100, "N64Recomp backend built")
        return {"op": op, "result": receipt}
    if op == "generate":
        if not _repo_ready(ctx.config):
            raise ToolUnavailable("N64Recomp source not provisioned on this node; run op=provision first")
        repo = _repo(ctx.config)
        project = Path(inp.project_dir or str(ctx.config.runtime / "n64recomp" / "mods" / inp.name))
        project.mkdir(parents=True, exist_ok=True)
        template = repo / "config" / "RecompModInfo.toml"
        if not template.is_file():
            raise RuntimeError(f"upstream template missing at {template}; re-provision or check the repo layout")
        config_toml = project / "RecompModInfo.toml"
        # The upstream template is copied verbatim; edit its fields (mod name, asset dirs)
        # before or after generation — the recompiler only consumes the paths it declares.
        config_toml.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        cmd = _generate_command(repo, inp.rom, config_toml)
        ctx.progress(10, "recompiling ROM (first run compiles the recompiler)")
        r = subprocess.run(cmd, cwd=str(project), capture_output=True, text=True, timeout=3500,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        receipt = {"op": "generate", "rom": inp.rom, "name": inp.name, "project_dir": str(project),
                   "generated": sorted(p.name for p in project.iterdir()) if project.is_dir() else [],
                   "returncode": r.returncode,
                   "log_tail": (r.stdout + r.stderr)[-1500:], "at": time.time()}
        (ctx.config.runtime / "n64recomp").mkdir(parents=True, exist_ok=True)
        (ctx.config.runtime / "n64recomp" / "generate.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
        ctx.artifact("n64recomp.json", json.dumps(receipt, indent=1).encode(), "application/json")
        if r.returncode:
            raise RuntimeError(f"n64recomp generate failed ({r.returncode}): {(r.stdout + r.stderr)[-1500:]}")
        return {"op": op, "result": receipt}
    if op == "status":
        d = ctx.config.runtime / "n64recomp"
        receipts = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in d.glob("*.json")} if d.is_dir() else {}
        return {"op": op, "result": {"repo": str(_repo(ctx.config)), "ready": _repo_ready(ctx.config),
                                     "toolchain": _toolchain(), "receipts": receipts}}
    raise ValueError("unknown op; use toolchain, provision, generate, status")
