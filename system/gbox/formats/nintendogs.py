"""Nintendogs (NDS, gamecode ADG*) reader: owned .7z/.nds -> breed slots (DogArc/*.narc) -> editable NSBMD.

Layout measured from the USA Dachshund & Friends ROM: ``DogArc/<Breed>_<variant>.narc`` holds one
``.nsbmd`` (BMD0 model, textured), ``.NCLR`` palette, ``.bncl`` and ``.nce.bncd`` per coat variant;
``Dog/Model/Tan_model.nsbmd`` and ``Dog/Anm/Keep.narc`` / ``Dog/Anm/Load/*.nsbca`` are shared
skeleton/animation assets.
"""
from __future__ import annotations

import hashlib
import struct
import subprocess
import tempfile
from pathlib import Path

from .nitro import NitroROM, narc


def sha256_stream(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_nds_from_7z(archive: str | Path, outdir: str | Path) -> Path:
    """Extract the first .nds member with 7z (gBox cannot list .7z itself)."""
    subprocess.run(["7z", "x", "-y", f"-o{outdir}", str(archive), "*.nds"], check=True, capture_output=True)
    found = sorted(Path(outdir).rglob("*.nds"))
    if not found:
        raise FileNotFoundError("no .nds member in archive")
    return found[0]


def parse_bmd0(blob: bytes) -> dict:
    """NSBMD header: magic, size, and the block table (MDL0 model / TEX0 textures)."""
    if blob[:4] != b"BMD0":
        raise ValueError("not a BMD0/NSBMD")
    bom, ver, size, hsize, nblk = struct.unpack_from("<HHIHH", blob, 4)
    if bom != 0xFEFF or size != len(blob):
        raise ValueError(f"bad BMD0 header bom={bom:#x} size={size} actual={len(blob)}")
    offs = struct.unpack_from(f"<{nblk}I", blob, 16)
    blocks = {}
    for o in offs:
        tag, bsize = blob[o:o + 4].decode("latin-1"), struct.unpack_from("<I", blob, o + 4)[0]
        if o + bsize > len(blob):
            raise ValueError(f"block {tag} overruns file")
        blocks[tag] = (o, bsize)
    return {"size": size, "blocks": blocks}


class Nintendogs:
    def __init__(self, rom_bytes: bytes):
        self.rom = NitroROM(rom_bytes)
        if not self.rom.gamecode.startswith("ADG"):
            raise ValueError(f"not Nintendogs: gamecode {self.rom.gamecode!r}")

    def slots(self) -> list[str]:
        """Breed/coat slot names, e.g. 'Bgl_a'."""
        return [p.split("/")[1][:-5] for p in self.rom.paths() if p.startswith("DogArc/") and p.endswith(".narc")]

    def slot_members(self, slot: str) -> dict[str, bytes]:
        return dict(narc(self.rom.raw(f"DogArc/{slot}.narc")))

    def export_model(self, slot: str) -> tuple[str, bytes, dict]:
        for name, data in self.slot_members(slot).items():
            if name.lower().endswith(".nsbmd"):
                return name, data, parse_bmd0(data)
        raise KeyError(f"slot {slot} has no nsbmd")

    def shared_animations(self) -> list[str]:
        return [p for p in self.rom.paths() if p.startswith("Dog/Anm/Load/") and p.endswith(".nsbca")]
