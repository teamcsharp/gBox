"""DOA3 donor fit: a gBox rigged donor (glTF with the 15 body roles) -> per-part geometry in DOA3's joint frames.

What the costumes pin (all 69 owned costumes, gbox.doa3_cast):

* The CAT render lists (at 0x14 + word@0x1C, marker bytes >= 0xE0, 0xFF ends) name every costume's parts:
  ``0xFE`` the 15 primary body parts, ``0xFD`` the two eyes, ``0xFB`` the two wrist-side forearm halves, ``0xF9``
  15 lower-detail copies in the same order as 0xFE, ``0xF8`` 15 shadow meshes, ``0xF7``/``0xF6`` hair and
  accessories. 69/69 costumes carry exactly 15 primary parts.
* The primary list is in a fixed joint order (checked on the geometry of 54/69 costumes by limb axis, the rest
  differ only by boots or a placeholder forearm): chest, head, hip, then per side (left first, fingers +x) foot,
  forearm, hand, thigh, shin, upper arm.
* Each part is rigid in its joint's frame: chest/head/hip/feet/hands keep y up and z forward (the face, the toes and
  the thumb point +z); a thigh and an upper arm run along +z from their joint, a shin and a forearm along -z.

The fit is per part: the donor's role segment is straightened onto the canonical stance (arms out along x, legs
down), scaled by one global factor (leg length), stretched along the bone to the native part's length (clamped),
then mapped into the part's frame with its proximal joint at the origin. Nothing here reads the native skeleton's
rest rotations (they are not decoded): limb twist follows a fixed convention, documented per role in LIMB_FRAMES.
"""
from __future__ import annotations

import struct

import numpy as np

from . import doa3_cast as C
from . import doa3_writer as W

ROLES = ("chest", "head", "hip", "l_foot", "l_fore", "l_hand", "l_thigh", "l_shin", "l_upper",
         "r_foot", "r_fore", "r_hand", "r_thigh", "r_shin", "r_upper")
LIST_PRIMARY, LIST_EYES, LIST_TWIST, LIST_LOD, LIST_SHADOW = 0xFE, 0xFD, 0xFB, 0xF9, 0xF8

# canonical stance direction of each limb bone in the donor's (left +x, up +y, front +z) frame
CANON = {"l_upper": (1, 0, 0), "l_fore": (1, 0, 0), "r_upper": (-1, 0, 0), "r_fore": (-1, 0, 0),
         "l_thigh": (0, -1, 0), "l_shin": (0, -1, 0), "r_thigh": (0, -1, 0), "r_shin": (0, -1, 0)}
CHILD = {"l_upper": "l_fore", "l_fore": "l_hand", "r_upper": "r_fore", "r_fore": "r_hand",
         "l_thigh": "l_shin", "l_shin": "l_foot", "r_thigh": "r_shin", "r_shin": "r_foot"}
# rows = the part frame's x, y, z axes written in the canonical stance frame (local = rows @ stance)
LIMB_FRAMES = {
    # arms out along x, y kept up: the bone is +z (upper) / -z (fore) in the part frame
    "l_upper": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    "l_fore": ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
    "r_upper": ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
    "r_fore": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    # legs down: thigh +z = down with y = front, shin -z = down with y = back
    "l_thigh": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "r_thigh": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "l_shin": ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
    "r_shin": ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
}
STRETCH = (0.6, 1.7)
HEAD_GROWTH = 2.0                 # a donor head may stand up to 2x the native head's height above the neck joint
HAND_GROWTH = 1.3                 # gloves reach up to 1.3x the native hand


# ------------------------------------------------------------------------------------------------ costume roles

def cat_render_lists(cat: bytes) -> dict[int, list[int]]:
    """{marker: [OBJ index, ...]} from a CAT companion's render lists."""
    start = 0x14 + struct.unpack_from("<I", cat, 0x1C)[0]
    out, current, p = {}, None, start
    while p < len(cat):
        value = cat[p]
        p += 1
        if value == 0xFF:
            return out
        if value >= 0xE0:
            current = value
            out[current] = []
        elif current is None:
            raise ValueError(f"CAT render list at {start:#x} starts with OBJ {value} before a marker")
        else:
            out[current].append(value)
    raise ValueError("CAT render lists are not terminated by 0xFF")


def costume_roles(cat: bytes, obj_count: int) -> dict:
    """Role -> primary OBJ (and its lower-detail copy), plus the eyes / twist / shadow / other part sets."""
    lists = cat_render_lists(cat)
    primary = lists.get(LIST_PRIMARY, [])
    if len(primary) != len(ROLES):
        raise ValueError(f"costume lists {len(primary)} primary parts, the DOA3 order needs {len(ROLES)}")
    lod = lists.get(LIST_LOD, [])
    every = {k for parts in lists.values() for k in parts}
    if any(k >= obj_count for k in every):
        raise ValueError("CAT render list names an OBJ the costume does not have")
    return {"primary": dict(zip(ROLES, primary)),
            "lod": dict(zip(ROLES, lod)) if len(lod) == len(ROLES) else {},
            "eyes": lists.get(LIST_EYES, []), "twist": lists.get(LIST_TWIST, []),
            "shadow": lists.get(LIST_SHADOW, []),
            "other": sorted(k for m, parts in lists.items() if m not in
                            (LIST_PRIMARY, LIST_EYES, LIST_TWIST, LIST_LOD, LIST_SHADOW) for k in parts),
            "unlisted": sorted(set(range(obj_count)) - every)}


def part_extent(geometry: dict, obj: int, role: str) -> float:
    """The native bone length estimate: how far the part reaches from its joint along its bone axis."""
    P = np.array([v[:3] for v in geometry["objects"][obj]["vertices"]])
    if role.endswith(("upper", "thigh")):
        return float(P[:, 2].max())
    if role.endswith(("fore", "shin")):
        return float(-P[:, 2].min())
    raise ValueError(role)


# ------------------------------------------------------------------------------------------------ donor

def _donor_role_per_vertex(rig: dict) -> list[np.ndarray]:
    """Per primitive: the role of each vertex's strongest influence (resolved through the donor's ancestry)."""
    from .re4gc_enemies import _role_of_joint
    mappable = {r: j for r, j in rig["roles"].items() if r in ROLES or r in ("neck", "l_clav", "r_clav")}
    joint_role = np.array(_role_of_joint({"roles": mappable, "parent": rig["parent"]}), dtype=object)
    out = []
    for p in rig["prims"]:
        J, Wt = np.asarray(p["J"]), np.asarray(p["W"])
        strongest = J[np.arange(len(J)), Wt.argmax(1)] if J.ndim == 2 else J
        roles = joint_role[strongest]
        roles = np.where(roles == "neck", "head", roles)
        roles = np.where(np.isin(roles, ["l_clav", "r_clav"]), "chest", roles)
        roles = np.where(np.isin(roles, list(ROLES)), roles, "hip")
        out.append(roles.astype(str))
    return out


def _stance(rig: dict):
    """Donor joints and primitives in its own facing frame (left +x, up +y, front +z)."""
    from .sm64_swap import facing
    B = facing(rig)
    joints = np.asarray(rig["joints"], float) @ B.T
    prims = [{**p, "pos": np.asarray(p["pos"], float) @ B.T, "nrm": np.asarray(p["nrm"], float) @ B.T}
             for p in rig["prims"]]
    return joints, prims, B


# a DOA3 fighter stands on two legs: the fit needs these donor roles (arms are optional)
DONOR_ROLES = ("hip", "head", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")


def fit(rig: dict, geometry: dict, roles: dict, *, texture_limit: int = 256, slots=None,
        lod_copies: bool = True) -> dict:
    """-> {"parts": {OBJ: encode_costume part}, "textures": [(word, payload)], "report": {...}}."""
    from .re4gc_enemies import _rot_between
    joints, prims, _basis = _stance(rig)
    ri = {r: j for r, j in rig["roles"].items()}
    missing = [r for r in DONOR_ROLES if r not in ri]
    if missing:
        raise ValueError(f"donor lacks the roles {missing}")
    vertex_roles = _donor_role_per_vertex(rig)
    primary = roles["primary"]

    allp = np.concatenate([p["pos"] for p in prims])
    allr = np.concatenate(vertex_roles)

    def segment(role):
        return allp[allr == role]

    def native_box(role):
        P = np.array([v[:3] for v in geometry["objects"][primary[role]]["vertices"]])
        return P.min(0), P.max(0)

    # body scale: the native torso reach (hip joint to the chest part's top) over the donor's hip -> head joint
    torso_native = float(native_box("chest")[1][1])
    torso_donor = float(np.linalg.norm(joints[ri["head"]] - joints[ri["hip"]]))
    scale = float(np.clip(torso_native / max(torso_donor, 1e-9), 1e-6, 1e6))

    rules, stretch, straightened, sizes = {}, {}, {}, {}
    for role in ROLES:
        if role not in ri or role not in CANON:
            continue
        origin = joints[ri[role]]
        child = CHILD[role]
        bone = joints[ri[child]] - origin if child in ri else np.array(CANON[role], float)
        length = float(np.linalg.norm(bone)) if child in ri else 0.0
        straighten = _rot_between(bone, np.array(CANON[role], float)) if length > 1e-9 else np.eye(3)
        native = part_extent(geometry, primary[role], role)
        k = float(np.clip(native / max(scale * length, 1e-9), *STRETCH)) if length > 1e-9 else 1.0
        d = np.array(CANON[role], float)
        stretch_m = np.eye(3) + (k - 1) * np.outer(d, d)
        frame = np.array(LIMB_FRAMES[role], float)
        rules[role] = (frame @ stretch_m @ (scale * straighten), origin, np.zeros(3))
        stretch[role] = k
        straightened[role] = straighten
    for role in ("chest", "hip"):
        if role in ri:
            rules[role] = (scale * np.eye(3), joints[ri[role]], np.zeros(3))
    # the head: at most HEAD_GROWTH times the native head's height above its joint (cartoon heads stay big, not giant)
    head = segment("head")
    if len(head):
        above = float(head[:, 1].max() - joints[ri["head"]][1])
        s_head = min(scale, HEAD_GROWTH * float(native_box("head")[1][1]) / max(above, 1e-9))
        rules["head"] = (s_head * np.eye(3), joints[ri["head"]], np.zeros(3))
        sizes["head"] = s_head
    for side in "lr":
        foot, hand = side + "_foot", side + "_hand"
        if foot in ri and len(segment(foot)):
            # a shoe keeps its shape: one scale from its length and depth, then it stands on the native sole
            turn = straightened.get(side + "_shin", np.eye(3))
            P = (segment(foot) - joints[ri[foot]]) @ turn.T
            lo, hi = native_box(foot)
            s_len = float(hi[2] - lo[2]) / max(float(np.ptp(P[:, 2])), 1e-9)
            s_depth = float(-lo[1]) / max(float(-P[:, 1].min()), 1e-9)
            s_foot = float(np.sqrt(s_len * s_depth))
            lift = np.array([0.0, float(lo[1]) - s_foot * float(P[:, 1].min()), 0.0])
            rules[foot] = (s_foot * turn, joints[ri[foot]], lift)
            sizes[foot] = s_foot
        if hand in ri and len(segment(hand)):
            # a glove spans the native hand's reach along its finger axis (HAND_GROWTH times), from the wrist
            turn = straightened.get(side + "_fore", np.eye(3))
            P = (segment(hand) - joints[ri[hand]]) @ turn.T
            axis = 1.0 if side == "l" else -1.0
            lo, hi = native_box(hand)
            reach_native = float(hi[0] if side == "l" else -lo[0])
            reach_donor = float((P[:, 0] * axis).max())
            s_hand = HAND_GROWTH * reach_native / max(reach_donor, 1e-9)
            rules[hand] = (s_hand * turn, joints[ri[hand]], np.zeros(3))
            sizes[hand] = s_hand

    # textures: one per donor primitive image (identity-deduplicated). With free native slots (``slots``: native
    # textures nothing visible uses any more) the donor images go into them at the slot's own size and format, so
    # the costume keeps its texture count and layout; any left over are appended (DXT, at most texture_limit)
    images, tex_index, tex_of_prim = [], {}, []
    for p in prims:
        image = p.get("tex")
        if image is None:
            color = np.array(p.get("color", (255, 255, 255, 255)), np.uint8)
            image = np.tile(color, (8, 8, 1))
            key = ("color",) + tuple(int(c) for c in color)
        else:
            key = id(image)
        if key not in tex_index:
            tex_index[key] = len(images)
            images.append(np.asarray(image))
        tex_of_prim.append(tex_index[key])
    native_count = geometry["chunk"]["tex_count"]
    free = sorted(slots or [], key=lambda s: -W.texture_info(s[1])["size"])
    by_size = sorted(range(len(images)), key=lambda i: -images[i].shape[0] * images[i].shape[1])
    final_index, texture_slots, textures = {}, {}, []
    for rank, i in enumerate(by_size):
        if rank < len(free):
            slot, word = free[rank]
            texture_slots[slot] = (word, W.encode_texture_as(images[i], word))
            final_index[i] = slot
        else:
            final_index[i] = native_count + len(textures)
            textures.append(W.encode_texture(images[i], texture_limit))
    tex_of_prim = [final_index[i] for i in tex_of_prim]

    parts, counts = {}, {}
    for role in ROLES:
        if role not in rules:
            continue
        matrix, origin, lift = rules[role]
        normal_m = np.linalg.inv(matrix).T
        verts, groups, remap_base = [], {}, 0
        for p, vr, tex in zip(prims, vertex_roles, tex_of_prim):
            tris = np.asarray(p["tris"], int).reshape(-1, 3)
            if not len(tris):
                continue
            tri_roles = vr[tris]
            # a triangle belongs to the role most of its corners carry (ties: the first corner's)
            own = np.where((tri_roles[:, 1] == tri_roles[:, 2]) & (tri_roles[:, 1] != tri_roles[:, 0]),
                           tri_roles[:, 1], tri_roles[:, 0])
            mine = tris[own == role]
            if not len(mine):
                continue
            used = np.unique(mine)
            remap = np.full(len(p["pos"]), -1)
            remap[used] = np.arange(len(used)) + remap_base
            pos = (p["pos"][used] - origin) @ matrix.T + lift
            nrm = p["nrm"][used] @ normal_m.T
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
            uv = np.asarray(p["uv"], float)[used]
            block = np.zeros((len(used), 8), np.float32)
            block[:, :3], block[:, 3:6], block[:, 6:8] = pos, nrm, uv
            verts.append(block)
            groups.setdefault(tex, []).append(remap[mine])
            remap_base += len(used)
        if not verts:
            continue
        vertices = np.concatenate(verts)
        if np.linalg.det(rules[role][0]) < 0:
            raise AssertionError(f"{role} fit mirrors its geometry")
        # weld identical vertices (position, normal and UV all equal): extracted donors often carry one vertex per
        # triangle corner, and every byte counts inside the costume's original AFS entry
        vertices, weld = np.unique(vertices, axis=0, return_inverse=True)
        weld = weld.reshape(-1)
        materials = [{"texture": tex, "triangles": weld[np.concatenate(t)]} for tex, t in groups.items()]
        part = {"vertices": vertices, "materials": materials}
        parts[primary[role]] = part
        if lod_copies and roles["lod"].get(role) is not None:
            parts[roles["lod"][role]] = part
        counts[role] = {"obj": primary[role], "vertices": len(vertices),
                        "triangles": int(sum(len(m["triangles"]) for m in materials))}
    report = {"scale": scale, "torso_native": torso_native, "torso_donor": torso_donor, "part_scales": sizes,
              "limb_stretch": stretch, "parts": counts, "textures": len(textures) + len(texture_slots),
              "textures_in_native_slots": sorted(texture_slots),
              "frames": "per-part local fit (native rest rotations not decoded; limb twist by LIMB_FRAMES)"}
    return {"parts": parts, "textures": textures, "texture_slots": texture_slots, "report": report}


def hidden_parts(roles: dict, replaced: set[int], obj_count: int) -> set[int]:
    """Every native part a donor build hides: eyes, wrist halves, hair/accessories, unlisted caps, and primary or
    lower-detail parts the donor had no geometry for. Shadow meshes stay native."""
    keep = set(replaced) | set(roles["shadow"])
    return {k for k in range(obj_count) if k not in keep}


# ------------------------------------------------------------------------------------------------ builds

# fighter family nickname (the <nick>.bin / motion bank) -> costume code prefix, from the owned loadfile.afs
FAMILY_CODES = {"zack": "zac", "tina": "tin", "janlee": "jan", "karate": "kte", "ryu": "ryu", "kasumi": "kas",
                "genfu": "gen", "hika": "hik", "bayman": "bay", "bass": "bas", "ninja": "nin", "leifang": "lei",
                "ayane": "aya", "koryu": "kor", "bosnin": "bni", "suiken": "sui", "gokei": "gok", "chin": "chi",
                "sambo": "sam"}
NO_COSTUME_FAMILIES = ("tengu",)          # Tengu's model is not a costume XPR/CAT pair: reported, never faked


def family_code(name: str) -> str:
    """'zack' / 'zac' / 'Zack' / a display name -> the costume code prefix."""
    from .doa3_inventory import FIGHTER_DISPLAY
    key = (name or "").strip().lower()
    if key in FAMILY_CODES:
        return FAMILY_CODES[key]
    if key in FAMILY_CODES.values():
        return key
    for nick, display in FIGHTER_DISPLAY.items():
        if display.lower() == key and nick in FAMILY_CODES:
            return FAMILY_CODES[nick]
    raise ValueError(f"no DOA3 fighter family {name!r} (one of {', '.join(sorted(FAMILY_CODES))})")


def costume_entries(entries: list[dict], code: str | None = None) -> list[tuple[dict, dict]]:
    """[(xpr entry, cat entry)] for every complete costume (optionally one family) in a read_afs entry list."""
    by_name = {e.get("name"): e for e in entries}
    out = []
    for e in entries:
        n = e.get("name") or ""
        if len(n) == 9 and n.endswith(".xpr") and n[:3].isalpha() and n[3:5].isdigit() and (code is None or n.startswith(code)):
            cat = by_name.get(n[:-4] + ".cat")
            if cat is not None and e.get("size") and cat.get("size"):
                out.append((e, cat))
    return out


def free_texture_slots(geometry: dict, roles: dict, table: dict) -> list[tuple[int, int]]:
    """[(native texture index, format word)] a donor build can repaint: single-level DXT textures no material of a
    part that stays drawn (the shadows) references, directly or as a stage-mode-3 environment texture. ``table``:
    the costume's doa3_cast.mdl_descriptor_table."""
    kept = set(roles["shadow"])
    used = set()
    for k in kept:
        for m in geometry["objects"][k]["materials"]:
            used.add(m["texture"])
            if m["mode"] == 3:
                used.add(m["header"][29])
    out = []
    for index, word in enumerate(d["format"] for d in table["texture_descriptors"]):
        info = W.texture_info(word)
        if index not in used and info["kind"] in ("DXT1", "DXT5") and info["mips"] == 1:
            out.append((index, word))
    return out


def costume_replacements(afs_path, plan: dict[str, dict], progress=lambda *_: None, *,
                         native_slots: bool = True) -> tuple[dict, list]:
    """plan: {costume code prefix: loaded donor rig} -> (AFS replacements {index: bytes}, per-costume reports).
    A costume the writer cannot decode stays native and is reported with its reason."""
    from .doa3_inventory import read_afs
    entries = read_afs(afs_path)["entries"]
    replacements, reports = {}, []
    pairs = [(x, c) for code in plan for x, c in costume_entries(entries, code)]
    with open(afs_path, "rb") as stream:
        def read(entry):
            stream.seek(entry["offset"])
            return stream.read(entry["size"])
        for k, (xe, ce) in enumerate(pairs):
            costume = xe["name"][:-4]
            rig = plan[costume[:3]]
            progress(100 * k / max(len(pairs), 1), f"fitting {costume}")
            try:
                xpr, cat = read(xe), read(ce)
                # the AFS entry keeps its exact size (the game's loader needs the archive's packing), and the
                # costume slot holds 2 MiB: the rewrite must fit the smaller of the two
                blob, res, hide, budget_steps = fit_costume(xpr, cat, rig, native_slots=native_slots,
                                                            budget=min(xe["size"], COSTUME_BUFFER))
            except Exception as error:  # noqa: BLE001 - the costume stays native; the reason is reported
                reports.append({"costume": costume, "status": "native_kept", "reason": repr(error)[:300]})
                continue
            replacements[xe["index"]] = blob
            reports.append({"costume": costume, "status": "replaced", "donor": rig.get("slug") or rig.get("source"),
                            "xpr_bytes": len(blob), "room": xe.get("room"), "hidden_parts": len(hide),
                            "budget_steps": budget_steps,
                            **{k: v for k, v in res["report"].items() if k != "parts"}})
    return replacements, reports


# The game loads a fighter's costume XPR into a fixed 2 MiB slot: the XBE's per-fighter allocation at 0x81cb0
# (MmAllocateContiguousMemoryEx 0x498000 per fighter, 4 fighters) is split 0x200000 costume | 0x18000 <nick>.bin |
# 0x80000 CAT | the rest motions. Native costumes reach 1,978,368 bytes (zac02); a larger one overruns the .bin.
COSTUME_BUFFER = 0x200000


def fit_costume(xpr: bytes, cat: bytes, rig: dict, *, native_slots: bool = True, budget: int = COSTUME_BUFFER):
    """One costume rewrite within ``budget`` bytes (callers pass the original AFS entry size: the archive keeps its
    layout). In order until it fits: the donor part also on the lower-detail copies, then those copies hidden, then
    free native texture slots the donor did not take shrunk to 4x4 stand-ins (largest first), then (the only step
    that costs detail) the donor images appended at 128, then 64 pixels with every free native slot shrunk.
    -> (blob, fit result, hidden OBJs, the budget steps taken)."""
    geo = C.costume_geometry(xpr)
    table = C.mdl_descriptor_table(xpr)
    roles = costume_roles(cat, geo["object_count"])
    slots = free_texture_slots(geo, roles, table) if native_slots else None
    steps = []
    for lod_copies in (True, False):
        res = fit(rig, geo, roles, slots=slots, lod_copies=lod_copies)
        hide = hidden_parts(roles, set(res["parts"]), geo["object_count"])
        # the CAT and the vertex numbering stay as they are; the costume gains the donor's vertices (after the native
        # ones), strips and materials, its images in native texture slots nothing visible uses
        blob = W.encode_costume(xpr, res["parts"], res["textures"], hide=hide, texture_slots=res["texture_slots"])
        if len(blob) <= budget:
            return blob, res, hide, steps
        steps.append(f"{len(blob)} bytes with{'' if lod_copies else 'out'} lower-detail copies")
    spare = sorted((s for s in (slots or []) if s[0] not in res["texture_slots"]),
                   key=lambda s: -W.texture_info(s[1])["size"])
    shrink = set()
    for index, word in spare:
        shrink.add(index)
        blob = W.encode_costume(xpr, res["parts"], res["textures"], hide=hide, texture_slots=res["texture_slots"],
                                shrink_textures=shrink)
        if len(blob) <= budget:
            steps.append(f"{len(shrink)} unused native textures shrunk")
            return blob, res, hide, steps
    if spare:
        steps.append(f"{len(blob)} bytes with {len(shrink)} unused native textures shrunk")
    shrink = {index for index, _word in slots or []}
    for limit in (128, 64):
        res = fit(rig, geo, roles, texture_limit=limit, slots=None, lod_copies=False)
        hide = hidden_parts(roles, set(res["parts"]), geo["object_count"])
        blob = W.encode_costume(xpr, res["parts"], res["textures"], hide=hide, shrink_textures=shrink)
        if len(blob) <= budget:
            steps.append(f"donor images appended at most {limit} px, {len(shrink)} free native textures shrunk")
            return blob, res, hide, steps
        steps.append(f"{len(blob)} bytes with donor images at most {limit} px")
    raise ValueError(f"the rewritten costume is {len(blob)} bytes; the game's costume slot holds {budget}")
