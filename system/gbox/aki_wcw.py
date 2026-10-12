"""AKI's WCW games on N64 (WCW vs. nWo: World Tour; WCW/nWo Revenge shares the engine): the roster, and a writer that
puts any rigged collection character in a wrestler's place as a modded ROM (characters op=use routes here from
gbox.aki_wrestling for these games; No Mercy has its own writer there).

World Tour (NWNE rev 1), from Ghidra on an RDRAM image (gBox DecompileAll, MIPS:BE:32, base 0x80000000) + the ROM:
  * File table: same AkiFileTable as No Mercy (gbox.aki_wrestling.FileTable): FirstFile 0x39500, table 0x7C1C70,
    0x157B entries. 0x80004c10 loads it (malloc(0x55EC), DMA, a sizes buffer malloc(0x55E8), loop to 0x55E8);
    0x80004d24 resolves an id (slti 0x157B, else hangs).
  * A wrestler in slot s: code s16 0x80057520[s] = group << 8 | member (1-based); costume s16 0x80057540[s].
  * Costume record (0x50 bytes): u16 hdr (bits 0-6 body definition, bit 7 a flag, bits 8-11 head definition, bits
    12-14 a size class), then 19 x {u16 palette id, u16 texture id} (one per body model), u16 0.
    0x80032BB0[group] -> member list -> member's costume record pointers (4, 0-terminated).
  * Body definition: 0x8002E570[body] -> 19 u16 model ids (+ pad); 0x8002DEA1 = part -> model index (parts 4/5 are the
    head). 44 bodies. Read at 0x8000bca4 only (lui 0x8000bc84).
  * Head definition: 0x8002F1C0[group][member][head] -> {u16 face model, back model, hair model, face palette, face
    texture, back palette, back texture, hair palette, hair texture, ...} (24 bytes).
  * Models are AkiModels (vertex = xyz + 16 * off in the wrestler's rest space, arms down, facing +Z, his left = +X).
    Body textures are CI4 (16-colour palettes, 32 bytes); head textures CI8 (256 colours).
  * Profiles (name, group, member) live as strings in the boot segment ("Hulk <Hogan>" ... u16 index, u8 group,
    u8 member).
The writer (no file is overwritten): new models/palettes/textures appended after the last id; the table moved to
Expansion Pak RAM (0x80700000) with, behind it, a 128-entry copy of the body-definition table (the original 44 + one
new body per replaced wrestler), the new body/head definitions and costume records; the code reading the body table
is pointed at the copy; the wrestler's costume pointers and head pointer 0 are repointed at the new records.
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import aki_wrestling as A

WORLD_TOUR = {"59bf059d2eadd372": "WCW vs. nWo: World Tour (USA)"}
REVENGE = {"bca7ec4ecf71d164": "WCW-nWo Revenge (USA)", "061264c636cc284d": "WCW-nWo Revenge (Europe)"}
GAME_IDS = {**WORLD_TOUR, "bca7ec4ecf71d164": REVENGE["bca7ec4ecf71d164"]}   # games with a writer (Revenge: USA)

RAM_EXP = 0x80700000

PROFILES = {
    ("NWNE", 1): {
        "game": "worldtour", "layout": "wt", "first": 0x39500, "ft": 0x7C1C70, "nfiles": 0x157A, "nmodels": 19,
        "costume_tbl": 0x80032BB0, "groups": 8, "head_tbl": 0x8002F1C0, "body_tbl": 0x8002E570, "bodies": 44,
        "part_map": 0x8002DEA1, "slot_code": 0x80057520, "slot_costume": 0x80057540,
        # (RAM, original instruction, kind)
        "patch": [(0x80004C34, 0x0C0001FD, "malloc"), (0x80004C44, 0x3C04007C, "ft_hi"), (0x80004C4C, 0x24841C70, "ft_lo"),
                  (0x80004C58, 0x240655EC, "total"), (0x80004C60, 0x240455E8, "sizes"), (0x80004C90, 0x241655E8, "loop_bytes"),
                  (0x80004D38, 0x29C1157B, "bound"), (0x8000BC84, 0x3C0B8003, "body_hi"), (0x8000BCA4, 0x8D6BE570, "body_lo")],
        "profile_area": (0x80035000, 0x80038000),
    },
    # WCW/nWo Revenge (NW2E): 0x8000bdd0 loads a slot's parts: code s16 0x8006A2A4[slot] (group << 8 | member);
    # 0x80031998[group] -> u16 per member (bits 0-6 = costume set); 0x800360F0[set] -> costume pointers -> variant
    # pointers (3) -> record {u16 hdr (body), 17 x (palette, texture)}; textures come from variant head.+0x16;
    # 0x800317F0[body] -> 17 model ids; 0x80032B44[group][member][head] -> head definition (as World Tour's, +0x16 =
    # texture variant). Sets are shared by several wrestlers, so a replaced one gets its own set.
    ("NW2E", 0): {
        "game": "revenge", "layout": "rv", "first": 0xDAC50, "ft": 0xCE2752, "nfiles": 0x1DE9, "nmodels": 17,
        "set_tbl": 0x80031998, "groups": 10, "costume_lists": 0x800360F0, "sets": 5, "head_tbl": 0x80032B44,
        "body_tbl": 0x800317F0, "bodies": 52, "part_map": 0x80031088, "slot_code": 0x8006A2A4, "slot_costume": 0x8007DFBC,
        "patch": [(0x800034C0, 0x0C000215, "malloc"), (0x800034C8, 0x3C0400CE, "ft_hi"), (0x800034CC, 0x24842752, "ft_lo"),
                  (0x800034E0, 0x240677A8, "total"), (0x800034E8, 0x240477A4, "sizes"), (0x8000357C, 0x2E421DE9, "loop_count"),
                  (0x800035C0, 0x2C421DEA, "bound"), (0x800036A4, 0x2C421DEA, "bound"),
                  (0x8000BEE0, 0x3C018003, "body_hi"), (0x8000BEE8, 0x8C2217F0, "body_lo"),
                  (0x8000BE94, 0x3C038003, "sets_hi"), (0x8000BE9C, 0x8C6360F0, "sets_lo"),
                  (0x8000C264, 0x3C018003, "sets_hi"), (0x8000C26C, 0x8C2260F0, "sets_lo")],
        "profile_area": (0x80037000, 0x80048000),
    },
    # WCW/nWo Revenge (Europe, NW2P rev 0; .zip member is byte-swapped .v64 data under a .z64 name). Same 0x1DEA-word
    # file table as NW2E (assets 0x2A70 bytes earlier in ROM); every NW2E patch site was matched uniquely in the PAL
    # code with immediates masked (code -0xE0, data tables -0x28B0, slot arrays -0x2CD0/-0x2CE0). Derived by
    # gbox.aki_wcw_inventory.derive_profile(us_rom, eu_rom) and re-checked by tests/test_aki_wcw_revenge_pal.py (#1317).
    ("NW2P", 0): {
        "game": "revenge", "layout": "rv", "first": 0xD81E0, "ft": 0xCDFCE2, "nfiles": 0x1DE9, "nmodels": 17,
        "set_tbl": 0x8002F0E8, "groups": 10, "costume_lists": 0x80033840, "sets": 5, "head_tbl": 0x80030294,
        "body_tbl": 0x8002EF40, "bodies": 52, "part_map": 0x8002E7D8, "slot_code": 0x800675D4, "slot_costume": 0x8007B2DC,
        "patch": [(0x800033E0, 0x0C00020C, "malloc"), (0x800033E8, 0x3C0400CE, "ft_hi"), (0x800033EC, 0x2484FCE2, "ft_lo"),
                  (0x80003400, 0x240677A8, "total"), (0x80003408, 0x240477A4, "sizes"), (0x8000349C, 0x2E421DE9, "loop_count"),
                  (0x800034E0, 0x2C421DEA, "bound"), (0x800035C4, 0x2C421DEA, "bound"),
                  (0x8000BE00, 0x3C018003, "body_hi"), (0x8000BE08, 0x8C22EF40, "body_lo"),
                  (0x8000BDB4, 0x3C038003, "sets_hi"), (0x8000BDBC, 0x8C633840, "sets_lo"),
                  (0x8000C184, 0x3C018003, "sets_hi"), (0x8000C18C, 0x8C223840, "sets_lo")],
        "profile_area": (0x80035000, 0x80046000),
    },
}

# body model index -> (name, joint); 19 body models + the head's face / back (keys 19, 20)
WPARTS = {0: ("pelvis", "hip"), 1: ("waist", "waist"), 2: ("chest", "chest"),
          3: ("l_lower_leg", "l_shin"), 4: ("l_upper_leg", "l_thigh"), 5: ("l_foot", "l_foot"),
          6: ("l_hand", "l_hand"), 7: ("l_fingers", "l_fingers"), 8: ("l_lower_arm", "l_fore"), 9: ("l_upper_arm", "l_upper"),
          10: ("r_lower_leg", "r_shin"), 11: ("r_upper_leg", "r_thigh"), 12: ("r_foot", "r_foot"),
          13: ("r_lower_arm", "r_fore"), 14: ("r_hand", "r_hand"), 15: ("r_fingers", "r_fingers"), 16: ("r_upper_arm", "r_upper"),
          17: ("l_sole", "l_foot"), 18: ("r_sole", "r_foot"), 19: ("face", "head"), 20: ("head_back", "head")}
JOINTS = ["hip", "waist", "chest", "head", "l_upper", "l_fore", "l_hand", "l_fingers", "r_upper", "r_fore", "r_hand",
          "r_fingers", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]
JPARENT = {"hip": None, "waist": "hip", "chest": "waist", "head": "chest", "l_upper": "chest", "l_fore": "l_upper",
           "l_hand": "l_fore", "l_fingers": "l_hand", "r_upper": "chest", "r_fore": "r_upper", "r_hand": "r_fore",
           "r_fingers": "r_hand", "l_thigh": "hip", "l_shin": "l_thigh", "l_foot": "l_shin", "r_thigh": "hip",
           "r_shin": "r_thigh", "r_foot": "r_shin"}
LIMB_PART = {"l_upper": 9, "l_fore": 8, "l_hand": 6, "l_fingers": 7, "l_thigh": 4, "l_shin": 3, "l_foot": 5,
             "r_upper": 16, "r_fore": 13, "r_hand": 14, "r_fingers": 15, "r_thigh": 11, "r_shin": 10, "r_foot": 12}


def profile(rom: bytes) -> dict:
    key = (rom[0x3B:0x3F].decode(errors="replace"), rom[0x3F])
    p = PROFILES.get(key)
    if not p:
        raise ValueError(f"no WCW writer profile for {key[0]} rev {key[1]} (have: " +
                         ", ".join(f"{c} rev {r}" for c, r in PROFILES) + ")")
    return p


class Rom:
    def __init__(self, rom: bytes):
        self.rom, self.p = rom, profile(rom)
        self.ft = A.FileTable(rom, {"game": self.p["game"], "first": self.p["first"], "ft": self.p["ft"],
                                     "nfiles": self.p["nfiles"]})

    @staticmethod
    def r2r(a: int) -> int:
        return a - 0x80000400 + 0x1000

    def rd(self, a: int, f: str, n: int = 1):
        return struct.unpack_from(f">{n}{f}", self.rom, self.r2r(a))

    def ptr_list(self, a: int, cap: int = 64) -> list[tuple[int, int]]:
        """[(address of the pointer word, pointer)] until a 0 word."""
        out = []
        while len(out) < cap:
            q = self.rd(a + 4 * len(out), "I")[0]
            if q == 0:
                break
            out.append((a + 4 * len(out), q))
        return out


def _clean(n: str) -> str:
    n = re.sub(r"\{[^}.]+\}", "", n.replace("{.}", " "))  # {DDP}: a short form, dropped; {.}: a space
    return re.sub(r"\s+", " ", re.sub(r"[<>{}]", "", n)).strip()


def roster(rom: bytes) -> list[dict]:
    """[{group, member (1-based), code, name, costumes [(ptr address, record)], heads [(ptr address, head def)]}]."""
    R = Rom(rom)
    p = R.p
    names = {}
    a0, a1 = (R.r2r(x) for x in p["profile_area"])
    seg = rom[a0:a1]
    for m in re.finditer(rb"([ -~]{2,40}?)\x00+\1\n#", seg):
        k = m.end()
        while k < len(seg) - 16:
            if seg[k] == 0x80 and seg[k + 4] == 0x80 and seg[k + 8] == 0x80 and seg[k + 1] in (2, 3):
                g, mem = seg[k - 6], seg[k - 5]
                names.setdefault((g, mem), _clean(m.group(1).decode("latin-1")))
                break
            k += 1
    if p["layout"] == "rv":                                # "<Sting>", height, weight, then u8 group, member, index, 00 1d
        for m in re.finditer(rb"([ -~]{2,40}?)\x00+(\d'\d+\")\x00+(\d+lbs\.)\x00+?([\x00-\x0f])([\x01-\x3f])([\x00-\x7f])\x00\x1d",
                             seg, re.S):
            names.setdefault((m.group(4)[0], m.group(5)[0]), _clean(m.group(1).decode("latin-1")))
    out = []
    heads = R.rd(p["head_tbl"], "I", p["groups"])
    if p["layout"] == "rv":
        sets = R.rd(p["set_tbl"], "I", p["groups"])
        bounds = list(sets) + [p["set_tbl"]]
        for g in range(p["groups"]):
            n = (bounds[g + 1] - sets[g]) // 2
            for mi in range(max(0, min(n, 40))):
                sa = sets[g] + 2 * mi
                sv = R.rd(sa, "H")[0]
                st = sv & 0x7F
                if st >= p["sets"]:
                    continue
                cl = R.rd(p["costume_lists"] + 4 * st, "I")[0]
                cs = R.ptr_list(cl, 8)
                hl = R.rd(heads[g] + 4 * mi, "I")[0]
                hs = R.ptr_list(hl, 8) if 0x80000000 <= hl < 0x80400000 else []
                if not cs or not hs:
                    continue
                out.append({"group": g, "member": mi + 1, "code": g << 8 | (mi + 1), "set_addr": sa, "set": sv,
                            "name": names.get((g, mi + 1)) or f"Wrestler {g}-{mi + 1}", "costumes": cs, "heads": hs})
        return out
    groups = R.rd(p["costume_tbl"], "I", p["groups"])
    bounds = list(groups) + [p["costume_tbl"]]             # member lists are back to back (no terminator)
    for g in range(p["groups"]):
        n = (bounds[g + 1] - groups[g]) // 4
        for mi in range(max(0, min(n, 40))):
            mp = R.rd(groups[g] + 4 * mi, "I")[0]
            if not 0x80000000 <= mp < 0x80400000:
                continue
            cs = R.ptr_list(mp, 8)
            hl = R.rd(heads[g] + 4 * mi, "I")[0]
            hs = R.ptr_list(hl, 8) if 0x80000000 <= hl < 0x80400000 else []
            out.append({"group": g, "member": mi + 1, "code": g << 8 | (mi + 1),
                        "name": names.get((g, mi + 1)) or f"Wrestler {g}-{mi + 1}", "costumes": cs, "heads": hs})
    return out


def slug_of(name: str) -> str:
    return "wt_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def find_wrestler(ros: list[dict], query: str) -> dict:
    from .characters import best_match
    q = str(query).strip()
    m = re.match(r"^(\d+)[-:/](\d+)$", q)
    if m:
        hit = next((w for w in ros if w["group"] == int(m.group(1)) and w["member"] == int(m.group(2))), None)
        if hit:
            return hit
    if q.isdigit() or q.lower().startswith("0x"):
        code = int(q, 0)
        hit = next((w for w in ros if w["code"] == code), None)
        if hit:
            return hit
    cands = [{"name": w["name"], "aliases": [], "slug": slug_of(w["name"]), "code": w["code"]} for w in ros]
    hit = best_match(cands, q)
    if not hit:
        raise LookupError(f"no World Tour wrestler matches {query!r}")
    return next(w for w in ros if w["code"] == hit["code"])


# ---------------------------------------------------------------- rest body

def costume(R: Rom, rec_addr: int) -> dict:
    n = R.p["nmodels"]
    v = R.rd(rec_addr, "H", 1 + 2 * n)
    return {"hdr": v[0], "body": v[0] & 0x7F, "head": (v[0] >> 8) & 0xF, "pairs": [(v[1 + 2 * k], v[2 + 2 * k]) for k in range(n)]}


def records_of(R: Rom, w: dict, ci: int = 0) -> tuple[int, int, int]:
    """(record with the body, record with the textures, head definition) of costume ci."""
    if R.p["layout"] == "rv":
        hd = w["heads"][0][1]
        var = R.rd(hd + 0x16, "h")[0]
        vl = w["costumes"][ci][1]
        recs = [q for _a, q in R.ptr_list(vl, 4)]
        return recs[0], recs[min(max(var, 0), len(recs) - 1)], hd
    rec = w["costumes"][ci][1]
    c = costume(R, rec)
    hd = w["heads"][min(c["head"], len(w["heads"]) - 1)][1] if w["heads"] else 0
    return rec, rec, hd


def rest_parts(R: Rom, w: dict, ci: int = 0) -> dict:
    """{model index: {model, mid, tex, pal, texhdr, raw}} of a costume (+ "_head", "_costume")."""
    rb, rt, hd = records_of(R, w, ci)
    c = costume(R, rb)
    ct = costume(R, rt)
    n = R.p["nmodels"]
    bptr = R.rd(R.p["body_tbl"] + 4 * c["body"], "I")[0]
    models = R.rd(bptr, "H", n)
    out = {}
    for k in range(n):
        pal, tex = ct["pairs"][k]
        if models[k] and tex:
            out[k] = {"model": A.model_parse(R.ft.get(models[k])), "mid": models[k], "tex": tex, "pal": pal,
                      "texhdr": R.ft.get(tex)[:8], "raw": R.ft.get(models[k])}
    if hd:
        h = R.rd(hd, "H", 12)
        for key, mid, pal, tex in ((19, h[0], h[3], h[4]), (20, h[1], h[5], h[6])):
            if mid and tex:
                out[key] = {"model": A.model_parse(R.ft.get(mid)), "mid": mid, "tex": tex, "pal": pal,
                            "texhdr": R.ft.get(tex)[:8], "raw": R.ft.get(mid)}
        out["_head"] = h
    out["_costume"] = c
    return out


def joints_from(parts: dict) -> dict:
    by = {}
    for k, v in parts.items():
        if isinstance(k, int):
            by.setdefault(WPARTS[k][1], []).append(v["model"]["pos"])
    P = {j: np.concatenate(v) for j, v in by.items()}

    def seam(child, parent):
        a, b = P.get(child), P.get(parent)
        if a is None or b is None:
            return None
        d = np.linalg.norm(a[:, None] - b[None], axis=2).min(1)
        near = a[d <= max(1.5, np.sort(d)[min(len(d) - 1, 5)])]
        return near.mean(0)
    J = {"hip": np.array([0.0, P["hip"][:, 1].max() - 4, P["hip"].mean(0)[2]])}
    for j in JOINTS[1:]:
        if j in P:
            s = seam(j, JPARENT[j])
            J[j] = s if s is not None else P[j].mean(0)
    if "head" not in J:
        J["head"] = J["chest"] + [0, 14.0, 0]
    for side in "lr":
        if f"{side}_hand" in J and f"{side}_fingers" not in J:
            J[f"{side}_fingers"] = J[f"{side}_hand"] + [0, -6.0, 0]
    return {k: np.asarray(v, float) for k, v in J.items()}


def target_skeleton(parts: dict, J: dict) -> dict:
    T = np.array([J[j] for j in JOINTS])
    allp = np.concatenate([v["model"]["pos"] for k, v in parts.items() if isinstance(k, int)])
    heads = [v["model"]["pos"] for k, v in parts.items() if k in (19, 20)]
    W = []
    for t in T:
        m = np.eye(4)
        m[3, :3] = t
        W.append(m)
    return {"T": T, "W": W, "parent": [JOINTS.index(JPARENT[j]) if JPARENT[j] else -1 for j in JOINTS],
            "ground": float(allp[:, 1].min()), "head_h": float(np.ptp(np.concatenate(heads)[:, 1])) if heads else 26.0,
            "joints": len(JOINTS)}


# ---------------------------------------------------------------- extraction (a wrestler -> rigged glTF)

def texture_colours(tex: bytes) -> int:
    """Revenge CI4 files can carry two 16-colour palette banks (header count 32)."""
    if len(tex) < 8:
        raise ValueError('truncated AKI texture header')
    pixels = (tex[0] + 1) * (tex[1] + 1)
    if len(tex) >= 8 + pixels:
        return 256
    if len(tex) >= 8 + (pixels + 1) // 2:
        return 16
    raise ValueError('truncated AKI texture pixels')


def tex_decode(tex: bytes, pal: bytes) -> np.ndarray:
    """CI4 / CI8 texture + RGBA5551 palette -> RGBA (mirrored axes baked in: the image is doubled along them)."""
    w, h, ncol = tex[0] + 1, tex[1] + 1, struct.unpack_from(">H", tex, 2)[0]
    if texture_colours(tex) == 16:
        b = np.frombuffer(tex, np.uint8, (w * h + 1) // 2, 8)
        idx = np.stack([b >> 4, b & 15], 1).reshape(-1)[:w * h].reshape(h, w)
    else:
        idx = np.frombuffer(tex, np.uint8, w * h, 8).reshape(h, w)
    n = max(ncol, 16)
    p = A.rgba5551(np.frombuffer(pal.ljust(2 * n, bytes(1)), ">u2")[:n])
    img = p[np.minimum(idx, len(p) - 1)]
    img[..., 3] = 255
    if tex[4]:
        img = np.concatenate([img, img[:, ::-1]], 1)
    if tex[5]:
        img = np.concatenate([img, img[::-1]], 0)
    return img


def extract(rom: bytes, w: dict, out: Path, name: str, costume_i: int = 0) -> dict:
    from .melee_models import write_gltf
    R = Rom(rom)
    parts = rest_parts(R, w, costume_i)
    J = joints_from(parts)
    S = 0.01                                               # game units -> metres (a wrestler is ~170 units)
    prims = []
    for k, v in parts.items():
        if not isinstance(k, int):
            continue
        m = v["model"]
        if not len(m["faces"]):
            continue
        tex = R.ft.get(v["tex"])
        img = tex_decode(tex, R.ft.get(v["pal"]) if v["pal"] else b"")
        tw, th = (tex[0] + 1) * (2 if tex[4] else 1), (tex[1] + 1) * (2 if tex[5] else 1)
        ji = JOINTS.index(WPARTS[k][1])
        n = len(m["pos"])
        Jm = np.zeros((n, 4), np.uint16)
        Jm[:, 0] = ji
        Wm = np.zeros((n, 4), np.float32)
        Wm[:, 0] = 1
        nr = m["nrm"] / np.maximum(np.linalg.norm(m["nrm"], axis=1, keepdims=True), 1e-9)
        prims.append({"pos": m["pos"] * S, "nrm": nr, "uv": (m["uv"] + 0.5) / [tw, th], "tris": m["faces"], "J": Jm, "W": Wm,
                      "tex": img, "color": (255, 255, 255, 255)})
    joints = []
    for j in JOINTS:
        mm = np.eye(4)
        mm[:3, 3] = J[j] * S
        joints.append({"parent": JOINTS.index(JPARENT[j]) if JPARENT[j] else -1, "world": mm})
    write_gltf(Path(out), joints, prims, 1.0, name, list(JOINTS))
    roles = {r: r for r in ("hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                            "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")}
    return {"roles": roles, "triangles": sum(len(p["tris"]) for p in prims)}


WT_NAMES = [("0-1", "Hulk Hogan"), ("0-3", "Buff Bagwell"), ("0-4", "Eric Bischoff"), ("0-5", "Scott Norton"),
            ("0-6", "Kevin Nash"), ("0-7", "Scott Hall"), ("0-8", "Syxx"), ("0-9", "Randy Savage"), ("1-1", "Lex Luger"),
            ("1-2", "Sting"), ("1-3", "Giant"), ("1-4", "Scott Steiner"), ("1-5", "Rick Steiner"), ("1-6", "Ric Flair"),
            ("1-7", "Ultimo Dragon"), ("1-8", "Dean Malenko"), ("1-9", "Eddy Guerrero"), ("1-10", "Rey Mysterio Jr."),
            ("1-11", "Chris Benoit"), ("1-12", "Steven Regal"), ("1-13", "Diamond Dallas Page")]


def roster_entries() -> list[dict]:
    """characters.DEDICATED roster (World Tour): keys = 'group-member'."""
    return [{"key": k, "slug": slug_of(n), "name": n, "aliases": [f"World Tour {n}"], "kind": "character"} for k, n in WT_NAMES]


# Revenge (NW2E/NW2P): snapshot of aki_wcw.roster() on the owned builds (92 wrestlers, 13 hidden slots keep their
# generated "Wrestler g-m" placeholder because no profile string exists for them; #1317).
RV_NAMES = [
    (0, 1, "Sting"), (0, 2, "Giant"), (0, 3, "Lex Luger"), (0, 4, "Diamond Dallas Page"), (0, 5, "Rick Steiner"),
    (0, 6, "Wrestler 0-6"), (0, 7, "Roddy Piper"), (0, 8, "Bret Hart"), (0, 9, "Chris Benoit"), (0, 10, "Goldberg"),
    (0, 11, "Booker T"), (0, 12, "Disco Inferno"),
    (1, 1, "Fit Finley"), (1, 2, "Wrestler 1-2"), (1, 3, "Wrestler 1-3"), (1, 4, "Wrestler 1-4"), (1, 5, "Meng"),
    (1, 6, "Barbarian"), (1, 7, "Larry Zbysko"), (1, 8, "Stevie Ray"), (1, 9, "Wrestler 1-9"),
    (1, 10, "Wrestler 1-10"), (1, 11, "British Bulldog"), (1, 12, "Wrestler 1-12"), (1, 13, "Yugi Nagata"),
    (1, 14, "Jim Neidhart"), (1, 15, "Alex Wright"), (1, 16, "Wrestler 1-16"),
    (2, 1, "Hollywood Hogan"), (2, 2, "Macho Man Randy Savage"), (2, 3, "Kevin Nash"), (2, 4, "Scott Hall"),
    (2, 5, "Buff Bagwell"), (2, 6, "Scott Steiner"), (2, 7, "Curt Hennig"), (2, 8, "Konnan"), (2, 9, "Scott Norton"),
    (2, 10, "Wrestler 2-10"), (2, 11, "Wrestler 2-11"), (2, 12, "Brian Adams"), (2, 13, "Eric Bischoff"),
    (2, 14, "Wrestler 2-14"),
    (3, 1, "Ultimo Dragon"), (3, 2, "Eddy Guerrero"), (3, 3, "Chris Jericho"), (3, 4, "Rey Mysterio Jr."),
    (3, 5, "Juventud Guerrera"), (3, 6, "Dean Malenko"), (3, 7, "Chavo Guerrero Jr."), (3, 8, "La Parka"),
    (3, 9, "Psychosis"), (3, 10, "Wrestler 3-10"),
    (4, 1, "Glacier"), (4, 2, "Wrestler 4-2"), (4, 3, "Wrath"), (4, 4, "Kanyon"),
    (5, 1, "Raven"), (5, 2, "Saturn"), (5, 3, "Kidman"), (5, 4, "Riggs"), (5, 5, "Van Hammer"), (5, 6, "Sick Boy"),
    (5, 7, "Lodi"), (5, 8, "Reese"),
    (6, 1, "AKI man"), (6, 2, "Shogun"), (6, 3, "Executioner"), (6, 4, "Dr. Frank"), (6, 5, "Jekel"),
    (6, 6, "Maya Inca Boy"),
    (7, 1, "Hawk Hana"), (7, 2, "Kim Chee"), (7, 3, "Dake Ken"), (7, 4, "Brickowski"), (7, 5, "Ming Chee"),
    (7, 6, "Han Zo Mon"),
    (8, 1, "Eric Bischoff"), (8, 2, "Onoo"), (8, 3, "Jimmy Hart"), (8, 4, "Rick Rude"), (8, 5, "Dusty Rhodes"),
    (8, 6, "Ted Debisas"), (8, 7, "James Bandenderg"), (8, 8, "Vincent"),
    (9, 1, "Elizabeth"), (9, 2, "Kimberly"), (9, 3, "Jackreen"), (9, 4, "Sister Sherri"), (9, 5, "Woman"),
    (9, 6, "WHITE"), (9, 7, "RED"), (9, 8, "DRIVER"),
]


def revenge_roster() -> list[dict]:
    """characters.DEDICATED roster (Revenge): keys = 'group-member'; slugs match dedicated_entries' rv_* scheme."""
    out = []
    for g, m, n in RV_NAMES:
        out.append({"key": f"{g}-{m}", "slug": f"rv_{g}_{m}_{re.sub(r'[^a-z0-9]+', '_', n.lower()).strip('_')}",
                    "name": n, "aliases": [f"Revenge {n}", f"{g}-{m}"], "kind": "character"})
    return out


def extract_run(ctx, game, e, work):
    from .characters import _rom
    rom = A.rom_bytes(_rom(ctx, game))
    w = find_wrestler(roster(rom), e["key"])
    out = Path(work) / f"{e['slug']}.gltf"
    r = extract(rom, w, out, e["name"])
    return {"files": [out], "tool": "gbox.aki_wcw (extract)", "roles": r["roles"],
            "source_files": [f"body definition + head definition + costume 0 textures of wrestler {e['key']}"],
            "notes": f"{game['title']} wrestler in AKI's rest pose (arms down); one rigid joint per body part"}


# ---------------------------------------------------------------- textures

def tex_encode(hdr: bytes, img: np.ndarray, ncol: int) -> tuple[bytes, bytes]:
    """RGBA image (h, w) -> (texture file = original 8-byte header + CI4/CI8 pixels, palette file RGBA5551 BE)."""
    idx, pal = A.quantize(img, ncol)
    idx = np.asarray(idx, np.uint8)
    pal = np.asarray(pal)
    c = pal.astype(np.uint16)
    v5 = ((c[:, 0] >> 3) << 11) | ((c[:, 1] >> 3) << 6) | ((c[:, 2] >> 3) << 1) | 1
    palb = v5.astype(">u2").tobytes().ljust(2 * ncol, b"\0")
    declared = max(ncol, struct.unpack_from('>H', hdr, 2)[0])
    # Preserve every bank the native costume loader expects, using the baked replacement colours.
    palb = (palb * ((declared + ncol - 1) // ncol))[:2 * declared]
    if ncol == 16:
        flat = idx.reshape(-1) & 15
        pix = ((flat[0::2] << 4) | flat[1::2]).astype(np.uint8).tobytes()
    else:
        pix = idx.reshape(-1).tobytes()
    return bytes(hdr) + pix, palb


# ---------------------------------------------------------------- fit

def fit_character(R: Rom, w: dict, model: Path, roles: dict, work: Path, name: str, props=(), scale=None,
                  blender: str | None = None, progress=lambda p, m: None) -> dict:
    from .sm64_swap import load_rig, retarget, write_rigged, read_rigged
    from .re4gc_enemies import decimate
    parts0 = rest_parts(R, w, 0)
    J = joints_from(parts0)
    tgt = target_skeleton(parts0, J)
    jmap = {j: i for i, j in enumerate(JOINTS)}
    progress(20, f"Retargeting {name} onto {w['name']}'s skeleton")
    rig = load_rig(Path(model), roles, props)
    tris_src = sum(len(p["tris"]) for p in rig["prims"])
    prims, rep = retarget(rig, tgt, scale, {k: v for k, v in jmap.items() if k in
                                           ("hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore",
                                            "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")})
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    rigged = write_rigged(prims, tgt, work / "wt_rigged.gltf", name)
    src = rigged
    if tris_src > 8000 and blender:
        src = decimate(rigged, work / "wt_dec.glb", 8000.0, blender)
    rp = read_rigged(src)
    progress(40, "Cutting the model into the wrestler's parts")
    mats, mkey = [], {}
    allP, allN, allUV, allJ, F, FM = [], [], [], [], [], []
    base = 0
    for p in rp:
        key = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
        if key not in mkey:
            mkey[key] = len(mats)
            mats.append({"tex": p["tex"], "color": p["color"]})
        allP.append(p["pos"]); allN.append(p["nrm"]); allUV.append(p["uv"]); allJ.append(p["jid"])
        F.append(p["tris"] + base)
        FM.append(np.full(len(p["tris"]), mkey[key]))
        base += len(p["pos"])
    P, N, UV, JV = np.concatenate(allP), np.concatenate(allN), np.concatenate(allUV), np.concatenate(allJ)
    F, FM = np.concatenate(F), np.concatenate(FM)
    jn = np.array(JOINTS)
    fj = np.array([np.bincount(JV[f]).argmax() for f in F])
    cen = P[F].mean(1)
    part = np.empty(len(F), int)
    for i, (j, c) in enumerate(zip(jn[fj], cen)):
        if j in ("hip", "waist", "chest"):
            part[i] = 2 if c[1] >= J["chest"][1] else 1 if c[1] >= J["waist"][1] else 0
        elif j == "head":
            part[i] = 19 if c[2] >= J["head"][2] else 20
        else:
            part[i] = LIMB_PART[j]
    caps = {k: (max(len(v["model"]["pos"]), 12), max(len(v["model"]["faces"]), 12)) for k, v in parts0.items()
            if isinstance(k, int)}
    for k in set(part.tolist()) - set(caps):
        part[part == k] = 2
    geo = A._decimate_parts(P, N, UV, F, FM, part, mats, caps, work, blender, progress)
    out, report = {}, {}
    for k, v in parts0.items():
        if not isinstance(k, int):
            continue
        hdr = v["texhdr"]
        tw, th = hdr[0] + 1, hdr[1] + 1
        ncol = texture_colours(R.ft.get(v['tex']))
        texbyte = v["raw"][7]
        if k in geo and len(geo[k]["F"]):
            img, pv = A._bake_parts([geo[k]], mats, tw, th, [J.get(WPARTS[k][1])])
            vp, vn, vu, faces = (list(x) for x in pv[0])
            cv, cf = caps[k]
            dropped = 0
            while len(vp) > min(A.MAX_V, cv) or len(faces) > min(A.MAX_F, cf):
                area = [np.linalg.norm(np.cross(vp[f[1]] - vp[f[0]], vp[f[2]] - vp[f[0]])) for f in faces]
                faces.pop(int(np.argmin(area)))
                dropped += 1
                usedv = sorted({x for f in faces for x in f})
                remap = {x: i for i, x in enumerate(usedv)}
                vp = [vp[x] for x in usedv]; vn = [vn[x] for x in usedv]; vu = [vu[x] for x in usedv]
                faces = [[remap[x] for x in f] for f in faces]
        else:
            faces = []
        if faces:
            mb = A.model_encode(np.array(vp), np.array(vn), np.array(vu), np.array(faces), texbyte)
            report[WPARTS[k][0]] = {"verts": len(vp), "faces": len(faces), "budget": list(caps[k]), "dropped": dropped,
                                    "tex": f"{tw}x{th}x{ncol}"}
        else:                                              # every part exists: a hidden speck at its joint
            img = np.zeros((th, tw, 4), np.uint8)
            img[..., 3] = 255
            j = J.get(WPARTS[k][1], J["chest"])
            vpp = np.array([j, j + [0.6, 0, 0], j + [0, 0.6, 0]])
            mb = A.model_encode(vpp, np.tile([0, 0, 1.0], (3, 1)), np.zeros((3, 2)), np.array([[0, 1, 2]]), texbyte)
            report[WPARTS[k][0]] = {"verts": 3, "faces": 1, "placeholder": True}
        texb, palb = tex_encode(hdr, img, ncol)
        out[k] = {"model": mb, "tex": texb, "pal": palb}
    return {"parts": out, "rigged": rigged, "head": parts0.get("_head"), "costume": parts0["_costume"],
            "report": {"retarget": rep, "parts": report, "source_triangles": tris_src,
                       "triangles": sum(v["faces"] for v in report.values())}}


# ---------------------------------------------------------------- writer

class Writer:
    def __init__(self, rom: bytes):
        self.R = Rom(rom)
        self.p = self.R.p
        self.files: list[bytes] = []
        self.bodies: list[list[int]] = []
        self.heads: list[list[int]] = []
        self.records: list[list[int]] = []
        self.sets: list[int] = []                          # Revenge: costume count of each new set
        self.repoint: list[tuple[int, str, int]] = []      # (RAM address of a pointer word, kind, index)
        self.u16: list[tuple[int, int]] = []               # (RAM address, new u16)

    def add_file(self, data: bytes) -> int:
        self.files.append(data)
        return self.p["nfiles"] + 1 + len(self.files)      # id nfiles+1 is the spacer

    def replace(self, w: dict, fit: dict) -> dict:
        n = self.p["nmodels"]
        ids = {k: (self.add_file(v["model"]), self.add_file(v["pal"]), self.add_file(v["tex"])) for k, v in fit["parts"].items()}
        body = [ids[k][0] if k in ids else 0 for k in range(n)] + [0]     # model ids + a pad word, like the game's
        self.bodies.append(body)
        bi = self.p["bodies"] + len(self.bodies) - 1
        if bi > 0x7F:
            raise ValueError("too many replaced wrestlers in one ROM")
        h = list(fit["head"] or [0] * 12)
        for key, (mi, pi, ti) in ((19, (0, 3, 4)), (20, (1, 5, 6))):
            if key in ids:
                h[mi], h[pi], h[ti] = ids[key][0], ids[key][1], ids[key][2]
        h[2] = h[7] = h[8] = 0                             # no hair model
        h[9] = h[10] = h[11] = 0                           # (Revenge: +0x16 = texture variant 0)
        self.heads.append(h[:12])
        hi_ = len(self.heads) - 1
        hdr0 = fit["costume"]["hdr"]
        rec = [(hdr0 & 0x7080) | bi] + [x for k in range(n) for x in ((ids[k][1], ids[k][2]) if k in ids else (0, 0))] + [0]
        self.records.append(rec)
        ri = len(self.records) - 1
        if self.p["layout"] == "rv":
            self.sets.append((ri, len(w["costumes"])))
            si = self.p["sets"] + len(self.sets) - 1
            self.u16.append((w["set_addr"], (w["set"] & ~0x7F & 0xFFFF) | si))
        else:
            for pa, _old in w["costumes"]:
                self.repoint.append((pa, "record", ri))
        for pa, _old in w["heads"]:
            self.repoint.append((pa, "head", hi_))
        return {"body": bi, "files": len(ids) * 3}

    def build(self) -> bytes:
        from .sm64_writer import fix_crc
        R, p = self.R, self.p
        rom = bytearray(R.rom)
        first = p["first"]
        end = len(rom.rstrip(rom[-1:]))
        data_at = (max(end, p["ft"] + 4 * (p["nfiles"] + 4)) + 0xFFF) & ~0xFFF
        blob, offs, flags = bytearray(), [], []
        for f in self.files:
            blob += bytes((-len(blob)) % 8)
            offs.append(data_at + len(blob))
            z = A.lzss_store(f)
            flags.append(len(z) < len(f))
            blob += z if flags[-1] else f
        blob += bytes((-len(blob)) % 8)
        data_end = data_at + len(blob)
        raw = list(R.ft.raw)
        raw[-1] &= ~1
        raw.append((data_at - first) | (1 if flags and flags[0] else 0))
        for o, fl in zip(offs[1:], flags[1:]):
            raw.append((o - first) | int(fl))
        raw.append(data_end - first)
        n_entries = len(raw)
        table = struct.pack(f">{n_entries}I", *raw)
        # payload in Expansion RAM: table | body table (128) | bodies | heads | records | (Revenge: set table, sets)
        pay = bytearray(table)
        pay += bytes((-len(pay)) % 16)
        body_tbl = RAM_EXP + len(pay)
        pay += bytes(4 * 128)
        bodies_at, bsize = RAM_EXP + len(pay), 2 * len(self.bodies[0]) if self.bodies else 0
        for bd in self.bodies:
            pay += struct.pack(f">{len(bd)}H", *bd)
        pay += bytes((-len(pay)) % 4)
        heads_at = RAM_EXP + len(pay)
        for h in self.heads:
            pay += struct.pack(">12H", *h)
        recs_at, rsize = RAM_EXP + len(pay), 2 * len(self.records[0]) if self.records else 0
        rsize += (-rsize) % 4
        for r in self.records:
            pay += struct.pack(f">{len(r)}H", *r).ljust(rsize, b"\0")
        orig = list(R.rd(p["body_tbl"], "I", p["bodies"]))
        allb = orig + [bodies_at + bsize * i for i in range(len(self.bodies))]
        allb += [orig[0]] * (128 - len(allb))
        struct.pack_into(">128I", pay, body_tbl - RAM_EXP, *allb)
        sets_tbl = 0
        if p["layout"] == "rv":
            sets_tbl = RAM_EXP + len(pay)
            pay += bytes(4 * 128)
            set_ptrs = []
            for ri, ncost in self.sets:
                var_at = RAM_EXP + len(pay)                    # variant list: the record 3 times
                pay += struct.pack(">4I", recs_at + rsize * ri, recs_at + rsize * ri, recs_at + rsize * ri, 0)
                set_ptrs.append(RAM_EXP + len(pay))            # costume list: every costume -> that variant list
                pay += struct.pack(f">{ncost + 1}I", *([var_at] * ncost + [0]))
            origs = list(R.rd(p["costume_lists"], "I", p["sets"]))
            alls = origs + set_ptrs
            alls += [origs[0]] * (128 - len(alls))
            struct.pack_into(">128I", pay, sets_tbl - RAM_EXP, *alls)
        pay += bytes((-len(pay)) % 16)
        total = len(pay)
        if total > 0xFFFF:
            raise ValueError(f"payload {total:#x} bytes is over the loader's 16-bit DMA size")
        ft_rom = data_end
        need = ft_rom + total
        size = len(rom)
        while size < need:
            size *= 2
        if size > 0x4000000:
            raise ValueError("the modded ROM would exceed 64 MB")
        if size > len(rom):
            rom += b"\xff" * (size - len(rom))
        rom[data_at:data_end] = blob
        rom[ft_rom:ft_rom + total] = pay

        def put(ram, old, new):
            o = R.r2r(ram)
            cur = struct.unpack_from(">I", rom, o)[0]
            if cur != old:
                raise ValueError(f"unexpected code at {ram:#x}: {cur:08x} (want {old:08x})")
            struct.pack_into(">I", rom, o, new)
        hi = lambda a: ((a + 0x8000) >> 16) & 0xFFFF
        ori = lambda old, imm: 0x34000000 | (old & 0x001F0000) | (imm & 0xFFFF)   # addiu rt,zero,imm -> ori (16-bit unsigned)
        for ram, old, kind in p["patch"]:
            new = {"malloc": 0x3C020000 | (RAM_EXP >> 16),
                   "ft_hi": (old & 0xFFFF0000) | hi(ft_rom), "ft_lo": (old & 0xFFFF0000) | (ft_rom & 0xFFFF),
                   "total": ori(old, total), "sizes": ori(old, 4 * (n_entries - 1)),
                   "loop_bytes": ori(old, 4 * (n_entries - 1)), "loop_count": (old & 0xFFFF0000) | (n_entries - 1),
                   "bound": (old & 0xFFFF0000) | n_entries,
                   "body_hi": (old & 0xFFFF0000) | hi(body_tbl), "body_lo": (old & 0xFFFF0000) | (body_tbl & 0xFFFF),
                   "sets_hi": (old & 0xFFFF0000) | hi(sets_tbl), "sets_lo": (old & 0xFFFF0000) | (sets_tbl & 0xFFFF)}[kind]
            put(ram, old, new)
        for pa, kind, i in self.repoint:
            struct.pack_into(">I", rom, R.r2r(pa), (recs_at + rsize * i) if kind == "record" else (heads_at + 24 * i))
        for a_, v in self.u16:
            struct.pack_into(">H", rom, R.r2r(a_), v)
        return bytes(fix_crc(rom))


def build_rom(rom: bytes, jobs: list[dict], work: Path, blender=None, progress=lambda p, m: None) -> dict:
    """jobs [{code, model, roles, name, props, scale}] -> {rom, reports}."""
    wr = Writer(rom)
    ros = roster(rom)
    reports = []
    for k, jb in enumerate(jobs):
        w = next(x for x in ros if x["code"] == jb["code"])
        fit = fit_character(wr.R, w, jb["model"], jb["roles"], Path(work) / f"w{w['code']:x}", jb["name"],
                            jb.get("props", ()), jb.get("scale"), blender,
                            progress=lambda p, m, k=k: progress(5 + (k * 80 + p * 0.8) / max(1, len(jobs)), m))
        r = wr.replace(w, fit)
        reports.append({"wrestler": w["name"], "code": hex(w["code"]), "character": jb["name"], "rigged": str(fit["rigged"]),
                        **r, **fit["report"]})
    progress(90, "Writing the ROM (file table moved to Expansion Pak RAM, records repointed)")
    return {"rom": wr.build(), "reports": reports}


# ---------------------------------------------------------------- gBox: characters op=use

def mod_name(pairs: list[tuple[dict, dict]], title: str | None = None) -> str:
    if title and len(pairs) > 2:
        return "worldtour_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:48]
    if len(pairs) == 1:
        return f"worldtour_{pairs[0][0]['slug']}_as_{slug_of(pairs[0][1]['name'])[3:]}"
    return "worldtour_" + "_vs_".join(m["slug"] for m, _w in pairs)


def build_mod(cfg, game: dict, pairs: list[tuple[dict, dict]], progress=lambda p, m: None, title: str | None = None) -> dict:
    from . import characters as C, filemods
    from .models import CatalogEntry
    from .tools import rom_path
    from .sm64_swap import _blender
    root = C.library_root(cfg)
    gid = game["game_id"]
    rom = A.rom_bytes(rom_path(CatalogEntry.model_validate(game), cfg))
    jobs = []
    for meta, w in pairs:
        roles = (meta.get("rig") or {}).get("roles") or {}
        if "hip" not in roles:
            raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't map it onto a wrestler")
        jobs.append({"code": w["code"], "model": root / meta["slug"] / meta["model"], "roles": roles, "name": meta["name"],
                     "props": [p["node"] for p in meta.get("props") or []], "scale": (meta.get("rig") or {}).get("scale")})
    name = mod_name(pairs, title)
    work = Path(cfg.cache) / "characters_build" / gid / name
    shutil.rmtree(work, ignore_errors=True)
    b = build_rom(rom, jobs, work, _blender(cfg), progress)
    previews = []
    for (meta, w), rep in zip(pairs, b["reports"]):
        tdir = root / meta["slug"] / "targets"
        tdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rep["rigged"], tdir / f"wcw_{gid}_wrestler.gltf")
        try:
            previews.append(str(C.render_preview(tdir / f"wcw_{gid}_wrestler.gltf", tdir / f"wcw_{gid}_preview.png")))
        except Exception:                                  # noqa: BLE001
            pass
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    t = title or " vs ".join(m["name"] for m, _w in pairs)
    img = ("WCW vs. nWo World Tour - " if gid == "59bf059d2eadd372" else "WCW nWo Revenge - ") + re.sub(r"[^\w .()'-]+", "", t).strip() + " (USA).z64"
    (d / img).write_bytes(b["rom"])
    (d / ".gbox-mod.json").write_text(json.dumps({
        "name": name, "game_id": gid, "image": img, "title": t, "built": time.time(),
        "files": ["@image: wrestler models (gbox.aki_wcw)"], "characters": [m["slug"] for m, _w in pairs],
        "replaces": [w["name"] for _m, w in pairs], "triangles": [r["triangles"] for r in b["reports"]]}))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": img, "previews": previews,
            "reports": [{k: v for k, v in r.items() if k != "rigged"} for r in b["reports"]]}


def _player1(ctx, sess, ros, address=0x80057520) -> dict | None:
    """Player 1's wrestler in a running session of the game (slot code at 0x80057520)."""
    try:
        from .characters import _job
        import httpx
        j = _job(ctx, "read_memory", {"session_id": sess["session_id"], "address": address, "length": 16}, None, 120)
        if j.get("state") != "succeeded":
            return None
        r = httpx.get(f"{ctx.server}/api/artifacts/{j['output']['sha256']}", headers=ctx.headers, timeout=60)
        d = r.content
        code = struct.unpack_from(">H", d, 0)[0]
        if code & 0xE0E0 or not code & 0xFF:                # RetroArch reads N64 RAM word-swapped
            d = np.frombuffer(d[:16], "<u4").astype(">u4").tobytes()
            code = struct.unpack_from(">H", d, 0)[0]
        return next((w for w in ros if w["code"] == code), None)
    except Exception:                                      # noqa: BLE001
        return None


def use(ctx, meta: dict, game: dict, inp, pairs: list | None = None, title: str | None = None) -> dict:
    """characters op=use for World Tour: slot = a wrestler's name / "group-member" / "player" (player 1's wrestler in
    the session, else the first wrestler); build on the control plane, launch."""
    from . import characters as C, filemods
    from .models import CatalogEntry
    from .tools import rom_path
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "message": "Native writers support WCW World Tour USA and WCW/nWo Revenge USA."}
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    if not C.library_root(ctx.config).is_dir():
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
        slot = inp.slot
        if slot == "player" and sess and sess.get("game_id") == gid:
            rom = A.rom_bytes(rom_path(CatalogEntry.model_validate(game), ctx.config))
            ros = roster(rom)
            w = _player1(ctx, sess, ros, Rom(rom).p['slot_code'])
            if not w:
                return {'status': 'choose_slot', 'message': "Couldn't identify the active wrestler. Choose a wrestler by name.",
                        'roster': [w['name'] for w in ros]}
            slot = f"{w['group']}-{w['member']}"
        args = {"op": inp.op, "character": inp.character, "game_id": gid, "slot": slot, "rebuild": inp.rebuild,
                "launch": False, "pairs": inp.pairs, "title": inp.title}
        j = C._job(ctx, "characters", args, cp, 2400)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        name, built = r["mod"], r.get("build")
    else:
        rom = A.rom_bytes(rom_path(CatalogEntry.model_validate(game), ctx.config))
        ros = roster(rom)
        if pairs is None:
            if inp.slot and inp.slot != "player":
                w = find_wrestler(ros, inp.slot)
            else:
                w = _player1(ctx, sess, ros, Rom(rom).p['slot_code']) if sess and sess.get("game_id") == gid else ros[0]
                if not w:
                    return {'status': 'choose_slot', 'message': "Couldn't identify the active wrestler. Choose a wrestler by name.",
                            'roster': [w['name'] for w in ros]}
            pairs = [(meta, w)]
        name = mod_name(pairs, title)
        have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
        built = None
        if inp.rebuild or not have:
            built = build_mod(ctx.config, game, pairs, ctx.progress, title=title)
            for m, w in pairs:
                C._api(ctx, "POST", f"/api/characters/{m['slug']}/targets",
                       json={"game_id": gid, "slot": w["name"], "mod": name, "nodes": [C.HOST_OS],
                             "notes": f"replaces {w['name']} (every costume; the game's skeleton, moves and grapples); "
                                      f"preview targets/wcw_{gid}_preview.png"})
    res = {"mod": name, "build": built, "replaces": ", ".join(f"{w['name']} -> {m['name']}" for m, w in (pairs or []))}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(92, f"Launching {game['title']} (mod {name})")
    from .sm64_swap import _wait
    lj = _wait(ctx, C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name,
                                                                                         "node": node}}), 600)
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = (f"{game['title']} is running with {res['replaces']} (mod {name}). Pick the replaced wrestler on the select "
           "screen. Needs the Expansion Pak (on in parallel_n64)." if ok else
           f"Mod {name} built but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": ("built+launched" if built else "launched") if ok else "built, launch failed", "launch": launch,
                  "message": msg}


def match(ctx, chars: list, game: dict, inp, pairs_in: list[tuple[str, str]], title: str | None = None) -> dict:
    from .characters import best_match
    from .models import CatalogEntry
    from .tools import rom_path
    ros = roster(A.rom_bytes(rom_path(CatalogEntry.model_validate(game), ctx.config)))
    pairs, used = [], set()
    for cq, wq in pairs_in:
        meta = best_match(chars, cq)
        if not meta:
            raise LookupError(f"{cq!r} isn't in the collection")
        w = find_wrestler(ros, wq) if wq else next(x for x in ros if x["code"] not in used)
        if w["code"] in used:
            raise ValueError(f"{w['name']} is already replaced")
        used.add(w["code"])
        pairs.append((meta, w))
    return use(ctx, pairs[0][0], game, inp, pairs, title)
