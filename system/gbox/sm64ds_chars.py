"""Super Mario 64 DS (USA) character models -> rigged, textured GLBs with body roles (characters.DEDICATED "sm64ds").

Super Mario 64 DS predates the NITRO-System G3D formats: it has no NSBMD/NSBTX files. Its 450 models are ".bmd"
files, Nintendo's in-house model format of that game (bones, GX display lists, materials, textures and palettes in
one file), most of them stored as b"LZ77" + an LZ10 stream; the player models sit in ARCHIVE/arc0.narc, everything
else in the cartridge file system (data/enemy, data/normal_obj ...). The geometry is drawn through the same GX
command lists an NSBMD MDL0 uses, and the textures use the same seven DS texel formats, so the shared decoders live
in gbox.formats.nitro (NitroFS, NARC, LZ77, texels, GX lists); this module reads the BMD container.

BMD (every offset absolute in the decompressed file; header 0x3C bytes):

    0x00 u32 scale shift (model units = vertex * (1 << shift))   0x04/0x08 bone count / offset (0x40 bytes each)
    0x0C/0x10 display-list count / offset (8 bytes: u32 count?, u32 -> 16-byte descriptor
              {u32 matrix count, u32 -> u8 transform ids, u32 GX size, u32 -> GX data})
    0x14/0x18 texture count / offset (0x14 bytes: name, data, size, u16 w, u16 h, u32 TEXIMAGE_PARAM)
    0x1C/0x20 palette count / offset (0x10 bytes: name, data, size, u32)
    0x24/0x28 material count / offset (0x30 bytes: name, texture id, palette id, s32 scale s/t (20.12), u16 rot,
              s32 trans s/t, TEXIMAGE_PARAM (repeat / flip bits), POLYGON_ATTR, DIF_AMB, SPE_EMI)
    0x2C      transform -> bone map (u16 per transform id)
    bone      u32 id, name, s16 parent offset (relative bone index, 0 = root), u16 has children, s32 sibling
              offset, s32 scale xyz (20.12), s16 rotation xyz (4096 = 360 degrees), s32 translation xyz (20.12),
              u32 (material, display list) pair count, -> u8 materials, -> u8 display lists, u32 flags

The scale shift applies to the vertex coordinates, not to the bone translations. A display list's MTX_RESTORE(slot) selects matrix-stack slot -> the list's transform id -> the bone; vertices are in
that bone's space, so every vertex is bound rigidly to one bone (the DS has no weighted skinning). A bone's local
matrix is T * Rz * Ry * Rx * S. Texture coordinates are in texels (12.4) times the material's texture scale; mirrored
repeat (flip bits) is baked into a mirrored texture. The 4x4-compressed format's palette-index data follows its
texel data (size / 2 bytes).

Some materials name a state variant rather than the texture the game normally draws: Luigi's head material points at
luigi_head_2, the screen-door texture of his vanish power-up (every other texel transparent). CHARACTERS[...]["textures"]
names the texture to draw per material; any other material whose texture is a stipple (nitro.screen_door) takes the
opaque sibling of the same name stem (name_1 for name_2) when the BMD has one, and the swap is recorded in its source.

Characters with a separate head model (the playable four) get it attached under the body's face_1 bone, as the game
draws it. Models face +Z with +Y up (left at +X), the convention of characters.tree_roles and the swap writers.

    python -m gbox.sm64ds_chars ROM.nds|ROM.7z OUT_DIR --char mario
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

import numpy as np

from .formats import nitro

GAME_IDS = {"917483267d246594": "Super Mario 64 DS (USA)"}
READER = "gbox.sm64ds_chars + gbox.formats.nitro"
READER_VERSION = 2          # 2: Luigi's head draws luigi_head_1, not the screen-door "vanish" texture; 4x4 blends in 5 bits
GAMECODE = "ASME"
ROM_SHA256 = "916056a27ffb07d1bae2ce0ca6f6464c1621c737dc96657a7b9eab4d3bccfc87"   # the owned dump (16 MiB)

# Body roles for the SM64 skeleton the playable cast, Peach and Bowser share (skl_root -> legs; spin -> arms, face_1)
SM64_ROLES = {"hip": "skl_root", "chest": "spin", "head": "face_1",
              "l_upper": "arm_l1", "l_fore": "arm_l2", "l_hand": "wrist_l1",
              "r_upper": "arm_r1", "r_fore": "arm_r2", "r_hand": "wrist_r1",
              "l_thigh": "leg_l1", "l_shin": "leg_l2", "l_foot": "ankle_l1",
              "r_thigh": "leg_r1", "r_shin": "leg_r2", "r_foot": "ankle_r1"}
HEADED = dict(SM64_ROLES, neck="face_1", head="head:root")   # the separate head model draws the face

# key -> (name, aliases, body BMD, head BMD | None, role map, extra) ; extra: chest (insert a chest bone under the
# hip parenting these bones), kind ("character" for everyone, partial rigs report what they lack)
CHARACTERS: dict[str, dict] = {
    "mario": {"name": "Mario (Super Mario 64 DS)", "aliases": ["Mario", "SM64DS Mario"],
              "body": "data/player/mario_model.bmd", "head": "data/player/mario_head_cap.bmd", "roles": HEADED,
              "lead": True},
    "luigi": {"name": "Luigi", "aliases": ["SM64DS Luigi", "Luigi (Super Mario 64 DS)"],
              "body": "data/player/luigi_model.bmd", "head": "data/player/luigi_head_cap.bmd", "roles": HEADED,
              # the head BMD's material names luigi_head_2, the stippled texture of Luigi's vanish power-up (two thirds
              # of its texels transparent); the game draws luigi_head_1 the rest of the time
              "textures": {"head:mat_head": "luigi_head_1"}},
    "wario": {"name": "Wario", "aliases": ["SM64DS Wario", "Wario (Super Mario 64 DS)"],
              "body": "data/player/wario_model.bmd", "head": "data/player/wario_head_cap.bmd", "roles": HEADED},
    "yoshi": {"name": "Yoshi", "aliases": ["SM64DS Yoshi", "Yoshi (Super Mario 64 DS)"],
              "body": "data/player/yoshi_model.bmd", "head": "data/player/yoshi_head.bmd", "roles": HEADED,
              "hide": ["head:tongue1", "head:tongue_tip"]},
    "metal_wario": {"name": "Metal Wario", "aliases": ["SM64DS Metal Wario"],
                    "body": "data/player/wario_metal_model.bmd", "head": None, "roles": SM64_ROLES},
    "peach": {"name": "Princess Peach", "aliases": ["Peach", "SM64DS Peach"],
              "body": "data/enemy/peach/peach_high.bmd", "head": None, "roles": SM64_ROLES},
    "bowser": {"name": "Bowser", "aliases": ["Koopa", "King Koopa", "SM64DS Bowser"],
               "body": "data/enemy/koopa/koopa_model.bmd", "head": None, "roles": SM64_ROLES},
    "koopa_troopa": {"name": "Koopa Troopa", "aliases": ["Nokonoko", "SM64DS Koopa Troopa"],
                     "body": "data/enemy/nokonoko/nokonoko.bmd", "head": None,
                     "roles": dict(SM64_ROLES, chest="chest"),
                     "chest": ["arm_l1", "arm_r1", "face_1"]},
    "toad": {"name": "Toad", "aliases": ["Kinopio", "SM64DS Toad"], "body": "data/enemy/kinopio/kinopio.bmd",
             "head": None, "roles": {"hip": "skl_root", "head": "head", "l_hand": "hand_l", "r_hand": "hand_r",
                                     "l_foot": "foot_l", "r_foot": "foot_r"},
             "absent": "Toad's hands and feet are free bones on the body (no arm or leg chains)"},
    "king_bobomb": {"name": "King Bob-omb", "aliases": ["Bomb King", "SM64DS King Bob-omb"],
                    "body": "data/enemy/bombking/bomb_king.bmd", "head": None,
                    "roles": {"hip": "body", "head": "eye", "l_shin": "sune_l", "l_foot": "asi_l",
                              "r_shin": "sune_r", "r_foot": "asi_r", "l_upper": "kata_l", "l_hand": "hand_l_1",
                              "r_upper": "kata_r", "r_hand": "hand_r_1"},
                    "absent": "a round body: no thighs, forearms or chest"},
    "ukiki": {"name": "Ukiki", "aliases": ["Monkey", "SM64DS Ukiki"], "body": "data/enemy/monkey/monkey.bmd",
              "head": None, "roles": {"hip": "skl_root", "head": "head_01", "l_upper": "arm_l_01",
                                      "l_fore": "arm_l_02", "r_upper": "arm_r_01", "r_fore": "arm_r_02",
                                      "l_thigh": "leg_l_01", "l_shin": "leg_l_02", "l_foot": "ankle_l_01",
                                      "r_thigh": "leg_r_01", "r_shin": "leg_r_02", "r_foot": "ankle_r_01"},
              "absent": "no hand bones (the forearm draws the hand), no chest"},
    "mips": {"name": "MIPS", "aliases": ["Mips the rabbit", "SM64DS MIPS"], "body": "data/enemy/mip/mip.bmd",
             "head": None, "roles": {"hip": "skl_root", "head": "head1", "l_hand": "arm_l1", "r_hand": "arm_r1",
                                     "l_thigh": "leg_l1", "l_shin": "leg_l2", "l_foot": "ankle_l1",
                                     "r_thigh": "leg_r1", "r_shin": "leg_r2", "r_foot": "ankle_r1"},
             "absent": "one-bone arms"},
    "penguin": {"name": "Penguin", "aliases": ["SM64DS Penguin"], "body": "data/enemy/penguin/penguin.bmd",
                "head": None, "roles": {"hip": "joint_waist", "chest": "joint_chest", "head": "joint_head",
                                        "l_hand": "joint_l_hand", "r_hand": "joint_r_hand",
                                        "l_foot": "joint_l_foot", "r_foot": "joint_r_foot"},
                "absent": "flippers and feet are single bones"},
    "lakitu": {"name": "Lakitu", "aliases": ["Jugem", "SM64DS Lakitu"], "body": "data/enemy/jugem/jugem.bmd",
               "head": None, "roles": {"hip": "body", "head": "head"}, "absent": "rides a cloud: no legs"},
    "shy_guy": {"name": "Fly Guy", "aliases": ["Propeller Shy Guy", "Heyho", "SM64DS Fly Guy"],
                "body": "data/enemy/propeller_heyho/propeller_heyho.bmd", "head": None,
                "roles": {"hip": "skl_root", "chest": "spin", "l_hand": "arm_l", "r_hand": "arm_r",
                          "l_foot": "leg_l", "r_foot": "leg_r"}, "absent": "one-bone limbs"},
    "goomba": {"name": "Goomba", "aliases": ["Kuribo", "SM64DS Goomba"], "body": "data/enemy/kuribo/kuribo_model.bmd",
               "head": None, "roles": {"hip": "skl_root", "l_foot": "leg_l", "r_foot": "leg_r"},
               "absent": "a head on two feet"},
    "goomboss": {"name": "Goomboss", "aliases": ["Kuriking", "SM64DS Goomboss"],
                 "body": "data/enemy/kuriking/kuriking_model.bmd", "head": None,
                 "roles": {"hip": "skl_root", "head": "head", "l_thigh": "leg_l", "l_foot": "toe_l",
                           "r_thigh": "leg_r", "r_foot": "toe_r"}, "absent": "a head on two feet"},
    "big_boo": {"name": "Big Boo", "aliases": ["Boss Teresa", "SM64DS Big Boo"],
                "body": "data/enemy/boss_teresa/boss_teresa.bmd", "head": None,
                "roles": {"hip": "skl_root", "l_hand": "arm_l1", "r_hand": "arm_r1"}, "absent": "a ghost"},
    "boo": {"name": "Boo", "aliases": ["Teresa", "SM64DS Boo"], "body": "data/enemy/teresa/teresa.bmd", "head": None,
            "roles": {"hip": "skl_root"}, "absent": "a ghost"},
    "chief_chilly": {"name": "Chief Chilly", "aliases": ["King Ice Donketu", "SM64DS Chief Chilly"],
                     "body": "data/enemy/king_ice_donketu/king_ice_donketu_model.bmd", "head": None,
                     "roles": {"hip": "skl_root", "l_foot": "foot_l", "r_foot": "foot_r"}, "absent": "a bully"},
    "big_bully": {"name": "Big Bully", "aliases": ["Boss Donketu", "SM64DS Big Bully"],
                  "body": "data/enemy/donketu/boss_donketu.bmd", "head": None,
                  "roles": {"hip": "body", "l_foot": "leg_l", "r_foot": "leg_r"}, "absent": "a bully"},
    "whomp_king": {"name": "Whomp King", "aliases": ["Battan King", "SM64DS Whomp King"],
                   "body": "data/enemy/battan_king/battan_king.bmd", "head": None,
                   "roles": {"hip": "skl_root", "l_hand": "arm_l", "r_hand": "arm_r", "l_foot": "leg_l",
                             "r_foot": "leg_r"}, "absent": "a slab with one-bone limbs"},
    "bobomb": {"name": "Bob-omb", "aliases": ["Bombhei", "SM64DS Bob-omb"], "body": "data/enemy/bombhei/bombhei.bmd",
               "head": None, "roles": {"hip": "skl_root", "l_foot": "foot_l1", "r_foot": "foot_r1"},
               "absent": "a bomb on two feet"},
    "hoot": {"name": "Hoot", "aliases": ["Owl", "SM64DS Hoot"], "body": "data/enemy/owl/owl.bmd", "head": None,
             "roles": {"hip": "skl_root", "l_upper": "wing_l_01", "l_fore": "wing_l_02", "r_upper": "wing_r_01",
                       "r_fore": "wing_r_02", "l_foot": "foot_l_01", "r_foot": "foot_r_01"}, "absent": "a bird"},
    "piranha_plant": {"name": "Piranha Plant", "aliases": ["Pakkun", "SM64DS Piranha Plant"],
                      "body": "data/enemy/pakkun/pakkun_model.bmd", "head": None,
                      "roles": {"hip": "skl_root", "neck": "neck_01", "head": "neck_03", "l_hand": "hand_L",
                                "r_hand": "hand_R"}, "absent": "a plant"},
    "dorrie": {"name": "Dorrie", "aliases": ["Dossy", "SM64DS Dorrie"], "body": "data/enemy/dossy/dossy.bmd",
               "head": None, "roles": {"hip": "skl_root", "neck": "neck", "head": "head"},
               "absent": "a plesiosaur"},
}


def roster() -> list[dict]:
    """characters.DEDICATED roster rows (slugs sm64ds_<key>: the N64 reader owns the plain 'mario' slug)."""
    return [{"key": k, "slug": f"sm64ds_{k}", "name": c["name"], "aliases": c["aliases"], "kind": "character"}
            for k, c in CHARACTERS.items()]


# ---------------------------------------------------------------- the ROM

class SM64DSRom:
    """The cartridge with every NARC member visible under its own path (members win over loose files)."""

    def __init__(self, data: bytes):
        self.rom = nitro.NitroROM(data)
        if self.rom.gamecode != GAMECODE:
            raise ValueError(f"not Super Mario 64 DS (USA): game code {self.rom.gamecode!r}")
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.members: dict[str, tuple[str, bytes]] = {}
        for path in self.rom.paths():
            if path.lower().endswith(".narc"):
                for name, blob in nitro.narc(self.rom.raw(path)):
                    self.members[name.lower()] = (path, blob)

    def where(self, path: str) -> str:
        key = path.lower()
        return f"{self.members[key][0]}:{path}" if key in self.members else path

    def read(self, path: str) -> bytes:
        key = path.lower()
        blob = self.members[key][1] if key in self.members else self.rom.raw(path)
        return nitro.decompress(blob)


_ROM_CACHE: dict = {}


def load_rom(path: str | Path) -> bytes:
    """An .nds file, or the catalog's .7z / .zip holding one (kept per process: a collect reads it 26 times)."""
    p = Path(path)
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime)
    if key not in _ROM_CACHE:
        _ROM_CACHE.clear()
        _ROM_CACHE[key] = _read_rom(p)
    return _ROM_CACHE[key]


def _read_rom(p: Path) -> bytes:
    import shutil
    import tempfile
    if p.suffix.lower() == ".nds":
        return p.read_bytes()
    if p.suffix.lower() == ".zip":
        import zipfile
        with zipfile.ZipFile(p) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".nds"))
            return z.read(name)
    if p.suffix.lower() != ".7z":
        raise ValueError(f"{p.name}: expected a .nds, .7z or .zip")
    with tempfile.TemporaryDirectory(prefix="sm64ds_") as tmp:
        try:
            import py7zr
            with py7zr.SevenZipFile(p) as z:
                names = [n for n in z.getnames() if n.lower().endswith(".nds")]
                z.extract(path=tmp, targets=names[:1])
        except ImportError:
            import subprocess
            exe = next((x for x in ("7z", "7zz", "7za") if shutil.which(x)), None)
            if exe is None:
                raise ValueError(f"{p.name}: reading a .7z ROM needs py7zr or the 7z CLI") from None
            subprocess.run([exe, "x", "-y", f"-o{tmp}", str(p)], check=True, capture_output=True)
        found = next(Path(tmp).rglob("*.nds"), None)
        if found is None:
            raise ValueError(f"{p.name}: no .nds inside")
        return found.read_bytes()


# ---------------------------------------------------------------- BMD

def _cstr(b: bytes, off: int) -> str:
    end = b.index(b"\0", off)
    return b[off:end].decode("latin-1")


def parse_bmd(b: bytes) -> dict:
    """Decompressed BMD -> {scale, bones, display_lists, textures, palettes, materials, transform_bone}."""
    if len(b) < 0x3C:
        raise ValueError("BMD shorter than its header")
    (shift, nb, bo, nd, do, nt, to, npl, po, nm, mo, tmap, _a, _b, _c) = struct.unpack_from("<15I", b, 0)
    if shift > 16 or nb > 256 or nd > 256 or nt > 256 or nm > 256:
        raise ValueError(f"BMD header out of range (shift {shift}, bones {nb}, lists {nd})")
    bones = []
    for i in range(nb):
        o = bo + i * 0x40
        bid, name, par, kids, sib = struct.unpack_from("<IIhHi", b, o)
        scale = [v / 4096.0 for v in struct.unpack_from("<3i", b, o + 0x10)]
        rot = [v * 2 * math.pi / 4096.0 for v in struct.unpack_from("<3h", b, o + 0x1C)]
        trans = [v / 4096.0 for v in struct.unpack_from("<3i", b, o + 0x24)]
        npair, mo_, do_, flags = struct.unpack_from("<4I", b, o + 0x30)
        parent = i + par if par else -1
        if not -1 <= parent < i:
            raise ValueError(f"BMD bone {i} has parent {parent}")
        bones.append({"id": bid, "name": _cstr(b, name), "parent": parent, "scale": scale, "rotation": rot,
                      "translation": trans, "pairs": list(zip(b[mo_:mo_ + npair], b[do_:do_ + npair])),
                      "flags": flags})
    lists = []
    for i in range(nd):
        _n, desc = struct.unpack_from("<II", b, do + 8 * i)
        nmtx, mtx_off, size, data = struct.unpack_from("<4I", b, desc)
        if data + size > len(b):
            raise ValueError(f"BMD display list {i} runs past the file")
        lists.append({"transforms": list(b[mtx_off:mtx_off + nmtx]), "gx": b[data:data + size]})
    textures = []
    for i in range(nt):
        name, data, size, w, h, param = struct.unpack_from("<IIIHHI", b, to + 0x14 * i)
        textures.append({"name": _cstr(b, name), "data": data, "size": size, "width": w, "height": h,
                         "param": param})
    palettes = []
    for i in range(npl):
        name, data, size, _x = struct.unpack_from("<IIII", b, po + 0x10 * i)
        palettes.append({"name": _cstr(b, name), "data": data, "size": size})
    materials = []
    for i in range(nm):
        (name, tex, pal, ss, st, rot, _p, ts, tt, param, pattr, difamb, speemi) = \
            struct.unpack_from("<IIIiiHHiiIIII", b, mo + 0x30 * i)
        materials.append({"name": _cstr(b, name), "texture": None if tex == 0xFFFFFFFF else tex,
                          "palette": None if pal == 0xFFFFFFFF else pal, "scale": (ss / 4096.0, st / 4096.0),
                          "rotation": rot, "translate": (ts / 4096.0, tt / 4096.0), "param": param,
                          "polygon_attr": pattr, "dif_amb": difamb, "spe_emi": speemi})
    ntrans = max((t for dl in lists for t in dl["transforms"]), default=-1) + 1
    transform_bone = list(struct.unpack_from(f"<{ntrans}H", b, tmap)) if ntrans else []
    if any(t >= nb for t in transform_bone):
        raise ValueError("BMD transform map names a missing bone")
    return {"scale": 1 << shift, "bones": bones, "display_lists": lists, "textures": textures,
            "palettes": palettes, "materials": materials, "transform_bone": transform_bone, "raw": b}


def euler_matrix(rx: float, ry: float, rz: float) -> np.ndarray:
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    X = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Z @ Y @ X


def bone_local(bone: dict) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = euler_matrix(*bone["rotation"]) @ np.diag(bone["scale"])
    m[:3, 3] = bone["translation"]
    return m


def bone_world(bones: list[dict], root: np.ndarray | None = None) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for bone in bones:
        parent = out[bone["parent"]] if bone["parent"] >= 0 else (root if root is not None else np.eye(4))
        out.append(parent @ bone_local(bone))
    return out


def texture_rgba(bmd: dict, tex_id: int, pal_id: int | None) -> np.ndarray:
    """One BMD texture (with its palette) -> (h, w, 4) RGBA."""
    b = bmd["raw"]
    t = bmd["textures"][tex_id]
    info = nitro.teximage(t["param"])
    fmt, w, h = info["format"], t["width"] or info["width"], t["height"] or info["height"]
    texels = b[t["data"]:t["data"] + t["size"]]
    pal = b""
    if pal_id is not None and pal_id < len(bmd["palettes"]):
        p = bmd["palettes"][pal_id]
        pal = b[p["data"]:p["data"] + p["size"]]
    pidx = b""
    if fmt == 5:
        pidx = b[t["data"] + t["size"]:t["data"] + t["size"] + t["size"] // 2]
    return nitro.decode_texture(fmt, w, h, texels, pal, color0_transparent=info["color0_transparent"],
                                palette_index=pidx)


SCREEN_DOOR = 0.2      # nitro.screen_door above this = a stipple (Luigi's vanish head 0.55; real cut-outs stay < 0.05)


def _palette_for(bmd: dict, tex: int, fallback: int | None) -> int | None:
    """A texture's own palette: the one named '<texture>_pl', else the same index, else the material's."""
    name = bmd["textures"][tex]["name"]
    for i, p in enumerate(bmd["palettes"]):
        if p["name"] == name + "_pl":
            return i
    return tex if tex < len(bmd["palettes"]) else fallback


def _stem(name: str) -> str:
    return name.rstrip("0123456789").rstrip("_")


def pick_texture(bmd: dict, mat: dict, wanted: str | None = None) -> tuple[int, int | None, dict]:
    """(texture id, palette id, source note) the material should draw. `wanted` names the texture outright; otherwise
    a stippled (screen-door) texture gives way to an opaque sibling with the same name stem."""
    tex, pal = mat["texture"], mat["palette"]
    names = [t["name"] for t in bmd["textures"]]
    if wanted is not None:
        if wanted not in names:
            raise ValueError(f"{mat['name']}: no texture {wanted!r} in the BMD ({names})")
        new = names.index(wanted)
        if new == tex:
            return tex, pal, {}
        return new, _palette_for(bmd, new, pal), {"texture_substituted": {"bmd_names": names[tex], "drawn": wanted,
                                                                          "reason": "state variant (CHARACTERS)"}}
    score = nitro.screen_door(texture_rgba(bmd, tex, pal))
    if score <= SCREEN_DOOR:
        return tex, pal, {}
    for i, nm in enumerate(names):
        if i != tex and _stem(nm) == _stem(names[tex]):
            p = _palette_for(bmd, i, pal)
            if nitro.screen_door(texture_rgba(bmd, i, p)) <= SCREEN_DOOR:
                return i, p, {"texture_substituted": {"bmd_names": names[tex], "drawn": nm,
                                                      "reason": f"screen-door texture ({score:.2f})"}}
    return tex, pal, {"screen_door": round(score, 3)}


def _png(rgba: np.ndarray) -> bytes:
    from .ninja import png
    h, w = rgba.shape[:2]
    return png(w, h, np.ascontiguousarray(rgba, dtype=np.uint8).tobytes())


# ---------------------------------------------------------------- model assembly

class Model:
    """Bones (world matrices) + rigid, textured primitives assembled from one or more BMDs."""

    def __init__(self, textures: dict[str, str] | None = None):
        self.texture_names = dict(textures or {})   # material key -> texture name to draw (state variants)
        self.names: list[str] = []
        self.parent: list[int] = []
        self.world: list[np.ndarray] = []
        self.prims: list[dict] = []          # {pos (n,3), uv (n,2), bone (n,), tris (m,3), material key}
        self.materials: dict[str, dict] = {}  # key -> {png bytes | None, color, source}

    def add_bmd(self, bmd: dict, prefix: str = "", attach: int = -1, attach_world: np.ndarray | None = None) -> list[int]:
        base = len(self.names)
        root = attach_world if attach_world is not None else np.eye(4)
        world = bone_world(bmd["bones"], root)
        for i, bone in enumerate(bmd["bones"]):
            self.names.append(prefix + bone["name"])
            self.parent.append(base + bone["parent"] if bone["parent"] >= 0 else attach)
            self.world.append(world[i])
        scale = bmd["scale"]
        for bi, bone in enumerate(bmd["bones"]):
            for mat_id, dl_id in bone["pairs"]:
                if dl_id >= len(bmd["display_lists"]):
                    raise ValueError(f"{bone['name']}: display list {dl_id} missing")
                dl = bmd["display_lists"][dl_id]
                g = nitro.decode_display_list(dl["gx"])
                if not g["tris"]:
                    continue
                key, w, h, sc = self._material(bmd, mat_id, prefix)
                slots = np.array(g["slot"], dtype=np.int64)
                if slots.size and slots.max() >= max(1, len(dl["transforms"])):
                    raise ValueError(f"display list {dl_id} restores matrix slot {int(slots.max())} beyond its "
                                     f"{len(dl['transforms'])} transforms")
                if dl["transforms"]:
                    bones = np.array([bmd["transform_bone"][dl["transforms"][s]] for s in slots], dtype=np.int64)
                else:
                    bones = np.full(len(slots), bi, dtype=np.int64)
                local = np.array(g["pos"], dtype=np.float64) * scale     # the shift scales the vertices only
                pos = np.empty_like(local)
                for k in np.unique(bones):
                    sel = bones == k
                    W = world[k]
                    pos[sel] = local[sel] @ W[:3, :3].T + W[:3, 3]
                uv = np.array(g["uv"], dtype=np.float64) * np.array(sc)
                uv = uv / np.array([w, h], dtype=np.float64) if w and h else uv * 0
                self.prims.append({"pos": pos, "uv": uv, "bone": bones + base,
                                   "tris": np.array(g["tris"], dtype=np.int64), "material": key,
                                   "color": np.array(g["color"], dtype=np.float64).mean(axis=0) / 255.0})
        return list(range(base, len(self.names)))

    def _material(self, bmd: dict, mat_id: int, prefix: str):
        mat = bmd["materials"][mat_id]
        key = prefix + mat["name"]
        tex = mat["texture"]
        if tex is None or tex >= len(bmd["textures"]):
            self.materials.setdefault(key, {"png": None, "source": {"material": mat["name"],
                                                                    "polygon_attr": f"{mat['polygon_attr']:#010x}"}})
            return key, 0, 0, (1.0, 1.0)
        tex, pal, note = pick_texture(bmd, mat, self.texture_names.get(key))
        t = bmd["textures"][tex]
        rgba = texture_rgba(bmd, tex, pal)
        h, w = rgba.shape[:2]
        sc = list(mat["scale"])
        p = nitro.teximage(mat["param"])
        if p["flip_s"] and p["repeat_s"]:               # mirrored repeat -> bake the mirror, halve the u range
            rgba = np.concatenate([rgba, rgba[:, ::-1]], axis=1)
            sc[0] *= 0.5
        if p["flip_t"] and p["repeat_t"]:
            rgba = np.concatenate([rgba, rgba[::-1]], axis=0)
            sc[1] *= 0.5
        if key not in self.materials:
            self.materials[key] = {"png": _png(rgba), "texture": t["name"],
                                   "source": {"material": mat["name"], "texture": t["name"],
                                              "format": nitro.FORMATS[nitro.teximage(t["param"])["format"]],
                                              "teximage_param": f"{mat['param']:#010x}",
                                              "polygon_attr": f"{mat['polygon_attr']:#010x}"} | note}
        return key, w, h, tuple(sc)

    def insert_bone(self, name: str, parent: int, at: np.ndarray, children: list[int]) -> int:
        """Add a bone (world matrix `at`) under `parent` and move `children` under it (their world is unchanged)."""
        self.names.append(name)
        self.parent.append(parent)
        self.world.append(at)
        k = len(self.names) - 1
        for c in children:
            self.parent[c] = k
        return k

    def face_z(self, left: int, right: int) -> None:
        """Turn the whole model about +Y so `left` sits at +X and the model faces +Z."""
        lx, rx = self.world[left][:3, 3], self.world[right][:3, 3]
        d = lx - rx
        ang = math.atan2(d[2], d[0])                   # rotate d onto +X
        if abs(ang) < 1e-6:
            return
        R = np.eye(4)
        c, s = math.cos(ang), math.sin(ang)
        R[:3, :3] = [[c, 0, s], [0, 1, 0], [-s, 0, c]]
        self.world = [R @ W for W in self.world]
        for p in self.prims:
            p["pos"] = p["pos"] @ R[:3, :3].T

    def order(self) -> list[int]:
        """Bones in parent-before-child order (inserted bones may come after their children)."""
        seen, out = set(), []

        def visit(i):
            if i in seen:
                return
            if self.parent[i] >= 0:
                visit(self.parent[i])
            seen.add(i)
            out.append(i)
        for i in range(len(self.names)):
            visit(i)
        return out


def _quat(m: np.ndarray) -> list[float]:
    """Rotation part of a matrix (scale removed) -> [x, y, z, w]."""
    r = m[:3, :3] / np.linalg.norm(m[:3, :3], axis=0)
    t = np.trace(r)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, 0.25 * s]
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
        q = [0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s, (r[2, 1] - r[1, 2]) / s]
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
        q = [(r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s, (r[0, 2] - r[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
        q = [(r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s, (r[1, 0] - r[0, 1]) / s]
    n = math.sqrt(sum(v * v for v in q))
    return [float(v / n) for v in q]


POLY_BACK = 0x40          # POLYGON_ATTR bit 6: the DS draws the back surface (bit 7 is the front one)


def double_sided(source: dict) -> bool:
    """A material's DS POLYGON_ATTR (as preserved in its glTF source extras) asks for back faces too: Peach's body,
    skirt and arms are open shells the DS draws from both sides; a writer that culls them loses her back half."""
    try:
        return bool(int(str(source.get("polygon_attr", "0")), 0) & POLY_BACK)
    except ValueError:
        return False


def to_manifest(model: Model, name: str, source: dict, out: Path):
    """Model -> uap.Manifest (one skin, one joint per vertex at weight 1) with textures written under out/textures."""
    from . import uap
    order = model.order()
    index = {old: new for new, old in enumerate(order)}
    skeleton = []
    for old in order:
        W, p = model.world[old], model.parent[old]
        local = W if p < 0 else np.linalg.inv(model.world[p]) @ W
        sc = np.linalg.norm(local[:3, :3], axis=0)
        skeleton.append(uap.Bone(name=model.names[old], parent=None if p < 0 else index[p],
                                 translation=[float(v) for v in local[:3, 3]], rotation=_quat(local),
                                 scale=[float(v) for v in sc]))
    (out / "textures").mkdir(parents=True, exist_ok=True)
    mats, mat_index = [], {}
    for key, m in model.materials.items():
        mat_index[key] = len(mats)
        tex = None
        if m.get("png"):
            fn = f"textures/{key}.png"
            (out / fn).write_bytes(m["png"])
            tex = fn
        mats.append(uap.Material(name=key, texture=tex, source=m["source"], double_sided=double_sided(m["source"])))
    meshes, nodes = [], []
    for i, p in enumerate(model.prims):
        n = len(p["pos"])
        if not len(p["tris"]):
            continue
        mi = mat_index[p["material"]]
        if mats[mi].texture is None:
            mats[mi].base_color = [float(v) for v in p["color"]] + [1.0]
        meshes.append(uap.Mesh(name=f"{p['material']}_{i}", positions=p["pos"].round(5).tolist(),
                               uvs=p["uv"].round(6).tolist(), indices=p["tris"].reshape(-1).tolist(), material=mi,
                               joints=[[index[int(b)], 0, 0, 0] for b in p["bone"]],
                               weights=[[1.0, 0.0, 0.0, 0.0]] * n))
        nodes.append(uap.Node(name=meshes[-1].name, mesh=len(meshes) - 1, skinned=True))
    m = uap.Manifest(name=name, source=source, meshes=meshes, materials=mats, skeleton=skeleton, nodes=nodes,
                     roots=list(range(len(nodes))),
                     provenance=[{"step": "extract", "tool": READER, "reader_version": READER_VERSION,
                                  "files": list(source.get("files") or [])}])
    m.confidence.update(geometry="verified", textures="verified", skeleton="verified", skin_weights="verified",
                        source_identity="verified", animations="missing")
    return m


def build(rom: SM64DSRom, key: str) -> tuple[Model, dict, list[str]]:
    """Assemble one character -> (model, roles {role: bone name}, source files)."""
    spec = CHARACTERS[key]
    model = Model(spec.get("textures"))
    body = parse_bmd(rom.read(spec["body"]))
    files = [rom.where(spec["body"])]
    model.add_bmd(body)
    if spec.get("head"):
        head = parse_bmd(rom.read(spec["head"]))
        face = model.names.index("face_1")
        at = model.world[face]
        if head["bones"][0]["name"] == "face_1":           # Yoshi's head root is the face bone itself
            at = at @ np.linalg.inv(bone_local(head["bones"][0]))
        model.add_bmd(head, prefix="head:", attach=face, attach_world=at)
        model.names[model.names.index("head:" + head["bones"][0]["name"])] = "head:root"
        files.append(rom.where(spec["head"]))
    hide = [model.names.index(n) for n in spec.get("hide", ()) if n in model.names]
    if hide:                                               # parts the game keeps hidden (Yoshi's tongue)
        for p in model.prims:
            keep = ~np.isin(p["bone"], hide)[p["tris"]].any(axis=1)
            p["tris"] = p["tris"][keep]
    if spec.get("chest"):
        kids = [model.names.index(n) for n in spec["chest"]]
        hip = model.names.index(spec["roles"]["hip"])
        at = np.eye(4)
        at[:3, 3] = np.mean([model.world[k][:3, 3] for k in kids[:2]], axis=0)
        model.insert_bone("chest", hip, at, kids)
    roles = {r: n for r, n in spec["roles"].items() if n in model.names}
    left = next((roles[r] for r in ("l_thigh", "l_foot", "l_upper", "l_hand") if r in roles), None)
    right = next((roles[r] for r in ("r_thigh", "r_foot", "r_upper", "r_hand") if r in roles), None)
    if left and right:
        model.face_z(model.names.index(left), model.names.index(right))
    return model, roles, files


def export(rom_path: str | Path, out_dir: str | Path, key: str = "mario", rom: SM64DSRom | None = None) -> Path:
    from . import uap
    rom = rom or SM64DSRom(load_rom(rom_path))
    model, roles, files = build(rom, key)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = f"sm64ds_{key}"
    spec = CHARACTERS[key]
    source = {"game": "Super Mario 64 DS (USA)", "rom_sha256": rom.sha256, "gamecode": GAMECODE, "files": files,
              "extraction_method": "gbox.sm64ds_chars", "body_roles": roles,
              "roles_absent_reason": spec.get("absent", ""), "bones": len(model.names),
              "reader_version": READER_VERSION}
    m = to_manifest(model, name, source, out)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED run(): the GLB + manifest + textures, the source files and the body roles."""
    from . import characters as C
    rom = SM64DSRom(load_rom(C._rom(ctx, game)))
    glb = export(None, work, e["key"], rom=rom)
    man = json.loads((Path(work) / "manifest.json").read_text())
    spec = CHARACTERS[e["key"]]
    roles = man["source"]["body_roles"]
    out = {"files": [glb, Path(work) / "textures", Path(work) / "manifest.json"], "tool": READER,
           "source_files": man["source"]["files"], "roles": roles,
           "notes": (f"Super Mario 64 DS BMD ({len(man['skeleton'])} bones, rigid one-bone skinning, "
                     f"{len(man['materials'])} materials)" + (f"; partial rig: {spec['absent']}"
                                                              if spec.get("absent") else "")),
           "extra": {"sm64ds_reader": READER_VERSION}}
    if spec.get("lead"):
        out["extra"]["native_player"] = True
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("out")
    ap.add_argument("--char", default="mario", choices=sorted(CHARACTERS) + ["all"])
    a = ap.parse_args(argv)
    rom = SM64DSRom(load_rom(a.rom))
    for key in (sorted(CHARACTERS) if a.char == "all" else [a.char]):
        print(export(None, Path(a.out) / key, key, rom=rom))


if __name__ == "__main__":
    main()
