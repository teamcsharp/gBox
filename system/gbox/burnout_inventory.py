"""Burnout (USA, GameCube, GBOE51) -- owned-disc inventory for character-replacement work.

Catalog e827de330b62e67d is the HyperSpin Dolphin GCZ
``collections/Nintendo GameCube/roms/Burnout (USA).gcz`` (885,626,680 bytes).  The GCZ is never
modified; this module reads it in place through ``gcdisc.GCDisc`` (which transparently inflates the
touched 16 KiB blocks via ``gbox.gcz``).  Mod builds later unpack it once with
``filemods.gcz_to_iso`` to ``cache/modbase/<game_id>/<stem>.iso``.

Fingerprint correction (the assimilate fingerprint guessed "RenderWare clump (DFF) x4" for the
models and pointed at ``gbox.gta_rw``/``gbox.gta_vc_models`` -- that is WRONG for the cars).  This
disc stores playable-vehicle assets in Criterion GameCube banks; identifying those outer
banks does not exclude nested RenderWare data or establish a complete vehicle decoder:

  main.dol          1,934,336-byte PowerPC DOL at the header 0x420 offset (not in the FST).
  playcars/<car>/   9 playable vehicles (the roster).  Per car:
                    <car>.cfg          physics (CRLF text, ``mName = value``).
                    <car>.esm          engine-SOUND model (text "Src Engine Model Definition";
                                       RPM->freq/volume, gear/accelerator curves, sample names
                                       scfund/scchar*/schigh*/scexh*).
                    <car>{a,e,n}.gcb   engine-audio sample banks (binary; header is the car id then
                                       "sclfund"/"sclchar1" clip names matching the .esm samples).
                    <car>gcn.ac{2,3,4} visual asset banks (big-endian 0x81xxxxxx pointer table).
                    <car>gcn.pc{1,2,f} visual asset banks (same pointer-table family, larger).
  trafcars/         trafficgcn.tra -- all traffic vehicles packed in one .tra bank (same BE pointer
                    table family; the exe still names "trafcars/models/%s/%s.dff", so the .tra
                    likely packs RenderWare clumps).
  tracks/<t>/       <t>{1..N}gcn.sgd = "SGDVER 7" Criterion streamed geometry; <t>.PSW/.PSS/.p1w =
                    RenderWare world streams.  track directories are enumerated from the actual FST.
  misc/             the loose RenderWare DFF files found in the FST: start.dff check.dff finish.dff
                    (1,488 B each) + global/shadowr.dff (2,552 B) -- UI/start-line props, not cars.
  frontend|misc/    .dic = RenderWare TXD texture dictionaries (frontend.dic 4.7 MB, texture.dic,
                    loading.dic, global.dic); .tpl = GameCube TPL (burnout.tpl fxcorona.tpl icon.tpl).
  audio/            .ulw music (Dolby/Mono), .gcb sfx.

The replacement target is a playable car. Analyze the .ac/.pc visual banks and their loader
before claiming a mesh format; .gcb files identified here are audio banks. Reuse of existing
RenderWare readers depends on confirming nested payload signatures and layout.

``python -m gbox.burnout_inventory <disc .gcz> --source <gcz> --source-sha256 SHA --out manifest.json``
writes the manifest (game identity, DOL hash, per-top-dir layout, 9-car roster with per-file
hashes, traffic bank, track list, texture formats, launch notes).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME_IDS = {"e827de330b62e67d": "Burnout (USA)"}
DISC_ID = "GBOE51"
SOURCE_REL = "collections/Nintendo GameCube/roms/Burnout (USA).gcz"
GC_MAGIC = 0xC2339F3D
TPL_MAGIC = 0x0020AF30
GX_FORMATS = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3", 6: "RGBA8", 8: "C4",
              9: "C8", 10: "C14X2", 14: "CMPR"}
# RenderWare chunk IDs; stream headers on the inspected files are little-endian.
RW_CHUNK_NAMES = {0x01:"Struct",0x02:"String",0x03:"Extension",0x06:"Texture",0x07:"Material",
                  0x08:"MaterialList",0x0E:"FrameList",0x0F:"Geometry",0x10:"Clump",
                  0x14:"Atomic",0x15:"TextureNative",0x16:"TextureDictionary",0x1A:"GeometryList"}
# The 9 playable vehicles.  "fire"/"default" appear in main.dol strings but are not on this disc.
CAR_EXT_PART = {"cfg": "physics", "esm": "engine-sound model", "gcb": "engine-audio bank",
                "ac2": "asset bank (ptr table)", "ac3": "asset bank (ptr table)",
                "ac4": "asset bank (ptr table)", "pc1": "asset bank (ptr table)",
                "pc2": "asset bank (ptr table)", "pcf": "asset bank (ptr table)"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def disc_header(head: bytes, bi2: bytes) -> dict:
    """Boot header (first 0x440 bytes) + bi2 -> identity, DOL/FST location and region."""
    if len(head) < 0x430 or len(bi2) < 0x1C:
        raise ValueError("disc header too short")
    if struct.unpack_from(">I", head, 0x1C)[0] != GC_MAGIC:
        raise ValueError("not a GameCube disc (magic at 0x1C)")
    dol_off, fst_off, fst_size = struct.unpack_from(">III", head, 0x420)
    region = struct.unpack_from(">I", bi2, 0x18)[0]
    regions = {0: "NTSC-J", 1: "NTSC-U", 2: "PAL"}
    return {"disc_id": head[:6].decode("ascii", "replace"), "maker": head[4:6].decode("ascii", "replace"),
            "disc_number": head[6] + 1, "version": head[7],
            "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
            "dol_offset": dol_off, "fst_offset": fst_off, "fst_size": fst_size,
            "region": regions.get(region, f"unknown({region})")}


def tpl_images(b: bytes) -> list[dict]:
    """[{w, h, fmt}] for a GameCube TPL (magic 0x0020AF30)."""
    if len(b) < 12 or struct.unpack_from(">I", b, 0)[0] != TPL_MAGIC:
        raise ValueError("not a TPL (magic 0x0020AF30)")
    n, table = struct.unpack_from(">II", b, 4)
    if table<12 or table + 8 * n > len(b):
        raise ValueError("TPL image table runs past the end")
    out = []
    for i in range(n):
        ih = struct.unpack_from(">I", b, table + 8 * i)[0]
        if ih + 12 > len(b):
            raise ValueError(f"TPL image header {i} outside the file")
        h, w, fmt, data = struct.unpack_from(">HHII", b, ih)
        if not w or not h or data > len(b):
            raise ValueError(f"TPL image {i} data outside the file")
        out.append({"w": w, "h": h, "fmt": GX_FORMATS.get(fmt, str(fmt))})
    return out


def rw_chunks(b: bytes) -> list[dict]:
    """Read top-level RenderWare records; size excludes the 12-byte header."""
    out=[];off=0
    while off<len(b):
        if off+12>len(b):raise ValueError('Truncated RenderWare header')
        typ,size,version=struct.unpack_from('<III',b,off)
        if size>len(b)-off-12:raise ValueError('RenderWare payload outside buffer')
        out.append({'type':RW_CHUNK_NAMES.get(typ,hex(typ)),'size':size,'version':hex(version),'offset':off})
        off+=12+size
    return out


def esm_samples(b: bytes) -> dict:
    """Count sample names and curve sections in an engine-sound .esm (text)."""
    text = b.decode("latin-1", "replace")
    samples = [ln.strip() for ln in text.splitlines() if ln.startswith("  sc") and len(ln.strip()) <= 16]
    curves = [ln.strip() for ln in text.splitlines() if ";RPM -> frequency function" in ln]
    return {"sample_names": samples[:64], "n_samples": len(samples),
            "n_curve_blocks": len(curves)}


def asset_bank(b: bytes) -> dict:
    """Analyse the Criterion .ac/.pc/.tra family: a leading run of big-endian u32s in the
    0x80000000..0x817FFFFF GameCube RAM range (a pointer-like candidate run; loader interpretation remains unverified).  Bounded to the first
    4096 bytes; reports the table shape and where the table ends."""
    n = 0
    end = 0
    while end + 4 <= min(len(b), 4096):
        v = struct.unpack_from(">I", b, end)[0]
        if not (0x80000000 <= v <= 0x817FFFFF):
            break
        n += 1
        end += 4
    return {"ptr_table_entries": n, "ptr_table_bytes": end,
            "first": hex(struct.unpack_from(">I", b, 0)[0]) if len(b) >= 4 else None,
            "candidate_prefix_ends": end}


def sgd_header(b: bytes) -> dict:
    """Criterion streamed-geometry header ('SGDVER 7')."""
    if len(b) < 0x40 or b[:8] != b"SGDVER 7":
        raise ValueError("not an SGD (want 'SGDVER 7')")
    # Raw words after the magic; section semantics require loader analysis
    vals = struct.unpack_from(">12I", b, 0x08)
    return {"raw_header_words": list(vals), "layout_verified":False}


def car_components(disc, car: str) -> list[dict]:
    """[(file, size, sha256, kind)] for one playcars/<car>/ directory."""
    rows = []
    for name in sorted(disc.files):
        if not name.startswith(f"playcars/{car}/"):
            continue
        data = disc.read(name)
        ext = name.rsplit(".", 1)[-1].lower()
        rows.append({"file": name, "size": len(data), "sha256": _sha(data),
                     "kind": CAR_EXT_PART.get(ext, "?"), "ext": ext})
    return rows


def inventory(iso: Path, source: Path | None = None, source_sha256: str | None = None) -> dict:
    from .gcdisc import GCDisc

    digest=hashlib.sha256()
    with open(iso,"rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    actual_hash=digest.hexdigest()
    if source_sha256 is not None and source_sha256.lower()!=actual_hash:
        raise ValueError("Source SHA-256 mismatch")
    disc = GCDisc(iso)
    try:
        hdr = disc_header(disc._r(0, 0x440), disc._r(0x440, 0x20))
        if hdr["disc_id"] != DISC_ID:
            raise ValueError(f"{iso}: disc id {hdr['disc_id']}, expected {DISC_ID}")
        dol = disc.dol()

        # per-top-dir layout + extension histogram
        dirs, sizes = defaultdict(Counter), Counter()
        for name, (_off, size) in disc.files.items():
            top = name.split("/", 1)[0] if "/" in name else "<root>"
            ext = name.rsplit(".", 1)[-1].lower() if "." in name.rsplit("/", 1)[-1] else ""
            dirs[top][ext] += 1
            sizes[top] += size

        cars = sorted({n.split("/")[1] for n in disc.files
                       if n.startswith("playcars/") and "/" in n[9:] and n.split("/")[1] != "global"})
        roster = []
        for car in cars:
            comps = car_components(disc, car)
            fp = b"".join(c["sha256"].encode("ascii") for c in comps)
            roster.append({"car": car, "files": comps, "bytes": sum(c["size"] for c in comps),
                           "sha256": _sha(fp)})
        traffic = disc.read("trafcars/trafficgcn.tra")
        tracks = sorted({n.split("/")[1] for n in disc.files if n.startswith("tracks/") and "/" in n[7:]})
        sgd_file = next((n for n in sorted(disc.files) if n.endswith(".sgd")
                         and disc._r(disc.files[n][0], 8) == b"SGDVER 7"), None)
        rpc_sgds = [n for n in sorted(disc.files) if n.endswith("rpcgcn.sgd")]

        # format probes
        probes = {}
        for n in ("misc/start.dff", "misc/check.dff", "misc/finish.dff", "playcars/global/shadowr.dff"):
            try:
                probes[n] = {"chunks": rw_chunks(disc.read(n))}
            except ValueError as e:
                probes[n] = {"error": str(e)}
        probes["frontend/frontend.dic"] = {"chunks": rw_chunks(disc.read("frontend/frontend.dic"))[:3]}
        probes["misc/burnout.tpl"] = {"images": tpl_images(disc.read("misc/burnout.tpl"))}
        probes["playcars/coupe/coupegcn.pc1"] = asset_bank(disc.read("playcars/coupe/coupegcn.pc1"))
        probes["playcars/coupe/coupegcn.ac2"] = asset_bank(disc.read("playcars/coupe/coupegcn.ac2"))
        probes["playcars/coupe/coupee.gcb"] = asset_bank(disc.read("playcars/coupe/coupee.gcb"))
        probes["trafcars/trafficgcn.tra"] = asset_bank(traffic)
        probes["coupe.esm"] = esm_samples(disc.read("playcars/coupe/coupe.esm"))

        return {
            "game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
            "source": {"catalog_rel_path": SOURCE_REL, "path": str(iso), "label":str(source) if source else None,
                       "sha256": actual_hash, "format": "Dolphin GCZ" if str(iso).lower().endswith(".gcz") else "GameCube ISO", "image": str(iso)},
            "disc": hdr, "files": len(disc.files),
            "dol": {"size": len(dol), "sha256": _sha(dol), "entry": hex(struct.unpack_from(">I", dol, 0xE0)[0])},
            "layout": {d: {"files": sum(c.values()), "bytes": sizes[d], "ext": dict(c)}
                       for d, c in sorted(dirs.items())},
            "roster": roster, "roster_size": len(roster),
            "traffic": {"file": "trafcars/trafficgcn.tra", "size": len(traffic), "sha256": _sha(traffic)},
            "tracks": tracks,
            "sgd_file": sgd_file,
            "sgd_sections": sgd_header(disc.read(sgd_file)) if sgd_file else None,
            "reflection_probe_sgds": rpc_sgds,
            "format_probes": probes,
            "launch": {"core": "dolphin (catalog runtimes retroarch/dolphin, rocketlauncher windows-node)",
                       "mod_base": "filemods.gcz_to_iso -> cache/modbase/<game_id>/<stem>.iso; mods are "
                                   "copies (filemods.build_image), the GCZ stays untouched",
                       "region": hdr["region"], "players": 1},
        }
    finally:
        disc.f.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Burnout (USA, GC, GBOE51) owned-disc inventory manifest")
    ap.add_argument("disc", type=Path, help="owned .gcz or .iso")
    ap.add_argument("--source", type=Path)
    ap.add_argument("--source-sha256")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    m = inventory(a.disc, a.source, a.source_sha256)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
