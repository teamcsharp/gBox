"""RE4 (Switch) Mercenaries enemies: which Ganado packs each stage spawns, how a Ganado pack is laid out, and a writer
that puts a library donor (the shared `re5_donor_pool.Donor`) onto every Ganado body of a pack - one donor per body
variant - so a round shows several different characters at once, as the RE5 enemy pools do.

Nothing here has been drawn by the game. Every output is a LayeredFS overlay candidate with a receipt that says
`live_verified: false`, what a round must show and how it fails.

**The roster** (measured, `etc/omake01.esl` and `omake02.esl`, 32-byte entries as the GameCube lists: +1 em id, +2 type,
+8 u16 hp, +0xC three s16 coordinates / 10, +0x18 u16 room): r400 Village = `em16` x 124 (types 3, 4, 11, 12) + `em28`
x 6 (the dogs); r402 Castle = `em1c` x 117; r403 Base = `em1d` x 164; r404 Waterworld = `em20` x 109. Stage names from
`re4_menus.STAGE_ROOMS`. What each type byte selects inside a pack is code in `main` and was not read: that a pack's
body slots are its type variants is inferred from the counts (em16 has four bodies and four types).

**A Ganado pack** (measured on em16, em1c, em1d, em20: 698 slots each) holds several body groups: a body BIN (the
whole figure, headless and handless, 1,600-6,600 vertices, skeleton ids 0..25 the same tree as the player's), its
texture table in the next slot, and its head pieces after that; the hand poses (nine, bones 9/10 and 15/16) and the
gear pieces (vests, hoods, straps) are shared by the bodies; the head parasite (slot 629, its own 26-bone tree) and the
items are separate. `measure_class` reads that layout from the bytes; `KNOWN` pins what it found on the stock packs.

The texture join is the player's: a table image names `imagepackhd/000000XX.pack.fen` entry k. Each donor's atlas is
appended to the pack's archive and the body's table image that only the body samples (image 1 on em16: the shirt;
image 0 is the face, image 2 the skin the hands share) is pointed at it. The atlas goes up opaque and without black
texels (`re4_switch_models.finish_atlas`): the stock body colour maps are opaque and RE4 draws cut-outs through a
separate opacity map, so the donor's plain material draws every texel's colour - the black under the atlas's empty
space and under a source cut-out included (measured 2026-11-10; the `recovery-re4-enemy-pool-01` atlases had it).
"""
from __future__ import annotations

import collections
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import re4_switch_assets as A
from . import re4_switch_models as M

TITLE_ID = M.TITLE_ID
GAME_ID = M.GAME_ID
ESL_ENTRY = 32
#: Mercenaries stage -> (room, enemy set list) - re4_menus.STAGE_ROOMS and re4_navmap's reading of the ESL files.
STAGES = {"Village": (0x400, "omake01.esl"), "Castle": (0x402, "omake01.esl"),
          "Base": (0x403, "omake02.esl"), "Waterworld": (0x404, "omake02.esl")}
#: Role bones for a Ganado body: the player's ids (0..25 are one tree) with the hips on bone 17, the pelvis, which is
#: where the native Ganado skins (and Leon's) bind their hip vertices; bone 0 is the root and carries no native skin.
ENEMY_ROLE_BONES = {**M.ROLE_BONES, "hip": 17}
LEGS = frozenset({18, 19, 20, 21, 22, 23, 24, 25})
ARMS = frozenset(range(5, 17))
HEAD_BONES = frozenset({1, 2, 3, 4} | set(range(26, 34)))
RIGHT_HAND, LEFT_HAND = frozenset({8, 9, 10}), frozenset({14, 15, 16})
BODY_MIN_VERTICES = 500
ATLAS_SIZE = (512, 512)

#: Measured 2026-11-09 on the stock packs (sha256 of each .udas in the receipt): body slots and their tables, head
#: pieces, hands and gear, as `measure_class` finds them. A pack that measures differently is refused by `build_class`
#: unless `trust_measurement` is set, so a wrong RomFS copy cannot be written over silently.
KNOWN = {
    "em16": {"sha256": "5b8026bfe7cdf3769299f1ce00ba2650dd29f85713989ae77902c38e67e3bf97",
             "archive": "00000016.pack.fen", "bodies": {453: 454, 457: 458, 472: 473, 476: 477},
             "heads": (455, 456, 459, 460, 461, 463, 474, 475, 478, 479, 480), "hands": tuple(range(444, 453)),
             "parts": (), "native": {"parasite": 629}, "esl_types": (3, 4, 11, 12),
             "what": "village Ganado: four bodies (1,920-2,139 vertices, 34 bones), their heads behind each, nine "
                     "shared hand poses; slot 629 is the head parasite on its own 26-bone tree and stays native"},
    "em1c": {"sha256": "00bd13eab74a0592de5e9ae17515dc54c1af14ac532dd56a485c5162ca81c768",
             "archive": "0000001c.pack.fen", "bodies": {504: 505, 537: 538, 541: 542, 543: 544},
             "heads": (506, 507, 508, 527, 531, 539), "hands": tuple(range(512, 521)),
             "parts": (510, 511, 521, 523, 525, 529), "native": {"other_skeleton": 640}, "esl_types": (7, 9, 10, 13),
             "what": "castle zealots: two robed monks and two leaders whose meshes reach x 1,677 (38 bones, wide "
                     "sleeves on bones 34/35); hoods, cowls and mitres (510, 511, 529) are hidden; slot 640 is a "
                     "31-bone figure on its own tree (the Garrador, inferred) and stays native"},
    "em1d": {"sha256": "a61632700f2f6006a2097d8dc55b60a3f7610872f0c2bd946552ef5868f1ae63",
             "archive": "0000001d.pack.fen", "bodies": {551: 552, 555: 556, 579: 580},
             "heads": (557, 559, 571, 573, 581, 583, 585, 587), "hands": (394, *range(560, 569)),
             "parts": (569, 575, 577), "native": {"parasite": 629}, "esl_types": (2, 14, 15, 16, 17, 18, 19, 20, 21),
             "what": "base militia: two soldiers (2,086 / 2,138 vertices) and one 6,614-vertex figure whose mesh "
                     "reaches x -1,824 (a weapon in the body mesh - J.J., inferred); vests and helmet pieces hidden"},
    "em20": {"sha256": "6f3ccb89b71ea532ad30965eb815c1e4f27720343675ec2eeef0fdfe9e82d255",
             "archive": "00000020.pack.fen", "bodies": {476: 477, 555: 556, 579: 580},
             "heads": (557, 559, 571, 573, 581, 583, 585, 587), "hands": (394, *range(560, 569)),
             "parts": (569, 575, 577), "native": {"parasite": 629}, "esl_types": (14, 15, 16, 17, 18, 19, 20, 21, 22),
             "what": "waterworld: the two militia bodies of em1d (same slots, same bytes count) and one 4,747-vertex "
                     "40-bone figure (its bones 34-39 lie beyond the shared tree; the donor leaves them unweighted)"},
}
NOT_WRITTEN = {"em28": "the Village dogs: a 19-bone quadruped skeleton (head at y 515, legs 12-17), no biped donor fits"}


class EnemyError(ValueError):
    """The pack is not the measured Ganado layout, or a donor cannot be written onto it."""


# ------------------------------------------------------------------------------------------------- the roster

def read_esl(data: bytes) -> list[dict]:
    """The entries of an enemy set list (32 bytes each; a zero row is unused)."""
    if len(data) % ESL_ENTRY:
        raise EnemyError(f"an ESL is a multiple of {ESL_ENTRY} bytes")
    out = []
    for at in range(0, len(data), ESL_ENTRY):
        flags, em, kind = data[at], data[at + 1], data[at + 2]
        hp = struct.unpack_from("<H", data, at + 8)[0]
        x, y, z = struct.unpack_from("<3h", data, at + 0xC)
        room = struct.unpack_from("<H", data, at + 0x18)[0]
        if em == 0 and hp == 0 and room == 0:
            continue
        out.append({"flags": flags, "em": f"em{em:02x}", "type": kind, "hp": hp, "pos": (x * 10, y * 10, z * 10),
                    "room": room})
    return out


def roster(etc_dir: Path) -> dict:
    """{stage: {room, esl, packs: {emXX: {type: count}}}} from the Mercenaries set lists in `etc/`."""
    etc_dir = Path(etc_dir)
    lists = {}
    out = {}
    for stage, (room, esl) in STAGES.items():
        if esl not in lists:
            lists[esl] = read_esl((etc_dir / esl).read_bytes())
        packs: dict[str, collections.Counter] = {}
        for entry in lists[esl]:
            if entry["room"] == room:
                packs.setdefault(entry["em"], collections.Counter())[entry["type"]] += 1
        out[stage] = {"room": f"{room:04x}", "esl": esl,
                      "packs": {em: dict(sorted(c.items())) for em, c in sorted(packs.items())},
                      "spawns": sum(sum(c.values()) for c in packs.values())}
    return out


# ------------------------------------------------------------------------------------------------- the layout

@dataclass
class ClassLayout:
    """One Ganado pack's slots: bodies -> their tables, the head pieces, hands and gear to hide, what stays."""
    pack: str
    archive: str
    bodies: dict[int, int]                      # body slot -> table slot
    heads: tuple
    hands: tuple
    parts: tuple
    native: dict = field(default_factory=dict)  # name -> slot kept as shipped (parasite, foreign skeletons)
    group_heads: dict = field(default_factory=dict)   # body slot -> the head slots that follow it

    def hidden(self) -> tuple:
        return tuple(sorted({*self.heads, *self.hands, *self.parts}))


def _same_tree(model: A.HdBin, reference: list[tuple[int, int]]) -> bool:
    parents = {ident: parent for ident, parent, _t in model.bones()}
    return all(parents.get(ident) == parent for ident, parent in reference)


#: ids 0..25 of the shared humanoid tree (measured on Leon's body and every Ganado body).
TREE = [(0, 0xFF), (1, 0), (2, 1), (3, 2), (4, 3), (5, 2), (6, 5), (7, 5), (8, 7), (9, 8), (10, 9), (11, 2), (12, 11),
        (13, 11), (14, 13), (15, 14), (16, 15), (17, 0), (18, 17), (19, 18), (20, 19), (21, 20), (22, 17), (23, 22),
        (24, 23), (25, 24)]


def measure_class(udas: bytes, pack: str = "") -> ClassLayout:
    """The body groups, head pieces, hands and gear of a Ganado pack, read from its BIN slots.

    A body lists its skeleton as ids 0..n-1 with the shared tree on 0..25, skins both legs and arms, has at least
    `BODY_MIN_VERTICES` vertices, stands on the floor (y from under 100) and reaches the shoulders (y over 1,450);
    its table is the TPL in the next slot. A head piece skins only head bones (1-4, 26-33), sits above y 1,350 within
    250 of the midline; a hand skins only one hand's bones (8-10 or 14-16) and sits past x 600; gear skins arm, torso
    or pelvis bones without legs and sits inside the torso's box. Whatever fits none of these stays native.
    """
    _pack, dat = A.pack_slots(udas)
    rows = {}
    for index, (ext, payload) in enumerate(dat.slots):
        if ext != "BIN":
            continue
        model = A.HdBin.parse(payload)
        used = {bone for entry in model.weights() for bone, _w in entry}
        pos = model.positions()
        rows[index] = (model, used, pos.min(0), pos.max(0))
    bodies, heads, hands, parts, native = {}, [], [], [], {}
    for index, (model, used, lo, hi) in rows.items():
        ids = [ident for ident, _p, _t in model.bones()]
        full = ids == list(range(model.bone_count)) and model.bone_count >= 26 and _same_tree(model, TREE)
        if full and used & LEGS and used & ARMS and model.vertex_count >= BODY_MIN_VERTICES and lo[1] < 100 \
                and hi[1] > 1450:
            table = index + 1
            if table >= len(dat.slots) or dat.slots[table][0] != "TPL":
                raise EnemyError(f"{pack or 'pack'} slot {index} is a body with no texture table in slot {table}")
            bodies[index] = table
        elif used and (used - {b for b in used if b >= 34}) <= HEAD_BONES and lo[1] > 1350 and abs(lo[0]) <= 250 \
                and abs(hi[0]) <= 250:
            heads.append(index)                      # bones 34+ are a pack's own extras (a hood's tail on em1c)
        elif used and (used <= RIGHT_HAND or used <= LEFT_HAND) and min(abs(lo[0]), abs(hi[0])) >= 600:
            hands.append(index)
        elif used and not used & LEGS and used <= (ARMS | HEAD_BONES | {0, 1, 2, 17}) and lo[1] >= 850 \
                and hi[1] <= 1950 and abs(lo[0]) <= 450 and abs(hi[0]) <= 450 and model.vertex_count < 1300:
            parts.append(index)
        elif full and used & LEGS and used & ARMS and model.vertex_count < BODY_MIN_VERTICES and hi[1] > 1450:
            parts.append(index)                      # a thin full-body piece (a chain, a belt)
        elif model.bone_count >= 26 and used & LEGS and used & ARMS:
            native[f"other_skeleton_{index}" if not _same_tree(model, TREE) else f"figure_{index}"] = index
    if not bodies:
        raise EnemyError(f"{pack or 'pack'}: no Ganado body found (no full-skeleton BIN skinning legs and arms)")
    archive = None
    for body, table in bodies.items():
        images = A.Tpl.parse(dat.slots[table][1]).images
        names = {image.archive() for image in images}
        if len(names) != 1 or (archive is not None and names != {archive}):
            raise EnemyError(f"{pack or 'pack'}: body {body}'s table names several archives {sorted(names)}")
        archive = names.pop()
    group_heads = {}
    ordered = sorted(bodies)
    for k, body in enumerate(ordered):
        stop = ordered[k + 1] if k + 1 < len(ordered) else len(dat.slots)
        group_heads[body] = tuple(h for h in heads if body < h < stop)
    return ClassLayout(pack=pack, archive=archive, bodies=dict(sorted(bodies.items())), heads=tuple(sorted(heads)),
                       hands=tuple(sorted(hands)), parts=tuple(sorted(parts)), native=native, group_heads=group_heads)


def layout_matches(layout: ClassLayout, known: dict) -> list[str]:
    """What differs between a measured layout and the pinned table (empty when they agree)."""
    out = []
    if layout.archive != known["archive"]:
        out.append(f"archive {layout.archive} != {known['archive']}")
    if layout.bodies != dict(known["bodies"]):
        out.append(f"bodies {layout.bodies} != {known['bodies']}")
    for name in ("heads", "hands", "parts"):
        if tuple(sorted(getattr(layout, name))) != tuple(sorted(known[name])):
            out.append(f"{name} {sorted(getattr(layout, name))} != {sorted(known[name])}")
    for slot in known["native"].values():
        if slot not in layout.native.values():
            out.append(f"native slot {slot} not found")
    return out


def body_image(dat: A.Dat, layout: ClassLayout, body: int) -> tuple[int, dict]:
    """The body table's image the donor atlas goes to: the body's most-drawn diffuse image that no native-staying
    model with the same table size samples; else the most-drawn one (and the receipt names who shares it)."""
    model = A.HdBin.parse(dat.slots[body][1])
    table = A.Tpl.parse(dat.slots[layout.bodies[body]][1])
    drawn: collections.Counter = collections.Counter()
    for material in model.materials():
        if material.diffuse != 0xFF:
            drawn[material.diffuse] += material.triangle_count
    if not drawn:
        raise EnemyError(f"body {body} has no diffuse texture")
    replaced = set(layout.bodies) | set(layout.hidden())
    shared: dict[int, list[int]] = {}
    for index, (ext, payload) in enumerate(dat.slots):
        if ext != "BIN" or index in replaced:
            continue
        other = A.HdBin.parse(payload)
        if other.texture_count == len(table.images):
            for texture in {t for m in other.materials() for t in m.textures()}:
                shared.setdefault(texture, []).append(index)
    free = [image for image, _n in drawn.most_common() if image not in shared]
    image = free[0] if free else drawn.most_common(1)[0][0]
    return image, {"body_diffuse_triangles": dict(drawn), "shared_with_native_models": {str(k): v for k, v in shared.items()},
                   "chosen": image, "free_of_native_models": image not in shared}


# ------------------------------------------------------------------------------------------------- the writer

PINNED = object()                                  # build_class(known=PINNED): the KNOWN table of the pack


def build_class(udas: bytes, archive: bytes, donors: list[dict], *, pack: str = "", layout: ClassLayout | None = None,
                known=PINNED, trust_measurement: bool = False, shrink: float = 0.1,
                scales: dict[str, float] = M.SCALES, opaque_atlas: bool = True) -> tuple[bytes, bytes, dict]:
    """One Ganado pack with a donor on each body: (pack bytes, archive bytes, receipt).

    `donors` are donor records (`re4_switch_models.load_donor` / `library_donor`), one per body in slot order; a
    donor may be given once for every body. Each donor's atlas is appended to the pack's archive; the head pieces of
    each group are shrunk toward that donor's head, hands and gear toward their own centre; everything else is byte
    for byte the stock pack. The measured layout must agree with `known` (`KNOWN[pack]` by default; None = no
    pinned table) unless `trust_measurement`. `opaque_atlas` (default) uploads each atlas through
    `re4_switch_models.finish_atlas`; False keeps the bytes `recovery-re4-enemy-pool-01` was built with.
    """
    layout = layout or measure_class(udas, pack)
    known = KNOWN.get(pack) if known is PINNED else known
    if known and not trust_measurement:
        differences = layout_matches(layout, known)
        if differences:
            raise EnemyError(f"{pack}: the pack does not measure as the pinned layout: " + "; ".join(differences))
    bodies = list(layout.bodies)
    if len(donors) == 1 and len(bodies) > 1:
        donors = donors * len(bodies)
    if len(donors) != len(bodies):
        raise EnemyError(f"{pack}: {len(bodies)} bodies need {len(bodies)} donors, {len(donors)} given")
    pack_obj, dat = A.pack_slots(udas)
    images = A.ImagePack.parse(archive)
    if f"{images.pack_id:08x}.pack.fen" != layout.archive:
        raise EnemyError(f"{pack}: the archive is {images.pack_id:08x}, the tables name {layout.archive}")
    before = [M.sha256(payload) for _ext, payload in dat.slots]
    groups, hidden = [], {}
    for body, donor in zip(bodies, donors):
        model = A.HdBin.parse(dat.slots[body][1])
        table = A.Tpl.parse(dat.slots[layout.bodies[body]][1])
        image, choice = body_image(dat, layout, body)
        slug = (donor.get("donor") or {}).get("slug") or donor.get("name") or "donor"
        try:
            built, fit_report, step = M.donor_surface(model, donor, image=image, scales=scales,
                                                      role_bones=ENEMY_ROLE_BONES)
        except (ValueError, A.AssetError) as exc:              # a fit the donor's rig cannot take, named after it
            raise EnemyError(f"{pack} body {body} <- {slug}: {exc}") from exc
        low, high = fit_report.pop("_bounds")
        pixels, finish = M.donor_atlas(donor, opaque=opaque_atlas)
        entry = images.append(A.encode_dds(pixels))
        table.images[image] = A.TplImage(pixels.shape[1] // 4, pixels.shape[0] // 4, 0x0E, images.pack_id, entry,
                                         table.images[image].sampler)
        dat.replace(body, built.build())
        dat.replace(layout.bodies[body], A.Tpl(table.images).slot())
        bones = model.bone_world()
        head_bone = ENEMY_ROLE_BONES["head"]
        head_centre = np.asarray(bones[head_bone], float) + [0.0, 0.25 * (high[1] - bones[head_bone][1]), 0.0]
        for slot in layout.group_heads.get(body, ()):
            if dat.slots[slot][0] == "BIN" and slot not in hidden:
                dat.replace(slot, M.shrink_part(dat.slots[slot][1], shrink, head_centre))
                hidden[slot] = f"head piece of body {body}, toward the donor head"
        check = A.HdBin.parse(dat.slots[body][1])
        groups.append({"body": body, "table": layout.bodies[body], "image": image, "image_choice": choice,
                       "donor": donor.get("donor") or {"name": donor.get("name")},
                       "vertices": check.vertex_count, "triangles": len(donor["faces"]),
                       "weight_sets": check.weight_count, "weight_percent_step": step,
                       "bones_used": sorted({b for w in check.weights() for b, _w in w}),
                       "stock_vertices": model.vertex_count, "bytes": [len(model.build()), len(built.build())],
                       "skeleton_bytes_identical": check.sections["bones"] == model.sections["bones"],
                       "fit": fit_report, "atlas_entry": entry,
                       "atlas": {"width": int(pixels.shape[1]), "height": int(pixels.shape[0]), "format": "DXT5",
                                 "finish": finish}})
    for slot in layout.hidden():
        if slot in hidden or dat.slots[slot][0] != "BIN":
            continue
        dat.replace(slot, M.shrink_part(dat.slots[slot][1], shrink))
        hidden[slot] = ("hand pose" if slot in layout.hands else "head piece" if slot in layout.heads else "gear") \
            + ", toward its own centroid"
    out = A.pack_build(pack_obj, dat)
    _again, again = A.pack_slots(out)
    after = [M.sha256(payload) for _ext, payload in again.slots]
    changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    expected = sorted({*bodies, *layout.bodies.values(), *hidden})
    if changed != expected:
        raise EnemyError(f"{pack}: the rebuilt pack changed slots {changed}, expected {expected}")
    if len(out) != len(A.pack_build(*A.pack_slots(out))):
        raise EnemyError(f"{pack}: the rebuilt pack does not round-trip")
    grown = images.build()
    if A.ImagePack.parse(grown).build() != grown:
        raise EnemyError(f"{pack}: the grown archive does not round-trip")
    receipt = {"operation": "library donors on every Ganado body of the pack", "pack": pack, "archive": layout.archive,
               "layout": {"bodies": {str(k): v for k, v in layout.bodies.items()}, "heads": list(layout.heads),
                          "hands": list(layout.hands), "parts": list(layout.parts),
                          "native": {k: v for k, v in layout.native.items()}},
               "role_bones": dict(ENEMY_ROLE_BONES), "groups": groups,
               "parts_shrunk": {str(k): v for k, v in sorted(hidden.items())}, "shrink": shrink,
               "slots_replaced": changed, "other_slots_byte_identical": len(after) - len(changed),
               "archive_entries": [len(A.ImagePack.parse(archive).entries), len(images.entries)],
               "live_verified": False}
    return out, grown, receipt


EXPECTATION = {
    "what_must_be_seen": [
        "Village round: the Ganados are four different library characters at once (one per body variant), each a "
        "whole figure about 1.8 m tall with Ganado limb lengths, no Ganado head, hands or clothes on them; the dogs "
        "are stock",
        "a character keeps its look while it walks, attacks, is shot and falls (the skeleton and animations are the "
        "pack's own)",
        "a parasite that bursts from a head is the stock parasite, on top of the donor's head area",
        "Castle, Base and Waterworld rounds: the same, with four, three and three characters",
    ],
    "failure_signs": [
        "stock Ganados: the overlay was not applied, or the round draws bodies from another pack than the ESL names",
        "a figure that can be hit but is not drawn: the composed body is refused (the rebuilt container loaded)",
        "a donor in a stock cloth texture: the appended archive entry is not read or the table image is another "
        "model's",
        "stock heads, hands or vests floating on a donor: a shared piece drawn from a table other than measured; the "
        "parts_shrunk list of the receipt names the slots that were hidden",
        "a hang when the stage loads: the rebuilt container (bisect by removing one pack file; em28 is never written)",
        "all four Village Ganados look the same: the type byte does not select the body slots as inferred",
    ],
}


def enemy_pool(em_dir: Path, imagepack_dir: Path, library: Path, donors: list, seed, out: Path, *,
               classes: tuple = ("em16", "em1c", "em1d", "em20"), history: list | tuple = (), avoid_last: int = 3,
               games: list[str] | None = None, exclude: dict[str, str] | None = None, atlas_size=ATLAS_SIZE,
               max_vertices: int = 6000, name: str | None = None, etc_dir: Path | None = None,
               assignment: dict[str, str] | None = None, opaque_atlas: bool = True,
               rejects: dict[str, str] | None = None) -> dict:
    """Deal library donors over every body of every Mercenaries Ganado class from a seed (`re5_donor_pool.plan`)
    and write one overlay tree: `romfs/bio4/em/emXX.udas` and `romfs/bio4/imagepackhd/000000XX.pack.fen` per
    class, plus `receipt.json`. Slots are `emXX:body` (14 with the four classes), so 14 distinct donors.

    A donor a body refuses is set aside and the plan is dealt again from the same seed, as the RE5 pools do.
    `assignment` pins the deal ({`emXX:body`: slug}, an earlier receipt's): nothing is dealt and a refusal is an
    error, so a pool is rebuilt with the same donors (e.g. after a writer fix). `rejects` ({slug: reason}, default:
    RE4's entries of gbox.donor_rejects) are never dealt; a pinned assignment still rebuilds them.
    """
    from . import donor_rejects, re5_donor_pool

    em_dir, imagepack_dir, library, out = Path(em_dir), Path(imagepack_dir), Path(library), Path(out)
    if (out / "receipt.json").exists():
        raise EnemyError(f"{out} already holds an overlay; candidates are never overwritten")
    packs = {}
    for pack in classes:
        udas = (em_dir / f"{pack}.udas").read_bytes()
        layout = measure_class(udas, pack)
        if pack in KNOWN:
            differences = layout_matches(layout, KNOWN[pack])
            if differences:
                raise EnemyError(f"{pack}: " + "; ".join(differences))
        packs[pack] = (udas, layout, (imagepack_dir / layout.archive).read_bytes())
    slots = [f"{pack}:{body}" for pack, (_u, layout, _a) in packs.items() for body in layout.bodies]
    pinned = dict(assignment) if assignment else None
    listed = donor_rejects.rejected("re4") if rejects is None else dict(rejects)
    leave_out = dict(exclude or {}) | ({} if pinned else listed)
    pool = [d for d in donors if d.slug not in leave_out]
    refused: dict[str, str] = dict(leave_out)
    records: dict[str, dict] = {}
    if pinned:
        known_slugs = {d.slug for d in pool}
        wrong = sorted(set(pinned) ^ set(slots)) + [s for s in pinned.values() if s not in known_slugs]
        if wrong:
            raise EnemyError(f"the pinned assignment does not fit these classes and this survey: {wrong}")
    while True:
        assignment = pinned or re5_donor_pool.plan(seed, slots, pool, history=history, avoid_last=avoid_last,
                                                   games=games, exclude=set(refused))
        failed = None
        for slot, slug in assignment.items():
            if slug in records:
                continue
            donor = next(d for d in pool if d.slug == slug)
            try:
                record = M.library_donor(library, slug, roles=donor.role_names(), atlas_size=atlas_size,
                                         sha256_expected=donor.sha256)
                if len(record["vertices"]) > max_vertices:
                    raise M.ModelError(f"{len(record['vertices'])} vertices, above the pool limit {max_vertices}")
                record["donor"] |= {"platform": donor.platform, "provenance": donor.provenance}
                records[slug] = record
            except (M.ModelError, A.AssetError, ValueError, OSError) as exc:
                failed = (slug, f"{slot} <- {slug}: {exc}")
                break
        if failed is None:
            files, sources, rows = {}, {}, {}
            for pack, (udas, layout, archive) in packs.items():
                chosen = [records[assignment[f"{pack}:{body}"]] for body in layout.bodies]
                try:
                    pack_out, grown, receipt = build_class(udas, archive, chosen, pack=pack, layout=layout,
                                                           opaque_atlas=opaque_atlas)
                except (M.ModelError, A.AssetError, EnemyError) as exc:
                    text = str(exc)
                    culprit = next((s for s in (r["donor"]["slug"] for r in chosen) if s in text), None)
                    if culprit is None:
                        raise
                    failed = (culprit, f"{pack} <- {culprit}: {exc}")
                    break
                files[f"{M.PACK_DIR}/{pack}.udas"] = pack_out
                files[f"{M.IMAGE_DIR}/{layout.archive}"] = grown
                sources[f"{M.PACK_DIR}/{pack}.udas"] = udas
                sources[f"{M.IMAGE_DIR}/{layout.archive}"] = archive
                rows[pack] = receipt | {"what": KNOWN.get(pack, {}).get("what"),
                                        "esl_types": list(KNOWN.get(pack, {}).get("esl_types", ())),
                                        "pack_sha256": M.sha256(pack_out), "archive_sha256": M.sha256(grown)}
        if failed is None:
            break
        slug, reason = failed
        if pinned or slug in refused:
            raise EnemyError(reason)
        refused[slug] = reason
        print(f"set aside: {reason}", flush=True)
    stages = roster(etc_dir) if etc_dir else {}
    receipt = {"recipe": "re4_switch_enemies.enemy_pool", "name": name or out.name, "game_id": GAME_ID,
               "plan": {"seed": seed, "slots": slots, "games": games, "avoid_last": avoid_last,
                        "history": [dict(row) if isinstance(row, dict) else list(row) for row in history],
                        "pool_size": len(pool), "max_vertices": max_vertices, "atlas_size": list(atlas_size),
                        "set_aside": dict(refused), "pinned_assignment": bool(pinned), "opaque_atlas": opaque_atlas,
                        "rule": "re5_donor_pool.plan: a donor at most once, recently used donors last, franchises in turn"},
               "assignment": assignment,
               "donors": {slot: {k: records[slug]["donor"][k] for k in ("slug", "name", "game", "franchise", "sha256")}
                          for slot, slug in assignment.items()},
               "classes": rows, "not_written": NOT_WRITTEN, "stages": stages,
               "role_bones": {"hip": ENEMY_ROLE_BONES["hip"],
                              "note": "hips on bone 17 (pelvis), where the native Ganado skins bind them"},
               **EXPECTATION, "acceptance": "experimental; offline structural checks only"}
    return M.write_overlay(out, files, receipt, sources)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="RE4 Switch Mercenaries enemies: roster, pack layout, donor overlays (offline)")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("roster", help="which packs each Mercenaries stage spawns, from etc/omake0*.esl")
    r.add_argument("--etc", type=Path, required=True)
    m = sub.add_parser("measure", help="the body groups, heads, hands and gear of a Ganado pack")
    m.add_argument("--em", type=Path, required=True)
    m.add_argument("packs", nargs="+")
    p = sub.add_parser("pool", help="deal surveyed library donors over every Ganado body of the Mercenaries classes")
    p.add_argument("--em", type=Path, required=True)
    p.add_argument("--imagepack", type=Path, required=True)
    p.add_argument("--etc", type=Path, help="etc/ folder, to record the stage roster in the receipt")
    p.add_argument("--library", type=Path, required=True)
    p.add_argument("--survey", type=Path, required=True, help="a re5_donor_pool.survey JSON of that library")
    p.add_argument("--seed", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--classes", default="em16,em1c,em1d,em20")
    p.add_argument("--history", default="")
    p.add_argument("--avoid-last", type=int, default=3)
    p.add_argument("--games", default="")
    p.add_argument("--exclude", default="")
    p.add_argument("--max-vertices", type=int, default=6000)
    p.add_argument("--assignment", type=Path, help="an earlier pool's receipt.json: rebuild with its donors (no deal)")
    p.add_argument("--atlas-as-built", action="store_true",
                   help="upload each atlas as mtf_materials built it (the pools before 2026-11-10)")
    args = parser.parse_args(argv)
    if args.command == "roster":
        print(json.dumps(roster(args.etc), indent=2))
        return 0
    if args.command == "measure":
        for pack in args.packs:
            data = (args.em / f"{pack}.udas").read_bytes()
            layout = measure_class(data, pack)
            print(json.dumps({"pack": pack, "sha256": M.sha256(data), "archive": layout.archive,
                              "bodies": {str(k): v for k, v in layout.bodies.items()}, "heads": list(layout.heads),
                              "hands": list(layout.hands), "parts": list(layout.parts), "native": layout.native,
                              "group_heads": {str(k): list(v) for k, v in layout.group_heads.items()},
                              "agrees_with_KNOWN": layout_matches(layout, KNOWN[pack]) if pack in KNOWN else None}))
        return 0
    from . import re5_donor_pool
    donors = re5_donor_pool.donors_of(json.loads(args.survey.read_text(encoding="utf-8")))
    history = [json.loads(Path(name).read_text(encoding="utf-8"))["assignment"] for name in args.history.split(",") if name]
    result = enemy_pool(args.em, args.imagepack, args.library, donors, args.seed, args.out,
                        classes=tuple(c for c in args.classes.split(",") if c), history=history,
                        avoid_last=args.avoid_last, games=[g for g in args.games.split(",") if g] or None,
                        exclude={s: "left out by the caller" for s in args.exclude.split(",") if s},
                        max_vertices=args.max_vertices, etc_dir=args.etc,
                        assignment=json.loads(args.assignment.read_text(encoding="utf-8"))["assignment"]
                        if args.assignment else None, opaque_atlas=not args.atlas_as_built)
    print(json.dumps({"out": str(args.out), "assignment": result["assignment"], "files": result["files"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
