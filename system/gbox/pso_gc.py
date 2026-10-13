"""Phantasy Star Online Episode I & II Plus (GameCube) — player-character reader.

Owned source: GPOE8P (USA), sha256 2f1c56b66f2143ed7b15a75c071116b08d6578f16b569f2e831011ad32e1f963.

Stage: analysis probe.  Verifies that the PSO GC player bodies are Ninja chunk models
(pl<bdy>.nj) that decode with gbox.ninja (big-endian node structs) and exports an editable
UAP/glTF of the body.  Heads/hair/caps are separate single-node NJ files that attach to the
body at a mount node (HUcast-style node 59 is reused for the humanoid classes here).

The real game executable is PsoV3.dol (sha256 1f80fb82...), not main.dol; main.dol is only
the AppSwitcher bootstrap.  Ghidra analysis of PsoV3.dol locates the asset loaders at
FUN_8001f018 (textures), FUN_8001f128 (BML/model) and FUN_8001fcc4 (motion).
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from . import gcdisc, ninja, uap

GAME_ID = "GPOE8P"
CLASSES = ["HUmar", "HUnewearl", "HUcast", "RAmar", "RAcast", "RAcaseal", "FOmarl", "FOnewm", "FOnewearl"]
CLASS_LETTER = {c: chr(ord("A") + i) for i, c in enumerate(CLASSES)}
HEAD_MOUNT = {"HUcast": 59, "HUmar": 59}  # same 64-node layout; others mapped when verified


def player_body_nj(disc: gcdisc.GCDisc, cls: str) -> bytes:
    """Return the raw bytes of pl<X>bdy00.nj for a class name/letter."""
    letter = CLASS_LETTER.get(cls, cls).upper()
    return disc.read(f"pl{letter}bdy00.nj")


def player_head_nj(disc: gcdisc.GCDisc, cls: str, head: int = 0) -> bytes:
    letter = CLASS_LETTER.get(cls, cls).upper()
    return disc.read(f"pl{letter}hed{head:02d}.nj")


def read_body(disc: gcdisc.GCDisc, cls: str) -> ninja.NJ:
    """Parse the class body NJCM model (big-endian node structs)."""
    return ninja.NJ(player_body_nj(disc, cls), be=True)


def build_body_manifest(disc: gcdisc.GCDisc, cls: str, out_dir: Path | None = None,
                        name: str | None = None) -> uap.Manifest:
    """UAP manifest for a single class body.  Textures are not decoded yet; material
    slots record the Ninja texture ids so a later writer can bind GVM entries."""
    letter = CLASS_LETTER.get(cls, cls).upper()
    nj = read_body(disc, cls)
    idx = ord(letter) - ord("A")
    name = name or f"pso_gc_{CLASSES[idx].lower() if 0 <= idx < len(CLASSES) else 'pl' + letter.lower()}"
    textures = [""] * 256
    return ninja.to_manifest(nj, name, {
        "game": "Phantasy Star Online Episode I & II Plus (USA) (GC)",
        "game_id": GAME_ID,
        "class": letter,
        "files": [f"pl{letter}bdy00.nj"],
        "extraction_method": "gbox.pso_gc",
    }, textures)


def export_body(disc_path: Path, cls: str, out_dir: Path) -> Path:
    """-> path to the written .glb."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    disc = gcdisc.GCDisc(disc_path)
    m = build_body_manifest(disc, cls, out)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{m.name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


# ---------------------------------------------------------------- texture-list probe (GVM)
def gvm_list(data: bytes) -> dict:
    """Parse just the GVMH header: return {header_size, flags, count, names[]}.  Full GVRT
    decoding is future work; this proves we can identify the texture archive layout.

    Header: "GVMH", u32 LE header size, u16 BE flags, u16 BE count, then per texture
    {u16 BE id, char name[28] (flags & 8), u16 format (& 4), u16 dims (& 2), u32 gbix (& 1)}."""
    if len(data) < 12 or data[:4] != b"GVMH":
        raise ValueError("not a GVM file")
    size = struct.unpack_from("<I", data, 4)[0]
    count = struct.unpack_from(">H", data, 0xA)[0]
    flags = (data[8] | data[9]) & 0x0F       # entry-field bits; taken from either byte of the u16 flag word
    end = min(len(data), 8 + size)
    stride = 2 + (28 if flags & 8 else 0) + (2 if flags & 4 else 0) + (2 if flags & 2 else 0) + (4 if flags & 1 else 0)
    if 12 + count * stride > end:
        raise ValueError(f"{count} GVM entries of {stride} bytes overrun the {size}-byte header")
    names = []
    for i in range(count):
        off = 12 + i * stride + 2
        names.append(data[off:off + 28].split(b"\0")[0].decode("latin-1", "replace")
                     if flags & 8 else f"tex{i}")
    return {"header_size": size, "flags": flags, "count": count, "names": names}


def _selftest():
    import tempfile
    iso = Path.home() / "gbox-cache" / "gc" / "436e0bb84d5337d1" / "disc.iso"
    if not iso.exists():
        print("pso_gc selftest skipped: no owned ISO")
        return
    disc = gcdisc.GCDisc(iso)
    for cls in ["A", "C"]:
        nj = read_body(disc, cls)
        assert len(nj.bones) == 64, (cls, len(nj.bones))
        assert nj.tris, f"{cls}: no triangles"
    with tempfile.TemporaryDirectory() as td:
        glb = export_body(iso, "HUcast", Path(td) / "out")
        assert glb.exists() and glb.stat().st_size > 0
        print("pso_gc selftest ok:", glb, glb.stat().st_size)


if __name__ == "__main__":
    _selftest()
