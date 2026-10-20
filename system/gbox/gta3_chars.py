"""GTA III (PS2) native character reader (#1309): Claude, the player ped, read from the owned disc into the collection.

The player is model index 0 (MI_PLAYER), a *special* ped model whose skin is its own GTA3.IMG pair: 'player'
(player.dff + player.txd, his Liberty City outfit) and the prison jumpsuit 'playerp' that main.scm loads for the
opening mission. Both are RenderWare 3.1 clumps with 17 named frames (Swaist, Smid, Storso, Shead, the arm and leg
chains), one plain (non-native) geometry per atomic, rigid parts (no skin plugin), textured from one 8-bit PS2
raster. The format code is shared with the native writer (gbox/gta_rw.py, gbox/gta3_swap.py), so the collection
entry is exactly the rig the writer fits other characters onto, and every ped animation in ANIM/PED.IFP keys
these frame names.

Source: the owned image is a .7z holding the 4.6 GB DVD ISO. `stream_entries` streams the ISO out of 7-Zip without
unpacking it to disk, walks the ISO9660 tree and MODELS/GTA3.DIR, grabs only the wanted IMG entries (from the first
of the identical GTA3*.IMG copies still ahead in the stream) and hashes the whole image on the way (the exact-build
check). The few hundred KB are cached with their sha256 (`stock_entries`).

Actor identity: CModelInfo::ms_modelInfoPtrs[0] in a RAM image of the session names the skin the player wears
(`identify_skin`); a centre pick with slot=player resolves to that roster entry (`pick_entry`).
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
import time
from pathlib import Path

import numpy as np

from . import gta_rw as R

GAME_IDS = {"265819390074bb4e": "Grand Theft Auto III (USA, Canada)"}
SECTOR = R.SECTOR
# owned quickswap2 7z (sha256 98d17cb7...) -> this ISO. Entry hashes are sector-padded GTA3.IMG entries, as
# gta3_swap.build_mod recorded them from the unpacked vanilla image (mods gta3_sa2_amy_rose*/.gbox-mod.json).
ISO_SHA256 = {"707714a290e8a6b700fb424dc437ffe0ee580181243ad6fa56b2c025bdca9e68":
              "Grand Theft Auto III (USA, Canada), SLUS-20062"}
STOCK_SHA256 = {"player.dff": "922b2758090d55e4095d27c69825d619211f5b200e5d015c417ecad800e968a1",
                "player.txd": "2a7cc19ba52cd969832c6aede7151d42f664ebb064cfa0410a508cedd4c29872",
                "playerp.dff": "aabbd81e865f96822d7bdabcaed85876f5b3a0cefe312eb0f0a7b79f74e3a544",
                "playerp.txd": "3cd4467d852994111facd46736fbad51758a69297d23878c1623a369ce8016ef"}
SKINS = {"player": ("gta3_claude", "Claude (GTA III)",
                    ["Claude", "GTA III Claude", "GTA 3 Claude", "GTA III player"]),
         "playerp": ("gta3_claude_prison", "Claude, prison outfit (GTA III)",
                     ["prison Claude", "Claude prison outfit", "Claude in prison clothes", "GTA III prison Claude"])}
ANIM_FILE = "ANIM/PED.IFP"
RW_TEXTURE = 0x06
PED_IDS = ("cop", "swat", "fbi")              # GTA III ped model indices 1..3 (default.ide / peds.ide order)


def roster() -> list[dict]:
    return [{"key": k, "slug": s, "name": n, "aliases": list(a), "kind": "character"} for k, (s, n, a) in SKINS.items()]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------------------------- streamed disc
def _iso_chunks(rom: Path, size: int = 1 << 24):
    """The 2048-byte-sector image of a .7z/.zip (its .iso member, streamed by 7-Zip) or of a plain .iso."""
    rom = Path(rom)
    if rom.suffix.lower() in (".7z", ".zip"):
        lst = subprocess.run(["7z", "l", "-slt", str(rom)], capture_output=True, text=True, timeout=900)
        members = [ln[7:] for ln in lst.stdout.splitlines() if ln.startswith("Path = ") and ln.lower().endswith(".iso")]
        if lst.returncode or not members:
            raise ValueError(f"{rom.name}: no .iso member ({(lst.stdout + lst.stderr)[-300:]})")
        p = subprocess.Popen(["7z", "x", "-so", str(rom), members[0]], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                b = p.stdout.read(size)
                if not b:
                    break
                yield b
        finally:
            p.stdout.close()
            if p.poll() is None:
                p.kill()
            p.wait()
    else:
        with open(rom, "rb") as f:
            while b := f.read(size):
                yield b


def _dir_records(buf: bytes, pre: str):
    o = 0
    while o < len(buf):
        ln = buf[o]
        if ln == 0:
            o = (o // SECTOR + 1) * SECTOR
            continue
        if o >= SECTOR and not any(buf[o - o % SECTOR:]):
            break
        lba, size = struct.unpack_from("<I", buf, o + 2)[0], struct.unpack_from("<I", buf, o + 10)[0]
        nm = buf[o + 33:o + 33 + buf[o + 32]]
        if nm not in (b"\0", b"\1"):
            yield pre + nm.decode("ascii", "replace").split(";")[0].upper(), lba, size, bool(buf[o + 25] & 2)
        o += ln


def stream_entries(rom: Path, names, img: str = "MODELS/GTA3.IMG", extra_files=(ANIM_FILE,), progress=None,
                   max_passes: int = 4) -> dict:
    """IMG entries (sector padded, keyed lower case) + whole files from the ISO, read in stream order. Directory
    records, the .DIR and the entries can sit anywhere: whatever is behind the stream position when it becomes known
    is taken from a later identical IMG copy, else on the next pass. Pass 1 always reads to the end (iso_sha256)."""
    names = [n.lower() for n in names]
    stem = img.rsplit(".", 1)[0]
    dir_path = stem + ".DIR"
    files: dict[str, tuple[int, int]] = {}
    want: dict[str, list[tuple[int, int]]] = {"pvd": [(16 * SECTOR, SECTOR)]}
    got: dict[str, bytes] = {}
    used: dict[str, int] = {}
    where: dict[str, dict] = {}

    def follow(key: str, data: bytes) -> dict:
        new = {}
        if key == "pvd":
            if data[1:6] != b"CD001":
                raise ValueError("not an ISO9660 image (no CD001 at sector 16)")
            new["dir:"] = [(struct.unpack_from("<I", data, 158)[0] * SECTOR, struct.unpack_from("<I", data, 166)[0])]
        elif key.startswith("dir:"):
            for path, lba, size, isdir in _dir_records(data, key[4:]):
                if isdir:
                    new[f"dir:{path}/"] = [(lba * SECTOR, size)]
                else:
                    files[path] = (lba, size)
            for f in (dir_path, *extra_files):
                if f in files and f"file:{f}" not in want:
                    new[f"file:{f}"] = [(files[f][0] * SECTOR, files[f][1])]
        elif key == f"file:{dir_path}":
            idx = {e[2].lower(): e for e in R.dir_read(data)}
            imgs = [i for i in [img] + sorted((k for k in files if k.startswith(stem + "_") and k.endswith(".IMG")),
                                              key=lambda k: int(k[len(stem) + 1:-4]) if k[len(stem) + 1:-4].isdigit() else 0)
                    if i in files]
            for n in names:
                if n not in idx:
                    raise KeyError(f"{n} isn't in {dir_path}")
                o, s, _ = idx[n]
                new[f"entry:{n}"] = [((files[i][0] + o) * SECTOR, s * SECTOR) for i in imgs]
                where[n] = {"offset_sectors": o, "sectors": s, "imgs": imgs}
        return new

    iso_sha = iso_bytes = None
    npass = 0
    for npass in range(1, max_passes + 1):
        h = hashlib.sha256() if iso_sha is None else None
        pos, bufs = 0, {}

        def arm(key, cands, at):
            for ci, (a, n) in enumerate(cands):
                if a >= at:
                    bufs[key] = (a, n, bytearray(), ci)
                    return True
            return False
        for k, c in want.items():
            if k not in got:
                arm(k, c, 0)
        for chunk in _iso_chunks(rom):
            end = pos + len(chunk)
            if h is not None:
                h.update(chunk)
            busy = True
            while busy:
                busy = False
                for k in list(bufs):
                    a, n, b, ci = bufs[k]
                    lo, hi = max(a + len(b), pos), min(a + n, end)
                    if lo < hi:
                        b += chunk[lo - pos:hi - pos]
                    if len(b) == n:
                        got[k], used[k] = bytes(b), ci
                        del bufs[k]
                        for k2, c2 in follow(k, got[k]).items():
                            if k2 not in want:
                                want[k2] = c2
                                arm(k2, c2, pos)
                                busy = True
            pos = end
            if progress and h is not None and pos % (1 << 30) < len(chunk):
                progress(25 + min(30, pos >> 28), f"Streaming the disc image: {pos >> 20} MB (pass {npass})")
            if h is None and not bufs:
                break
        if h is not None:
            iso_sha, iso_bytes = h.hexdigest(), pos
        if all(k in got for k in want):
            break
    missing = [k for k in want if k not in got]
    if missing:
        raise RuntimeError(f"{Path(rom).name}: {missing} not read after {npass} passes")
    for n in names:
        w = where[n]
        w["img"] = w["imgs"][used[f"entry:{n}"]]
        w["lba"] = files[w["img"]][0] + w["offset_sectors"]
        w["copies"] = len(w.pop("imgs"))
    return {"entries": {n: got[f"entry:{n}"] for n in names},
            "files": {k[5:]: v for k, v in got.items() if k.startswith("file:")},
            "where": where, "iso_sha256": iso_sha, "iso_bytes": iso_bytes, "passes": npass}


def stock_entries(rom: Path, cache: Path, names, progress=None) -> dict:
    """Vanilla IMG entries of the owned image, cached under `cache` with their sha256 (re-streamed when the source
    file changes). A known build whose entry hashes differ from STOCK_SHA256 is refused (a modded image)."""
    rom, cache = Path(rom), Path(cache)
    names = [n.lower() for n in names]
    st = rom.stat()
    key = {"source": str(rom), "bytes": st.st_size, "mtime": int(st.st_mtime)}
    man_p = cache / "manifest.json"
    man = json.loads(man_p.read_text()) if man_p.is_file() else {}
    if man.get("key") == key:
        have = {n: (cache / n).read_bytes() for n in [*man.get("entries", {}), "ped.ifp"] if (cache / n).is_file()}
        if all(n in have and _sha(have[n]) == man["entries"].get(n, {}).get("sha256") for n in names):
            return {**man, "data": have, "cached": True}
    old = sorted(man.get("entries", {})) if man.get("key") == key else []
    want = sorted(set(names) | set(old))
    if progress:
        progress(25, f"Streaming {rom.name} (no unpack): ISO9660 tree, GTA3.DIR, {', '.join(want)}")
    r = stream_entries(rom, want, progress=progress)
    cache.mkdir(parents=True, exist_ok=True)
    known = r["iso_sha256"] in ISO_SHA256
    ents = {}
    for n, b in r["entries"].items():
        exp = STOCK_SHA256.get(n) if known else None
        if exp and _sha(b) != exp:
            raise ValueError(f"{n}: sha256 {_sha(b)[:12]} isn't the vanilla {exp[:12]} (modded image?)")
        (cache / n).write_bytes(b)
        ents[n] = {"sha256": _sha(b), **r["where"][n]}
    data = dict(r["entries"])
    if ANIM_FILE in r["files"]:
        data["ped.ifp"] = r["files"][ANIM_FILE]
        (cache / "ped.ifp").write_bytes(data["ped.ifp"])
    man = {"key": key, "iso_sha256": r["iso_sha256"], "iso_bytes": r["iso_bytes"],
           "build": ISO_SHA256.get(r["iso_sha256"], "unknown build"), "passes": r["passes"], "entries": ents,
           "ped_ifp_sha256": _sha(data["ped.ifp"]) if "ped.ifp" in data else None, "streamed": time.time()}
    man_p.write_text(json.dumps(man, indent=1))
    return {**man, "data": data, "cached": False}


# ---------------------------------------------------------------------------------------------- model
def _walk(c):
    yield c
    for k in getattr(c, "kids", None) or ():
        yield from _walk(k)


def texture_names(dff: bytes) -> list[str]:
    """Texture names the clump's materials reference (RW Texture chunk -> first String)."""
    root, _ = R.parse(dff)
    out = []
    for c in _walk(root):
        if c.type == RW_TEXTURE:
            s = [k for k in (getattr(c, "kids", None) or ()) if k.type == R.STRING]
            if s:
                out.append(s[0].data.split(b"\0")[0].decode("ascii", "replace"))
    return out


def export(dff: bytes, txd: bytes, out: Path, name: str = "Claude") -> dict:
    """player*.dff + player*.txd -> rigged .glb (gta_rw.clump_to_gltf: joints = the 17 frames, each part 100% on its
    frame, the PS2 raster as base colour) and the body roles on the real frame names."""
    from .gta3_swap import Rig, txd_rasters
    rig = Rig(dff)
    rasters = {r.name.lower(): r for r in txd_rasters(txd)}
    used = sorted({t.lower() for t in texture_names(dff)})
    if not used or any(t not in rasters for t in used):
        raise ValueError(f"materials use textures {used}; the TXD has {sorted(rasters)}")
    if len(used) > 1:
        raise NotImplementedError(f"{len(used)} textures {used}: the rigid-ped GLB carries one")
    ras = rasters[used[0]]
    R.clump_to_gltf(dff, Path(out), R.raster_rgba(ras), name)
    names = [f["name"] for f in rig.frames]
    geo = [R.geometry_read(rig.geoms[gi]) for _fi, gi in rig.atomics]
    return {"roles": {r: names[i] for r, i in rig.roles.items()}, "frames": names, "atomics": len(rig.atomics),
            "triangles": int(sum(len(g.tris) for g in geo)), "vertices": int(sum(len(g.pos) for g in geo)),
            "texture": {"name": ras.name, "width": ras.width, "height": ras.height, "depth": ras.depth}}


def self_check(dff: bytes, glb: Path, roles: dict) -> dict:
    """The collection GLB is the writer's own rig: (1) the clump re-serialises byte-identically, (2) the GLB, read back
    through the library loader and fitted onto Claude's frames by gta3_swap.retarget, lands on the stock vertices,
    (3) gta3_swap rebuilds a clump from it with every frame's triangle count unchanged."""
    from . import gta3_swap as S
    rig = S.Rig(dff)
    root, tail = R.parse(dff)
    prims = S.retarget(rig, Path(glb), roles)
    dev = 0.0
    for fi, gi in rig.atomics:
        g = R.geometry_read(rig.geoms[gi])
        world = (np.c_[g.pos, np.ones(len(g.pos))] @ rig.frames[fi]["world"].T)[:, :3]
        mine = [np.asarray(p["pos"], float)[(np.asarray(p["J"])[:, 0] if np.ndim(p["J"]) > 1 else np.asarray(p["J"])) == fi]
                for p in prims]
        mine = np.concatenate(mine) if mine else np.zeros((0, 3))
        if not len(mine):
            dev = float("inf")
            continue
        dev = max(dev, float(np.sqrt(((world[:, None, :] - mine[None, :, :]) ** 2).sum(-1)).min(1).max()))
    uvs = []
    for p in prims:
        T = np.asarray(p["tris"], int).reshape(-1, 3)
        uv = np.asarray(p["uv"], float) if p.get("uv") is not None else np.zeros((len(p["pos"]), 2))
        uvs.append(uv[T])
    new = S.build_dff(rig, S.part_geometries(rig, prims, uvs))
    a, b = S.dff_parts(dff), S.dff_parts(new)
    # The GLB keeps every triangle; seam triangles at joint boundaries can move to the other frame's part, so compare
    # the whole-clump triangle total, not per-frame counts. Byte round trip stays exact.
    total_match = sum(x["triangles"] for x in a.values()) == sum(x["triangles"] for x in b.values())
    return {"byte_roundtrip": root.to_bytes() + tail == dff, "self_retarget_max_dev_m": dev,
            "writer_parts_match": total_match,
            "stock_parts": a, "rebuilt_parts": b}


def ifp_summary(d: bytes) -> dict:
    """ANPK animation package (GTA III PED.IFP): animation names and the frame names they key."""
    def hdr(o):
        return d[o:o + 4], struct.unpack_from("<I", d, o + 4)[0]
    if d[:4] != b"ANPK":
        raise ValueError(f"not an ANPK package ({d[:4]!r})")
    _t, s = hdr(8)
    count = struct.unpack_from("<i", d, 16)[0]
    o = 16 + ((s + 3) & ~3)
    anims, bones = [], set()
    for _ in range(count):
        t, s = hdr(o)
        if t != b"NAME":
            raise ValueError(f"NAME expected at {o:#x}, got {t!r}")
        anims.append(d[o + 8:o + 8 + s].split(b"\0")[0].decode("latin1"))
        o += 8 + ((s + 3) & ~3)
        t, s = hdr(o)
        if t != b"DGAN":
            raise ValueError(f"DGAN expected at {o:#x}, got {t!r}")
        end, p = o + 8 + s, o + 8
        _t2, s2 = hdr(p)
        nobj = struct.unpack_from("<i", d, p + 8)[0]
        p += 8 + ((s2 + 3) & ~3)
        for _ in range(nobj):
            t3, s3 = hdr(p)
            if t3 != b"CPAN":
                raise ValueError(f"CPAN expected at {p:#x}, got {t3!r}")
            if d[p + 8:p + 12] == b"ANIM":
                bones.add(d[p + 16:p + 44].split(b"\0")[0].decode("latin1").lower())
            p += 8 + ((s3 + 3) & ~3)
        o = end + (-end % 4)
    return {"animations": len(anims), "names": anims, "bones": sorted(bones)}


# ---------------------------------------------------------------------------------------------- actor identity
def ram_from_elf(elf: bytes) -> tuple[int, bytes]:
    """(base address, bytes) of the first PT_LOAD of a 32-bit little-endian ELF (gBox re_executable source=ram)."""
    if elf[:4] != b"\x7fELF":
        raise ValueError("not an ELF image")
    phoff = struct.unpack_from("<I", elf, 0x1C)[0]
    phentsize, phnum = struct.unpack_from("<HH", elf, 0x2A)
    for i in range(phnum):
        t, off, va, _pa, fs, _ms, _fl, _al = struct.unpack_from("<8I", elf, phoff + i * phentsize)
        if t == 1:
            return va, elf[off:off + fs]
    raise ValueError("no PT_LOAD segment")


def identify_skin(ram: bytes, base: int = 0) -> dict | None:
    """CModelInfo::ms_modelInfoPtrs in PS2 RAM: the pointer table whose entries 1..3 name cop, swat and fbi. Entry 0
    is the player's model (MI_PLAYER); its name is the special skin he wears now ('player' / 'playerp')."""
    def name_at(addr, k):
        o = addr - base + k
        return ram[o:o + 24].split(b"\0")[0].decode("latin1") if 0 <= o <= len(ram) - 24 else None
    cops, i = [], ram.find(b"cop\0")
    while i >= 0:
        if i % 4 == 0:
            cops.append(i)
        i = ram.find(b"cop\0", i + 1)
    for k in (4, *range(0, 0x40, 4)):
        for c in cops:
            pat = struct.pack("<I", base + c - k)
            j = ram.find(pat)
            while j >= 0:
                if j % 4 == 0 and 4 <= j <= len(ram) - 12:
                    ptrs = struct.unpack_from("<4I", ram, j - 4)
                    if [name_at(p, k) for p in ptrs[1:]] == list(PED_IDS):
                        skin = name_at(ptrs[0], k)
                        if skin:
                            return {"table": base + j - 4, "name_offset": k, "model0": ptrs[0], "skin": skin.lower()}
                j = ram.find(pat, j + 1)
    return None


def session_ram(cfg, game_id: str, sess) -> Path | None:
    """The newest RAM image gBox's re_executable (source=ram) saved for this game while `sess` was running."""
    if not isinstance(sess, dict):
        return None
    data = getattr(cfg, "data", None) or getattr(cfg, "data_dir", None)
    d = Path(data) / "analysis" / "re" / game_id if data else None
    if d is None or not d.is_dir():
        return None
    lo, hi = float(sess.get("started") or 0), float(sess.get("ended") or time.time()) + 60
    cands = [p for p in d.glob("ram_*.elf") if lo <= p.stat().st_mtime <= hi]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


_GENERIC = re.compile(r"\b(character|player|guy|man|person|him|he|this|middle|cent(?:er|re)|screen|protagonist)\b")
_NOT_PED = re.compile(r"\b(car|cars|taxi|truck|van|bus|bike|boat|vehicle|plane|helicopter|tank|train|building|weapon|gun)\b")


def pick_entry(ctx, game: dict, entries: list[dict], what: str, pick: dict) -> tuple[dict, dict] | None:
    """'the character in the middle of the screen' (slot=player, a centre pick): GTA III's chase camera keeps the
    player ped at the screen centre, so the pick is model 0. His skin comes from a RAM image of that session
    (identify_skin) when one exists, else the default skin, reported as unconfirmed. Off-centre picks, vehicles and
    other slots return None: that is another ped or a car, which this reader doesn't hold."""
    pick, text = pick or {}, (what or "").lower()
    if (pick.get("slot") or "player") != "player" or (pick.get("kind") or "character") != "character":
        return None
    if not _GENERIC.search(text) or _NOT_PED.search(text):
        return None
    x, y = pick.get("x"), pick.get("y")
    if x is not None and y is not None and not (0.3 <= float(x) <= 0.7 and 0.3 <= float(y) <= 0.8):
        return None
    why = {"rule": "slot=player centre pick -> model index 0 (MI_PLAYER)", "x": x, "y": y}
    skin = pick.get("skin")
    if skin:
        why["skin_from"] = "caller"
    elif ctx is not None:
        p = session_ram(ctx.config, game["game_id"], pick.get("session"))
        hit = identify_skin(*reversed(ram_from_elf(p.read_bytes()))) if p is not None else None
        if hit:
            skin = hit["skin"]
            why.update(skin_from=str(p), model_info_table=hex(hit["table"]), model0=hex(hit["model0"]))
    if not skin:
        skin, why["skin_from"] = "player", "default (no RAM image of this session)"
    e = next((x for x in entries if x["key"] == skin), None)
    return (e, {**why, "skin": skin}) if e else None


# ---------------------------------------------------------------------------------------------- DEDICATED route
def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters op=extract / collect (DEDICATED 'gta3'): one of Claude's skins straight from the owned disc."""
    from . import characters as C
    skin = (e.get("key") or "player").lower()
    if skin not in SKINS:
        raise ValueError(f"{skin}: not a GTA III player skin ({', '.join(SKINS)})")
    rom = C._rom(ctx, game)
    dn, tn = f"{skin}.dff", f"{skin}.txd"
    src = stock_entries(rom, Path(ctx.config.cache) / "gta3" / game["game_id"], [dn, tn], ctx.progress)
    dff, txd = src["data"][dn], src["data"][tn]
    ctx.progress(60, f"Decoding {dn} (RW 3.1 clump, 17 frames) and {tn} (PS2 8-bit raster)")
    out = Path(work) / f"{e['slug']}.glb"
    info = export(dff, txd, out, e["name"])
    ctx.progress(70, "Checking it against Claude's own rig (byte round trip, self-retarget, writer rebuild)")
    chk = self_check(dff, out, info["roles"])
    if not (chk["byte_roundtrip"] and chk["writer_parts_match"]):
        raise RuntimeError(f"{skin}: round trip failed: {chk}")
    anim = None
    if src["data"].get("ped.ifp"):
        try:
            s = ifp_summary(src["data"]["ped.ifp"])
            fr = {f.lower() for f in info["frames"]}
            anim = {"file": ANIM_FILE, "sha256": _sha(src["data"]["ped.ifp"]), "animations": s["animations"],
                    "frames_keyed": sorted(fr & set(s["bones"])), "frames_unkeyed": sorted(fr - set(s["bones"]))}
        except (ValueError, struct.error) as exc:
            anim = {"file": ANIM_FILE, "error": str(exc)}
    where = {n: src["entries"][n] for n in (dn, tn)}
    native = {"model_index": 0, "special_model": skin, "iso_sha256": src["iso_sha256"], "build": src["build"],
              "source_sha256": {n: w["sha256"] for n, w in where.items()}, "img": where, "texture": info["texture"],
              "frames": info["frames"], "animation": anim,
              "check": {k: v for k, v in chk.items() if k not in ("stock_parts", "rebuilt_parts")}}
    return {"files": [out], "tool": "gbox.gta3_chars (RW 3.1 clump + PS2 TXD reader shared with gta3_swap)",
            "roles": info["roles"],
            "source_files": [f"MODELS/GTA3.IMG: {n} (LBA {w['lba']}, {w['sectors']} sectors, sha256 {w['sha256'][:16]})"
                             for n, w in where.items()],
            "notes": (f"GTA III player ped (model 0, special skin '{skin}'): {info['atomics']} rigid parts on "
                      f"{len(info['frames'])} frames, {info['triangles']} triangles, texture {info['texture']['name']} "
                      f"{info['texture']['width']}x{info['texture']['height']} 8-bit. Self-retarget max deviation "
                      f"{chk['self_retarget_max_dev_m'] * 1000:.2f} mm; the writer rebuild keeps every part."),
            "extra": {"native_player": True, "native": native},
            "check": {k: v for k, v in chk.items() if k not in ("stock_parts", "rebuilt_parts")}}
