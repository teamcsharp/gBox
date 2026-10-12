"""Generic Unreal Engine 4/5 Steam game analysis: locate, safety-check, index pak files,
and find actor/locomotion/animation symbols through static Ghidra analysis.

Scope for this run:
- Read-only discovery of the operator's own Steam install.
- Refuse any game that ships an anti-cheat (BattlEye, EasyAntiCheat, XignCode, etc.) or
  that is currently running with a protected process.
- PUBG (Steam app 578080) is the example target; if it is not installed or has anti-cheat,
  the tool reports that cleanly instead of trying to bypass anything.

Future stages can add:
- UAsset/FModel/umodel extraction of .pak content.
- A REFramework-like non-intrusive UObject reader for games with no anti-cheat.
- Live memory correlation once a safe, offline single-player target is installed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from pydantic import BaseModel

from .catalog import parse_vdf
from .models import Permission as P
from .registry import tool, Ctx

APPID_PUBG = "578080"
TITLE_PUBG = "PLAYERUNKNOWN'S BATTLEGROUNDS"

# Anti-cheat / anti-tamper indicators we refuse to interact with.
ANTICHEAT = re.compile(
    r"(?i)easyanticheat|battleye|beservice|beclient|\beac_|anticheat|anti-cheat|xigncode|nprotect|"
    r"gameguard|vanguard|equ8|ricochet|faceit|pubganticheat|tencentprotect|tenprotect|xenuine|"
    r"nacl64|securom|safedisc|denuvo"
)

# Known Unreal Engine actor / locomotion / animation symbols we look for in functions/strings.
MOVEMENT_SYMBOLS = [
    ("UCharacterMovementComponent", "class", "high", "Unreal CharacterMovementComponent class"),
    ("CharacterMovementComponent", "class", "high", "CharacterMovementComponent class"),
    ("FSavedMove_Character", "class", "high", "saved move buffer for networked movement"),
    ("FSavedMove", "class", "medium", "saved move base class"),
    ("FCharacterMovementComponentPostPhysicsTickFunction", "class", "high", "post-physics movement tick"),
    ("MaxWalkSpeed", "field", "high", "maximum ground speed"),
    ("MaxWalkSpeedCrouched", "field", "high", "crouched maximum speed"),
    ("MaxAcceleration", "field", "high", "acceleration limit"),
    ("JumpZVelocity", "field", "high", "jump impulse magnitude"),
    ("AirControl", "field", "high", "air control multiplier"),
    ("BrakingDecelerationWalking", "field", "medium", "ground braking"),
    ("BrakingFriction", "field", "medium", "friction braking"),
    ("CrouchedHalfHeight", "field", "medium", "crouch capsule half-height"),
    ("NavAgentProps", "field", "medium", "navigation agent properties"),
    ("NetworkSmoothingMode", "field", "medium", "networked smoothing mode"),
    ("bNetworkSkipProxyPredictionOnNetUpdate", "field", "low", "proxy prediction flag"),
]

ANIMATION_SYMBOLS = [
    ("UAnimInstance", "class", "high", "Unreal animation instance base class"),
    ("AnimInstance", "class", "high", "animation instance class"),
    ("UAnimBlueprint", "class", "high", "animation blueprint class"),
    ("UAnimMontage", "class", "high", "animation montage asset"),
    ("UAnimSequence", "class", "high", "animation sequence asset"),
    ("AnimStateMachine", "class", "medium", "animation state machine"),
    ("FAnimNode", "class", "medium", "animation graph node base"),
    ("AnimInstanceProxy", "class", "medium", "animation update proxy"),
    ("UpdateAnimation", "method", "high", "animation update entry point"),
    ("NativeUpdateAnimation", "method", "high", "native animation update override"),
    ("EvaluateAnimation", "method", "high", "animation evaluation"),
    ("PlayAnim", "method", "medium", "play animation helper"),
    ("BlendSpace", "class", "medium", "blend-space asset"),
    ("AimOffset", "class", "medium", "aim-offset asset"),
]

LOCOMOTION_TERMS = [
    ("crouch", "behavior", "medium", "crouch state"),
    ("prone", "behavior", "medium", "prone state"),
    ("vault", "behavior", "medium", "vaulting behavior"),
    ("sprint", "behavior", "medium", "sprint behavior"),
    ("slide", "behavior", "medium", "slide behavior"),
    ("mantle", "behavior", "low", "mantle behavior"),
    ("falling", "state", "medium", "falling movement state"),
    ("jumping", "state", "medium", "jumping movement state"),
    ("rotation", "property", "low", "rotation handling"),
    ("locomotion", "domain", "medium", "locomotion domain"),
    ("movement state", "domain", "high", "movement state machine"),
]


def steam_root(cfg=None) -> Path | None:
    """Return configured Steam root, or try the Windows registry."""
    if cfg is not None and getattr(cfg, "steam_root", None):
        return Path(cfg.steam_root)
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                return Path(winreg.QueryValueEx(k, "SteamPath")[0])
        except OSError:
            return None
    return None


def game_dir(appid: str, cfg=None) -> Path:
    """Resolve a Steam appid to its installed common folder."""
    root = steam_root(cfg)
    if not root:
        raise FileNotFoundError("Steam is not installed or steam_root is not configured")
    lf = root / "steamapps" / "libraryfolders.vdf"
    if not lf.exists():
        raise FileNotFoundError(f"no Steam libraryfolders.vdf under {root}")
    libs = [Path(v["path"]) for v in parse_vdf(lf.read_text(errors="replace")).get("libraryfolders", {}).values()
            if isinstance(v, dict) and "path" in v]
    for lib in libs:
        acf = lib / "steamapps" / f"appmanifest_{appid}.acf"
        if acf.is_file():
            st = parse_vdf(acf.read_text(errors="replace")).get("AppState", {})
            d = lib / "steamapps" / "common" / st.get("installdir", "")
            if d.is_dir():
                return d
    raise FileNotFoundError(f"Steam app {appid} is not installed in any library on this PC")


def _anticheat_scan(gd: Path, max_files: int = 500) -> list[str]:
    """Top-level and one-level-deep scan for anti-cheat indicators. Avoids crawling huge content trees."""
    hits = []
    count = 0
    for p in gd.iterdir():
        if count >= max_files:
            break
        if p.is_file() and ANTICHEAT.search(p.name):
            hits.append(p.relative_to(gd).as_posix())
            count += 1
        elif p.is_dir():
            for c in p.iterdir():
                if count >= max_files:
                    break
                if c.is_file() and ANTICHEAT.search(c.name):
                    hits.append(c.relative_to(gd).as_posix())
                    count += 1
    return hits


def safety(gd: Path) -> dict:
    hits = _anticheat_scan(gd)
    running = _game_process(gd) is not None
    return {
        "ok": not hits and not running,
        "anticheat_files": hits,
        "protected_process_running": running,
        "note": ("no anti-cheat indicators found; static analysis of owned files is allowed"
                 if not hits else "anti-cheat indicators found: gBox does not attach, inject, or bypass this game"),
    }


def _game_process(gd: Path | None = None):
    """Check whether any executable from this game folder is currently running."""
    try:
        import psutil
    except ImportError:
        return None
    for p in psutil.process_iter(["name", "exe"]):
        exe = str(p.info.get("exe") or "")
        if not exe:
            continue
        if gd is None:
            return p
        try:
            parent = Path(exe).parent.resolve()
            target = Path(gd).resolve()
        except OSError:
            continue
        if parent == target or parent.is_relative_to(target):
            return p
    return None


def engine_version(gd: Path) -> dict:
    """Read Engine/Build/Build.version if present, fall back to string scanning the main executable."""
    bv = gd / "Engine" / "Build" / "Build.version"
    if bv.is_file():
        try:
            data = json.loads(bv.read_text())
            return {
                "source": "Engine/Build/Build.version",
                "major": data.get("MajorVersion"),
                "minor": data.get("MinorVersion"),
                "patch": data.get("PatchVersion"),
                "version": f"{data.get('MajorVersion')}.{data.get('MinorVersion')}.{data.get('PatchVersion')}",
            }
        except (OSError, ValueError):
            pass
    # Fall back to scanning the largest .exe for version strings.
    exe = _main_executable(gd)
    if exe:
        try:
            blob = exe.read_bytes()[:4_000_000]
            m = re.search(rb"Unreal Engine (\d+)\.(\d+)", blob)
            if m:
                return {"source": "exe strings", "major": int(m.group(1)), "minor": int(m.group(2)), "patch": None,
                        "version": f"{int(m.group(1))}.{int(m.group(2))}"}
            if b"UE4" in blob[:1_000_000]:
                return {"source": "exe strings", "major": 4, "minor": None, "patch": None, "version": "4.x"}
            if b"UE5" in blob[:1_000_000]:
                return {"source": "exe strings", "major": 5, "minor": None, "patch": None, "version": "5.x"}
        except OSError:
            pass
    return {"source": None, "major": None, "minor": None, "patch": None, "version": None}


def _main_executable(gd: Path) -> Path | None:
    """Pick the largest .exe that is not an installer/updater."""
    candidates = [p for p in gd.rglob("*.exe") if p.is_file() and not p.name.lower().startswith(("uninstall", "setup", "crashreport"))]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def _binaries(gd: Path, include_dlls: bool, max_binaries: int) -> list[Path]:
    """Return main exe + up to max_binaries largest non-anticheat DLLs under Binaries/Win64."""
    main = _main_executable(gd)
    out = [main] if main else []
    if include_dlls and main:
        bin_dir = main.parent
        dlls = [p for p in bin_dir.glob("*.dll") if p.is_file() and not ANTICHEAT.search(p.name)]
        dlls.sort(key=lambda p: p.stat().st_size, reverse=True)
        out += dlls[:max_binaries - 1]
    return [p for p in out if p and p.is_file()]


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _classify_symbol(text: str) -> dict | None:
    """Return a candidate evidence entry if the text matches a known UE locomotion/animation symbol."""
    t = text.strip()
    if not t:
        return None
    for symbol, kind, confidence, note in MOVEMENT_SYMBOLS + ANIMATION_SYMBOLS:
        if t == symbol:
            return {"symbol": symbol, "kind": kind, "confidence": confidence, "match": "exact", "note": note}
        if t.lower() == symbol.lower():
            return {"symbol": symbol, "kind": kind, "confidence": confidence, "match": "case-insensitive", "note": note}
        if symbol in t and len(t) < len(symbol) * 3:
            return {"symbol": symbol, "kind": kind, "confidence": "low", "match": "substring", "note": note}
    for term, kind, confidence, note in LOCOMOTION_TERMS:
        if re.search(rf"(?i)\b{re.escape(term)}\b", t):
            return {"symbol": t, "kind": kind, "confidence": confidence, "match": "term", "note": note}
    return None


def _analyze_artifact(artifact_json: bytes) -> list[dict]:
    """Heuristic locomotion/animation classification over a Ghidra analysis.json artifact."""
    try:
        data = json.loads(artifact_json)
    except ValueError:
        return []
    seen = set()
    hits = []
    for fn in data.get("functions", []):
        name = fn.get("name", "")
        c = _classify_symbol(name)
        if c and ("symbol", c["symbol"]) not in seen:
            seen.add(("symbol", c["symbol"]))
            hits.append({**c, "source": "function", "address": fn.get("entryPoint"), "raw": name})
    for s in data.get("strings", []):
        st = s.get("string", "")
        c = _classify_symbol(st)
        if c and ("string", st) not in seen:
            seen.add(("string", st))
            hits.append({**c, "source": "string", "address": s.get("address"), "raw": st})
    return hits


def _ghidra_analysis(binary_path: Path, ctx: Ctx | None) -> dict:
    """Run the existing analyze_binary tool on a single binary and return the analysis artifact payload."""
    from .tools import analyze_binary, GhidraIn
    if ctx is None:
        raise RuntimeError("internal static analysis needs a tool context")
    inp = GhidraIn(binary_path=str(binary_path))
    out = analyze_binary(inp, ctx)
    # The artifact data is appended to ctx.artifacts as the analysis.json payload.
    for name, data, media, _prov in ctx.artifacts:
        if name == "analysis.json":
            return {"functions": out["functions"], "strings": out["strings"], "program": out["program"],
                    "artifact": data, "sha256": hashlib.sha256(data).hexdigest()}
    # If the tool ran but the artifact was not kept locally, return empty but report counts.
    return {"functions": out["functions"], "strings": out["strings"], "program": out["program"],
            "artifact": b"", "sha256": ""}


def run_static_analysis(gd: Path, ctx: Ctx | None, include_dlls: bool = True, max_binaries: int = 5) -> dict:
    """Run Ghidra analysis on the main executable and selected DLLs, then classify UE locomotion symbols."""
    s = safety(gd)
    if not s["ok"]:
        return {"safe": False, **s}

    binaries = _binaries(gd, include_dlls, max_binaries)
    if not binaries:
        return {"safe": True, "error": "no usable executable found in the game folder"}

    results = []
    for p in binaries:
        if ctx:
            ctx.progress(5 + 90 * (binaries.index(p) + 1) // len(binaries), f"analyzing {p.name}")
        try:
            a = _ghidra_analysis(p, ctx)
            hits = _analyze_artifact(a["artifact"])
            results.append({
                "file": p.name,
                "sha256": _sha256(p),
                "functions": a["functions"],
                "strings": a["strings"],
                "candidates": hits,
                "program": a["program"],
            })
        except Exception as e:
            results.append({"file": p.name, "error": str(e)[:200]})

    all_hits = [h for r in results if "candidates" in r for h in r["candidates"]]
    return {
        "safe": True,
        "engine": engine_version(gd),
        "binaries": results,
        "candidate_count": len(all_hits),
        "candidates": sorted(all_hits, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["confidence"], 3)),
    }


def run_pak_index(gd: Path) -> list[dict]:
    """List .pak files with sizes; newest patch last."""
    paks = sorted(gd.rglob("*.pak"), key=lambda p: p.name)
    return [{"path": p.relative_to(gd).as_posix(), "size": p.stat().st_size,
             "sha256": _sha256(p) if p.stat().st_size < 512 * 1024 * 1024 else None}
            for p in paks]


class UESteamIn(BaseModel):
    op: str = "status"                      # status | locate | analyze | pak_index | extract_assets
    appid: str = APPID_PUBG                 # Steam appid to target
    title: str = TITLE_PUBG                 # human-readable title used when not installed
    include_dlls: bool = True
    max_binaries: int = 5
    engine: str = ""                        # optional hint: "ue4" or "ue5"


class UESteamOut(BaseModel):
    result: dict


def _check(cfg) -> str | None:
    if sys.platform != "win32":
        return "UE Steam analysis runs on the Windows PC (the game install is there)"
    if not steam_root(cfg):
        return "Steam is not installed or steam_root is not configured"
    return None


@tool("ue_steam", "1.0", UESteamIn, UESteamOut, capabilities=["analysis", "ghidra", "extract"], platforms=["windows"],
      permissions=[P.READ, P.EXECUTE], timeout_s=7200, check=_check,
      side_effects=["static Ghidra analysis of owned game files only; never launches or injects into the game"])
def ue_steam_tool(inp: UESteamIn, ctx: Ctx):
    """Static analysis of an Unreal Engine Steam game: locate, safety-check, index paks, and infer locomotion/animation symbols."""
    if inp.op == "locate":
        try:
            d = game_dir(inp.appid, ctx.config)
            return {"result": {"appid": inp.appid, "title": inp.title, "game_dir": str(d), "installed": True}}
        except FileNotFoundError as e:
            return {"result": {"appid": inp.appid, "title": inp.title, "installed": False, "error": str(e)}}

    if inp.op == "status":
        try:
            d = game_dir(inp.appid, ctx.config)
            return {"result": {"appid": inp.appid, "title": inp.title, "game_dir": str(d), "installed": True,
                               "engine": engine_version(d), "safety": safety(d), "paks": len(run_pak_index(d))}}
        except FileNotFoundError as e:
            return {"result": {"appid": inp.appid, "title": inp.title, "installed": False, "error": str(e)}}

    if inp.op == "pak_index":
        d = game_dir(inp.appid, ctx.config)
        s = safety(d)
        return {"result": {"appid": inp.appid, "title": inp.title, "installed": True, "safety": s,
                           "paks": run_pak_index(d)}}

    if inp.op == "analyze":
        d = game_dir(inp.appid, ctx.config)
        r = run_static_analysis(d, ctx, include_dlls=inp.include_dlls, max_binaries=inp.max_binaries)
        r["appid"] = inp.appid
        r["title"] = inp.title
        return {"result": r}

    if inp.op == "extract_assets":
        d = game_dir(inp.appid, ctx.config)
        s = safety(d)
        if not s["ok"]:
            return {"result": {"safe": False, **s, "note": "asset extraction is blocked because the game has anti-cheat indicators"}}
        paks = run_pak_index(d)
        return {"result": {"safe": True, "paks": paks, "note": "asset extraction not yet implemented (this run adds static analysis only)"}}

    raise ValueError(f"unknown op {inp.op}")


try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    pass
