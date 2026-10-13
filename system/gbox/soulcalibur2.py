"""Soul Calibur II (GameCube, GRSEAF, USA): the fighters as rigged, textured GLBs (docs/soulcalibur2_gc.md).

The disc holds four files; `root.olk` (560 MB) is a Namco OLK archive of five nested OLKs (motinfo, cpudata, cdata,
stage, human; their names come from main.dol's table at 0x80257b2c). `human.olk` is the cast: per fighter a block of
entries starting at the fighter's base (main.dol table 0x80277a58, u16 per fighter id):

  base + c       costume c (c < the fighter's costume count, main.dol 0x80275a60 + id * 0xf8, +0x8a)
  base + 8 + c   the same costume for the Extra modes (fighters flagged in 0x80277a9c)
  base + 16 + w  weapon w (Weapon Master / weapon select), a 3-child package: VMG, motion, hit spheres

A costume entry is a 14-child package (u32 count, u32 child offsets, 0x80-aligned): 0 the VMG model (gbox.sc2_vmg),
1 hit spheres, 2/12 motions ("mmg"), 3 face data, 4 "lpb" move list, 5 "vtb", 6 a table, 13 the default weapon
package. The body loader (0x800a1e4c, case 7) asks for base + min(costume, count) (+8 in Extra mode).

`characters op=collect` on the disc runs `extract_run` per `roster()` entry (characters.DEDICATED "soulcalibur2"):
costume 1's body on the full skeleton (the 21 body bones, fingers, face and swing bones; skin weights up to 4),
every texture, the default weapon attached to the hand bones as the game holds it, metres, +Y up, facing +Z, left
+X, the 18 body roles from the bone names (KOSHI hip, MUNE2 chest, KUBI neck, ATAMA head, SAKOTSU / KATA / UDE / TE
arms, MOMO / HIZA / ASHI legs). The writer is gbox.soulcalibur2_swap.

  python -m gbox.soulcalibur2 <disc .iso|.gcz> <out dir> [fighter key ...]     GLBs + preview PNGs
"""
from __future__ import annotations

import functools
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import sc2_vmg as V

READER_VERSION = 1
DISC_ID = "GRSEAF"
GAME_TITLE = "Soul Calibur II"
GAME_IDS = {"201629ad498aba7b": "Soul Calibur II (USA) [gcz]",
            "e08e8a0c1b3c9060": "Soulcalibur II (USA) [iso]"}
OLK_NAMES = ("motinfo", "cpudata", "cdata", "stage", "human")
HUMAN = OLK_NAMES.index("human")
# main.dol (virtual addresses; the DOL's own section table maps them to file offsets)
BASE_TABLE = 0x80277A58          # s16 human.olk base entry per fighter id (-1 = no fighter)
EXTRA_TABLE = 0x80277A9C         # u8 per fighter id: costumes are duplicated at +8 for the Extra modes
CHAR_TABLE = 0x80275A60          # 0xf8 per fighter id; +0x8a s16 costume count
COSTUME_LOAD = 0x800A213C        # body load: lha r27, 0x64(r31) (the costume) ... cmpw / bgt / mr r3, r27

# Fighter ids are the game's (1-based; 7-10, 14, 16, 28, 29 are unused on the GameCube disc).
FIGHTERS = [
    (1, "mitsurugi", "Heishiro Mitsurugi", ["Mitsurugi"]),
    (2, "seung_mina", "Seung Mina", ["Mina"]),
    (3, "taki", "Taki", []),
    (4, "maxi", "Maxi", []),
    (5, "voldo", "Voldo", []),
    (6, "sophitia", "Sophitia Alexandra", ["Sophitia"]),
    (11, "ivy", "Isabella Valentine", ["Ivy"]),
    (12, "kilik", "Kilik", []),
    (13, "xianghua", "Chai Xianghua", ["Xianghua"]),
    (15, "yoshimitsu", "Yoshimitsu", []),
    (17, "nightmare", "Nightmare", []),
    (18, "astaroth", "Astaroth", []),
    (19, "inferno", "Inferno", []),
    (20, "cervantes", "Cervantes de Leon", ["Cervantes"]),
    (21, "raphael", "Raphael Sorel", ["Raphael"]),
    (22, "talim", "Talim", []),
    (23, "cassandra", "Cassandra Alexandra", ["Cassandra"]),
    (24, "charade", "Charade", []),
    (25, "necrid", "Necrid", []),
    (26, "yunsung", "Hong Yunsung", ["Yunsung"]),
    (27, "link", "Link", ["Link (Soul Calibur II)", "Hyrule"]),
    (30, "lizardman", "Lizardman", []),
    (31, "assassin", "Assassin", []),
    (32, "berserker", "Berserker", []),
]
# what the owned disc says (main.dol tables), kept for documentation and the synthetic tests
EXPECTED = {"mitsurugi": (46, 3, 1), "seung_mina": (85, 3, 1), "taki": (124, 3, 1), "maxi": (163, 2, 1),
            "voldo": (202, 3, 0), "sophitia": (241, 3, 1), "ivy": (280, 3, 1), "kilik": (319, 2, 1),
            "xianghua": (358, 3, 1), "yoshimitsu": (397, 2, 1), "nightmare": (436, 3, 1), "astaroth": (475, 3, 1),
            "inferno": (748, 1, 0), "cervantes": (514, 2, 1), "raphael": (553, 3, 1), "talim": (592, 3, 1),
            "cassandra": (631, 3, 1), "charade": (787, 2, 0), "necrid": (670, 2, 0), "yunsung": (709, 2, 1),
            "link": (943, 4, 0), "lizardman": (826, 6, 0), "assassin": (865, 6, 0), "berserker": (904, 6, 0)}
ROLE_BONES = {"hip": "KOSHI", "chest": "MUNE2", "neck": "KUBI", "head": "ATAMA", "l_clav": "SAKOTSU_L",
              "r_clav": "SAKOTSU_R", "l_upper": "KATA_L", "l_fore": "UDE_L", "l_hand": "TE_L", "r_upper": "KATA_R",
              "r_fore": "UDE_R", "r_hand": "TE_R", "l_thigh": "MOMO_L", "l_shin": "HIZA_L", "l_foot": "ASHI_L",
              "r_thigh": "MOMO_R", "r_shin": "HIZA_R", "r_foot": "ASHI_R"}
WEAPON_BONES = {"BUKI_1": "TE_R", "BUKI_2": "TE_L"}     # weapon VMG bone -> the hand bone it rides


def slug_of(key: str) -> str:
    return f"sc2_{key}"


def fighter(key: str) -> tuple:
    k = key.lower().removeprefix("sc2_").replace(" ", "_").replace("-", "_")
    for f in FIGHTERS:
        if k in (f[1], f[2].lower().replace(" ", "_")) or k in [a.lower().replace(" ", "_") for a in f[3]]:
            return f
    raise KeyError(f"no Soul Calibur II fighter {key!r} ({', '.join(f[1] for f in FIGHTERS)})")


def roster() -> list[dict]:
    return [{"key": k, "slug": slug_of(k), "name": f"{name} (Soul Calibur II)", "aliases": [name, *al, f"SC2 {name}"],
             "kind": "character", "fighter_id": fid, "native_player": k == "mitsurugi"}
            for fid, k, name, al in FIGHTERS]


# ------------------------------------------------------------------------------------------------ the disc

class Disc:
    """Random access over a Soul Calibur II disc image (.iso / .gcm, or .gcz through gbox.gcz), read-only."""

    def __init__(self, path):
        self.path = Path(path)
        if self.path.suffix.lower() == ".gcz":
            from .gcz import GCZ
            self._g = GCZ(str(self.path))
            self.read = self._g.read
            self.size = self._g.data_size
        else:
            self._f = open(self.path, "rb")
            self.size = self.path.stat().st_size
        hdr = self.read(0, 0x440)
        self.game_id = hdr[:6].decode("ascii", "replace")
        if self.game_id != DISC_ID:
            raise ValueError(f"{self.path.name}: expected Soul Calibur II ({DISC_ID}), got {self.game_id}")
        from .formats.gcfst import parse_fst
        self.dol_offset, fst_off, fst_size = struct.unpack_from(">III", hdr, 0x420)
        self.files = {p: (a, b) for p, a, b, _e in parse_fst(self.read(fst_off, fst_size), fst_off)}
        self.fst_entries = {p: e for p, _a, _b, e in parse_fst(self.read(fst_off, fst_size), fst_off)}
        self.root = self.files["root.olk"][0]
        self.groups = olk_table(self.read(self.root, 0x800), self.root)
        self._human = None

    def read(self, off: int, n: int) -> bytes:              # replaced by the GCZ reader for .gcz images
        self._f.seek(off)
        return self._f.read(n)

    def close(self):
        if hasattr(self, "_f"):
            self._f.close()
        if hasattr(self, "_g"):
            self._g.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def group(self, i: int) -> list[tuple[int, int]]:
        """Entries of the i-th nested OLK as absolute (disc offset, size)."""
        off, size = self.groups[i]
        head = self.read(off, 16)
        n = struct.unpack_from("<I", head)[0]
        return olk_table(self.read(off, 16 * (n + 2)), off)

    @property
    def human(self) -> list[tuple[int, int]]:
        if self._human is None:
            self._human = self.group(HUMAN)
        return self._human

    def entry(self, i: int) -> bytes:
        off, size = self.human[i]
        return self.read(off, size) if size else b""

    @functools.cached_property
    def dol(self) -> bytes:
        hdr = self.read(self.dol_offset, 0x100)
        offs, sizes = struct.unpack_from(">18I", hdr, 0), struct.unpack_from(">18I", hdr, 0x90)
        end = max(o + s for o, s in zip(offs, sizes) if s)
        return self.read(self.dol_offset, end)


def olk_table(head: bytes, base: int = 0) -> list[tuple[int, int]]:
    """An OLK ("olnk", little-endian) header + records -> [(absolute offset, size)] (size 0 = empty slot)."""
    if head[4:8] != b"olnk":
        raise ValueError("not an OLK archive (no 'olnk' at +4)")
    n = struct.unpack_from("<I", head)[0]
    data_start = struct.unpack_from("<I", head, 16)[0]
    out = []
    for i in range(n):
        off, size = struct.unpack_from("<II", head, 32 + 16 * i)
        out.append((base + data_start + off, size))
    return out


def package(data: bytes) -> list[tuple[int, int]] | None:
    """A Namco package (big-endian u32 count, u32 child offsets, 0 = absent) -> [(offset, size)] per child (size 0
    for an absent / empty child), or None when `data` is not one."""
    if len(data) < 8:
        return None
    c = struct.unpack_from(">I", data)[0]
    if not 0 < c < 64 or 4 + 4 * c > len(data):
        return None
    offs = struct.unpack_from(f">{c}I", data, 4)
    nz = [x for x in offs if x]
    if not nz or nz != sorted(nz) or nz[0] < 4 + 4 * c or nz[-1] > len(data):
        return None
    out = []
    for i, x in enumerate(offs):
        nxt = [y for y in offs[i + 1:] if y]
        out.append((x, ((nxt[0] if nxt else len(data)) - x) if x else 0))
    return out


def dol_read(dol: bytes, addr: int, n: int) -> bytes:
    o = dol_offset(dol, addr)
    return dol[o:o + n]


def dol_offset(dol: bytes, addr: int) -> int:
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0, 0x48, 0x90))
    for o, a, s in zip(offs, addrs, sizes):
        if s and a <= addr < a + s:
            return o + addr - a
    raise ValueError(f"{addr:#x} is not in main.dol")


def fighter_table(dol: bytes) -> dict[str, dict]:
    """{key: {id, base, costumes, extra, entries: [[normal, extra?] per costume], weapons}} from main.dol."""
    out = {}
    for fid, key, name, _al in FIGHTERS:
        base = struct.unpack(">h", dol_read(dol, BASE_TABLE + 2 * fid, 2))[0]
        count = struct.unpack(">h", dol_read(dol, CHAR_TABLE + fid * 0xF8 + 0x8A, 2))[0]
        extra = dol_read(dol, EXTRA_TABLE + fid, 1)[0] != 0
        if base < 0 or count < 1:
            continue
        out[key] = {"id": fid, "name": name, "base": base, "costumes": count, "extra": extra,
                    "entries": [[base + c] + ([base + 8 + c] if extra else []) for c in range(count)]}
    return out


# ------------------------------------------------------------------------------------------------ models

@dataclass
class Costume:
    key: str
    costume: int
    entry: int
    package: bytes
    children: list
    vmg: V.Vmg

    @property
    def weapon(self) -> V.Vmg | None:
        if len(self.children) > 13 and self.children[13][1]:
            o, s = self.children[13]
            w = self.package[o:o + s]
            kids = package(w)
            if kids and kids[0][1] and w[kids[0][0]:kids[0][0] + 4] == V.MAGIC:
                return V.parse(w[kids[0][0]:kids[0][0] + kids[0][1]])
        return None


def read_costume(disc: Disc, key: str, costume: int = 0, extra: bool = False) -> Costume:
    t = fighter_table(disc.dol)
    f = t[fighter(key)[1]]
    if not 0 <= costume < f["costumes"]:
        raise ValueError(f"{f['name']} has {f['costumes']} costumes (asked for {costume + 1})")
    ents = f["entries"][costume]
    entry = ents[1] if extra and len(ents) > 1 else ents[0]
    data = disc.entry(entry)
    kids = package(data)
    if not kids or not kids[0][1] or data[kids[0][0]:kids[0][0] + 4] != V.MAGIC:
        raise ValueError(f"human.olk entry {entry} is not a costume package")
    o, s = kids[0]
    return Costume(fighter(key)[1], costume, entry, data, kids, V.parse(data[o:o + s]))


def roles_of(v: V.Vmg) -> dict[str, str]:
    names = {b.name for b in v.bones}
    return {r: n for r, n in ROLE_BONES.items() if n in names}


def joints_of(v: V.Vmg, W: np.ndarray) -> list[dict]:
    return [{"parent": b.parent if 0 <= b.parent < b.index else -1, "world": W[b.index]} for b in v.bones]


def joint_names(v: V.Vmg) -> list[str]:
    seen, out = set(), []
    for b in v.bones:
        n = b.name or f"bone{b.index:03d}"
        if n in seen:
            n = f"{n}_{b.index}"
        seen.add(n)
        out.append(n)
    return out


def weapon_prims(body: V.Vmg, W: np.ndarray, weapon: V.Vmg) -> list[dict]:
    """The weapon's meshes on the body's hand bones (BUKI_1 -> TE_R, BUKI_2 -> TE_L, with their child bones), in the
    body's bind pose. In game every weapon root is driven by the weapon's own motion (package child 1), so the grip
    angle here is the root's rest frame, not a fight stance; other roots (Link's bombs, bow, boomerang ...) are
    props the moves bring out and are left off."""
    prims, _Ww, _n = V.decode(weapon)
    by_name = {b.name: b.index for b in body.bones}
    wW = V.bind_world(weapon)
    out = []
    for p in prims:
        wb = int(p["J"][0, 0])
        root = wb
        while 0 <= root < len(weapon.bones) and 0 <= weapon.bones[root].parent < root:
            root = weapon.bones[root].parent
        hand_name = WEAPON_BONES.get(weapon.bones[root].name if 0 <= root < len(weapon.bones) else "")
        if hand_name is None or hand_name not in by_name:
            continue
        hand = by_name[hand_name]
        local = np.linalg.inv(wW[root])                # decode() put the weapon in its own frame: back to root space
        P = p["pos"] @ local[:3, :3].T + local[:3, 3]
        N = p["nrm"] @ local[:3, :3].T
        M = W[hand]
        J = np.zeros_like(p["J"])
        J[:, 0] = hand
        Wt = np.zeros_like(p["W"])
        Wt[:, 0] = 1
        out.append(p | {"pos": P @ M[:3, :3].T + M[:3, 3], "nrm": N @ M[:3, :3].T, "J": J, "W": Wt,
                        "weapon": True})
    return out


def export(c: Costume, out: Path, name: str = "", weapon: bool = True, second_colour: bool = False) -> dict:
    """Costume -> skinned GLB (bind pose, metres) with the default weapon on the hands."""
    from .melee_models import write_gltf
    from .twin_snakes import gltf_to_glb
    prims, W, _names = V.decode(c.vmg, second_colour)
    wv = c.weapon if weapon else None
    wprims = weapon_prims(c.vmg, W, wv) if wv is not None else []
    gp = []
    for p in prims + wprims:
        gp.append({"pos": p["pos"], "nrm": p["nrm"], "uv": p["uv"], "tris": p["tris"], "J": p["J"], "W": p["W"],
                   "tex": p["image"], "color": (255, 255, 255, 255), "wrap": (10497, 10497),
                   "name": ("weapon_" if p.get("weapon") else "") + f"l{p['mesh'][0]}m{p['mesh'][1]:02d}"})
    tmp = Path(out).with_suffix(".gltf")
    write_gltf(tmp, joints_of(c.vmg, W), gp, 1.0, name or c.key, joint_names(c.vmg),
               extras={"sc2_fighter": c.key, "sc2_costume": c.costume + 1, "sc2_entry": c.entry})
    gl = json.loads(tmp.read_text())
    tmp.unlink()
    gl["asset"]["generator"] = "gbox soulcalibur2"
    Path(out).write_bytes(gltf_to_glb(gl))
    return {"path": Path(out), "triangles": int(sum(len(p["tris"]) for p in prims)),
            "weapon_triangles": int(sum(len(p["tris"]) for p in wprims)),
            "textures": len({id(p["image"]) for p in prims if p["image"] is not None}),
            "roles": roles_of(c.vmg), "bones": len(c.vmg.bones), "stats": V.stats(c.vmg)}


def extract(image: Path, key: str, out: Path, name: str = "", costume: int = 0) -> dict:
    with Disc(image) as d:
        c = read_costume(d, key, costume)
    return export(c, out, name) | {"entry": c.entry, "costume": costume}


def _image(ctx, game) -> Path:
    from . import characters as C
    return C._gc_iso(ctx, game)


def extract_run(ctx, game, e, work):
    """characters.DEDICATED run for one roster entry (characters.extract_dedicated)."""
    key = e.get("key") or e["slug"].removeprefix("sc2_")
    image = _image(ctx, game)
    ctx.progress(30, f"Reading root.olk / human.olk for {e['name']}")
    r = extract(image, key, Path(work) / f"{e['slug']}.glb", e["name"])
    ctx.progress(70, f"{e['name']}: {r['triangles']} triangles (+{r['weapon_triangles']} weapon), "
                     f"{r['textures']} textures")
    extra = {"sc2_reader": READER_VERSION, "sc2_fighter": key, "sc2_entry": r["entry"], "sc2_costume": 1,
             "sc2_slot": f"fighter:{key}", "native_player": key == "mitsurugi",
             "attachments": [{"kind": "weapon", "bones": dict(WEAPON_BONES), "triangles": r["weapon_triangles"]}]}
    return {"files": [r["path"]], "tool": "gbox.soulcalibur2 (root.olk / human.olk VMG reader)",
            "source_files": [f"root.olk:human.olk:{r['entry']}"], "roles": r["roles"], "extra": extra,
            "notes": f"{r['triangles']} triangles, {r['textures']} textures, {r['bones']} bones (skin weights up to 4), "
                     f"costume 1 (human.olk entry {r['entry']}) with the default weapon on the hands. Writer slot: "
                     f"characters op=use slot=fighter:{key}."}


def main(argv=None) -> int:
    import argparse
    from . import characters as C
    ap = argparse.ArgumentParser(description="Soul Calibur II (GC) fighters -> rigged GLBs")
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("keys", nargs="*")
    ap.add_argument("--costume", type=int, default=1)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ok = True
    with Disc(Path(a.image)) as d:
        table = fighter_table(d.dol)
        for fid, key, name, _al in FIGHTERS:
            if a.keys and key not in a.keys:
                continue
            try:
                c = read_costume(d, key, min(a.costume, table[key]["costumes"]) - 1)
                r = export(c, out / f"{slug_of(key)}.glb", name)
                C.render_preview(r["path"], out / f"{slug_of(key)}.png")
                print(json.dumps({"key": key, "entry": c.entry, "triangles": r["triangles"],
                                  "weapon": r["weapon_triangles"], "bones": r["bones"], "roles": len(r["roles"])}),
                      flush=True)
            except Exception as err:                     # noqa: BLE001 - report every fighter
                ok = False
                print(json.dumps({"key": key, "error": f"{type(err).__name__}: {err}"}), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
