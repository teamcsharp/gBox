"""Switch container tools for gBox: hactool / nut / 4nxci discovery and the one-time `main` extraction the native
research needs (the class DTIs: RE5's `uWp0a` proximity bomb, RE6's shell classes, RE4's campaign weapon classes).

The game's `main` image lives inside the NSP; every extractor in TOOLS can pull it. This module finds whichever is
installed on the host, extracts `main` (and the ExeFS) into the profile's cache once per title id, and reports the
result to the mod sidebar and to agents through the `switch_extract` tool. An unavailable extractor is an honest
report (the caller then supplies a pre-extracted `main`), never a crash.

CLI: python -m gbox.switch_tools status | extract <nsp-path> [title-id]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: The Switch container extractors, in preference order. hactool is the reference (C); nut and 4nxci are the common
#: Python/Rust alternatives. All three write the ExeFS's `main` from an NSP.
TOOLS = ("hactool", "nut", "4nxci")

#: Where an extractor may live besides PATH (the provisioned bins and the Rust toolchain's bin dir).
EXTRA_DIRS = ("~/.local/bin", "~/bin", "~/.cargo/bin", "/usr/local/bin")

#: The files an NSP extraction produces that the native research reads.
WANTED = ("main", "main.npdm", "main.nca")


def _candidates() -> list[str]:
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    dirs += [str(Path(d).expanduser()) for d in EXTRA_DIRS]
    return dirs


def find_tool(prefer=None) -> str | None:
    """The absolute path of the first installed extractor (a PATH or EXTRA_DIRS hit), else None."""
    order = (prefer,) + TOOLS if prefer else TOOLS
    for name in order:
        if not name:
            continue
        found = shutil.which(name, path=os.pathsep.join(_candidates()))
        if found:
            return found
    return None


def cache_root(profile: str | None = None) -> Path:
    """The extraction cache: <profile>/switch-extract (the profile's own gbox-data, like every other cache)."""
    root = Path(profile or os.environ.get("GBOX_DATA") or "gbox-data")
    return root / "switch-extract"


def title_id_from_name(name: str) -> str | None:
    """The 16-hex Switch title id in an NSP path/name (`Resident Evil 5 [010018100CD46000].nsp`), upper-cased."""
    import re
    m = re.search(r"\b([0-9A-Fa-f]{16})\b", str(name or ""))
    return m.group(1).upper() if m else None


def extracted(tid: str, profile: str | None = None) -> Path | None:
    """The cached `main` for a title id, when it is already extracted."""
    at = cache_root(profile) / str(tid).upper() / "main"
    return at if at.is_file() and at.stat().st_size > 0 else None


def extract(nsp: str | os.PathLike, tid: str | None = None, profile: str | None = None,
            timeout: float = 600.0) -> dict:
    """Extract the NSP's ExeFS into the cache once and return the report.

    {"ok": bool, "tool": name|None, "title_id", "main": path|None, "cached": bool, "reason": str}.
    A cached `main` short-circuits the work. No extractor installed is ok=False with the honest reason.
    """
    nsp = Path(nsp)
    tid = (tid or title_id_from_name(nsp.name) or "").upper() or None
    if not tid:
        return {"ok": False, "tool": None, "title_id": None, "main": None, "cached": False,
                "reason": "the file name carries no 16-hex title id"}
    have = extracted(tid, profile)
    if have is not None:
        return {"ok": True, "tool": None, "title_id": tid, "main": str(have), "cached": True, "reason": ""}
    if not nsp.is_file():
        return {"ok": False, "tool": None, "title_id": tid, "main": None, "cached": False,
                "reason": f"the NSP is not there: {nsp}"}
    tool = find_tool()
    if not tool:
        return {"ok": False, "tool": None, "title_id": tid, "main": None, "cached": False,
                "reason": "no Switch extractor installed (hactool, nut or 4nxci): install one or drop the extracted main"}
    out = cache_root(profile) / tid
    out.mkdir(parents=True, exist_ok=True)
    exefs = out / "exefs"
    exefs.mkdir(parents=True, exist_ok=True)
    name = Path(tool).name
    if name.startswith("hactool"):
        cmd = [tool, "-t", "nsp", f"--exefsdir={exefs}", str(nsp)]
    elif name.startswith("nut"):
        cmd = [tool, "extract", "-t", "nsp", "-o", str(out / "raw"), str(nsp)]
    else:                                            # 4nxci and the like take the output dir
        cmd = [tool, "-o", str(out / "raw"), str(nsp)]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "tool": name, "title_id": tid, "main": None, "cached": False,
                "reason": f"{name} could not run: {type(e).__name__}: {e}"[:300]}
    # Find the main the extractor wrote (hactool: exefs/main; nut/4nxci: a raw tree with the ExeFS somewhere).
    found = None
    for base in (exefs, out / "raw", out):
        try:
            for p in Path(base).rglob("main"):
                if p.is_file() and p.stat().st_size > 0:
                    found = p
                    break
        except OSError:
            pass
        if found:
            break
    if not found:
        return {"ok": False, "tool": name, "title_id": tid, "main": None, "cached": False,
                "reason": (f"{name} ran (exit {done.returncode}) but no main was written: "
                           f"{(done.stderr or done.stdout or '').strip()[-200:]}")}
    if found != out / "main":
        shutil.copyfile(found, out / "main")
    return {"ok": True, "tool": name, "title_id": tid, "main": str(out / "main"), "cached": False, "reason": ""}


def status(profile: str | None = None) -> list[dict]:
    """The extractor report for the mod sidebar / agents: one row per known tool plus the cached titles."""
    rows = []
    for name in TOOLS:
        found = find_tool(name)
        rows.append({"tool": name, "available": bool(found), "path": found,
                     "reason": "" if found else f"{name} is not installed on this host"})
    try:
        if cache_root(profile).is_dir():
            for d in sorted(cache_root(profile).iterdir()):
                if d.is_dir() and (d / "main").is_file():
                    rows.append({"tool": "cache", "available": True, "path": str(d / "main"),
                                 "title_id": d.name, "reason": ""})
    except OSError:
        pass
    return rows


def _main(argv: list[str]) -> int:
    cmd = (argv[0] if argv else "status").lower()
    if cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if cmd == "extract" and len(argv) >= 2:
        print(json.dumps(extract(argv[1], argv[2] if len(argv) > 2 else None), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
