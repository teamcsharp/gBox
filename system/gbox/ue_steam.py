"""Generic Unreal Engine 4/5 Steam game analysis: locate, safety-check, index pak files,
and find actor/locomotion/animation symbols through static Ghidra analysis.

Scope for this run:
- Read-only discovery of the operator's own Steam install.
- Refuse any game that ships an anti-cheat (BattlEye, EasyAntiCheat, XignCode, etc.) or
  that is currently running with a protected process.
- PUBG (Steam app 578080) is the example target; if it is not installed or has anti-cheat,
  the tool reports that cleanly instead of trying to bypass anything.

Pak contents (ue_pak / ue_asset / ue_mesh, docs/ue_steam.md):
- list_files / inventory / extract / export over unencrypted .pak archives (v1-v11): the actor and animation
  inventory (SkeletalMesh, Skeleton, AnimSequence/Montage/BlendSpace, AnimBlueprint, pawn Blueprints) as a JSON
  manifest, raw .uasset/.uexp/.ubulk extraction, and UE 4.24-4.27 skeletal meshes as rigged GLB.

Future stages can add:
- IoStore (.utoc/.ucas zen packages) reading, AnimSequence track decoding, UE5 meshes.
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

from .catalog import default_steam_root, parse_vdf
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
    """The configured Steam root, else the install the Windows registry names (catalog.default_steam_root)."""
    if cfg is not None and getattr(cfg, "steam_root", None):
        return Path(cfg.steam_root)
    return default_steam_root()


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


def _anticheat_scan(gd: Path, max_files: int = 500, max_depth: int = 4, max_entries: int = 50000) -> list[str]:
    """Scan file and folder names down to <Game>/Binaries/Win64/<AntiCheat>/ (depth 4) for anti-cheat indicators.

    UE games keep BattlEye / EasyAntiCheat next to the shipping exe (PUBG: TslGame/Binaries/Win64/BattlEye), so a
    one-level scan misses them. Content trees are skipped (only paks live there) to keep this cheap."""
    hits, seen = [], 0
    stack = [(Path(gd), 0)]
    while stack and len(hits) < max_files and seen < max_entries:
        d, depth = stack.pop()
        try:
            children = list(os.scandir(d))
        except OSError:
            continue
        for c in children:
            seen += 1
            if ANTICHEAT.search(c.name):
                hits.append(Path(c.path).relative_to(gd).as_posix())
                if len(hits) >= max_files:
                    break
            try:
                is_dir = c.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir and depth + 1 < max_depth and c.name.lower() not in ("content", "movies", "paks"):
                stack.append((Path(c.path), depth + 1))
    return sorted(hits)


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
    # Shipped games have no Build.version; the small launcher exe in the game root carries the engine release string
    # ("UE4+Release-4.27", UTF-16) and the engine version in its version resource.
    for launcher in sorted(gd.glob("*.exe")):
        rel = _exe_release(launcher)
        if rel:
            return rel
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


def _exe_release(exe: Path, max_size: int = 8 << 20) -> dict | None:
    """'UE4+Release-4.27' (UTF-16) in a launcher exe, plus the patch number from VS_FIXEDFILEINFO when it agrees."""
    try:
        if not exe.is_file() or exe.stat().st_size > max_size or ANTICHEAT.search(exe.name):
            return None
        blob = exe.read_bytes()
    except OSError:
        return None
    text = blob.decode("utf-16-le", "ignore") if b"U\x00E\x00" in blob else ""
    m = re.search(r"UE([45])\+Release-(\d)\.(\d+)", text)
    if not m:
        text = blob[1:].decode("utf-16-le", "ignore")
        m = re.search(r"UE([45])\+Release-(\d)\.(\d+)", text)
    if not m:
        return None
    major, minor, patch = int(m.group(2)), int(m.group(3)), None
    vi = blob.find("VS_VERSION_INFO".encode("utf-16-le"))
    fixed = blob.find(b"\xbd\x04\xef\xfe", vi) if vi >= 0 else -1
    if fixed >= 0 and fixed + 16 <= len(blob):
        ms, ls = int.from_bytes(blob[fixed + 8:fixed + 12], "little"), int.from_bytes(blob[fixed + 12:fixed + 16], "little")
        if (ms >> 16, ms & 0xFFFF) == (major, minor):
            patch = ls >> 16
    return {"source": f"{exe.name} release string", "major": major, "minor": minor, "patch": patch,
            "version": f"{major}.{minor}" + (f".{patch}" if patch is not None else "")}


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


def _pak_count(gd: Path) -> int:
    """How many .pak files the install has, without reading them (status must stay cheap on a 30 GB game)."""
    return sum(1 for p in gd.rglob("*.pak") if p.is_file())


def run_pak_index(gd: Path) -> list[dict]:
    """List .pak files with sizes; newest patch last."""
    paks = sorted(gd.rglob("*.pak"), key=lambda p: p.name)
    return [{"path": p.relative_to(gd).as_posix(), "size": p.stat().st_size,
             "sha256": _sha256(p) if p.stat().st_size < 512 * 1024 * 1024 else None}
            for p in paks]


# ---------------------------------------------------------------------- pak contents (inventory / extract / export)

# Oldest engine that writes each pak version; used only when the executable names no engine version.
PAK_ENGINE_GUESS = {1: (4, 0), 2: (4, 0), 3: (4, 15), 4: (4, 19), 5: (4, 20), 6: (4, 20), 7: (4, 21), 8: (4, 23),
                    9: (4, 25), 10: (4, 25), 11: (4, 27)}
ASSET_EXTS = (".uasset", ".uexp", ".ubulk")


class GameArchive:
    """Every Unreal .pak of an install, opened read-only and merged in mount order (patch paks override)."""

    def __init__(self, gd: Path):
        from . import ue_pak
        self.gd = Path(gd)
        self.paks, self.status, self.entries = [], [], {}
        for p in sorted(self.gd.rglob("*.pak"), key=ue_pak.pak_priority):
            if not p.is_file():
                continue
            pf, s = ue_pak.open_pak(p, self.gd)
            s["path"] = p.relative_to(self.gd).as_posix()
            self.status.append(s)
            if pf is None:
                continue
            self.paks.append(pf)
            for name, e in pf.entries.items():
                if e.deleted:
                    self.entries.pop(name, None)
                else:
                    self.entries[name] = (pf, e)

    def read(self, name: str) -> bytes:
        pf, e = self.entries[name]
        return pf.read(e)

    def size(self, name: str) -> int | None:
        hit = self.entries.get(name)
        return hit[1].usize if hit else None

    def close(self):
        for pf in self.paks:
            pf.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def resolve_engine(gd: Path, hint: str = "", pak_status: list[dict] | None = None) -> dict:
    """Engine (major, minor) for unversioned packages: explicit hint, else the executable, else the pak version."""
    m = re.match(r"^\s*(\d)\.(\d+)", hint or "")
    if m:
        return {"major": int(m.group(1)), "minor": int(m.group(2)), "source": "engine hint"}
    ev = engine_version(gd)
    if ev.get("major") in (4, 5) and ev.get("minor") is not None:
        return {"major": ev["major"], "minor": ev["minor"], "source": ev["source"], "version": ev["version"]}
    versions = [s["version"] for s in pak_status or [] if s.get("status") == "ok" and s.get("version")]
    if versions:
        major, minor = PAK_ENGINE_GUESS.get(max(versions), (4, 27))
        return {"major": major, "minor": minor, "source": f"guessed from pak v{max(versions)} (pass engine=\"4.xx\")"}
    return {"major": None, "minor": None, "source": None}


def work_dir(cfg, appid: str, gd: Path, out_dir: str = "") -> Path:
    """Where extracted files go: never inside the game install (the install is read-only for gBox)."""
    base = Path(out_dir) if out_dir else Path(getattr(cfg, "data_dir", "gbox-data")) / "ue_steam" / str(appid)
    out = base.resolve()
    if out.is_relative_to(Path(gd).resolve()):
        raise ValueError(f"refusing to write into the game install ({out}); choose a work directory outside it")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _pawnish(name: str, supers: dict[str, str]) -> str | None:
    """Walk blueprint super classes (collected across the inventory) to a native pawn base, if any."""
    from .ue_asset import PAWN_BASES
    seen = set()
    while name and name not in seen:
        seen.add(name)
        if name in PAWN_BASES:
            return name
        if name not in supers:      # native (C++) game class: Character/Pawn subclasses keep the suffix by convention
            return name if re.search(r"(Character|Pawn)$", name) else None
        name = supers[name]
    return None


def run_inventory(arch: GameArchive, engine: tuple, patterns: list[str] | None = None, max_packages: int = 100000,
                  ctx: Ctx | None = None) -> dict:
    """Parse every matching .uasset header and group SkeletalMesh / Skeleton / animation / blueprint exports."""
    from . import ue_asset, ue_pak
    names = sorted(n for n in arch.entries if n.endswith((".uasset", ".umap")) and ue_pak.match(n, patterns))
    assets: dict[str, list] = {k: [] for k in ("skeletal_mesh", "skeleton", "animation", "anim_blueprint",
                                               "physics_asset", "blueprint_class")}
    failures, encrypted, scanned = [], 0, 0
    for i, name in enumerate(names[:max_packages]):
        if ctx and i % 500 == 0:
            ctx.progress(10 + 80 * i / max(1, min(len(names), max_packages)), f"inventory {i}/{len(names)}")
        scanned += 1
        try:
            pkg = ue_asset.parse_package(arch.read(name), engine)
        except ue_pak.PakEncrypted:
            encrypted += 1
            continue
        except (ue_pak.PakError, ValueError) as e:
            if len(failures) < 50:
                failures.append({"package": name, "error": str(e)[:200]})
            continue
        base = name.rsplit(".", 1)[0]
        for row in ue_asset.classify(pkg):
            row["package"] = base
            row["uexp_size"] = arch.size(base + ".uexp")
            row["ubulk_size"] = arch.size(base + ".ubulk")
            assets[row.pop("kind")].append(row)
    supers = {r["export"]: r.get("super", "") for r in assets["blueprint_class"] + assets["anim_blueprint"]}
    actors = []
    for r in assets["blueprint_class"]:
        base = _pawnish(r["export"], supers)
        uses = r.get("uses", {})
        if base or uses.get("skeletal_mesh") or uses.get("anim_blueprint"):
            actors.append({"class": r["export"], "package": r["package"], "super": r.get("super"),
                           "kind": "pawn" if base else "skeletal_actor", "pawn_base": base,
                           "skeletal_meshes": uses.get("skeletal_mesh", []),
                           "anim_blueprints": uses.get("anim_blueprint", [])})
    return {"schema": "gbox.ue_inventory/1", "engine": {"major": engine[0], "minor": engine[1]},
            "packages_total": len(names), "packages_scanned": scanned, "packages_encrypted": encrypted,
            "packages_failed": len(failures), "failures": failures,
            "counts": {k: len(v) for k, v in assets.items()} | {
                "pawn_actors": sum(1 for a in actors if a["kind"] == "pawn"),
                "skeletal_actors": sum(1 for a in actors if a["kind"] == "skeletal_actor")},
            "actors": actors, "assets": assets}


def run_extract(arch: GameArchive, patterns: list[str], out: Path, exts=ASSET_EXTS, max_files: int = 200,
                max_bytes: int = 2 << 30) -> dict:
    """Copy matching entries (uncompressed) under out/files/<archive path>. Read-only on the install."""
    from . import ue_pak
    root = out / "files"
    done, skipped, total = [], [], 0
    for name in sorted(arch.entries):
        if not name.lower().endswith(tuple(exts)) or not ue_pak.match(name, patterns):
            continue
        if len(done) >= max_files:
            skipped.append({"path": name, "reason": f"max_files={max_files} reached"})
            continue
        size = arch.size(name) or 0
        if total + size > max_bytes:
            skipped.append({"path": name, "reason": f"max_bytes={max_bytes} reached"})
            continue
        try:
            dest = ue_pak.safe_out_path(root, name)
            data = arch.read(name)
        except ue_pak.PakError as e:
            skipped.append({"path": name, "reason": str(e)[:200]})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        total += len(data)
        done.append({"path": name, "size": len(data), "file": str(dest)})
    return {"out_dir": str(root), "extracted": done, "bytes": total, "skipped": skipped[:200],
            "skipped_count": len(skipped)}


def run_export(arch: GameArchive, engine: tuple, patterns: list[str], out: Path, max_files: int = 20,
               ctx: Ctx | None = None) -> dict:
    """SkeletalMesh exports -> rigged GLB (+ JSON report); Skeleton exports -> bone JSON. Blockers are reported."""
    from . import ue_asset, ue_mesh, ue_pak
    gdir = out / "glb"
    gdir.mkdir(parents=True, exist_ok=True)
    results, blockers, used = [], {}, set()
    names = sorted(n for n in arch.entries if n.endswith(".uasset") and ue_pak.match(n, patterns))
    for name in names:
        if len([r for r in results if r.get("glb") or r.get("skeleton_json")]) >= max_files:
            break
        try:
            ua = arch.read(name)
            pkg = ue_asset.parse_package(ua, engine)
        except ue_pak.PakError as e:
            results.append({"package": name, "error": str(e)[:200]})
            continue
        wanted = [(i, e) for i, e in enumerate(pkg.exports, 1) if e.class_name in ("SkeletalMesh", "Skeleton")]
        if not wanted:
            continue
        base = name[:-len(".uasset")]
        try:
            uexp = arch.read(base + ".uexp") if base + ".uexp" in arch.entries else None
            ubulk = arch.read(base + ".ubulk") if base + ".ubulk" in arch.entries else None
        except ue_pak.PakError as e:
            results.append({"package": base, "error": str(e)[:200]})
            continue
        for i, e in wanted:
            stem = re.sub(r"[^A-Za-z0-9_.-]", "_", e.name)
            k = 2
            while stem in used:            # same asset name in two packages (e.g. two SK_Mannequin copies)
                stem = re.sub(r"[^A-Za-z0-9_.-]", "_", e.name) + f"_{k}"
                k += 1
            used.add(stem)
            row = {"package": base, "export": e.name, "class": e.class_name}
            try:
                if e.class_name == "Skeleton":
                    bones = ue_mesh.skeleton_from_export(pkg, ue_asset.export_body(pkg, e, ua, uexp), e.flags)
                    p = gdir / f"{stem}.skeleton.json"
                    p.write_text(json.dumps({"package": base, "skeleton": e.name, "bones": bones}, indent=1))
                    row.update(bones=len(bones), skeleton_json=str(p))
                else:
                    m = ue_mesh.parse_skeletal_mesh(pkg, i, ua, uexp, ubulk, engine)
                    p = ue_mesh.to_glb(m, gdir / f"{stem}.glb")
                    rep = ue_mesh.mesh_report(m)
                    (gdir / f"{stem}.json").write_text(json.dumps({"package": base, **rep}, indent=1))
                    row.update(rep, glb=str(p), glb_size=p.stat().st_size)
                    if ctx is not None and sum(1 for r in results if r.get("glb")) < 20 and row["glb_size"] < 64 << 20:
                        ctx.artifact(f"{stem}.glb", p.read_bytes(), "model/gltf-binary", source=f"{base}:{e.name}")
            except ue_mesh.MeshUnsupported as x:
                row["blocker"] = str(x)
                blockers[str(x)] = blockers.get(str(x), 0) + 1
            except (ue_pak.PakError, ValueError, IndexError) as x:
                row["error"] = f"{type(x).__name__}: {str(x)[:200]}"
            results.append(row)
            if ctx:
                ctx.progress(min(95, 10 + 85 * len(results) / max(1, max_files)), f"export {e.name}")
    return {"out_dir": str(gdir), "results": results, "blockers": blockers,
            "glb_count": sum(1 for r in results if r.get("glb")),
            "skeleton_count": sum(1 for r in results if r.get("skeleton_json"))}


class UESteamIn(BaseModel):
    # status | locate | analyze | pak_index | list_files | inventory | extract (alias extract_assets) | export
    op: str = "status"
    appid: str = APPID_PUBG                 # Steam appid to target
    title: str = TITLE_PUBG                 # human-readable title used when not installed
    include_dlls: bool = True
    max_binaries: int = 5
    engine: str = ""                        # engine override for unversioned packages, e.g. "4.27"
    paths: list[str] = []                   # in-pak path globs/substrings (list_files, inventory, extract, export)
    extensions: list[str] = []              # extract: file types (default .uasset .uexp .ubulk)
    max_files: int = 200                    # list_files rows / extract files / export assets
    max_packages: int = 100000              # inventory: package headers to parse
    out_dir: str = ""                       # work dir (default <data_dir>/ue_steam/<appid>); never inside the game


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
      side_effects=["static Ghidra analysis of owned game files only; never launches or injects into the game",
                    "reads .pak archives read-only and writes extracted files / GLBs to a work dir outside the install",
                    "Oodle paks: loads the game's own oo2core DLL (from the game folder only) to decompress"])
def ue_steam_tool(inp: UESteamIn, ctx: Ctx):
    """Static analysis of an Unreal Engine Steam game: locate, safety-check, index paks, infer locomotion/animation
    symbols, and read unencrypted paks: list files, inventory actors/meshes/skeletons/animations, extract assets,
    export UE 4.24-4.27 skeletal meshes to rigged GLB. Refuses anti-cheat games."""
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
                               "engine": engine_version(d), "safety": safety(d), "paks": _pak_count(d)}}
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

    if inp.op in ("list_files", "inventory", "extract", "extract_assets", "export"):
        return {"result": _pak_op(inp, ctx)}

    raise ValueError(f"unknown op {inp.op}")


def _pak_op(inp: UESteamIn, ctx: Ctx) -> dict:
    """list_files / inventory / extract / export over the install's paks. Anti-cheat games are refused before any
    archive is opened; the install is only ever opened read-only; output goes to a work dir outside it."""
    from . import ue_pak
    d = game_dir(inp.appid, ctx.config)
    s = safety(d)
    head = {"appid": inp.appid, "title": inp.title, "game_dir": str(d), "op": inp.op}
    if not s["ok"]:
        return {**head, "safe": False, **s,
                "note": "blocked: anti-cheat indicators or a running game process; gBox does not open this game's archives"}
    ctx.progress(2, "opening pak files")
    with GameArchive(d) as arch:
        eng = resolve_engine(d, inp.engine, arch.status)
        engine = (eng["major"], eng["minor"])
        iostore = ue_pak.list_iostore(d)
        head.update(safe=True, engine=eng, paks=[p for p in arch.status if p.get("status") != "not_unreal"],
                    iostore=iostore, files=len(arch.entries))
        if not arch.paks and not iostore:
            return {**head, "error": "no readable Unreal pak files (see paks for encrypted/unsupported status)"}
        if iostore:
            head["iostore_note"] = (f"{len(iostore)} IoStore container(s) listed; their packages are not read yet "
                                    "(zen package reading is the next stage)")
        patterns = [p for p in inp.paths if p]
        if inp.op == "list_files":
            rows = [e.summary() for n, (_pf, e) in sorted(arch.entries.items()) if ue_pak.match(n, patterns)]
            return {**head, "matched": len(rows), "entries": rows[:inp.max_files], "truncated": len(rows) > inp.max_files}
        out = work_dir(ctx.config, inp.appid, d, inp.out_dir)
        head["work_dir"] = str(out)
        if inp.op == "inventory":
            man = run_inventory(arch, engine, patterns, inp.max_packages, ctx)
            man.update(appid=inp.appid, title=inp.title, game_dir=str(d), engine=eng, paks=head["paks"],
                       iostore=iostore)
            path = out / "inventory.json"
            blob = json.dumps(man, indent=1).encode()
            path.write_bytes(blob)
            ctx.artifact("ue_inventory.json", blob, "application/json", appid=inp.appid)
            sample = {k: v[:25] for k, v in man["assets"].items()}
            return {**head, "manifest": str(path), "counts": man["counts"],
                    "packages_scanned": man["packages_scanned"], "packages_encrypted": man["packages_encrypted"],
                    "packages_failed": man["packages_failed"], "failures": man["failures"][:10],
                    "actors": man["actors"][:100], "sample": sample}
        if inp.op in ("extract", "extract_assets"):
            if not patterns:
                return {**head, "error": "extract needs paths=[...] (glob or substring of the in-pak path)"}
            exts = tuple(x if x.startswith(".") else "." + x for x in inp.extensions) or ASSET_EXTS
            return {**head, **run_extract(arch, patterns, out, exts, inp.max_files)}
        return {**head, **run_export(arch, engine, patterns, out, inp.max_files, ctx)}
