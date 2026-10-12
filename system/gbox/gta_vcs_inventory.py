"""GTA Vice City Stories (PS2): owned-source inventory for native character replacement (#1376).

Builds a reproducible manifest of the exact owned build: the catalog CHD and the plain ISO a writer will patch,
their hashes, the boot executable (SYSTEM.CNF BOOT2 -> SLUS_215.90), launch prerequisites, the disc container
layout, and the character / texture / cutscene-animation inventory read from the disc's own tables. Nothing on the
disc is modified.

Verified on "Grand Theft Auto - Vice City Stories (USA).chd" (catalog 6f5a05916536492b, CHD v5 CD-type, one
MODE1/2048 track; SLUS_215.90 VER 1.00 NTSC):

  * The LCS module's fixed paths do not apply: GAME.DTZ is PS2/GAME.DTZ (LCS: CHK/PS2/GAME.DTZ) and the ped /
    vehicle archive is GTA3PS2.IMG in the disc root (LCS: MODELS/GTA3PS2.IMG). BEACH/MAINLA/MALL .IMG + .LVZ are the
    three streamed map levels; PS2/MOCAPPS2.DIR + .IMG hold the cutscenes (49 x .CAM/.CUT/.ANIM).
  * GAME.DTZ = zlib(GTAG relocatable chunk). Its ResourceImage at 0x20 keeps the LCS offsets for +0x18
    numModelInfos (7941), +0x1C modelInfoPtrs and +0x40 the TXD pool (items of 28 bytes, name at +8: fsfonts, hud,
    generic, particle, empire, plr, cop, ...). Model infos keep hash +0x08, type +0x10 (7 = ped) and TXD slot
    +0x1E; model 0 is a ped using TXD slot 5 'plr' (the player). CStreaming (+0x5C) does NOT hold the LCS inline
    20-byte info array (its header reads 0, 0x74000, 7534, 8365, 8392, 8482, ...), so the model-id -> IMG sector
    map is left to the analysis stage; this module records the header words for it.
  * The special-model directory sits inside GAME.DTZ as 32-byte {u32 sector, u32 sectors, char name[24] 'x\\0mdl'}
    records: special01, story characters, CS* cutscene peds, csplr/CSPlr2..14 (cutscene player outfits) and CS_*
    props. Every entry starts an 'ldm' chunk in GTA3PS2.IMG. Unlike LCS there is no 'player' entry.
  * GTA3PS2.IMG holds the LCS relocatable chunk kinds (757 'ldm\\0' models, 823 'xet\\0' texture lists). Under the
    LCS raster-flag layout every VCS raster decodes as depth 16 (2748/2748), so gta_stories_models.read_chk raises
    NotImplementedError: either VCS uses another flag layout or 16-bit pixels, which the reader stage must settle
    (sizes below are LCS-layout decodes). The LCS read_ped fails on VCS peds (KeyError resolving anim-tree node
    ids). Both results are recorded per build instead of assumed.
  * The player: model 0 / TXD 'plr'. By shared texture names, the IMG 'ldm' chunk at sector 23 pairs with the
    'ig_vance_*' texture list at sector 0 (as LCS player.mdl sits at sector 23); 14 more Vance-textured chunks are
    outfit candidates. The streaming table must confirm model 0 -> sector 23 in the analysis stage.

    python -m gbox.gta_vcs_inventory DISC.iso [--rom ROM.chd] [--out manifest.json] [--copy-exe DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import re
import shutil
import struct
import subprocess
import zlib
from collections import Counter
from pathlib import Path

from .gta_rw import iso_files
from .gta_stories_models import GTAG_IDENT, MDL_IDENT, SECTOR, TEX_IDENT, Reloc, read_chk, read_ped

GAME_IDS = {"6f5a05916536492b": "Grand Theft Auto - Vice City Stories (USA)"}
EXPECTED_BOOT = "SLUS_215.90"
DTZ_PATH, IMG_PATH, MOCAP_DIR = "PS2/GAME.DTZ", "GTA3PS2.IMG", "PS2/MOCAPPS2.DIR"
LEVELS = ("BEACH", "MAINLA", "MALL")
DIR_ENTRY = 32
RI = 0x20                                              # ResourceImage inside the GTAG chunk
RI_NUM_MODELINFOS, RI_MODELINFOS, RI_TXD_POOL, RI_STREAMING = 0x18, 0x1C, 0x40, 0x5C
MI_HASH, MI_TYPE, MI_TXD = 0x08, 0x10, 0x1E
MITYPE_PED = 7
TXD_ITEM, TXD_NAME = 28, 8
BONE_WORDS = ("pelvis", "spine", "thigh", "calf", "clavicle", "upperarm", "forearm", "bip01")
LAUNCH = {
    "platform": "ps2",
    "region": "NTSC-U",
    "emulator": "PCSX2 (RetroArch pcsx2_libretro; catalog runtimes retroarch/pcsx2 auto-install, "
                "rocketlauncher windows-node)",
    "bios": "a PS2 BIOS dump is required by PCSX2; it is not on the disc",
    "media": "CHD v5 CD-type (single MODE1/2048 track) boots directly in PCSX2; writers patch the extracted ISO",
}
_SPECIAL = re.compile(rb"[\x21-\x7e]{1,23}\x00mdl\x00")
_STR = re.compile(rb"[\x20-\x7e]{3,31}\x00")


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def parse_system_cnf(text: str) -> dict:
    """SYSTEM.CNF -> {boot, executable, ver, vmode}. BOOT2 = cdrom0:\\SLUS_215.90;1."""
    out = {}
    for line in text.replace("\r", "").split("\n"):
        if "=" in line:
            k, v = (s.strip() for s in line.split("=", 1))
            out[k.lower()] = v
    boot = out.get("boot2", "")
    m = re.match(r"cdrom0:\\+([^;]+)", boot, re.I)
    return {"boot": boot, "executable": m.group(1).upper() if m else "", "ver": out.get("ver", ""),
            "vmode": out.get("vmode", "")}


def elf_info(b: bytes) -> dict:
    """ELF32 little-endian header + PT_LOAD segments (the PS2 EE boot executable is MIPS, e_machine 8)."""
    if b[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    if b[4] != 1 or b[5] != 1:
        raise ValueError("not a 32-bit little-endian ELF")
    machine = struct.unpack_from("<H", b, 18)[0]
    entry, phoff = struct.unpack_from("<II", b, 24)
    phentsize, phnum = struct.unpack_from("<HH", b, 42)
    segs = []
    for k in range(phnum):
        p_type, off, vaddr, _pa, filesz, memsz, flags, _al = struct.unpack_from("<8I", b, phoff + k * phentsize)
        if p_type == 1:
            segs.append({"offset": off, "vaddr": f"0x{vaddr:08x}", "filesz": filesz, "memsz": memsz, "flags": flags})
    return {"machine": machine, "mips": machine == 8, "entry": f"0x{entry:08x}", "load_segments": segs}


def parse_dir(b: bytes) -> list[dict]:
    """A GTA Stories CDirectory blob (MOCAPPS2.DIR): 32-byte {u32 sector, u32 sectors, char name[24]} entries."""
    out = []
    for k in range(0, len(b) - DIR_ENTRY + 1, DIR_ENTRY):
        s, n = struct.unpack_from("<II", b, k)
        name = b[k + 8:k + 32].split(b"\0")[0]
        if not name or not all(32 < c < 127 for c in name):
            break
        out.append({"name": name.decode("ascii"), "sector": s, "sectors": n})
    return out


def find_special_dir(d: bytes) -> list[dict]:
    """The longest run of 32-byte {sector, sectors, 'name\\0mdl'} records in a GTAG chunk (the special models)."""
    def ok(o):
        return 0 <= o and o + DIR_ENTRY <= len(d) and 32 < d[o + 8] < 127 and b"\0mdl\0" in d[o + 8:o + 32]
    runs, pos = [], 0
    while (mt := _SPECIAL.search(d, pos)) is not None:
        o = mt.start() - 8
        if not ok(o):
            pos = mt.end()
            continue
        while ok(o - DIR_ENTRY):
            o -= DIR_ENTRY
        run = []
        while ok(o):
            s, n = struct.unpack_from("<II", d, o)
            run.append({"name": d[o + 8:o + 32].split(b"\0")[0].decode("latin-1"), "sector": s, "sectors": n,
                        "dir_offset": o})
            o += DIR_ENTRY
        runs.append(run)
        pos = max(o, mt.end())
    return max(runs, key=len) if runs else []


def classify_special(name: str) -> str:
    n = name.lower()
    if re.fullmatch(r"csplr\d*", n):
        return "cutscene_player"
    if n.startswith("cs_"):
        return "cutscene_prop"
    if n.startswith("cs"):
        return "cutscene_ped"
    if re.fullmatch(r"special\d+", n):
        return "special_slot"
    return "story"


def texlist_headers(b: bytes) -> list[dict]:
    """Names and raster formats of a Stories texture list ('xet') without decoding pixels (any depth)."""
    r = Reloc(b)
    if r.ident != TEX_IDENT:
        raise ValueError("not a texture list chunk")
    out, head = [], 0x20 + 8                             # RslTexList.texturesInDict link
    link, seen = r.u32(head), set()
    while link and link != head and link not in seen:
        if link < 8 or link + 8 > len(b):
            raise ValueError(f"texture link 0x{link:x} outside the chunk")
        seen.add(link)
        t = link - 8
        ras = r.u32(t)
        if ras + 8 > len(b):
            raise ValueError(f"raster 0x{ras:x} outside the chunk")
        fl = r.u32(ras + 4)
        out.append({"name": r.cstr(t + 16, 32), "w": 1 << (fl & 0x3F), "h": 1 << ((fl >> 6) & 0x3F),
                    "depth": (fl >> 12) & 0x3F, "mips": (fl >> 20) & 0xF, "swizzle": (fl >> 24) & 1})
        link = r.u32(link)
    return out


def chunk_strings(b: bytes) -> list[str]:
    return [m.group(0)[:-1].decode("ascii") for m in _STR.finditer(b, 0x20)]


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:160]


class VcsDisc:
    """GTA3PS2.IMG + PS2/GAME.DTZ of a VCS PS2 disc image (.iso, 2048-byte sectors), read in place."""

    def __init__(self, iso: Path):
        self.iso = Path(iso)
        self._f = open(self.iso, "rb")
        self.files = iso_files(self._f)
        for need in (DTZ_PATH, IMG_PATH):
            if need not in self.files:
                self._f.close()
                raise FileNotFoundError(f"{need} is not on this disc (not the VCS PS2 layout)")
        self._m = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        self.dtz = self.read(DTZ_PATH)
        self.game = Reloc(zlib.decompress(self.dtz))
        if self.game.ident != GTAG_IDENT:
            raise ValueError("GAME.DTZ is not a GTAG chunk")
        self.img_lba, self.img_size = self.files[IMG_PATH]
        self.img_sectors = self.img_size // SECTOR

    def close(self):
        self._m.close()
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def read(self, path: str) -> bytes:
        lba, size = self.files[path]
        return self._m[lba * SECTOR:lba * SECTOR + size]

    def img_read(self, sector: int, sectors: int) -> bytes:
        o = (self.img_lba + sector) * SECTOR
        return self._m[o:o + sectors * SECTOR]

    def chunk(self, sector: int) -> bytes:
        """The relocatable chunk starting at an IMG sector, trimmed to its fileSize."""
        n = struct.unpack_from("<I", self.img_read(sector, 1), 8)[0]
        return self.img_read(sector, (n + SECTOR - 1) // SECTOR)[:n]

    def img_chunks(self) -> tuple[list[dict], int]:
        """Walk GTA3PS2.IMG: every 'ldm'/'xet' chunk start (sector, sectors, size, kind) + unrecognised sectors."""
        out, other, s = [], 0, 0
        while s < self.img_sectors:
            h = self.img_read(s, 1)[:12]
            ident, size = struct.unpack_from("<I", h)[0], struct.unpack_from("<I", h, 8)[0]
            if ident in (MDL_IDENT, TEX_IDENT) and 0x20 <= size:
                n = (size + SECTOR - 1) // SECTOR
                out.append({"sector": s, "sectors": n, "size": size, "kind": "mdl" if ident == MDL_IDENT else "txd"})
                s += n
            else:
                other += 1
                s += 1
        return out, other

    def model_infos(self) -> list[dict]:
        g = self.game
        n, arr = g.u32(RI + RI_NUM_MODELINFOS), g.u32(RI + RI_MODELINFOS)
        out = []
        for i in range(n):
            p = g.u32(arr + 4 * i)
            if p:
                out.append({"index": i, "hash": f"0x{g.u32(p + MI_HASH):08x}", "type": g.u8(p + MI_TYPE),
                            "txd_slot": g.i16(p + MI_TXD)})
        return out

    def txd_names(self) -> list[str]:
        g = self.game
        pool = g.u32(RI + RI_TXD_POOL)
        items, size = g.u32(pool), g.u32(pool + 8)
        names = []
        for k in range(size if 0 < size < 20000 else 5000):
            o = items + k * TXD_ITEM + TXD_NAME
            if o + 20 > len(g.b):
                break
            names.append(g.cstr(o, 20))
        return names

    def streaming_header(self) -> list[int]:
        cs = self.game.u32(RI + RI_STREAMING)
        return [self.game.u32(cs + 4 * k) for k in range(8)]


def containers(files: dict[str, tuple[int, int]]) -> dict:
    groups: dict[str, dict] = {}
    for path, (_lba, size) in files.items():
        top = path.split("/")[0] if "/" in path else "/"
        g = groups.setdefault(top, {"files": 0, "bytes": 0})
        g["files"] += 1
        g["bytes"] += size
    key = {p: {"lba": l, "size": s} for p, (l, s) in sorted(files.items())
           if p.endswith((".IMG", ".DIR", ".DTZ", ".LVZ", ".CNF", ".GXT", ".SCM", ".XTX"))
           or re.fullmatch(r"S[LC][UE]S_\d+\.\d+", p)}
    return {"file_count": len(files), "groups": groups, "key_files": key}


def character_inventory(disc: VcsDisc) -> dict:
    """Model infos, TXD pool, special-model directory and the GTA3PS2.IMG chunk census, cross-referenced."""
    mis = disc.model_infos()
    txdn = disc.txd_names()
    peds = [dict(mi, txd=txdn[mi["txd_slot"]] if 0 <= mi["txd_slot"] < len(txdn) else "")
            for mi in mis if mi["type"] == MITYPE_PED]
    chunks, other = disc.img_chunks()
    starts = {c["sector"]: c for c in chunks}
    special = []
    for e in find_special_dir(disc.game.b):
        c = starts.get(e["sector"])
        special.append(dict(e, role=classify_special(e["name"]), chunk=c["kind"] if c else None))
    sp_by_sector = {e["sector"]: e["name"] for e in special}

    txds, by_name, depth = [], {}, Counter()
    for c in chunks:
        b = disc.chunk(c["sector"])
        c["sha256"] = hashlib.sha256(b).hexdigest()
        if c["kind"] != "txd":
            continue
        try:
            heads = texlist_headers(b)
        except Exception as e:                           # recorded, not hidden
            txds.append({"sector": c["sector"], "error": _err(e)})
            continue
        for t in heads:
            depth[t["depth"]] += 1
            by_name.setdefault(t["name"].lower(), set()).add(c["sector"])
        txds.append({"sector": c["sector"], "textures": [[t["name"], t["w"], t["h"], t["depth"]] for t in heads]})

    models, skeletal = [], 0
    for c in chunks:
        if c["kind"] != "mdl":
            continue
        s = chunk_strings(disc.chunk(c["sector"]))
        low = {x.lower() for x in s}
        votes = Counter(t for x in low for t in by_name.get(x, ()))
        bones = sorted({w for w in BONE_WORDS for x in low if w in x.replace(" ", "")})
        skeletal += bool(bones)
        row = {"sector": c["sector"], "size": c["size"], "sha256": c["sha256"], "special": sp_by_sector.get(c["sector"]),
               "bone_names": bones, "texture_refs": sorted(x for x in s if x.lower() in by_name)[:24]}
        if votes:
            row["txd_sector"], row["txd_shared_names"] = votes.most_common(1)[0]
        models.append(row)

    vance_txd = sorted({c for n, secs in by_name.items() if "vance" in n for c in secs})
    player_candidates = [m for m in models if m.get("txd_sector") in vance_txd and not m["special"]]
    return {
        "model_infos": {"count_field": disc.game.u32(RI + RI_NUM_MODELINFOS), "used": len(mis),
                        "types": dict(sorted(Counter(m["type"] for m in mis).items()))},
        "txd_pool": {"size": len(txdn), "first": txdn[:16]},
        "peds": peds,
        "player_model_info": next((p for p in peds if p["index"] == 0), None),
        "special_dir": special,
        "special_roles": dict(Counter(e["role"] for e in special)),
        "img": {"path": IMG_PATH, "sectors": disc.img_sectors, "mdl": sum(c["kind"] == "mdl" for c in chunks),
                "txd": sum(c["kind"] == "txd" for c in chunks), "unrecognised_sectors": other},
        "texture_depths": {str(k): v for k, v in sorted(depth.items())},
        "txds": txds,
        "models": models,
        "models_with_bone_names": skeletal,
        "vance_txd_sectors": vance_txd,
        "player_candidates": [{k: m[k] for k in ("sector", "size", "sha256", "txd_sector", "txd_shared_names")}
                              for m in player_candidates],
        "streaming_header": disc.streaming_header(),
    }


def lcs_reader_check(disc: VcsDisc, special: list[dict], chunks_txd: list[int]) -> dict:
    """Does the LCS reader (gta_stories_models) parse this build's peds and texture lists? Recorded, not assumed."""
    out = {"read_ped": {}, "read_chk": {}}
    for e in [x for x in special if x["role"] in ("story", "cutscene_player")][:4]:
        try:
            m = read_ped(disc.chunk(e["sector"]))
            out["read_ped"][e["name"]] = f"ok: {len(m.hier)} bones, {len(m.strips)} strips"
        except Exception as ex:
            out["read_ped"][e["name"]] = _err(ex)
    for s in chunks_txd[:3]:
        try:
            out["read_chk"][str(s)] = f"ok: {len(read_chk(disc.chunk(s)))} textures"
        except Exception as ex:
            out["read_chk"][str(s)] = _err(ex)
    return out


def chd_info(rom: Path, chdman: str | None = None) -> dict:
    exe = chdman or shutil.which("chdman")
    if not exe:
        return {"error": "chdman not found"}
    try:
        txt = subprocess.run([exe, "info", "-i", str(rom)], capture_output=True, text=True, timeout=120).stdout
    except Exception as e:
        return {"error": _err(e)}
    keep = [ln.strip() for ln in txt.splitlines()
            if ln.strip().startswith(("File Version", "Logical size", "Hunk Size", "Metadata", "TRACK"))]
    return {"lines": keep, "cd_type": "CHT2" in txt or "CHTR" in txt or "CHCD" in txt}


def build_manifest(iso: Path, rom: Path | None = None, hash_sources: bool = True, chdman: str | None = None) -> dict:
    iso = Path(iso)
    with VcsDisc(iso) as disc:
        cnf = parse_system_cnf(disc.read("SYSTEM.CNF").decode("latin-1"))
        exe = disc.read(cnf["executable"])
        chars = character_inventory(disc)
        mocap = parse_dir(disc.read(MOCAP_DIR))
        stems = sorted({e["name"].rsplit(".", 1)[0] for e in mocap})
        man = {
            "game_ids": GAME_IDS,
            "source": {"rom": str(rom) if rom else None, "iso": str(iso), "iso_size": iso.stat().st_size},
            "boot": dict(cnf, expected=EXPECTED_BOOT, matches=cnf["executable"] == EXPECTED_BOOT,
                         sha256=hashlib.sha256(exe).hexdigest(), size=len(exe), elf=elf_info(exe)),
            "launch": LAUNCH,
            "containers": containers(disc.files),
            "levels": {lv: {"img": disc.files.get(f"{lv}.IMG", (0, 0))[1], "lvz": disc.files.get(f"{lv}.LVZ", (0, 0))[1]}
                       for lv in LEVELS},
            "game_dtz": {"path": DTZ_PATH, "sha256": hashlib.sha256(disc.dtz).hexdigest(), "size": len(disc.dtz),
                         "gtag_size": len(disc.game.b), "relocs": disc.game.num_relocs},
            "characters": chars,
            "cutscenes": {"dir": MOCAP_DIR, "entries": len(mocap), "cutscenes": len(stems),
                          "kinds": dict(Counter(e["name"].rsplit(".", 1)[-1].upper() for e in mocap)), "names": stems},
            "lcs_reader": lcs_reader_check(disc, chars["special_dir"], [t["sector"] for t in chars["txds"]]),
        }
    if hash_sources:
        man["source"]["iso_sha256"] = sha256_file(iso)
        if rom:
            man["source"]["rom_sha256"] = sha256_file(Path(rom))
            man["source"]["rom_size"] = Path(rom).stat().st_size
            man["source"]["chd"] = chd_info(Path(rom), chdman)
    return man


def summary(man: dict) -> dict:
    c = man["characters"]
    return {"boot": man["boot"]["executable"], "boot_sha256": man["boot"]["sha256"],
            "rom_sha256": man["source"].get("rom_sha256"), "iso_sha256": man["source"].get("iso_sha256"),
            "files": man["containers"]["file_count"], "model_infos": c["model_infos"], "peds": len(c["peds"]),
            "player": c["player_model_info"], "special": len(c["special_dir"]), "special_roles": c["special_roles"],
            "img": c["img"], "texture_depths": c["texture_depths"], "models_with_bone_names": c["models_with_bone_names"],
            "player_candidates": c["player_candidates"], "cutscenes": man["cutscenes"]["cutscenes"],
            "lcs_reader": man["lcs_reader"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("iso", type=Path)
    ap.add_argument("--rom", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--copy-exe", type=Path, help="also save the boot executable here (originals untouched)")
    ap.add_argument("--no-hash", action="store_true", help="skip hashing the ISO/ROM")
    a = ap.parse_args(argv)
    man = build_manifest(a.iso, a.rom, hash_sources=not a.no_hash)
    if a.copy_exe:
        a.copy_exe.mkdir(parents=True, exist_ok=True)
        with VcsDisc(a.iso) as d:
            (a.copy_exe / man["boot"]["executable"]).write_bytes(d.read(man["boot"]["executable"]))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(man, indent=1))
    print(json.dumps(summary(man), indent=1))


if __name__ == "__main__":
    main()
