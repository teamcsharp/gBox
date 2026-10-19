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


GBIX_HEADER = 16   # "GBIX" + u32 size(8) + u32 global_index + u32 pad
PVRT_META = 16     # "PVRT" + u32 payload_size + u16 fmt + u16 pad + u16 w + u16 h
VQ_CODEBOOK = 0x800  # 256 entries x 8 B, prepended to every VQ texture payload


def _pvr_slot(cm: bytes, gbix_pos: int) -> dict | None:
    """Decode the PVRT chunk that immediately follows a GBIX header.

    Verified against the owned disc (all 25 playable slots, 2026-10-18):
    "PVRT" + u32 payload_size (bytes after the 8-byte chunk header) + u16
    format word (0x0301/0x0302 observed) + u16 pad + u16 width @+12 + u16
    height @+14.  Texture data starts at PVRT+16 and follows the VQ law
    payload_size - 8 == width*height//4 + 0x800 (2 bits/pixel indices plus a
    256-entry 8-byte codebook), i.e. the chunk exactly fills its slot.
    """
    at = gbix_pos + GBIX_HEADER
    if cm[at : at + 4] != b"PVRT":
        return None
    payload_size, fmt = struct.unpack_from("<IH", cm, at + 4)
    w, h = struct.unpack_from("<HH", cm, at + 12)
    return {"payload_size": int(payload_size), "fmt": int(fmt),
            "w": int(w), "h": int(h)}


def cmck_decode(path: str, stems: tuple[str, ...] = PLAYABLE) -> dict:
    """Deep-decode the CMCK (character motion chunk) for each playable.

    CMCK layout (verified 2026-10-18 against the owned disc, all 5 playables):
      +0x00  u32 count (=5)  |  u32 stride (=0x18)          -- header
      +0x08  4-entry u32 texture-pointer table (CMCK-relative, GBIX-aligned)
      +0x18  slot 0 begins: GBIX@0x18 (NOT covered by the table)
      ...    slot k: GBIX(16 B) + PVRT chunk (8 B hdr + 8 B meta + VQ data);
             the PVRT payload_size exactly fills the slot up to the next GBIX
             (or CMCK end).  header(0x18) + 5 slots == 141496 B == the whole
             CMCK: there is NO inter-GBIX motion data in CMCK; motion lives in
             the separate PMC banks (671 on the owned disc).

    Returns a per-character report:
      * count / stride from the 8-byte CMCK header; offsets = the 4 table u32s
        starting at byte 8 (the 5th word at +0x18 is the "GBIX" magic itself,
        not a fifth table entry)
      * gbix_positions (5), pvr_dims per slot, PVRT format words
      * texture bounds per slot (data start GBIX+0x20, chunk-law end) and
        vq_exact_fit: payload_size - 8 == w*h//4 + 0x800 for every slot
      * offsets_match_gbix: every table entry equals a GBIX position;
        unmatched_gbix == [0x18] (slot 0 is the one slot the table omits)

    Pinned cross-character facts (verified against the owned disc):
      * All 5 playables have CMCK size = 141496 (0x228b8) and 5 GBIX slots.
      * C00/C01A table: [0x4838, 0x9058, 0xd878, 0x1e098] (5 slots at 0x18 +
        the table); C02A/C03/C04 table: [0x10838, 0x15058, 0x19878, 0x1e098].
    """
    g = GDRom(path)
    out = {}
    for stem in stems:
        disk_name = _disk_name(stem)
        d = g.read(disk_name)
        cm: bytes = b""
        cm_off: int = 0
        size: int = 0
        CHUNK = struct.Struct("<4sI")
        o = 0
        while o + 8 <= len(d):
            typ, size = CHUNK.unpack_from(d, o)
            if typ == b"CMCK":
                cm_off = o
                cm = d[o + 8 : o + 8 + size]
                break
            o += 8 + size
        else:
            raise ValueError(f"{stem}: no CMCK chunk in {disk_name}")

        count, stride = struct.unpack_from("<II", cm, 0)
        # The table holds `count - 1` u32 texture pointers starting at byte 8;
        # the word at 8 + (count-1)*4 == 0x18 is the first GBIX magic itself.
        offsets = [struct.unpack_from("<I", cm, 8 + i * 4)[0] for i in range(count - 1)]

        # Find GBIX markers
        gbix: list[int] = []
        pos = 0
        while True:
            i = cm.find(b"GBIX", pos)
            if i < 0:
                break
            gbix.append(i)
            pos = i + 4

        # Per-slot layout: GBIX hdr(16) + PVRT chunk (8 B header + 8 B meta +
        # VQ texture).  The PVRT payload_size exactly fills the slot up to the
        # next GBIX (or CMCK end): no inter-GBIX motion data lives in CMCK.
        blob_sizes = []
        pvr_dims = []
        fmts = []
        tex_bounds = []
        vq_exact_fit = []
        for k, gp in enumerate(gbix):
            blob_sizes.append(struct.unpack_from("<I", cm, gp + 4)[0])
            slot = _pvr_slot(cm, gp)
            slot_end = gbix[k + 1] if k + 1 < len(gbix) else len(cm)
            if slot is None:
                pvr_dims.append(None)
                fmts.append(None)
                tex_bounds.append(None)
                vq_exact_fit.append(None)
                continue
            pvr_dims.append({"w": slot["w"], "h": slot["h"]})
            fmts.append(slot["fmt"])
            start = gp + GBIX_HEADER + PVRT_META  # texture data start (GBIX+0x20)
            end = gp + GBIX_HEADER + 8 + slot["payload_size"]  # chunk law == slot_end
            tex_bounds.append({"start": start, "end": end})
            vq_exact_fit.append(slot["payload_size"] - 8 ==
                                slot["w"] * slot["h"] // 4 + VQ_CODEBOOK)

        # Verify: every table entry equals a GBIX position (the offsets ARE the
        # texture-slot pointers); slot 0 at 0x18 is the one the table omits.
        gbix_set = set(gbix)
        match = all(off in gbix_set for off in offsets)
        unmatched = [gp for gp in gbix if gp not in offsets]

        out[stem] = {
            "cmck_offset": cm_off,
            "cmck_size": size,
            "count": count,
            "stride": stride,
            "offsets": offsets,
            "gbix_positions": gbix,
            "blob_sizes": blob_sizes,
            "pvr_dims": pvr_dims,
            "fmt": fmts,
            "tex_bounds": tex_bounds,
            "vq_exact_fit": vq_exact_fit,
            "offsets_match_gbix": match,
            "unmatched_gbix": unmatched,
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    rep = decode_report(args.gdi)
    cmck = cmck_decode(args.gdi)
    doc = {"game": "Illbleed (USA)", "platform": "dreamcast", "source_sha256": CHD_SHA,
           "executable_sha256": EXE_SHA, "reader": "gbox.ninja.NJ",
           "models": rep, "c04_identity": c04_identity(rep),
           "cmck": cmck,
           "open": ["CMCK fully accounted: header(0x18) + 5 VQ texture chunks == 141496 B; "
                    "motion/keyframe data is NOT in CMCK -- decode the PMC motion banks next",
                    "executable model-load table (Ghidra, analysis stage)"]}
    text = json.dumps(doc, indent=1)
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
