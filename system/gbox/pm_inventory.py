"""Paper Mario (USA) (N64): owned-source inventory for the favorite-queue character replacement.

Favorite game b74d223b195befba (#1673). The owned hyperspin zip holds one ``Paper Mario (USA).n64`` member whose
normalized z64 md5 a722f816... / sha1 3837f44c... is the pmret/papermario ``baserom.us.z64`` (header
"PAPER MARIO", code NMQE, version 0, entry 0x80125C00). So the decomp's US splat map applies; it is used here as
documentation only, and every offset below is re-checked against the ROM content.

Paper Mario characters are 2D paper SPRITES, not rigged meshes (the assimilation fingerprint's nearest title,
SM64, shares only the libultra SDK; none of the sm64_mario geo/MIO0 reader applies). Layout (US):

  0x1943000  sprites   header: char build_date[16]; u32 player_rasters, player_yay0, npc_yay0, end
                       (offsets relative to sprites+0x10 = SPRITE_ROM_START, decomp src/101b90_len_8f0.c)
             player rasters: {u32 index_ranges, raster_info, ci4_data} then raster sets and packed
                       load descriptors (size/16 in bits 20-31, offset in bits 0-19, relative to player_rasters);
                       the CI4 pixels stay UNCOMPRESSED and are DMA'd per frame into a raster cache
             player yay0: 14-word split table -> 13 Yay0 sprites (Mario1, Mario1 back, MarioB1..3, MarioW1,
                       MarioW1 back, MarioW2, MarioW3, Peach1, Peach1 back, Peach2, Peach3)
             npc yay0: (N+1)-word split table -> N Yay0 sprites (partners, enemies, NPCs)
  0x1E40000  mapfs     char title[0x20]; then 0x1C entries {char name[16]; u32 off(rel +0x20), comp, decomp}
                       up to "end_data"; comp != decomp means Yay0 (maps *_shape/_hit/_tex, *_bg, party_*)

A decompressed sprite starts {u32 rasters_list, palettes_list, max_components, num_variations} followed by the
animation offset list; lists end with -1. NPC raster records are {u32 image, u8 w, u8 h, u8 palette, 0xFF}
(CI4 pixels inside the sprite); player raster records are {u32 cache_pos, u8 w, u8 h, u8 palette}.
Palettes are 16 RGBA5551 colors.

CLI: python -m gbox.pm_inventory SRC [--out manifest.json]
"""
from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path

from . import n64_rom

GAME_ID = "b74d223b195befba"
# normalized z64 sha1 -> build (hashed from the owned file on the Spark, #1673)
KNOWN = {
    "3837f44cda784b466c9a2d99df70d77c322b97a0": {"code": "NMQE", "region": "US", "version": 0,
                                                 "name": "Paper Mario (USA)", "decomp": "us",
                                                 "md5": "a722f8161ff489943191330bf8416496"},
}
SPRITES = 0x1943000
MAPFS = 0x1E40000
PLAYER_SPRITE_NAMES = ("Mario1", "Mario1_Back", "MarioB1", "MarioB2", "MarioB3", "MarioW1", "MarioW1_Back",
                       "MarioW2", "MarioW3", "Peach1", "Peach1_Back", "Peach2", "Peach3")
# First NPC sprite slots (decomp tools/splat_ext/npc_sprite_names.yaml order, re-checked by count only).
NPC_SPRITE_NAMES_HEAD = ("WorldGoombario", "WorldKooper", "WorldBombette", "WorldParakarry", "WorldBow")
END = 0xFFFFFFFF


def yay0_decompress(src: bytes, o: int = 0) -> bytes:
    """Nintendo Yay0: {'Yay0', u32 size, u32 link_off, u32 chunk_off}, MSB-first 32-bit mask words at +0x10."""
    if src[o:o + 4] != b"Yay0":
        raise ValueError(f"no Yay0 magic at {o:#x}")
    size, link, chunk = struct.unpack_from(">III", src, o + 4)
    link += o
    chunk += o
    mask_at = o + 0x10
    out = bytearray()
    mask = bits = 0
    while len(out) < size:
        if bits == 0:
            mask = int.from_bytes(src[mask_at:mask_at + 4], "big")
            mask_at += 4
            bits = 32
        if mask & 0x80000000:
            out.append(src[chunk])
            chunk += 1
        else:
            v = (src[link] << 8) | src[link + 1]
            link += 2
            dist = (v & 0xFFF) + 1
            n = v >> 12
            if n == 0:
                n = src[chunk] + 0x12
                chunk += 1
            else:
                n += 2
            if dist > len(out):
                raise ValueError(f"Yay0 back-reference {dist} before start at out {len(out):#x}")
            for _ in range(n):
                out.append(out[-dist])
        mask = (mask << 1) & 0xFFFFFFFF
        bits -= 1
    return bytes(out[:size])


def offset_list(d: bytes, o: int, limit: int = 4096) -> list[int]:
    out = []
    while o + 4 <= len(d) and len(out) < limit:
        v = struct.unpack_from(">I", d, o)[0]
        if v == END:
            return out
        out.append(v)
        o += 4
    raise ValueError(f"unterminated offset list at {o:#x}")


def raw_member(src: Path) -> tuple[str | None, bytes]:
    """(member name, first 4 raw bytes) so the original byte order is recorded."""
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            with z.open(names[0]) as f:
                return names[0], f.read(4)
    return None, src.read_bytes()[:4]


def identify(rom: bytes) -> dict:
    sha1 = hashlib.sha1(rom).hexdigest()
    entry = struct.unpack_from(">I", rom, 8)[0]
    return {"size": len(rom), "md5": hashlib.md5(rom).hexdigest(), "sha1": sha1,
            "sha256": hashlib.sha256(rom).hexdigest(), "title": rom[0x20:0x34].decode("ascii").strip(),
            "code": rom[0x3B:0x3F].decode("ascii"), "version": rom[0x3F], "entry": f"{entry:#010x}",
            "crc": rom[0x10:0x18].hex(), "bootcode_sha256": hashlib.sha256(rom[0x40:0x1000]).hexdigest(),
            "known": KNOWN.get(sha1)}


def sprite_header(rom: bytes) -> dict:
    base = SPRITES + 0x10
    date = rom[SPRITES:SPRITES + 0x10].split(b"\0")[0].decode("ascii")
    pr, py, ny, end = (base + v for v in struct.unpack_from(">IIII", rom, base))
    if not (base < pr < py < ny < end <= len(rom)):
        raise ValueError("sprite header offsets out of order")
    return {"build_date": date, "player_rasters": pr, "player_yay0": py, "npc_yay0": ny, "end": end}


def _sprite_summary(d: bytes, npc: bool) -> dict:
    rl, pl, max_comp, nvar = struct.unpack_from(">IIII", d, 0)
    anims = offset_list(d, 0x10)
    rasters = []
    for ro in offset_list(d, rl):
        if npc:
            img, w, h, pal, tail = struct.unpack_from(">IBBBB", d, ro)
            if tail != 0xFF or img + w * h // 2 > len(d):
                raise ValueError(f"bad NPC raster record at {ro:#x}")
        else:
            img, w, h, pal = struct.unpack_from(">iBBB", d, ro)
        rasters.append((w, h, pal))
    pals = offset_list(d, pl)
    if any(p + 0x20 > len(d) for p in pals):
        raise ValueError("palette past sprite end")
    comps = [len(offset_list(d, a)) for a in anims]
    return {"size": len(d), "sha256": hashlib.sha256(d).hexdigest(), "max_components": max_comp,
            "variations": nvar, "rasters": len(rasters), "palettes": len(pals), "animations": len(anims),
            "max_anim_components": max(comps, default=0),
            "max_raster": [max((r[0] for r in rasters), default=0), max((r[1] for r in rasters), default=0)]}


def _yay0_table(rom: bytes, base: int, end: int, n: int | None = None) -> list[tuple[int, int]]:
    if n is None:
        n = struct.unpack_from(">I", rom, base)[0] // 4 - 1
    offs = struct.unpack_from(f">{n + 1}I", rom, base)
    if list(offs) != sorted(offs) or base + offs[-1] > end:
        raise ValueError("sprite split table not ascending/in range")
    return [(base + offs[i], base + offs[i + 1]) for i in range(n)]


def player_rasters(rom: bytes, hdr: dict) -> dict:
    b = hdr["player_rasters"]
    ranges, info, ci4 = struct.unpack_from(">III", rom, b)
    sets = struct.unpack_from(f">{(info - ranges) // 4}I", rom, b + ranges)
    descs = struct.unpack_from(f">{(ci4 - info) // 4}I", rom, b + info)
    pool = hdr["player_yay0"] - (b + ci4)
    bad = [i for i, v in enumerate(descs) if (v & 0xFFFFF) + ((v >> 20) << 4) > hdr["player_yay0"] - b]
    return {"raster_sets": len(sets) - 1, "set_starts": list(sets), "load_descriptors": len(descs),
            "ci4_pool_offset": b + ci4, "ci4_pool_bytes": pool, "descriptors_out_of_range": bad,
            "max_raster_bytes": max((v >> 20) << 4 for v in descs)}


def sprites(rom: bytes) -> dict:
    hdr = sprite_header(rom)
    player = []
    for i, (s, e) in enumerate(_yay0_table(rom, hdr["player_yay0"], hdr["npc_yay0"], 13)):
        d = yay0_decompress(rom, s)
        player.append({"index": i, "name": PLAYER_SPRITE_NAMES[i], "rom": s, "comp": e - s, **_sprite_summary(d, False)})
    npc = []
    for i, (s, e) in enumerate(_yay0_table(rom, hdr["npc_yay0"], hdr["end"])):
        d = yay0_decompress(rom, s)
        name = NPC_SPRITE_NAMES_HEAD[i] if i < len(NPC_SPRITE_NAMES_HEAD) else None
        npc.append({"index": i, "sprite_id": i + 1, "name": name, "rom": s, "comp": e - s,
                    **_sprite_summary(d, True)})
    return {"header": hdr, "player_rasters": player_rasters(rom, hdr), "player": player, "npc": npc}


def mapfs(rom: bytes) -> list[dict]:
    title = rom[MAPFS:MAPFS + 0x20].split(b"\0")[0].decode("ascii")
    out = []
    o = MAPFS + 0x20
    while True:
        name = rom[o:o + 16].split(b"\0")[0].decode("ascii")
        off, comp, dec = struct.unpack_from(">III", rom, o + 16)
        if name == "end_data":
            break
        start = MAPFS + 0x20 + off
        yay0 = comp != dec
        if yay0 and rom[start:start + 4] != b"Yay0":
            raise ValueError(f"mapfs {name}: compressed entry without Yay0 magic")
        out.append({"name": name, "rom": start, "comp": comp, "size": dec, "yay0": yay0, "title": title})
        o += 0x1C
        if len(out) > 4096:
            raise ValueError("mapfs table unterminated")
    return out


def _kind(name: str) -> str:
    for suf in ("_shape", "_hit", "_tex", "_bg"):
        if name.endswith(suf):
            return suf[1:]
    return "party" if name.startswith("party_") else "title" if name.startswith("title") else "other"


def inventory(src: Path) -> dict:
    src = Path(src)
    rom = n64_rom.read(src)
    ident = identify(rom)
    member, first4 = raw_member(src)
    order = {b"\x80\x37\x12\x40": "z64", b"\x37\x80\x40\x12": "v64", b"\x40\x12\x37\x80": "n64"}.get(first4, "?")
    spr = sprites(rom)
    fs = mapfs(rom)
    kinds: dict[str, int] = {}
    for f in fs:
        kinds[_kind(f["name"])] = kinds.get(_kind(f["name"]), 0) + 1
    # verify one Yay0 mapfs entry decodes to its stated size (codec check beyond the sprite bank)
    probe = next(f for f in fs if f["yay0"])
    assert len(yay0_decompress(rom, probe["rom"])) == probe["size"]
    return {
        "game_id": GAME_ID,
        "source": {"path": str(src), "size": src.stat().st_size, "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                   "member": member, "member_byte_order": order},
        "rom": ident,
        "launch": {"core": "parallel_n64", "rom_bytes": len(rom), "notes": "40 MiB cart; save type FlashRAM per decomp"},
        "sprites": spr,
        "mapfs": {"count": len(fs), "kinds": kinds, "yay0": sum(f["yay0"] for f in fs),
                  "party": [f["name"] for f in fs if _kind(f["name"]) == "party"], "entries": fs},
        "characters": {"player_sprites": len(spr["player"]), "npc_sprites": len(spr["npc"]),
                       "player_rasters": sum(p["rasters"] for p in spr["player"]),
                       "npc_rasters": sum(p["rasters"] for p in spr["npc"]),
                       "npc_animations": sum(p["animations"] for p in spr["npc"])},
        "writer_constraints": [
            "sprites are 2D CI4 rasters + 16-colour RGBA5551 palettes; no meshes/skeletons",
            "player CI4 pixels are uncompressed in a pool addressed by 20-bit offsets with size/16 in 12 bits",
            "player/NPC sprite metadata are Yay0 blobs addressed by split tables; growth needs table rewrite",
        ],
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(Path(a.src))
    text = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    s = {k: m[k] for k in ("rom", "characters")}
    s["mapfs"] = {k: m["mapfs"][k] for k in ("count", "kinds", "yay0")}
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
