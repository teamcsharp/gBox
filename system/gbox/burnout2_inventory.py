"""Burnout 2 - Point of Impact (USA, GameCube, GB4E51) -- owned-disc inventory.

Stage-1 (inventory) artifact for the character-replacement queue.  This module resolves the exact owned
disc, hashes the source executable, and records the container layout and the racecar roster (in this
driving title the replaceable "characters" are the 22 driveable cars).

Owned source: the operator's QuickSwap2 raw ISO ``/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/
Burnout 2 - Point of Impact (USA).iso`` (catalog ``ca35e3d6b15f6d6e``, serial GB4E51), which is the same
build the HyperSpin GCZ catalog entry ``15cba5c2f83db274`` names.  The raw ISO is the authoritative image.

Disc facts (verified against the ISO):
  game id GB4E51, magic 0xC2339F3D, title "Burnout 2"; main.dol at 0x1EC00 (entry 0x80003140, 2 text +
  8 data sections, exact size 0x1EBB00 = right up to the FST); FST at 0x20A700, 703 entries / 634 files /
  69 dirs across the top-level dirs Frontend/, Racecars/, Traffic/, audio/, music/, tracks/ plus the root
  files banner.tpl, icon.tpl and opening.bnr.

Container layout (top level -> role):
  Frontend/     frontend.gcn (2.9 MB UI model pack), global.grd (510 KB shared UI globals).
  Racecars/     22 car dirs, each {car}.RCF (body), {car}.RCX (damage/extra), {car}a.rws and
                {car}e.rws (RenderWare Streams holding the car model + textures).
  Traffic/      Traffic.TRA (2.5 MB traffic vehicle data).
  audio/        sfx .rws (carext, crash, fe_menu, in_menu, special), modes/*.rws, weather/*.rws,
                tracks/{forward,reverse}/*.rws (per-track sfx).
  music/        streaming .rws tracks (trk*mg{pl,st}.rws, credits*.rws) -- the bulk of the disc.
  tracks/       Crash/ (150 .bcd collision chunks), forward/ + reverse/ (174 .bgd track geometry,
                .p2w/.psw track streaming audio, DReplay*/L*Intro* .dat replay+intro camera data,
                .pss movies).
  (root files)  banner.tpl + icon.tpl (GameCube TPL, magic 0x0020AF30), opening.bnr (disc banner).

Extension roles: .rws RenderWare Stream; .rcf car body; .rcx car damage; .bgd track geometry;
.bcd track collision; .p2w/.psw track streaming audio; .pss movie; .dat replay/intro data;
.tpl GC texture; .gcn/.grd frontend; .tra traffic; .bnr banner.

``python -m gbox.burnout2_inventory ISO [--json out.json]`` writes the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME_IDS = {"15cba5c2f83db274": "Burnout 2 - Point of Impact (USA) [GameCube]",
            "ca35e3d6b15f6d6e": "Burnout 2 - Point of Impact (raw ISO, GB4E51)"}
DISC_ID = "GB4E51"
GC_MAGIC = 0xC2339F3D
TPL_MAGIC = 0x0020AF30

ISO_SHA256 = "bcd28338c5e2a2e18ff77e5599125d8046c12e2252277aa4f8b217d80254dfd1"
DOL_OFFSET = 0x1EC00
DOL_ENTRY = 0x80003140
DOL_SHA256 = "86754556619de76b6fbefd47bc7259ba7c2604f7af13371cd236245c0b4946ea"
FST_OFFSET = 0x20A700
FST_SIZE = 0x3F8D

# audio/Racecars/<name>/<name>.{RCF,RCX,<name>a.rws,<name>e.rws}
RACECARS = ("classic", "comp", "compcs", "copcar", "coupe", "coupecs", "driveed", "gangsta", "hotrod",
            "jmus", "pick", "pickcs", "road", "roadcs", "sport", "sportcs", "stock", "super", "suv",
            "suvcs", "usmus", "usmuscs")

EXT_ROLES = {".rws": "renderware_stream", ".rcf": "car_body", ".rcx": "car_damage", ".bgd": "track_geo",
             ".bcd": "track_collision", ".p2w": "track_audio_fwd", ".psw": "track_audio_rev",
             ".pss": "movie", ".dat": "replay_intro_data", ".tpl": "gc_texture", ".gcn": "frontend",
             ".grd": "frontend_global", ".tra": "traffic", ".bnr": "banner"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def disc_header(head: bytes) -> dict:
    """First 0x440 bytes -> game id, title, magic, DOL/FST location."""
    if len(head) < 0x430:
        raise ValueError("disc header too short")
    magic = struct.unpack_from(">I", head, 0x1C)[0]
    if magic != GC_MAGIC:
        raise ValueError(f"not a GameCube disc (magic 0x{magic:08x})")
    dol, fst_off, fst_size = struct.unpack_from(">III", head, 0x420)
    return {"game_id": head[:6].decode("ascii", "replace"),
            "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
            "magic": magic, "dol_offset": dol, "fst_offset": fst_off, "fst_size": fst_size}


def dol_header(dol: bytes) -> dict:
    """Parse the DOL header: text/data section addresses+sizes, bss, entry, exact size."""
    if len(dol) < 0xE4:
        raise ValueError("DOL header too short")
    text_off = struct.unpack_from(">7I", dol, 0x00)
    data_off = struct.unpack_from(">11I", dol, 0x1C)
    text_addr = struct.unpack_from(">7I", dol, 0x48)
    data_addr = struct.unpack_from(">11I", dol, 0x64)
    text_size = struct.unpack_from(">7I", dol, 0x90)
    data_size = struct.unpack_from(">11I", dol, 0xAC)
    bss_addr = struct.unpack_from(">I", dol, 0xD8)[0]
    bss_size = struct.unpack_from(">I", dol, 0xDC)[0]
    entry = struct.unpack_from(">I", dol, 0xE0)[0]
    size = 0x100
    for off, sz in zip(text_off, text_size):
        if sz:
            if off<0x100:
                raise ValueError("DOL section overlaps header")
            size = max(size, off + sz)
    for off, sz in zip(data_off, data_size):
        if sz:
            if off<0x100:
                raise ValueError("DOL section overlaps header")
            size = max(size, off + sz)
    return {"entry": entry, "bss_addr": bss_addr, "bss_size": bss_size, "size": size,
            "text_sections": [(a, s) for a, s in zip(text_addr, text_size) if s],
            "data_sections": [(a, s) for a, s in zip(data_addr, data_size) if s]}


def rw_chunks(b: bytes, maxdepth: int = 4) -> list[dict]:
    """Read up to maxdepth top-level RenderWare chunk headers; do not infer nesting.

    Hypothesis (to confirm in the analysis stage): the GC RenderWare stream records are little-endian
    {u32 type, u32 size, u32 version}, where size is the payload size (excluding the 12-byte header) and
    version 0x1003ffff marks RenderWare 3.x.  This is a *reader probe*, not a verified decoder: the chunk
    type ids (e.g. 0x0809) still need to be mapped to RenderWare's type table.
    """
    if maxdepth<0:
        raise ValueError("Chunk count must be nonnegative")
    out=[];i=0
    while i<len(b) and len(out)<maxdepth:
        if i+12>len(b):
            raise ValueError("Truncated RenderWare chunk header")
        typ,size,version=struct.unpack_from("<III",b,i)
        if size>len(b)-i-12:
            raise ValueError("RenderWare chunk outside buffer")
        out.append({'type':typ,'size':size,'version':version,'offset':i})
        i+=12+size
    return out


def inventory(iso_path: str) -> dict:
    """Read the ISO and return the manifest (identity, DOL, FST, roster, layout)."""
    from gbox.formats import gcfst
    iso = Path(iso_path)
    h = hashlib.sha256()
    with iso.open("rb") as f:
        head = f.read(0x440)
        hdr = disc_header(head)
        image_size=iso.stat().st_size
        if hdr["game_id"]!=DISC_ID:
            raise ValueError(f"Expected {DISC_ID}, got {hdr['game_id']}")
        span=hdr["fst_offset"]-hdr["dol_offset"]
        if not (0x440<=hdr["dol_offset"] and 0x100<=span<=64*1024*1024):
            raise ValueError("Invalid bounded DOL span")
        if not (12<=hdr["fst_size"]<=16*1024*1024) or hdr["fst_offset"]+hdr["fst_size"]>image_size:
            raise ValueError("FST outside source image")
        f.seek(hdr["dol_offset"])
        dol = f.read(hdr["fst_offset"] - hdr["dol_offset"])
        f.seek(hdr["fst_offset"])
        fst = f.read(hdr["fst_size"])
        f.seek(0)
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    dh = dol_header(dol)
    if len(dol)!=span or len(fst)!=hdr["fst_size"] or dh["size"]>len(dol):
        raise ValueError("Truncated DOL or FST")
    count=struct.unpack_from(">I",fst,8)[0]
    if not count or count>len(fst)//12 or fst[0]!=1:
        raise ValueError("Invalid FST entry count or root")
    try:
        files = gcfst.parse_fst(fst, hdr["fst_offset"])
    except (struct.error,IndexError,ValueError) as exc:
        raise ValueError("Malformed FST") from exc
    if any(off>image_size or size>image_size-off for _,off,size,_ in files):
        raise ValueError("FST member outside source image")

    by_ext = Counter()
    cars = defaultdict(dict)
    for path, off, size, _eoff in files:
        ext = Path(path).suffix.lower()
        by_ext[ext] += 1
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "Racecars":
            cars[parts[1]][parts[-1].lower()] = {"offset": off, "size": size}

    layout = {ext: EXT_ROLES.get(ext, "other") for ext in by_ext}

    return {"game_id": hdr["game_id"], "title": hdr["title"], "disc_id": DISC_ID,
            "iso_sha256": h.hexdigest(),
            "dol": {"offset": hdr["dol_offset"], "sha256": _sha(dol), "entry": hex(dh["entry"]),
                    "size": dh["size"], "text_sections": dh["text_sections"],
                    "data_sections": dh["data_sections"]},
            "fst": {"offset": hdr["fst_offset"], "size": hdr["fst_size"], "files": len(files),
                    "extensions": dict(by_ext), "layout": layout},
            "racecars": {c: dict(v) for c, v in sorted(cars.items())}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Burnout 2 (GC) owned-disc inventory")
    ap.add_argument("iso")
    ap.add_argument("--json", dest="out", help="write the manifest here")
    args = ap.parse_args(argv)
    m = inventory(args.iso)
    text = json.dumps(m, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
