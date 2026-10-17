"""decomp.me / IDA Pro / N64Recomp as gBox tools (#90). Builds on the Hermes draft (PR #154), corrected:

- `decomp_me`: decomp.me's REST API (https://decomp.me/api; api.decomp.dev is decomp.dev's progress site and answers
  every path with an empty 200). Opt-in: nothing touches the network until `decomp_me_enabled = true` in gbox.toml, and
  every op defaults to dry_run=true, returning the exact request it would send. Submitting creates a PUBLIC scratch; the
  result keeps the claim_token so the operator can claim it on the site. decomp.me sits behind a Cloudflare challenge
  that can refuse scripted clients (HTTP 403 HTML); the tool says so instead of returning the challenge page.
- `ida`: IDA Pro headless (idat64 / idat) with an IDAPython export script that writes the same analysis.json shape as
  analyze_binary's Ghidra ExportAnalysis.java ({program, functions[{name, entry, size, source}], strings[{addr, value}]}),
  so re_lab.summarize_analysis, re_study and n64recomp take either. The binary is copied into a work folder and the
  database is written there (-o), so IDA never writes next to the game file.
- `n64recomp`: drives an installed N64Recomp (github.com/N64Recomp/N64Recomp, a C++ CMake build; gBox never builds or
  downloads it) on an owned ROM plus gBox's N64 analysis (the analysis.json of re_study's N64 boot ELF): a work folder
  with a normalized .z64 COPY of the ROM, a symbol TOML generated from the analysis, an N64Recomp config, and the
  recompiler's C output. The ROM is only read (its hash is checked before and after).

None of these tools change a game file, the operator's IDA settings or a running session.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path, PureWindowsPath

from pydantic import BaseModel

from .models import Permission as P
from .registry import ToolUnavailable, Unsupported, tool

NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(s: str, default: str = "job") -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s or "").strip("._")
    return s[:64] or default


# ============================================================================================ decomp.me

class DecompMeIn(BaseModel):
    op: str = "status"          # status | compilers | platforms | presets | fetch | list | submit | compile
    dry_run: bool = True        # true: return the request without sending it (always allowed, no network)
    slug: str = ""              # fetch / compile: the scratch slug (decomp.me/scratch/<slug>)
    params: dict = {}           # list: query filters, e.g. {"platform": "n64", "search": "func_80001234", "page_size": 20}
    platform: str = ""          # submit: n64 | ps1 | ps2 | gc_wii | ...
    compiler: str = ""          # submit / compile: e.g. ido7.1, gcc2.8.1pm, mwcc_247_92
    compiler_flags: str = ""
    preset: int | None = None   # submit: a decomp.me preset id (sets compiler + flags for a known project)
    diff_label: str = ""        # submit: the function symbol to diff (usually the function name)
    target_asm: str = ""        # submit: the function's assembly (GNU as syntax, with a glabel)
    context: str = ""           # submit / compile: C context (structs, prototypes)
    source_code: str = ""       # submit / compile: the candidate C
    name: str = ""              # submit: scratch name


class DecompMeOut(BaseModel):
    op: str
    dry_run: bool
    request: dict = {}
    status: int | None = None
    data: dict | list | None = None
    public: bool = False        # true when the op published something on decomp.me


def _dm_base(cfg) -> str:
    return (getattr(cfg, "decomp_me_url", None) or "https://decomp.me/api").rstrip("/")


def decomp_me_request(cfg, inp: DecompMeIn) -> dict:
    """The HTTP request an op maps to (method, url, params, json). Validates required fields; never sends anything."""
    base, op = _dm_base(cfg), inp.op.lower()
    if op == "compilers":
        return {"method": "GET", "url": f"{base}/compiler"}
    if op == "platforms":
        return {"method": "GET", "url": f"{base}/platform"}
    if op == "presets":
        return {"method": "GET", "url": f"{base}/preset", "params": inp.params or {}}
    if op == "fetch":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", inp.slug or ""):
            raise ValueError("fetch needs slug = the scratch id from decomp.me/scratch/<slug>")
        return {"method": "GET", "url": f"{base}/scratch/{inp.slug}"}
    if op == "list":
        return {"method": "GET", "url": f"{base}/scratch", "params": {"page_size": 20, **(inp.params or {})}}
    if op == "submit":
        missing = [k for k in ("target_asm",) if not getattr(inp, k).strip()]
        if not inp.preset and not (inp.platform and inp.compiler):
            missing.append("platform+compiler (or preset)")
        if missing:
            raise ValueError(f"submit needs {', '.join(missing)}")
        body = {"target_asm": inp.target_asm, "context": inp.context, "source_code": inp.source_code,
                "compiler_flags": inp.compiler_flags, "diff_label": inp.diff_label, "name": inp.name or inp.diff_label}
        if inp.preset:
            body["preset"] = inp.preset
        if inp.platform:
            body["platform"] = inp.platform
        if inp.compiler:
            body["compiler"] = inp.compiler
        return {"method": "POST", "url": f"{base}/scratch", "json": body}
    if op == "compile":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", inp.slug or ""):
            raise ValueError("compile needs slug")
        body = {k: v for k, v in (("compiler", inp.compiler), ("compiler_flags", inp.compiler_flags),
                                  ("source_code", inp.source_code), ("context", inp.context)) if v}
        return {"method": "POST", "url": f"{base}/scratch/{inp.slug}/compile", "json": body}
    raise ValueError("op: status | compilers | platforms | presets | fetch | list | submit | compile")


def _dm_send(req: dict):
    import httpx
    try:
        r = httpx.request(req["method"], req["url"], params=req.get("params"), json=req.get("json"), timeout=60,
                          headers={"accept": "application/json", "user-agent": "gBox decomp_me tool"})
    except httpx.HTTPError as e:
        raise ToolUnavailable(f"decomp.me unreachable: {e}") from e
    ctype = r.headers.get("content-type", "")
    if r.status_code in (403, 503) and "text/html" in ctype:
        raise ToolUnavailable(f"decomp.me's Cloudflare challenge refused this client (HTTP {r.status_code}); open the "
                              "request in a browser instead (dry_run=true shows it)")
    if r.status_code >= 400:
        raise RuntimeError(f"decomp.me {req['method']} {req['url']} -> HTTP {r.status_code}: {r.text[:400]}")
    if "json" not in ctype:
        raise RuntimeError(f"decomp.me answered {ctype or 'no content type'} instead of JSON ({len(r.content)} bytes)")
    return r.status_code, r.json()


@tool("decomp_me", "1.0", DecompMeIn, DecompMeOut, capabilities=["reverse-engineering", "decompilation", "network"],
      platforms=["windows", "linux", "darwin"], permissions=[P.READ, P.NETWORK], timeout_s=180,
      side_effects=["op=submit (dry_run=false) publishes the assembly, context and source as a public decomp.me scratch"])
def decomp_me(inp: DecompMeIn, ctx):
    """decomp.me (matching decompilation): op=status | compilers | platforms | presets | fetch (slug) | list (params) |
    submit (platform+compiler or preset, target_asm, diff_label, context, source_code: creates a PUBLIC scratch) |
    compile (slug, source_code). dry_run=true (default) returns the request without sending it; real calls need
    decomp_me_enabled = true in gbox.toml (opt-in)."""
    op = inp.op.lower()
    enabled = bool(getattr(ctx.config, "decomp_me_enabled", False))
    if op == "status":
        return {"op": op, "dry_run": True, "data": {"enabled": enabled, "url": _dm_base(ctx.config),
                "note": "set decomp_me_enabled = true in gbox.toml to allow network calls" if not enabled else "network allowed"}}
    req = decomp_me_request(ctx.config, inp)
    public = op == "submit"
    if inp.dry_run:
        return {"op": op, "dry_run": True, "request": req, "public": False}
    if not enabled:
        raise PermissionError("decomp_me is opt-in: set decomp_me_enabled = true in gbox.toml (or use dry_run=true)")
    ctx.progress(10, f"decomp.me {req['method']} {req['url']}")
    status, data = _dm_send(req)
    if public and isinstance(data, dict) and data.get("slug"):
        data = data | {"url": f"https://decomp.me/scratch/{data['slug']}"}
    return {"op": op, "dry_run": False, "request": req, "status": status, "data": data, "public": public}


# ============================================================================================ IDA Pro

IDA_EXPORT_PY = r'''# gBox: IDA headless export -> analysis.json (same shape as adapters/ghidra/ExportAnalysis.java)
import json, os
import idaapi, idautils, idc, ida_auto, ida_bytes, ida_funcs, ida_nalt, ida_pro
try:
    import ida_ida
except ImportError:
    ida_ida = None
out = os.environ["GBOX_IDA_OUT"]
ok = False
try:
    ida_auto.auto_wait()
    def hx(ea):
        return "%08x" % ea
    def call(name, default=None):
        try:
            return getattr(ida_ida, name)() if ida_ida else default
        except Exception:
            return default
    proc = call("inf_get_procname", "") or ""
    bits = 64 if call("inf_is_64bit", False) else 32
    endian = "BE" if call("inf_is_be", False) else "LE"
    try:
        sha = ida_nalt.retrieve_input_file_sha256()
        sha = sha.hex() if isinstance(sha, (bytes, bytearray)) else str(sha or "")
    except Exception:
        sha = ""
    program = {"name": ida_nalt.get_root_filename(), "language": "%s:%s:%d:ida" % (proc, endian, bits),
               "image_base": hx(idaapi.get_imagebase()), "sha256": sha}
    functions = []
    for ea in idautils.Functions():
        f = ida_funcs.get_func(ea)
        size = sum(e - s for s, e in idautils.Chunks(ea))
        if ida_bytes.has_dummy_name(ida_bytes.get_flags(ea)):
            source = "DEFAULT"
        elif f is not None and f.flags & ida_funcs.FUNC_LIB:
            source = "ANALYSIS"
        else:
            source = "IMPORTED"
        functions.append({"name": ida_funcs.get_func_name(ea), "entry": hx(ea), "size": size, "source": source})
    strings = [{"addr": hx(s.ea), "value": str(s)} for s in idautils.Strings()]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"program": program, "functions": functions, "strings": strings}, fh)
    ok = True
except Exception as e:
    with open(out + ".err", "w", encoding="utf-8") as fh:
        fh.write(repr(e))
ida_pro.qexit(0 if ok else 1)
'''

IDA_NAMES = ("idat64.exe", "idat.exe") if sys.platform == "win32" else ("idat64", "idat")


def ida_search_roots(cfg) -> list[Path]:
    roots = [Path("C:/_tools"), Path("C:/Program Files"), Path("C:/Program Files (x86)"), Path.home() / "tools",
             Path("/opt"), Path.home()]
    try:
        roots.append(Path(cfg.runtime) / "tools")
    except Exception:                                       # noqa: BLE001
        pass
    return [r for r in roots if r.is_dir()]


def find_idat(cfg) -> Path | None:
    """The headless IDA executable: ida_home (folder or exe), env IDA_HOME / IDADIR, then IDA* folders in the roots."""
    cands = []
    for p in (getattr(cfg, "ida_home", None), os.environ.get("IDA_HOME"), os.environ.get("IDADIR")):
        if p:
            p = Path(os.path.expandvars(str(p)))
            cands.append(p.parent if p.is_file() else p)
    if not cands:
        for root in ida_search_roots(cfg):
            cands += sorted((d for d in root.glob("*") if d.is_dir() and re.match(r"(?i)ida", d.name)), reverse=True)
    for d in cands:
        for n in IDA_NAMES:
            if (d / n).is_file():
                return d / n
    return None


def ida_check(cfg) -> str | None:
    if find_idat(cfg):
        return None
    return ("IDA Pro is not installed on this node (no idat64/idat found). gBox never installs it: install IDA Pro and set "
            "ida_home = \"<IDA folder>\" in gbox.toml (or env IDA_HOME), then restart the worker. analyze_binary "
            "(Ghidra) gives the same analysis.json without IDA.")


def ida_command(idat: Path, work_bin: Path, script: Path, db: Path, log: Path, processor: str = "",
                extra: list[str] | None = None) -> list[str]:
    cmd = [str(idat), "-A", f"-L{log}", f"-o{db}", f"-S{script}"]
    if processor:
        cmd.append(f"-p{processor}")
    return cmd + list(extra or []) + [str(work_bin)]


def _no_space(p: Path) -> Path:
    """-S<script> is split on spaces by IDA: use the 8.3 short path on Windows when the path has a space."""
    if " " not in str(p) or sys.platform != "win32":
        return p
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 1024)
    return Path(buf.value) if n and " " not in buf.value else p


class IdaIn(BaseModel):
    op: str = "analyze"          # status | analyze
    binary_path: str = ""        # analyze: an executable this worker can read (re_study's ELF, an extracted SLUS/DOL/.exe)
    processor: str = ""          # analyze: IDA processor (-p), e.g. mipsb (N64), mipsl (PS1), r5900l (PS2), ppc (GameCube)
    extra_args: list[str] = []   # analyze: more idat switches (e.g. loader options); never output paths


class IdaOut(BaseModel):
    op: str
    functions: int = 0
    strings: int = 0
    program: dict = {}
    detail: dict = {}


def _ida_validate(out: IdaOut, arts):
    if out.op != "analyze":
        return []
    from .tools import _ghidra_validate
    return _ghidra_validate(out, arts)


@tool("ida", "1.0", IdaIn, IdaOut, capabilities=["analysis", "ida", "reverse-engineering"], platforms=["windows", "linux"],
      permissions=[P.READ, P.EXECUTE], timeout_s=3600, artifacts=["analysis.json"], check=ida_check,
      validate=_ida_validate, validation="artifact counts (same as analyze_binary)")
def ida(inp: IdaIn, ctx):
    """IDA Pro headless (idat64/idat -A + an IDAPython export): op=analyze (binary_path, processor) writes analysis.json
    with the same shape as analyze_binary (functions + strings), so re_study / re_dossier / n64recomp take it; op=status
    shows which IDA it uses. The binary is copied to a work folder; nothing is written next to the original."""
    idat = find_idat(ctx.config)
    if idat is None:
        raise ToolUnavailable(ida_check(ctx.config))
    if inp.op.lower() == "status":
        return {"op": "status", "detail": {"idat": str(idat), "home": str(idat.parent)}}
    if inp.op.lower() != "analyze":
        raise ValueError("op: status | analyze")
    src = Path(inp.binary_path)
    if not src.is_file():
        raise FileNotFoundError(f"binary_path {inp.binary_path!r} is not a file on this worker")
    if any(re.match(r"(?i)-(o|s|l)", a) for a in inp.extra_args):
        raise ValueError("extra_args may not set -o / -S / -L (gBox owns the output paths)")
    work = Path(ctx.config.runtime) / "ida" / f"{_safe_name(src.stem)}-{ctx.job_id}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    wbin = work / _safe_name(src.name, "input.bin")
    shutil.copyfile(src, wbin)
    script = work / "gbox_ida_export.py"
    script.write_text(IDA_EXPORT_PY, encoding="utf-8")
    out, log = work / "analysis.json", work / "ida.log"
    cmd = ida_command(idat, wbin, _no_space(script), work / "db", log, inp.processor, inp.extra_args)
    env = dict(os.environ, GBOX_IDA_OUT=str(out), TVHEADLESS="1")
    ctx.progress(5, f"IDA analyzing {src.name}")
    r = subprocess.run(cmd, cwd=str(work), env=env, capture_output=True, text=True, timeout=3500, creationflags=NOWINDOW)
    if r.returncode or not out.is_file():
        tail = log.read_text(errors="replace")[-1500:] if log.is_file() else (r.stdout + r.stderr)[-1500:]
        err = Path(str(out) + ".err")
        raise RuntimeError(f"IDA failed ({r.returncode}){': ' + err.read_text() if err.is_file() else ''}: {tail}")
    d = out.read_bytes()
    a = json.loads(d)
    ctx.artifact("analysis.json", d, "application/json", binary=inp.binary_path, tool="ida")
    shutil.rmtree(work, ignore_errors=True)
    return {"op": "analyze", "functions": len(a["functions"]), "strings": len(a["strings"]), "program": a["program"],
            "detail": {"idat": str(idat)}}


# ============================================================================================ N64Recomp

N64_BOOT_ROM = 0x1000
N64_BOOT_SIZE = 0x100000           # re_lab_tool.n64_boot_to_elf: 1 MiB from ROM 0x1000 at the header entry point


def find_n64recomp(cfg) -> Path | None:
    names = ("N64Recomp.exe", "N64Recomp") if sys.platform == "win32" else ("N64Recomp",)
    cands = []
    for p in (getattr(cfg, "n64recomp_path", None), os.environ.get("N64RECOMP")):
        if p:
            p = Path(os.path.expandvars(str(p)))
            if p.is_file():
                return p
            cands += [p, p / "build", p / "build" / "Release", p / "Release"]
    if w := shutil.which("N64Recomp"):
        return Path(w)
    if not cands:
        roots = [Path("C:/_tools"), Path.home() / "tools", Path("/opt")]
        try:
            roots.append(Path(cfg.runtime) / "tools")
        except Exception:                                   # noqa: BLE001
            pass
        for root in (r for r in roots if r.is_dir()):
            for d in sorted(root.glob("*")):
                if d.is_dir() and "recomp" in d.name.lower():
                    cands += [d, d / "build", d / "build" / "Release", d / "build" / "Debug", d / "Release"]
    for d in cands:
        for n in names:
            if (d / n).is_file():
                return d / n
    return None


def n64recomp_check(cfg) -> str | None:
    if find_n64recomp(cfg):
        return None
    return ("N64Recomp is not installed on this node. gBox never downloads or builds it: build github.com/N64Recomp/"
            "N64Recomp (CMake) and set n64recomp_path = \"<N64Recomp executable or build folder>\" in gbox.toml (or env "
            "N64RECOMP), then restart the worker.")


def _addr(v) -> int:
    if isinstance(v, int):
        return v
    s = str(v).split(":")[-1].strip().lower()
    return int(s[2:] if s.startswith("0x") else s, 16)


def _c_ident(name: str, ea: int, used: set) -> str:
    n = re.sub(r"\W", "_", name or "")
    if not n or n[0].isdigit():
        n = f"func_{ea:08X}"
    base, k = n, 1
    while n in used:
        k += 1
        n = f"{base}_{k}"
    used.add(n)
    return n


def boot_functions(analysis: dict, entry: int, size: int = N64_BOOT_SIZE) -> tuple[list[dict], list[str]]:
    """analysis.json functions inside the boot segment [entry, entry+size) as N64Recomp symbols: word aligned, sorted,
    non-overlapping, unique C names. Returns (functions, notes)."""
    notes, fns, used = [], [], set()
    rows = []
    for f in analysis.get("functions") or []:
        try:
            ea, sz = _addr(f.get("entry")), int(f.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if entry <= ea < entry + size and sz > 0:
            rows.append((ea, sz, f.get("name") or ""))
    rows.sort()
    end_prev, skipped = 0, 0
    for ea, sz, name in rows:
        sz -= sz % 4
        if ea % 4 or sz <= 0 or ea < end_prev or ea + sz > entry + size:
            skipped += 1
            continue
        fns.append({"name": _c_ident(name, ea, used), "vram": ea, "size": sz})
        end_prev = ea + sz
    if skipped:
        notes.append(f"{skipped} functions skipped (unaligned, overlapping or past the boot segment)")
    return fns, notes


def syms_toml(functions: list[dict], entry: int, size: int) -> str:
    """N64Recomp symbol-file input: one section (the boot segment, ROM 0x1000 -> entry)."""
    lines = ["# generated by gBox n64recomp from analysis.json (boot segment only)", "[[section]]", 'name = ".boot"',
             f"rom = 0x{N64_BOOT_ROM:08X}", f"vram = 0x{entry:08X}", f"size = 0x{size:X}", "", "functions = ["]
    lines += [f'    {{ name = "{f["name"]}", vram = 0x{f["vram"]:08X}, size = 0x{f["size"]:X} }},' for f in functions]
    return "\n".join(lines + ["]", ""])


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"0x{v:X}" if v > 0xFFFF else str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v))


def config_toml(entry: int, overrides: dict | None = None, patches: dict | None = None) -> str:
    """N64Recomp config: [input] paths are relative to this file (the work folder)."""
    inp = {"entrypoint": entry, "output_func_path": "RecompiledFuncs", "symbols_file_path": "syms.toml",
           "rom_file_path": "rom.z64"} | dict(overrides or {})
    for k in list(inp):
        if k.endswith("_path") and isinstance(inp[k], str) and (Path(inp[k]).is_absolute() or PureWindowsPath(inp[k]).drive or ".." in PureWindowsPath(inp[k]).parts or ".." in Path(inp[k]).parts):
            raise ValueError(f"config override {k} must stay inside the work folder")
    lines = ["# generated by gBox n64recomp", "[input]"] + [f"{k} = {_toml_value(v)}" for k, v in inp.items()]
    if patches:
        lines += ["", "[patches]"] + [f"{k} = {_toml_value(v)}" for k, v in patches.items()]
    return "\n".join(lines + [""])


class N64RecompIn(BaseModel):
    op: str = "status"            # status | list | run
    rom_path: str = ""            # run: an owned N64 ROM (.z64/.v64/.n64, or one in a .zip/.7z) this worker can read
    analysis_sha256: str = ""     # run: analysis.json artifact (analyze_binary / ida on re_study's N64 ELF)
    analysis_path: str = ""       # run: or an analysis.json file on this worker
    name: str = ""                # run: work folder name (default: the ROM's name)
    entrypoint: str = ""          # run: hex override (default: the ROM header's boot address)
    config_overrides: dict = {}   # run: extra [input] keys (e.g. relocatable_sections_path inside the work folder)
    patches: dict = {}            # run: [patches] keys (stubs, ignored, ...)
    dry_run: bool = False         # run: write the work folder (ROM copy, syms.toml, config) but don't run N64Recomp


class N64RecompOut(BaseModel):
    op: str
    result: dict


def _work_root(cfg) -> Path:
    return Path(cfg.runtime) / "n64recomp"


def _fetch_artifact(ctx, sha: str) -> bytes:
    import httpx
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("analysis_sha256 must be a sha256 hex digest")
    if not getattr(ctx, "server", None):
        raise Unsupported("analysis_sha256 needs the control plane; pass analysis_path instead")
    r = httpx.get(f"{ctx.server}/api/artifacts/{sha}", headers=ctx.headers, timeout=300)
    r.raise_for_status()
    return r.content


@tool("n64recomp", "1.0", N64RecompIn, N64RecompOut, capabilities=["reverse-engineering", "recompilation", "n64"],
      platforms=["windows", "linux"], permissions=[P.READ, P.EXECUTE], timeout_s=3600, artifacts=["n64recomp.json"],
      side_effects=["writes a work folder under <runtime>/n64recomp (a ROM copy, symbols, config, generated C)"],
      check=n64recomp_check)
def n64recomp(inp: N64RecompIn, ctx):
    """N64Recomp (static recompilation of N64 code to C) on an owned ROM: op=status (which N64Recomp, work folders) |
    list (work folders + receipts) | run (rom_path + analysis_sha256 or analysis_path from analyze_binary/ida on
    re_study's N64 ELF): work folder with a .z64 copy of the ROM, syms.toml from the analysis (boot segment), config,
    then N64Recomp -> RecompiledFuncs/*.c. The ROM itself is only read; dry_run=true stops before running N64Recomp."""
    exe = find_n64recomp(ctx.config)
    if exe is None:
        raise ToolUnavailable(n64recomp_check(ctx.config))
    root, op = _work_root(ctx.config), inp.op.lower()
    if op in ("status", "list"):
        rows = []
        for d in sorted(root.glob("*")) if root.is_dir() else []:
            rc = d / "receipt.json"
            try:
                rows.append(json.loads(rc.read_text()) if rc.is_file() else {"name": d.name, "state": "no receipt"})
            except ValueError:
                rows.append({"name": d.name, "state": "unreadable receipt"})
        res = {"work": rows}
        if op == "status":
            res = {"n64recomp": str(exe), "work_root": str(root), "work_count": len(rows)}
        return {"op": op, "result": res}
    if op != "run":
        raise ValueError("op: status | list | run")
    from . import n64_rom
    rom = Path(inp.rom_path)
    if not rom.is_file():
        raise FileNotFoundError(f"rom_path {inp.rom_path!r} is not a file on this worker")
    before = (_sha256_file(rom), rom.stat().st_size, rom.stat().st_mtime_ns)
    z64 = n64_rom.read(rom)
    if z64[:4] != b"\x80\x37\x12\x40":
        raise ValueError("not an N64 ROM after normalization")
    if inp.analysis_path:
        analysis = json.loads(Path(inp.analysis_path).read_text(encoding="utf-8"))
    elif inp.analysis_sha256:
        analysis = json.loads(_fetch_artifact(ctx, inp.analysis_sha256))
    else:
        raise ValueError("run needs analysis_sha256 or analysis_path: re_study the game (or analyze_binary / ida on its "
                         "N64 ELF) first")
    entry = int(inp.entrypoint, 16) if inp.entrypoint else struct.unpack_from(">I", z64, 8)[0]
    size = min(N64_BOOT_SIZE, len(z64) - N64_BOOT_ROM)
    fns, notes = boot_functions(analysis, entry, size)
    if not fns:
        raise ValueError(f"the analysis has no functions in the boot segment 0x{entry:08X}..0x{entry + size:08X}; analyze "
                         "re_study's N64 ELF (it is loaded at the header entry point)")
    name = _safe_name(inp.name or rom.stem, "rom")
    work = root / name
    work.mkdir(parents=True, exist_ok=True)
    (work / "rom.z64").write_bytes(z64)
    (work / "syms.toml").write_text(syms_toml(fns, entry, size), encoding="utf-8")
    (work / "config.toml").write_text(config_toml(entry, inp.config_overrides, inp.patches), encoding="utf-8")
    (work / "RecompiledFuncs").mkdir(exist_ok=True)
    receipt = {"name": name, "work": str(work), "rom": str(rom), "rom_sha256": before[0], "z64_sha256": hashlib.sha256(z64).hexdigest(),
               "entrypoint": f"0x{entry:08X}", "functions": len(fns), "notes": notes, "n64recomp": str(exe),
               "analysis": inp.analysis_sha256 or inp.analysis_path, "at": time.time(), "state": "prepared"}
    if not inp.dry_run:
        ctx.progress(20, f"N64Recomp: {len(fns)} functions")
        r = subprocess.run([str(exe), "config.toml"], cwd=str(work), capture_output=True, text=True, timeout=3400,
                           creationflags=NOWINDOW)
        outs = sorted(p.name for p in (work / "RecompiledFuncs").glob("*"))
        receipt |= {"state": "recompiled" if r.returncode == 0 else "failed", "returncode": r.returncode,
                    "outputs": outs[:200], "output_count": len(outs), "log_tail": (r.stdout + r.stderr)[-2000:]}
    after = (_sha256_file(rom), rom.stat().st_size, rom.stat().st_mtime_ns)
    receipt["rom_unchanged"] = after == before
    if after != before:
        receipt["state"] = "failed"
        receipt["notes"].append("the ROM file changed during the run (not by gBox): treat the output as suspect")
    (work / "receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    ctx.artifact("n64recomp.json", json.dumps(receipt, indent=1).encode(), "application/json", rom=str(rom))
    if receipt["state"] == "failed":
        raise RuntimeError(f"N64Recomp failed ({receipt.get('returncode')}): {receipt.get('log_tail', '')[-1200:]}")
    return {"op": op, "result": receipt}
