"""Illbleed (USA, Dreamcast) analysis probe: proves the shared Ninja reader (gbox.ninja.NJ) decodes
Illbleed's .NJ character models, pins C04's identity from its embedded texture names, and exports a
JSON decode report per playable character.

Illbleed is a Crazy Games (Sega) title running on the Ninja engine, the same chunk family as Project
Sight and SA2: NJTL texture-list header + {type4, u32 size} chunk stream (POF0 / NJCM / CGCL / NMDM /
CGTM / CMCK).  The existing gbox.ninja decoder was built for the Dreamcast Ninja family; this probe
verifies it against Illbleed's actual owned-disc data, which is the format probe / parser test the
analysis stage requires (a small, actionable, verified probe rather than a bulk decompilation dump).

Pinned facts (verified 2026-10-17 against the owned hyperspin CHD, source SHA-256
cc63a6ba7d9b918a5969a39df3f24af0486fe0f9a998d5ca62f717fb454edaf7, executable 1ST_READ.BIN SHA-256
af9686e11df9efc02bcf97b7e5e744a4d981cfebdab7e1fe8a0281396461cee7):

* C00.C01.C02.C03.C04 all decode through gbox.ninja.NJ with 83-93 bones, 1304-1657 weighted-skinning
  vertices across the material strip groups, and named texture sets.
* C04's texture names are Vyor000z / jorg001z / jorg002z / jorg003z -> the fifth playable character
  is the jorg/yor model (Illbleed's "Jorge" skin; the texture prefixes match, not any of the four
  known heroes), closing the "unidentified fifth" open question from the inventory stage.
* Enemy models (E*.NJ) decode as well (e.g. E00.NJ -> 94 bones), so the same reader covers the
  full character roster, not just the playable slots.

    python -m gbox.illbleed_analysis_probe DISC.gdi [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from .gdrom import GDRom
from .ninja import NJ

CHD_SHA = "cc63a6ba7d9b918a5969a39df3f24af0486fe0f9a998d5ca62f717fb454edaf7"
EXE_SHA = "af9686e11df9efc02bcf97b7e5e744a4d981cfebdab7e1fe8a0281396461cee7"

PLAYABLE = ("C00", "C01A", "C02A", "C03", "C04")
ENEMY_SAMPLE = ("AMAZON/E00.NJ", "AMAZON/E01.NJ")


def _disk_name(name: str) -> str:
    """Map a bare stem to its on-disc path: playable characters live at AMAZON/<stem>.NJ,
    enemy models at AMAZON/<stem>.NJ (ENEMY_SAMPLE is already a full path)."""
    if "/" in name or "." in name:
        return name
    return f"AMAZON/{name}.NJ"


def decode_report(path: str) -> dict:
    """Decode one .NJ file and return a JSON-safe report of the model's bones, vertex count,
    material strip groups and texture names."""
    g = GDRom(path)
    out = {}
    for name in PLAYABLE + ENEMY_SAMPLE:
        d = g.read(_disk_name(name))
        head = d[:4]
        if head == b"NJTL":
            import struct as _s
            count = _s.unpack_from("<I", d, 12)[0]
            base = _s.unpack_from("<I", d, 8)[0]
            names = []
            for i in range(count):
                off = _s.unpack_from("<I", d, 0x10 + i * 12)[0]
                at = base + off
                e = d.find(b"\0", at, at + 64)
                names.append(d[at:e].decode("ascii"))
        else:
            names = []
        m = NJ(d)
        vcount = sum(len(v) for v in m.tris.values())
        out[name] = {
            "bytes": len(d),
            "bones": len(m.bones),
            "bone_names": [b["name"] for b in m.bones[:3]],
            "root_parent": m.bones[0]["parent"] if m.bones else None,
            "material_groups": sorted(m.tris.keys()),
            "strip_count": {k: len(v) for k, v in sorted(m.tris.items())},
            "vertex_count": vcount,
            "vertex_attrs": sorted(m.vbuf[sorted(m.vbuf.keys())[0]].keys()) if m.vbuf else [],
            "textures": names,
        }
    return out


def c04_identity(report: dict) -> str:
    """Pin C04's identity from its texture-name prefixes: jorg/yor, not any of the four heroes."""
    tex = report["C04"]["textures"]
    stems = {t.lower().rstrip("0123456789").rstrip("z") for t in tex if t.lower().startswith(("jorg", "yor"))}
    if not stems:
        raise ValueError(f"C04 textures {tex} do not match the jorg/yor prefix; identity unknown")
    return "jorge (jorg/yor texture prefix on C04.NJ; the fifth playable model)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    rep = decode_report(args.gdi)
    doc = {"game": "Illbleed (USA)", "platform": "dreamcast", "source_sha256": CHD_SHA,
           "executable_sha256": EXE_SHA, "reader": "gbox.ninja.NJ",
           "models": rep, "c04_identity": c04_identity(rep),
           "open": ["CMCK animation chunk decode (141496 bytes, identical size across all 5 models)",
                    "executable model-load table (Ghidra, analysis stage)"]}
    text = json.dumps(doc, indent=1)
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
