"""Resident Evil 4: Wii Edition (catalog 79c3a3eccb34fe62; the image's header says RB4P08, the PAL disc, English).

The Wii build uses the GameCube file formats (em/pl*.drs player packs are the same DAT/BIN/TPL layout, same item
order, a few KB larger), so gbox/re4gc_models.py + char_swap.swap_packs write the Wii packs unchanged.
A Wii disc is encrypted, so mods are not patched into the image: the disc is extracted once per node with
dolphin-tool (cache/modbase/<game_id>/disc: DATA/sys/main.dol, DATA/files/...), each mod is a tree of hard links to
it with only the replaced files copied (cache/mods/<game_id>/<mod>/disc), and Dolphin boots DATA/sys/main.dol of the
mod tree as an extracted disc (DirectoryBlob). No size limit on the Wii side (not a fixed-size disc).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

GAME_IDS = {"79c3a3eccb34fe62": "Resident Evil 4: Wii Edition (USA)"}
FLATPAK = "org.DolphinEmu.dolphin-emu"
BOOT = "disc/DATA/sys/main.dol"


def _tool_argv(cfg, src: Path, out: Path) -> list[str]:
    win = Path(cfg.runtime) / "dolphin" / "Dolphin-x64" / "DolphinTool.exe"
    if os.name == "nt":
        if not win.is_file():
            raise FileNotFoundError("DolphinTool.exe isn't in runtime/dolphin/Dolphin-x64 on this PC")
        return [str(win), "extract", "-q", "-i", str(src), "-o", str(out)]
    return ["flatpak", "run", f"--filesystem={out.parent}", f"--filesystem={src.parent}:ro", "--command=dolphin-tool",
            FLATPAK, "extract", "-q", "-i", str(src), "-o", str(out)]


def ensure_base(cfg, game_id: str, rom: Path, progress=None) -> Path:
    """The extracted disc (all partitions) once per node: cache/modbase/<game_id>/disc."""
    from . import filemods
    root = filemods.base_dir(cfg, game_id)
    disc, marker = root / "disc", root / ".gbox-base-complete"
    if marker.exists():
        want = json.loads(marker.read_text()).get("files", 0)
        if sum(1 for p in disc.rglob("*") if p.is_file()) >= want:
            return disc
    if disc.exists():                                     # incomplete (or files evicted): extract again
        shutil.rmtree(disc)
    root.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(5, f"Extracting the Wii disc {Path(rom).name} (dolphin-tool, ~5 min)")
    r = subprocess.run(_tool_argv(cfg, Path(rom), disc), capture_output=True, text=True, timeout=3600)
    if r.returncode or not (disc / "DATA" / "sys" / "main.dol").is_file():
        raise RuntimeError(f"dolphin-tool extract failed: {(r.stderr or r.stdout)[-400:]}")
    marker.write_text(json.dumps({"files": sum(1 for p in disc.rglob("*") if p.is_file()), "rom": str(rom)}))
    return disc


def _files_dir(disc: Path) -> Path:
    return disc / "DATA" / "files"


def disc_path(disc: Path, name: str) -> Path:
    """'em/pl00.drs' -> DATA/files/Em/pl00.drs (the Wii disc capitalises some folders)."""
    p = _files_dir(disc)
    for part in Path(name).parts:
        hit = next((c for c in p.iterdir() if c.name.lower() == part.lower()), None) if p.is_dir() else None
        if hit is None:
            raise FileNotFoundError(f"{name} is not on the Wii disc")
        p = hit
    return p


class FolderDisc:
    """The GCDisc read interface over an extracted disc folder (char_swap.swap_packs, re4gc_models.load_pack_from_iso)."""

    def __init__(self, disc: Path):
        self.disc = Path(disc)
        self.f = self                                    # GCDisc users call disc.f.close()

    def read(self, name: str) -> bytes:
        return disc_path(self.disc, name).read_bytes()

    def close(self):
        pass


def build_mod(cfg, game_id: str, disc: Path, name: str, changes: dict[str, Path], meta: dict | None = None) -> dict:
    """Hard-link tree of the extracted disc with `changes` ({'em/pl00.drs': local file}) copied in. Launch with
    launch_game(mod=name): filemods.launch_path -> <mod>/disc/DATA/sys/main.dol."""
    from . import filemods
    out = filemods.mod_dir(cfg, game_id, name)
    if out.exists():
        shutil.rmtree(out)
    repl = {disc_path(disc, k).resolve(): Path(v) for k, v in changes.items()}
    for f in disc.rglob("*"):
        t = out / "disc" / f.relative_to(disc)
        if f.is_dir():
            t.mkdir(parents=True, exist_ok=True)
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        src = repl.get(f.resolve())
        shutil.copy2(src, t) if src else os.link(f, t)
    (out / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": game_id, "image": BOOT, "files": sorted(changes),
                                                    "built": time.time(), **(meta or {})}))
    return {"mod": name, "dir": str(out), "image": BOOT, "files": sorted(changes)}
