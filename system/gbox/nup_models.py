"""Model sources inside an extracted NUP: find, extract and hand off to the model pipeline.

The operator's Switch titles are RE Engine games (RE4 Remake on Switch 2) and MT Framework games (RE5/RE6 on Switch 1).
Neither keeps meshes as loose files: RE Engine packs them into `re_chunk_000.pak*` (magic `KPKA`), MT Framework into
`.arc` archives (magic `ARC\\0`, gbox.mt_arc). So "extract the models" means two steps, and this module owns both:

1. **out of the container** - pull every model-bearing container and loose model file out of the NUP's `romfs/` into
   `<game dir>/models_src/` (with a manifest, sizes and the container hashes the TOC already carries). This is the step
   that needs the NUP and nothing else; it runs on Linux or Windows.
2. **into gBox's collection** - the container is unpacked and converted to GLB by the existing toolchain
   (gbox.re4r: ree-pak-cli + RE Mesh Editor in Blender for RE Engine; gbox.mt_arc/mt_model for MT Framework), then
   `characters op=add path=<glb>` registers it as a donor. This module reports exactly which reader/tool takes each
   container, and refuses to pretend an unknown Switch 2 mesh format was converted.

`extract_models` is what `switch_nup op=models` calls; a materialised title folder (`<game dir>/romfs`) is accepted too,
in which case the containers are already on disk and only the manifest/hand-off is built.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import nup

MODEL_SUFFIXES = {".glb", ".gltf", ".fbx", ".obj", ".dae", ".ply", ".smd", ".psk", ".mdl", ".mod", ".mrl",
                  ".mesh", ".skel", ".mot", ".motlist", ".anim", ".anm"}
CONTAINER_SUFFIXES = {".pak", ".arc", ".pkg", ".cpk", ".bundle", ".assets", ".fpk", ".big", ".bnd", ".sarc"}
SKIP_DIRS = {"__macosx", ".git"}                       # dump-tool litter, never game content
MANIFEST = "manifest.json"
SRC = "models_src"
HASH_LIMIT = 256 << 20                                 # hash loose files up to 256 MB; containers use the TOC hash
_MAGICS = ((b"KPKA", "re-engine-pak"), (b"ARC\x00", "mt-framework-arc"), (b"PK\x03\x04", "zip"),
           (b"NUP\x01", "nup"), (b"PFS0", "pfs0"), (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8", "jpeg"))


def classify(relpath: str) -> str | None:
    """'container' | 'model' | None for one RomFS path (case-insensitive; directories are never passed here)."""
    low = relpath.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    if any(part in SKIP_DIRS for part in low.split("/")[:-1]):
        return None
    if ".mesh." in name:                               # RE4 Remake PC: xx.mesh.221108797; Switch has its own suffix
        return "model"
    ext = Path(name).suffix
    if ext in MODEL_SUFFIXES:
        return "model"
    if name.startswith("re_chunk_000.pak") or ext in CONTAINER_SUFFIXES:
        return "container"
    return None


def magic_kind(head: bytes) -> str:
    for magic, kind in _MAGICS:
        if head.startswith(magic):
            return kind
    return "unknown"


def _converter(kind: str, name: str = "") -> dict:
    """Which gBox reader/converter takes this container next (never a claim that it already succeeded)."""
    if kind == "re-engine-pak":
        return {"reader": "gbox.re4r (ree-pak-cli unpack + RE Mesh Editor in Blender)",
                "needs": "a Windows worker with the re4r tools (op=install) and the title's PAK list",
                "then": "characters op=add path=<exported .glb> (or re4r op=export for a known character)"}
    if kind == "mt-framework-arc":
        return {"reader": "gbox.mt_arc / gbox.mt_model (entries: MRL model, MOD mesh, textures)",
                "needs": "Linux or Windows (pure Python)",
                "then": "gbox.re4_switch_models / model_swap for an in-slot swap, or characters op=add for a GLB"}
    if kind == "zip":
        return {"reader": "zipfile (an archive inside the dump, not a game model container)",
                "needs": "none", "then": "unpack it and re-run models on the result"}
    return {"reader": "none yet", "needs": "a reader for this container's format",
            "then": f"report the container ({name}) so the format can be mapped"}


def _plan_reader(reader: nup.NupReader, package: nup.NupPackage, subtree: str, containers: bool,
                 extra_patterns: list[str] | None) -> list[tuple[str, int, nup.NupFile, str]]:
    base = ""
    if subtree:
        node = reader.resolve(package, subtree)
        if node is not None:
            base = subtree.replace("\\", "/").strip("/").lower()
    patterns = [re.compile(p, re.I) for p in (extra_patterns or [])]
    out = []
    for rel, fi, f in reader.walk_indexed(package):
        low = rel.lower()
        if base and not (low == base or low.startswith(base + "/")):
            continue
        inner = rel[len(base) + 1:] if base else rel
        kind = classify(inner)
        if kind == "container" and not containers:
            kind = None
        if kind is None and patterns and any(p.search(inner) for p in patterns):
            kind = "model"
        if kind:
            out.append((rel, fi, f, kind))
    return out


def extract_from_reader(reader: nup.NupReader, package: nup.NupPackage | list[nup.NupPackage],
                        out: str | Path, *, subtree: str = "romfs", extra_patterns: list[str] | None = None,
                        containers: bool = True, progress=None, cancel=None) -> dict:
    """Extract the model sources of one or more packages into `<out>/models_src` and write the manifest.

    A list is read in order (base, then updates): a later package's file at the same path shadows the earlier one,
    the same way an update overlays its base at boot, so a title whose models were patched ships the patched ones.
    """
    packages = package if isinstance(package, (list, tuple)) else [package]
    found: dict[str, tuple[int, nup.NupFile, str]] = {}
    for pkg in packages:
        for rel, fi, f, kind in _plan_reader(reader, pkg, subtree, containers, extra_patterns):
            found[rel] = (fi, f, kind)
    if not found:
        where = subtree or "the package"
        raise nup.NupError(f"{reader.path.name}: no model containers or model files under {where}")
    prefix = SRC
    plan = [nup.PlannedFile(fi, f"{prefix}/{rel}", f.size) for rel, (fi, f, _kind) in found.items()]

    def report(ev: dict) -> None:
        if progress:
            progress(ev.get("percent", 0.0), f"{ev.get('file', '')} ({ev.get('files_done', 0)}/"
                                             f"{ev.get('files_total', 0)})")

    started = time.time()
    result = reader.extract(out, plan=plan, overwrite=True, verify=True, progress=report, cancel=cancel)
    rows = []
    for rel, (fi, f, kind) in found.items():
        head = reader.head(fi, 16) if f.size else b""
        magic = magic_kind(head)
        rows.append({"rel": rel, "kind": kind, "file": f"{prefix}/{rel}", "bytes": f.size,
                     "sha256": f.sha256_hex, "magic": magic, "codec": f.codec_name,
                     "container": _converter(magic, Path(rel).name) if kind == "container" else None})
    primary = packages[0]
    manifest = _manifest("nup", reader.path, out, rows, {
        "title_id": primary.title_id_hex, "kind_name": primary.kind_name,
        "display_version": (reader.meta(primary).get(nup.TLV_DISPLAY_VERSION) or b"").decode("utf-8", "replace") or None,
        "title": reader.title_name(primary),
        "packages": [{"index": p.index, "kind": p.kind_name, "title_id": p.title_id_hex, "version": p.version}
                     for p in packages],
    })
    return result | {"manifest": str(Path(out) / SRC / MANIFEST), "models": manifest["models"],
                     "containers": manifest["containers"], "next": manifest["next"],
                     "elapsed_s": round(time.time() - started, 2)}


def extract_from_folder(folder: str | Path, out: str | Path, *, extra_patterns: list[str] | None = None,
                        containers: bool = True, progress=None, cancel=None) -> dict:
    """Same selection over an already materialised title folder; copies nothing when `out` is that folder."""
    root = Path(folder)
    romfs = root / "romfs" if (root / "romfs").is_dir() else root
    patterns = [re.compile(p, re.I) for p in (extra_patterns or [])]
    found = []
    for dirpath, dirs, names in os.walk(romfs):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        for name in names:
            path = Path(dirpath, name)
            rel = path.relative_to(romfs).as_posix()
            kind = classify(rel)
            if kind == "container" and not containers:
                kind = None
            if kind is None and patterns and any(p.search(rel) for p in patterns):
                kind = "model"
            if kind:
                found.append((rel, path, kind))
    if not found:
        raise nup.NupError(f"{root}: no model containers or model files under {romfs}")
    dest = Path(out) / SRC
    same = dest.resolve() == romfs.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    total = sum(p.stat().st_size for _rel, p, _kind in found)
    done = written = 0
    for rel, path, kind in found:
        if cancel and cancel():
            raise nup.NupCancelled("cancelled by the operator")
        target = romfs / rel if same else dest / rel
        if not same:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target, follow_symlinks=True)
        size = path.stat().st_size
        with path.open("rb") as fh:
            head = fh.read(16)
        digest = None
        if size <= HASH_LIMIT:
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            digest = h.hexdigest()
        magic = magic_kind(head)
        rows.append({"rel": rel, "kind": kind, "file": target.relative_to(Path(out)).as_posix(),
                     "bytes": size, "sha256": digest, "magic": magic, "codec": None,
                     "container": _converter(magic, path.name) if kind == "container" else None})
        done += 1
        written += size
        if progress:
            progress(round(100 * written / total, 1) if total else 100.0,
                     f"{rel} ({done}/{len(found)})")
    manifest = _manifest("folder", root, out, rows, {})
    return {"mode": "folder", "out": str(out), "files": done, "bytes": written, "in_place": same,
            "manifest": str(dest / MANIFEST), "models": manifest["models"], "containers": manifest["containers"],
            "next": manifest["next"], "renamed": []}


def _manifest(source_kind: str, source: Path, out: str | Path, rows: list[dict], title: dict) -> dict:
    containers = [r for r in rows if r["kind"] == "container"]
    models = [r for r in rows if r["kind"] == "model"]
    importable = [r for r in models if Path(r["rel"]).suffix.lower() in (".glb", ".gltf")]
    handoffs = {}
    for row in containers:
        key = row["magic"]
        handoff = row["container"]
        if handoff:
            handoffs.setdefault(key, {"container": handoff, "files": []})["files"].append(row["rel"])
    next_steps = []
    if containers:
        kinds = ", ".join(sorted({r["magic"] for r in containers}))
        next_steps.append(f"unpack the {len(containers)} container(s) ({kinds}) with the reader named in `handoffs`, "
                          "then convert the meshes to GLB")
    if importable:
        next_steps.append(f"{len(importable)} GLB(s) can be registered now: characters op=add path=<glb>")
    if not containers and not importable:
        next_steps.append("no importable model yet: hand the listed files to a format reader before converting")
    manifest = {
        "schema": 1, "kind": "nup-models", "source_kind": source_kind, "source": str(source),
        "created": time.time(), "tool": "gbox.nup_models", **title,
        "counts": {"containers": len(containers), "models": len(models), "importable": len(importable)},
        "containers": containers, "models": models, "handoffs": handoffs, "next": next_steps,
    }
    path = Path(out) / SRC / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
