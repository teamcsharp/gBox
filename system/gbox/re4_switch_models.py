"""RE4 (Switch) Mercenaries player models: who is in which pack, and two offline writers for a pack overlay.

Nothing in this module has been drawn by the game. It builds LayeredFS overlay files (`romfs/bio4/em/plXX.udas`,
`romfs/bio4/imagepackhd/XXXXXXXX.pack.fen`) and a receipt that says what was replaced and `live_verified: false`.

A player pack is a DAT whose slots mean the same thing in every playable humanoid pack (measured on pl06, pl08,
pl0a, pl0b, pl0d - see docs/research/re4-switch-model-replacement.md): 0 body, 1 the body's texture table, 2 head,
3 the head's texture table, 4 face, 5 hair, 8 a one-bone far head, 14-21 hand poses, 22 effects, 23+ animations.
The parts are skinned to one skeleton by bone id, so a body can only be exchanged for one that keeps the ids the
other parts and the animations use.

* `native_body_swap` puts another pack's body in a pack's body slot, bytes untouched, and rebuilds the container.
* `author_body` writes a donor mesh (a skinned .glb) onto the pack's own skeleton in its own bind pose.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import re4_switch_assets as A

TITLE_ID = "010099A00BC1E000"
GAME_ID = "270a15eb98dab4d7"             # the catalog entry MercMode uses (gbox.re_switch.RE4_GAME_ID)
PACK_DIR = "bio4/em"
IMAGE_DIR = "bio4/imagepackhd"

#: The Mercenaries cast. "art" = the pack's own textures show the character (decoded and looked at), "layout" = the
#: pack has the playable 133+-slot layout; only Leon's pack was ever identified in a running round (an earlier
#: session's scale test), and Ada's is the weakest entry: three packs hold a playable Ada.
CAST = {
    "leon": {"pack": "pl08", "evidence": "art + layout; a scale edit of this pack changed the player in a live round "
                                         "(earlier session, 2026-11-08)"},
    "hunk": {"pack": "pl06", "evidence": "art (gas mask, black fatigues) + layout; same 119-bone count and the same "
                                         "animated bone set as Leon"},
    "krauser": {"pack": "pl0a", "evidence": "art (camouflage, war paint, blade arm) + layout"},
    "wesker": {"pack": "pl0d", "evidence": "art (sunglasses, black leather) + layout"},
    "ada": {"pack": "pl0b", "evidence": "inferred: art (plain red dress) + layout, but pl0c (tactical) and pl16 "
                                        "(butterfly dress) have the same layout - not told apart offline"},
}
#: Select Player order (re4_menus.PLAYERS) -> cast key: the roster the MercMode queue names its characters by.
ROSTER = {"Leon": "leon", "Ada": "ada", "Krauser": "krauser", "HUNK": "hunk", "Wesker": "wesker"}

BODY, BODY_TPL, HEAD, HEAD_TPL, FACE, HAIR, FAR_HEAD = 0, 1, 2, 3, 4, 5, 8
HANDS = tuple(range(14, 22))


@dataclass(frozen=True)
class PackLayout:
    """Which slots of one playable pack make up the character (measured 2026-11-09 on the stock packs: each BIN's
    skin bones, bounding box and texture indices - docs/research/re4-parity.md).

    `body` takes the donor; `image` is the body table's image the donor atlas goes to (one the body samples and no
    other model bound to that table does); `heads` are shrunk toward the donor's head, `hands` and `parts` (other
    pieces of the native body: Krauser's torso, Wesker's legs, straps) toward their own centre. Slots named by no
    field stay byte for byte native (knife, sheath, items, animations, effects).
    """
    pack: str
    body: int = BODY
    table: int = BODY_TPL
    image: int = 5
    heads: tuple = (HEAD, FACE, HAIR, FAR_HEAD)
    hands: tuple = HANDS
    parts: tuple = ()
    note: str = ""

    def hidden(self) -> tuple:
        return tuple(sorted({*self.heads, *self.hands, *self.parts}))


LAYOUTS = {
    # Leon: the layout the four published candidates were built with (sonic-on-leon-v1 etc.) - unchanged, so they
    # still reproduce. Slot 7 (a 98-vertex collar piece on bone 3) stays native here for that reason.
    "pl08": PackLayout("pl08", image=5, note="one body slot (6,591 vertices, headless and handless); image 5 is the "
                                               "shirt, sampled by the body only"),
    "pl06": PackLayout("pl06", image=0, heads=(2, 7, 8), hands=(14, 16, 17),
                       note="HUNK: one body slot (9,849 vertices); the gas mask is slot 2, slot 7 a collar; three hand "
                            "poses; slots 4, 5, 6, 9-12, 15, 18-21 are empty in this pack"),
    "pl0a": PackLayout("pl0a", image=1, heads=(2, 7, 8), hands=(14, 15, 16, 17), parts=(4, 6, 10, 20),
                       note="Krauser: slot 0 is the LEGS (bones 17-25 only, y -1..1240); the torso and arms are slot "
                            "4, slot 6 the torso with the blade arm (x to 1949), slot 10 a thigh piece, slot 20 a "
                            "strap over the left shoulder - all hidden under the donor; slot 9 (the knife on bone 10) "
                            "stays"),
    "pl0d": PackLayout("pl0d", image=0, heads=(2, 4, 7, 8), hands=(14, 16, 18, 20), parts=(6,),
                       note="Wesker: slot 0 is the upper body and coat (y 888..1647), slot 6 the legs (bones 17-25); "
                            "slot 4 the face, slot 7 the glasses; four hand poses"),
    "pl0b": PackLayout("pl0b", image=4, heads=(2, 4, 5, 7, 8), hands=(13, 14, 15, 16, 17, 18, 19, 21, 147),
                       note="Ada (plain red dress): one body slot (10,293 vertices, 81 bones; bind joints up to 104 "
                            "units from Leon's); slot 5 is the hair (19 bones), slot 10 a wrist item on bone 10 "
                            "(kept); nine hand poses, one of them slot 147"),
}

#: Leon-family skeleton ids for the body roles (`gbox.characters.tree_roles` vocabulary). x < 0 is the right side:
#: the model faces +z (toes at +z), y is up.
ROLE_BONES = {"hip": 0, "chest": 2, "head": 4,
              "r_upper": 7, "r_fore": 8, "r_hand": 10, "l_upper": 13, "l_fore": 14, "l_hand": 16,
              "r_thigh": 18, "r_shin": 19, "r_foot": 20, "l_thigh": 22, "l_shin": 23, "l_foot": 24}
SEGMENTS = {"hip": "chest", "chest": "head", "r_upper": "r_fore", "r_fore": "r_hand", "l_upper": "l_fore",
            "l_fore": "l_hand", "r_thigh": "r_shin", "r_shin": "r_foot", "l_thigh": "l_shin", "l_shin": "l_foot"}
#: Cross-section scale (model units per donor unit) by role family; along a limb the length is the skeleton's.
SCALES = {"torso": 150.0, "head": 80.0, "limb": 100.0, "end": 100.0}
ROLE_FAMILY = {"hip": "torso", "chest": "torso", "head": "head", "r_hand": "end", "l_hand": "end",
               "r_foot": "end", "l_foot": "end"}
#: Ends that keep the donor's own orientation (a head stays level, a sole stays flat); a hand follows its forearm.
UPRIGHT = ("head", "r_foot", "l_foot")


class ModelError(ValueError):
    """The pack is not the measured player layout, or the donor cannot be written onto it."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _body(dat: A.Dat, layout: "PackLayout | None" = None) -> tuple[A.HdBin, A.Tpl]:
    body_slot, table_slot = (layout.body, layout.table) if layout else (BODY, BODY_TPL)
    if len(dat.slots) < 22 or dat.slots[body_slot][0] != "BIN" or dat.slots[table_slot][0] != "TPL":
        raise ModelError("not a playable player pack: slot 0 is not a body BIN followed by its TPL")
    body = A.HdBin.parse(dat.slots[body_slot][1])
    if [ident for ident, _p, _t in body.bones()] != list(range(body.bone_count)):
        raise ModelError("the body does not list its skeleton as ids 0..n-1")
    return body, A.Tpl.parse(dat.slots[table_slot][1])


def skeleton_report(target: A.HdBin, donor: A.HdBin) -> dict:
    """Where a donor body's skeleton stops being the target's: the first id whose parent differs, and how far the
    bind joints before it have moved. Animations and the pack's other parts address bones by these ids."""
    a, b = target.bones(), donor.bones()
    shared = min(len(a), len(b))
    first = next((i for i in range(shared) if a[i][1] != b[i][1]), shared)
    shifts = [float(np.linalg.norm(np.subtract(a[i][2], b[i][2]))) for i in range(first)]
    later = [i for i in range(first, shared)
             if a[i][1] != b[i][1] or float(np.linalg.norm(np.subtract(a[i][2], b[i][2]))) > 1.0]
    return {"target_bones": len(a), "donor_bones": len(b), "first_id_with_another_parent": first,
            "largest_bind_shift_before_it": round(max(shifts, default=0.0), 3),
            "ids_that_differ_after_it": len(later), "identical": first == shared == len(a) == len(b) and not later
            and max(shifts, default=0.0) <= 1e-3}


def recompose(model: A.HdBin) -> A.HdBin:
    """The same surface written again by `HdBin.with_geometry`: every strip and quad becomes a triangle list.

    The result draws the same triangles with the same weights and materials but shares no mesh section with the
    original - which makes it the test of the writer itself, apart from any donor.
    """
    materials = model.materials()
    order, runs = A.soup(A.triangles(materials))
    normals = model.normals().astype(np.float64)[order]
    normals[np.linalg.norm(normals, axis=1) < 1e-12] = (0.0, 1.0, 0.0)
    return model.with_geometry(positions=model.positions()[order], normals=normals, uvs=model.uvs()[order],
                               colors=model.colors()[order], weight_sets=model.weights(),
                               weight_index=model.weight_index()[order],
                               materials=[A.Material(m.header, r) for m, r in zip(materials, runs)])


def native_body_swap(target: bytes, donor: bytes, *, rewrite: bool = False) -> tuple[bytes, dict]:
    """`target` pack with `donor` pack's body in slot 0; every other slot is the target's.

    The donor BIN goes in byte for byte (or, with `rewrite`, re-encoded by `recompose`). Its texture table replaces
    slot 1, padded with copies of its first image up to the target table's image count, so any other target model
    bound to slot 1 still finds every index it asks for (it gets the donor's art there). The pixels stay where
    they are: the table names the donor's archive.
    """
    pack, dat = A.pack_slots(target)
    _donor_pack, donor_dat = A.pack_slots(donor)
    body, table = _body(dat)
    donor_body, donor_table = _body(donor_dat)
    images = list(donor_table.images)
    images += [images[0]] * max(0, len(table.images) - len(images))
    before = [sha256(payload) for _ext, payload in dat.slots]
    written = recompose(donor_body) if rewrite else donor_body
    payload = written.build()
    dat.replace(BODY, payload)
    dat.replace(BODY_TPL, A.Tpl(images).slot())
    out = A.pack_build(pack, dat)
    _again_pack, again = A.pack_slots(out)
    after = [sha256(slot) for _ext, slot in again.slots]
    changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    if not set(changed) <= {BODY, BODY_TPL} or again.slots[BODY][1] != payload or (
            not rewrite and payload != donor_dat.slots[BODY][1]):
        raise ModelError(f"the rebuilt pack changed slots {changed}, expected the body and its table only")
    used = sorted({i for m in donor_body.materials() for i in m.textures()})
    triangle_count = sum(m.triangle_count for m in donor_body.materials())
    if sum(m.triangle_count for m in written.materials()) != triangle_count:
        raise ModelError("the rewritten body does not draw the donor's triangle count")
    return out, {"operation": "native body swap" + (", body rewritten by the composer" if rewrite else ""),
                 "slots_replaced": [BODY, BODY_TPL], "other_slots_byte_identical": len(after) - 2,
                 "body": {"stock_bytes": len(body.build()), "bytes": len(payload),
                          "donor_bin_bytes_kept": not rewrite, "vertices": written.vertex_count,
                          "donor_vertices": donor_body.vertex_count, "triangles": triangle_count,
                          "bones": donor_body.bone_count, "materials": donor_body.material_count,
                          "texture_indices_used": used, "donor_bin_sha256": sha256(donor_dat.slots[BODY][1])},
                 "texture_table": {"images": len(images), "donor_images": len(donor_table.images),
                                   "archives": sorted({i.archive() for i in images})},
                 "skeleton": skeleton_report(body, donor_body), "live_verified": False}


#: A texel at or above this alpha is drawn colour in the donor's own texture; below it the source meant a cut-out.
OPAQUE_ALPHA = 128


def _fill_from(rgb: np.ndarray, known: np.ndarray) -> np.ndarray:
    """`rgb` with every texel outside `known` replaced by a blend of the nearest known texels (push-pull: a known-only
    average down a 2x pyramid, then each unknown texel takes the finest level that covered it)."""
    if known.all() or not known.any():
        return rgb
    h, w = known.shape
    ph, pw = h + h % 2, w + w % 2
    weight = np.zeros((ph, pw), np.float64)
    weight[:h, :w] = known
    colour = np.zeros((ph, pw, rgb.shape[2]), np.float64)
    colour[:h, :w] = rgb * known[..., None]
    total = weight.reshape(ph // 2, 2, pw // 2, 2).sum((1, 3))
    summed = colour.reshape(ph // 2, 2, pw // 2, 2, -1).sum((1, 3))
    coarse_known = total > 0
    coarse = np.where(coarse_known[..., None], summed / np.maximum(total, 1e-12)[..., None], 0.0)
    coarse = _fill_from(coarse, coarse_known)
    up = np.repeat(np.repeat(coarse, 2, 0), 2, 1)[:h, :w]
    return np.where(known[..., None], rgb, up)


def finish_atlas(atlas: np.ndarray, uvs: np.ndarray | None = None, *, threshold: int = OPAQUE_ALPHA
                 ) -> tuple[np.ndarray, dict]:
    """A donor atlas as an RE4 colour map: opaque, with no black anywhere. Returns (RGBA uint8, report).

    Why (measured 2026-11-10 on the stock Ganado and player packs): every stock body colour map is opaque (alpha
    238-255 on all 48 body images of em16/em1c/em1d/em20), and an RE4 material draws a cut-out through a separate
    opacity map (header byte 14, a GX I4 image, material flag 4 or 7 - em16 461/612/629, em1c 523/531/545/626, pl08
    10), never through the colour map's alpha. The donor material is written plain (flag 0, no opacity map), so the
    game draws the colour of every texel the donor samples. `mtf_materials.build_atlas` leaves its empty space and the
    texels under a source cut-out RGBA (0, 0, 0, 0): black. The remap-all donors sampled such texels at up to 32% of
    their vertices (Golden Kane pistol 1 on em1d body 579: hair and brow cards), and 53-97% of each atlas was empty, so
    the box-filtered mips darken every chart edge with distance. Here every texel under `threshold` takes the colour
    of the nearest opaque texels (`_fill_from`), and alpha is 255 everywhere, as on the stock maps. A cut-out is then
    drawn as a solid card in the colour around it instead of a black one; true cut-outs need the opacity-map route.
    """
    pixels = np.asarray(atlas, np.uint8)
    if pixels.ndim != 3 or pixels.shape[2] != 4:
        raise ModelError("finish_atlas takes an RGBA atlas")
    alpha = pixels[..., 3]
    known = alpha >= threshold
    report = {"rule": "colour bled from the nearest opaque texels into every texel under alpha "
                      f"{threshold}; alpha 255 everywhere (the stock body maps are opaque; RE4 cut-outs use a "
                      "separate opacity map)",
              "texels": int(alpha.size), "texels_filled": int((~known).sum()),
              "filled_share": round(float((~known).mean()), 4)}
    if uvs is not None and len(uvs):
        h, w = alpha.shape
        uv = np.asarray(uvs, np.float64)
        xs = np.clip((uv[:, 0] % 1.0 * w).astype(int), 0, w - 1)
        ys = np.clip((uv[:, 1] % 1.0 * h).astype(int), 0, h - 1)
        report["vertices_on_cut_out_texels"] = round(float((alpha[ys, xs] < threshold).mean()), 4)
    if known.any():
        rgb = _fill_from(pixels[..., :3].astype(np.float64), known)
    else:                                             # nothing opaque: keep the colours, or a mid grey if all black
        rgb = pixels[..., :3].astype(np.float64) if pixels[..., :3].any() else np.full(pixels.shape[:2] + (3,), 128.0)
    out = np.empty_like(pixels)
    out[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    out[..., 3] = 255
    return out, report


def donor_atlas(donor: dict, *, opaque: bool) -> tuple[np.ndarray, dict | None]:
    """The pixels a writer uploads for `donor`: its atlas as built (`opaque` False, the published candidates' bytes)
    or finished for RE4 (`finish_atlas`)."""
    pixels = np.asarray(donor["atlas"], np.uint8)
    if not opaque:
        return pixels, None
    uvs = np.asarray([v["uv"] for v in donor["vertices"]], float) if donor.get("vertices") else None
    return finish_atlas(pixels, uvs)


def entry_uvs(packs: dict[str, bytes], pack_id: int) -> dict[int, np.ndarray]:
    """{archive entry: the UVs of every model that draws it}, over `packs` ({name: .udas bytes}): a BIN draws the
    entries its diffuse bytes pick from the TPL in the next slot (the binding measured on the player and Ganado
    packs)."""
    out: dict[int, list] = {}
    for udas in packs.values():
        _pack, dat = A.pack_slots(udas)
        for index, (ext, payload) in enumerate(dat.slots[:-1]):
            if ext != "BIN" or dat.slots[index + 1][0] != "TPL":
                continue
            model, table = A.HdBin.parse(payload), A.Tpl.parse(dat.slots[index + 1][1])
            uvs = model.uvs()
            start = 0
            for material in model.materials():
                count = material.vertex_count
                k = material.diffuse
                if k != 0xFF and k < len(table.images) and table.images[k].pack_id == pack_id:
                    out.setdefault(table.images[k].index, []).append(uvs[start:start + count])
                start += count
    return {entry: np.concatenate(parts) for entry, parts in out.items()}


def refinish_archive(archive: bytes, stock: bytes, packs: dict[str, bytes] | None = None) -> tuple[bytes, dict]:
    """`archive` (a pool's grown `.pack.fen`) with every entry it appended to `stock` - the donor atlases - put
    through `finish_atlas`: decoded, made opaque without black texels, encoded again at the same size, format and mip
    count. The stock entries (wrapper and DDS; `ImagePack.append` re-pads the last one) stay byte for byte, and
    every entry keeps its size and wrapper, so the packs built against the archive (their
    tables, the donor UVs) still fit it. `packs` (the build's .udas files) name the models that draw each entry, for
    the receipt. Returns (bytes, report)."""
    from PIL import Image
    import io

    grown, base = A.ImagePack.parse(archive), A.ImagePack.parse(stock)
    if grown.pack_id != base.pack_id or len(grown.entries) < len(base.entries) \
            or any(a[:2] != b[:2] for a, b in zip(base.entries, grown.entries)):
        raise ModelError("the archive is not the stock archive with entries appended")
    uvs = entry_uvs(packs or {}, grown.pack_id)
    rows = []
    for index in range(len(base.entries), len(grown.entries)):
        wrapper, dds, tail = grown.entries[index]
        info = A.dds_info(dds)
        if info["fourcc"] not in A.DXT_BLOCK_BYTES:
            raise ModelError(f"entry {index} is {info['fourcc']}, not a DXT the writers append")
        pixels = np.asarray(Image.open(io.BytesIO(dds)).convert("RGBA"), np.uint8)
        finished, report = finish_atlas(pixels, uvs.get(index))
        out = A.encode_dds(finished, mipmaps=max(1, info["mipmaps"]), fourcc=info["fourcc"])
        if len(out) != len(dds):
            raise ModelError(f"entry {index}: re-encoded {len(out)} bytes, the entry holds {len(dds)}")
        grown.entries[index] = (wrapper, out, tail)
        rows.append({"entry": index, "width": info["width"], "height": info["height"], "fourcc": info["fourcc"],
                     "mips": info["mipmaps"], "drawn_by_vertices": int(len(uvs[index])) if index in uvs else 0,
                     "before_sha256": sha256(dds), "after_sha256": sha256(out), **report})
    written = grown.build()
    again = A.ImagePack.parse(written)
    if again.build() != written or any(a[:2] != b[:2] for a, b in zip(base.entries, again.entries)):
        raise ModelError("the refinished archive does not round-trip with its stock entries intact")
    return written, {"archive": f"{grown.pack_id:08x}.pack.fen", "stock_entries": len(base.entries),
                     "entries": len(again.entries), "refinished": rows,
                     "source_sha256": sha256(archive), "sha256": sha256(written), "bytes": len(written)}


def shrink_part(payload: bytes, factor: float, centre=None) -> bytes:
    """A part model with its vertices pulled toward `centre` (default: its own centroid); topology untouched.

    A same-topology position edit is the one model change the earlier live rounds saw drawn, which is why a part
    is hidden this way instead of being emptied or rebuilt.
    """
    model = A.HdBin.parse(payload)
    points = model.positions().astype(np.float64)
    pivot = points.mean(0) if centre is None else np.asarray(centre, float)
    out = model.with_positions(pivot + (points - pivot) * factor).build()
    if len(out) != len(payload):
        raise ModelError("a position edit changed the slot size")
    return out


# ------------------------------------------------------------------------------------------------- donor bodies

def load_donor(source: Path, roles: dict[str, str] | None = None, *, atlas_size=(1024, 1024)) -> dict:
    """A skinned .glb as the donor record `author_body` takes, through the loaders the RE5/RE6 writers use.

    `vertices` carry position, normal, atlas uv and the glTF node ids that drive them; `joints` are node rest
    positions, `parents` the node tree, `role_nodes` the body roles (given as joint names in `roles`, or derived
    from the joint tree by `characters.tree_roles` when the rig has no names). +y up, facing +z, left at +x.
    """
    from . import characters, mtf_materials

    vertices, faces, atlas, report = mtf_materials.source_mesh(Path(source), atlas_size=tuple(atlas_size),
                                                              strict_samplers="in_range")
    gltf, _acc, _image, world = characters._load(Path(source))
    names = roles or characters.tree_roles(Path(source))
    by_name = {node.get("name"): index for index, node in enumerate(gltf["nodes"])}
    missing = [role for role in ROLE_BONES if role not in names or names[role] not in by_name]
    if missing:
        raise ModelError(f"the donor has no joint for {missing}")
    return {"name": Path(source).name, "vertices": vertices, "faces": faces,
            "atlas": np.asarray(atlas.convert("RGBA"), np.uint8),
            "joints": {index: np.asarray(matrix, float)[:3, 3] for index, matrix in enumerate(world)},
            "parents": {child: index for index, node in enumerate(gltf["nodes"]) for child in node.get("children", [])},
            "role_nodes": {role: by_name[names[role]] for role in ROLE_BONES},
            "report": {k: v for k, v in report.items() if isinstance(v, (int, float, str, bool))}}


def library_donor(library: Path, slug: str, *, roles: dict[str, str] | None = None, atlas_size=(1024, 1024),
                  sha256_expected: str | None = None) -> dict:
    """A library entry (`<library>/<slug>/meta.json` + model) as a donor record, through the shared donor module.

    With `roles` given (a `re5_donor_pool.Donor.role_names()` from a survey) the folder is not resolved again;
    without, `re5_donor_pool.resolve` judges the rig and supplies the roles. The record carries the donor's slug,
    name, game, franchise and model hash, so a receipt can name it the way the RE5 receipts do.
    """
    from . import re5_donor_pool

    folder = Path(library) / slug
    if not (folder / "meta.json").is_file():
        raise ModelError(f"no library entry {slug!r} under {library}")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    if roles is None:
        try:
            donor, _rig = re5_donor_pool.resolve(folder)
        except re5_donor_pool.DonorError as exc:
            raise ModelError(f"{slug}: {exc.category}: {exc}") from exc
        roles, model, info = donor.role_names(), folder / donor.model, donor
    else:
        model = folder / str(meta.get("model") or next(p.name for p in sorted(folder.iterdir()) if p.suffix.lower() in (".glb", ".gltf")))
        info = None
    data = model.read_bytes()
    digest = sha256(data)
    if sha256_expected and digest != sha256_expected:
        raise ModelError(f"{slug}: model is {digest[:12]}, the survey pinned {sha256_expected[:12]}")
    record = load_donor(model, roles=roles, atlas_size=atlas_size)
    game = info.game if info else re5_donor_pool.game_of(meta)
    record["donor"] = {"slug": slug, "name": str(meta.get("name") or slug), "game": game,
                       "franchise": info.franchise if info else re5_donor_pool.franchise_of(game),
                       "model": model.name, "sha256": digest, "roles": dict(roles)}
    return record


def fit(vertices: list[dict], joints: dict, parents: dict, role_nodes: dict[str, int], bones: dict[int, np.ndarray],
        *, scales: dict[str, float] = SCALES, role_bones: dict[str, int] = ROLE_BONES
        ) -> tuple[np.ndarray, np.ndarray, list[list[tuple[int, float]]], dict]:
    """Donor vertices placed on the native bind skeleton: (positions, normals, per-vertex (bone, weight), report).

    Every donor joint influence walks up to the nearest role joint. A role's part is rotated so its segment points
    along the native one, stretched along it to the native length and scaled across it by the role family's
    factor, then anchored on the native bone - so each native joint sits where the donor's joint was drawn, and no
    native bind joint moves. A foot is anchored so the donor's sole meets the native floor (y = 0) and still
    weighted to the native foot bone; head and feet keep the donor's orientation. This is the
    `mtf_retarget.transfer` rule with a per-family cross-section.
    """
    from .mtf_retarget import _aim_rotation

    floor = min(float(v["position"][1]) for v in vertices)
    anchor = {role: np.asarray(bones[role_bones[role]], float) for role in role_bones}
    cross = {role: float(scales[ROLE_FAMILY.get(role, "limb")]) for role in role_bones}
    for side in ("r_foot", "l_foot"):
        height = float(joints[role_nodes[side]][1]) - floor
        anchor[side] = np.array([anchor[side][0], height * cross[side], anchor[side][2]])
    transform = {}
    for role in role_bones:
        start = role if role in SEGMENTS else next(a for a, b in SEGMENTS.items() if b == role)
        end = SEGMENTS[start]
        source = joints[role_nodes[end]] - joints[role_nodes[start]]
        target = anchor[end] - anchor[start]
        rotation = _aim_rotation(source, target)
        if role in SEGMENTS:
            axis = source / np.linalg.norm(source)
            along = float(np.linalg.norm(target) / np.linalg.norm(source))
            transform[role] = rotation @ (np.eye(3) * cross[role] + (along - cross[role]) * np.outer(axis, axis))
        else:
            transform[role] = (np.eye(3) if role in UPRIGHT else rotation) * cross[role]
    by_node = {node: role for role, node in role_nodes.items()}

    def role_of(joint: int) -> str:
        seen = set()
        while joint not in by_node:
            if joint in seen or joint not in parents:
                return "hip"                             # a joint above the hip (scene root) rides the hip
            seen.add(joint)
            joint = parents[joint]
        return by_node[joint]

    positions, normals, influences = [], [], []
    for vertex in vertices:
        point, normal = np.asarray(vertex["position"], float), np.asarray(vertex["normal"], float)
        moved, turned, merged = np.zeros(3), np.zeros(3), {}
        for joint, weight in zip(vertex["source_joints"], vertex["source_weights"]):
            if weight <= 0:
                continue
            role = role_of(int(joint))
            moved += weight * (transform[role] @ (point - joints[role_nodes[role]]) + anchor[role])
            turned += weight * (np.linalg.inv(transform[role]).T @ normal)
            merged[role_bones[role]] = merged.get(role_bones[role], 0.0) + float(weight)
        total = sum(merged.values())
        if total <= 0 or not np.isfinite(moved).all():
            raise ModelError("a donor vertex has no usable joint influence")
        length = float(np.linalg.norm(turned))
        positions.append(moved / total)
        normals.append(turned / length if length > 1e-9 else np.array([0.0, 1.0, 0.0]))
        influences.append(sorted(merged.items()))
    report = {"method": "per-role rotate + stretch onto the native bind joints; native bind joints not moved",
              "scales": dict(scales), "donor_floor": floor,
              "foot_anchor_height": {s: float(anchor[s][1]) for s in ("r_foot", "l_foot")},
              "roles": {role: {"donor_node": int(role_nodes[role]), "bone": role_bones[role]} for role in role_bones}}
    return np.asarray(positions), np.asarray(normals), influences, report


def donor_surface(body: A.HdBin, donor: dict, *, image: int, scales: dict[str, float] = SCALES,
                  role_bones: dict[str, int] = ROLE_BONES) -> tuple[A.HdBin, dict, int]:
    """The donor fitted onto `body`'s skeleton and written as one material naming table image `image`:
    (model, fit report, weight percent step). Shared by the player and the enemy writers."""
    bones = body.bone_world()
    absent = [role for role, bone in role_bones.items() if bone not in bones]
    if absent:
        raise ModelError(f"the body skeleton has no bone for {absent}")
    vertices, faces = donor["vertices"], donor["faces"]
    positions, normals, influences, fit_report = fit(vertices, donor["joints"], donor["parents"], donor["role_nodes"],
                                                     bones, scales=scales, role_bones=role_bones)
    sets, index, step = A.weight_table(influences)
    order, runs = A.soup([np.asarray(faces, np.int64)])
    native = body.materials()
    plain = next((m for m in native if m.header[11] == 0 and m.textures() == [m.diffuse]), native[0])
    header = bytearray(plain.header)
    header[12], header[13], header[14], header[15], header[23] = image, 0xFF, 0xFF, 0xFF, 0xFF
    uvs = np.asarray([v["uv"] for v in vertices], float)
    built = body.with_geometry(positions=positions[order], normals=normals[order], uvs=uvs[order],
                               weight_sets=sets, weight_index=index[order],
                               materials=[A.Material(bytes(header), runs[0])])
    fit_report["bbox"] = [positions.min(0).round(2).tolist(), positions.max(0).round(2).tolist()]
    fit_report["_bounds"] = (positions.min(0), positions.max(0))          # unrounded, for the head centre
    return built, fit_report, step


def author_body(target: bytes, archive: bytes, donor: dict, *, image: int | None = None, shrink: float = 0.1,
                scales: dict[str, float] = SCALES, layout: PackLayout | None = None,
                role_bones: dict[str, int] = ROLE_BONES, opaque_atlas: bool = False
                ) -> tuple[bytes, tuple[str, bytes], dict]:
    """A donor body on `target`'s skeleton: (pack bytes, (archive file name, archive bytes), receipt).

    The donor surface replaces the body mesh (`layout.body`, slot 0) as one material drawn with the donor's atlas,
    which is appended to the pack's own archive and named by table image `image` (the layout's measured choice: an
    image only the body uses). The native head pieces, hands and other body parts the layout names are shrunk to
    `shrink` of their size where they stand, because the donor brings its own head and hands in the body mesh.
    Without a layout the pack is Leon's (the published candidates' layout). `opaque_atlas` uploads the atlas through
    `finish_atlas` (no black texels, alpha 255); off by default so the published candidates rebuild to their hashes.
    """
    layout = layout or LAYOUTS["pl08"]
    image = layout.image if image is None else image
    pack, dat = A.pack_slots(target)
    body, table = _body(dat, layout)
    if not 0 <= image < len(table.images):
        raise ModelError(f"the body table has {len(table.images)} images; {image} is not one of them")
    built, fit_report, step = donor_surface(body, donor, image=image, scales=scales, role_bones=role_bones)
    pixels, finish = donor_atlas(donor, opaque=opaque_atlas)
    images = A.ImagePack.parse(archive)
    if images.pack_id != table.images[image].pack_id:
        raise ModelError("the archive is not the one the body's texture table names")
    entry = images.append(A.encode_dds(pixels))
    table.images[image] = A.TplImage(pixels.shape[1] // 4, pixels.shape[0] // 4, 0x0E, images.pack_id, entry,
                                     table.images[image].sampler)
    before = [sha256(payload) for _ext, payload in dat.slots]
    dat.replace(layout.body, built.build())
    dat.replace(layout.table, A.Tpl(table.images).slot())
    low, high = fit_report.pop("_bounds")
    bones = body.bone_world()
    head_centre = np.asarray(bones[role_bones["head"]], float) + [0.0, 0.25 * (high[1] - bones[role_bones["head"]][1]), 0.0]
    hidden = {}
    for slot in layout.hidden():
        if slot >= len(dat.slots):
            continue
        ext, payload = dat.slots[slot]
        if ext != "BIN":
            continue
        centre = head_centre if slot in layout.heads and slot != FAR_HEAD else None
        dat.replace(slot, shrink_part(payload, shrink, centre))
        hidden[slot] = "toward the donor head" if centre is not None else "toward its own centroid"
    out = A.pack_build(pack, dat)
    _again_pack, again = A.pack_slots(out)
    after = [sha256(payload) for _ext, payload in again.slots]
    changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    if changed != sorted({layout.body, layout.table, *hidden}):
        raise ModelError(f"the rebuilt pack changed slots {changed}")
    check = A.HdBin.parse(again.slots[layout.body][1])
    used_bones = sorted({bone for entry_ in check.weights() for bone, _w in entry_})
    name = f"{images.pack_id:08x}.pack.fen"
    receipt = {"operation": "donor body authored on the native skeleton", "source": donor.get("name"),
               "source_report": donor.get("report", {}), "layout": layout.pack,
               "fit": fit_report,
               "body": {"slot": layout.body, "vertices": check.vertex_count, "triangles": len(donor["faces"]),
                        "materials": check.material_count,
                        "weight_sets": check.weight_count, "weight_percent_step": step, "bones_used": used_bones,
                        "bones": check.bone_count, "bytes": [len(body.build()), len(built.build())],
                        "bbox": fit_report["bbox"],
                        "skeleton_bytes_identical": check.sections["bones"] == body.sections["bones"]},
               "texture": {"archive": name, "entry": entry, "table_image": image, "width": int(pixels.shape[1]),
                           "height": int(pixels.shape[0]), "format": "DXT5", "entries": len(images.entries)}
               | ({"atlas_finish": finish} if finish else {}),
               "parts_shrunk": {str(k): v for k, v in sorted(hidden.items())}, "shrink": shrink,
               "slots_replaced": changed, "other_slots_byte_identical": len(after) - len(changed),
               "live_verified": False}
    if donor.get("donor"):
        receipt["donor"] = donor["donor"]
    return out, (name, images.build()), receipt


# ------------------------------------------------------------------------------------------------------ cast pool

CAST_EXPECTATION = {
    "what_must_be_seen": [
        "Leon's slot first: the round's player is the dealt library character, about 2 m tall with Leon's limb "
        "lengths, standing on the ground, no Leon head or hands, knife and sheath floating at his hip",
        "the character moves with Leon's animations (walk, aim, knife swing); the camera and the laser sight are "
        "where Leon's were",
        "another slot only once the Select Player walk steers to it (today the walk confirms the default, Leon): "
        "HUNK, Krauser, Wesker, Ada each drawn as their dealt donor",
    ],
    "failure_signs": [
        "stock character: the overlay was not applied, or the character loads a pack this table does not name "
        "(Ada: pl0c / pl16 instead of pl0b)",
        "body invisible or black with small specks at head height: the composed mesh or the appended archive entry "
        "is refused (see native-rewrite-v1 / sonic-on-leon-v1 first)",
        "donor shape in a stock texture: the appended archive entry is not read; the table's pack id is ignored",
        "native torso, legs or strap drawn through the donor (Krauser, Wesker): a hidden part slot the game draws "
        "from another table than measured",
        "hang at stage load: the rebuilt container of that pack (bisect by removing one pack file)",
    ],
}


def cast_pool(em_dir: Path, imagepack_dir: Path, library: Path, donors: list, seed, out: Path, *,
              slots: tuple = tuple(CAST), history: list | tuple = (), avoid_last: int = 3,
              games: list[str] | None = None, exclude: dict[str, str] | None = None,
              atlas_size=(1024, 1024), max_vertices: int = 12000, name: str | None = None,
              assignment: dict[str, str] | None = None, opaque_atlas: bool = True) -> dict:
    """Deal library donors to the Mercenaries player slots from a seed (`re5_donor_pool.plan`, the RE5 rule) and
    write one overlay: every dealt pack and its grown archive under `out/romfs/bio4/...`, plus `receipt.json`.

    `donors` are `re5_donor_pool.Donor` rows (a survey); donors above `max_vertices` are left out before the deal.
    A donor the writer refuses on its slot is set aside and the plan is dealt again from the same seed, so the
    outcome follows from the seed, the donors, the history and `exclude` alone (as `re5_cast_writer.pool_cast`).
    `assignment` pins the deal ({slot: slug}, an earlier receipt's): nothing is dealt and a refusal is an error, so
    a pool is rebuilt with the same donors. `opaque_atlas` uploads each atlas through `finish_atlas`.
    """
    from . import re5_donor_pool

    em_dir, imagepack_dir, library, out = Path(em_dir), Path(imagepack_dir), Path(library), Path(out)
    if (out / "receipt.json").exists():
        raise ModelError(f"{out} already holds an overlay; candidates are never overwritten")
    refused: dict[str, str] = dict(exclude or {})
    pool = list(donors)
    by_slug = {d.slug: d for d in pool}
    slot_names = list(assignment) if assignment else list(slots)
    pinned = dict(assignment) if assignment else None
    if pinned:
        unknown = [f"{slot} <- {slug}" for slot, slug in pinned.items() if slot not in CAST or slug not in by_slug]
        if unknown:
            raise ModelError(f"the pinned assignment names slots or donors this survey does not have: {unknown}")
    while True:
        assignment = pinned or re5_donor_pool.plan(seed, slot_names, pool, history=history, avoid_last=avoid_last,
                                                   games=games, exclude=set(refused))
        built, files, sources, rows = {}, {}, {}, {}
        failed = None
        for slot, slug in assignment.items():
            pack_name = CAST[slot]["pack"]
            layout = LAYOUTS[pack_name]
            donor = by_slug[slug]
            try:
                record = library_donor(library, slug, roles=donor.role_names(), atlas_size=atlas_size,
                                       sha256_expected=donor.sha256)
                if len(record["vertices"]) > max_vertices:
                    raise ModelError(f"{slug}: {len(record['vertices'])} vertices, above the pool limit {max_vertices}")
                target = (em_dir / f"{pack_name}.udas").read_bytes()
                _pack, dat = A.pack_slots(target)
                archive_name = A.Tpl.parse(dat.slots[layout.table][1]).images[layout.image].archive()
                archive = (imagepack_dir / archive_name).read_bytes()
                pack_out, (written_name, written), receipt = author_body(target, archive, record, layout=layout,
                                                                         opaque_atlas=opaque_atlas)
                if written_name != archive_name:
                    raise ModelError("the writer grew another archive than the one that was read")
            except (ModelError, A.AssetError, ValueError, OSError) as exc:
                failed = (slug, f"{slot} ({pack_name}) <- {slug}: {exc}")
                break
            files[f"{PACK_DIR}/{pack_name}.udas"] = pack_out
            files[f"{IMAGE_DIR}/{written_name}"] = written
            sources[f"{PACK_DIR}/{pack_name}.udas"] = target
            sources[f"{IMAGE_DIR}/{written_name}"] = archive
            rows[slot] = {"pack": pack_name, "roster_name": next(k for k, v in ROSTER.items() if v == slot),
                          "pack_evidence": CAST[slot]["evidence"], "layout": layout.note,
                          "donor": record["donor"] | {"platform": donor.platform, "provenance": donor.provenance},
                          "pack_sha256": sha256(pack_out), "archive": written_name, "archive_sha256": sha256(written),
                          "body": receipt["body"], "texture": receipt["texture"], "fit": receipt["fit"],
                          "parts_shrunk": receipt["parts_shrunk"], "slots_replaced": receipt["slots_replaced"],
                          "live_verified": False}
        if failed is None:
            break
        slug, reason = failed
        if pinned or slug in refused:
            raise ModelError(reason)
        refused[slug] = reason
        print(f"set aside: {reason}", flush=True)
    receipt = {"recipe": "re4_switch_models.cast_pool", "name": name or out.name, "game_id": GAME_ID,
               "plan": {"seed": seed, "slots": slot_names, "games": games, "avoid_last": avoid_last,
                        "history": [dict(row) if isinstance(row, dict) else list(row) for row in history],
                        "pool_size": len(pool), "max_vertices": max_vertices, "set_aside": dict(refused),
                        "pinned_assignment": bool(pinned), "opaque_atlas": opaque_atlas,
                        "rule": "re5_donor_pool.plan: a donor at most once, recently used donors last, franchises in turn"},
               "assignment": assignment, "slots": rows,
               "role_bones": {"hip": ROLE_BONES["hip"], "note": "hip on bone 0 (the root), as the published Leon "
                              "candidates; the native skins bind the hips to bone 17 (pelvis) - see re4-parity.md"},
               "roster_note": "The queue names characters by re4_menus.PLAYERS; the RE4 Switch walk today confirms "
                              "Select Player on its default (Leon), so only Leon's pack is drawn until the walk "
                              "steers to a portrait (re4_switch.step).",
               **CAST_EXPECTATION, "acceptance": "experimental; offline structural checks only"}
    return write_overlay(out, files, receipt, sources)


def refinish_overlay(stock_bio4: Path, build_bio4: Path, out: Path) -> dict:
    """Every archive of a built overlay (`build_bio4/imagepackhd/*.pack.fen`) that holds appended donor atlases,
    refinished (`refinish_archive`) into `out/romfs/bio4/imagepackhd/` with a receipt; the overlay's packs are read
    (for the UVs) and not copied - they stay byte for byte what was built and booted."""
    stock_bio4, build_bio4, out = Path(stock_bio4), Path(build_bio4), Path(out)
    if (out / "receipt.json").exists():
        raise ModelError(f"{out} already holds an overlay; candidates are never overwritten")
    packs = {path.name: path.read_bytes() for path in sorted((build_bio4 / "em").glob("*.udas"))}
    files, sources, rows = {}, {}, {}
    for path in sorted((build_bio4 / "imagepackhd").glob("*.pack.fen")):
        stock_path = stock_bio4 / "imagepackhd" / path.name
        if not stock_path.is_file():
            continue
        data, stock = path.read_bytes(), stock_path.read_bytes()
        if len(A.ImagePack.parse(data).entries) <= len(A.ImagePack.parse(stock).entries):
            continue                                       # nothing appended (a greybox archive): not a pool's
        written, report = refinish_archive(data, stock, packs)
        files[f"{IMAGE_DIR}/{path.name}"] = written
        sources[f"{IMAGE_DIR}/{path.name}"] = data
        rows[path.name] = report
    if not files:
        raise ModelError(f"{build_bio4} holds no archive with appended entries")
    receipt = {"recipe": "re4_switch_models.refinish_overlay", "build": str(build_bio4), "archives": rows,
               "note": "source_* in files is the built overlay's archive; only the appended donor atlases changed "
                       "(finish_atlas: opaque, no black texels); the packs that name them are unchanged",
               **CAST_EXPECTATION, "acceptance": "experimental; offline structural checks only"}
    return write_overlay(out, files, receipt, sources)


def write_overlay(root: Path, files: dict[str, bytes], receipt: dict, sources: dict[str, bytes]) -> dict:
    """Write `files` under `root/romfs/` and a `receipt.json` beside it. `sources` are the stock files by the same
    relative name (their hashes go in the receipt); refuses to write over an existing overlay."""
    root = Path(root)
    if (root / "receipt.json").exists():
        raise ModelError(f"{root} already holds an overlay; candidates are never overwritten")
    rows = []
    for name, payload in files.items():
        path = root / "romfs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        stock = sources.get(name)
        rows.append({"path": f"romfs/{name}", "bytes": len(payload), "sha256": sha256(payload),
                     "source_bytes": len(stock) if stock is not None else None,
                     "source_sha256": sha256(stock) if stock is not None else None})
    receipt = {"title_id": TITLE_ID, "files": rows} | receipt | {"live_verified": False}
    (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="RE4 Switch player model overlays (offline; never booted here)")
    sub = parser.add_subparsers(dest="command", required=True)
    swap = sub.add_parser("native-swap", help="another pack's body in a pack's body slot")
    swap.add_argument("--em", type=Path, required=True, help="a folder holding the stock plXX.udas files")
    swap.add_argument("--target", default="pl08")
    swap.add_argument("--donor", required=True)
    swap.add_argument("--rewrite", action="store_true", help="re-encode the donor body through the composer")
    swap.add_argument("--out", type=Path, required=True)
    author = sub.add_parser("author", help="a skinned .glb (or a library entry) written onto a pack's own skeleton")
    author.add_argument("--em", type=Path, required=True)
    author.add_argument("--imagepack", type=Path, required=True, help="a folder holding the stock .pack.fen files")
    author.add_argument("--target", default="pl08", help="plXX; the measured layout of that pack is used (LAYOUTS)")
    author.add_argument("--source", type=Path, help="a skinned .glb")
    author.add_argument("--library", type=Path, help="a character library folder (with --slug)")
    author.add_argument("--slug", help="the library entry to write")
    author.add_argument("--out", type=Path, required=True)
    pool = sub.add_parser("cast-pool", help="deal surveyed library donors to the five Mercenaries player packs")
    pool.add_argument("--em", type=Path, required=True)
    pool.add_argument("--imagepack", type=Path, required=True)
    pool.add_argument("--library", type=Path, required=True)
    pool.add_argument("--survey", type=Path, required=True, help="a re5_donor_pool.survey JSON of that library")
    pool.add_argument("--seed", required=True)
    pool.add_argument("--out", type=Path, required=True)
    pool.add_argument("--history", default="", help="comma-separated receipt.json files of earlier overlays, oldest first")
    pool.add_argument("--avoid-last", type=int, default=3)
    pool.add_argument("--games", default="", help="comma-separated game titles or franchises to keep")
    pool.add_argument("--exclude", default="", help="comma-separated donor slugs to leave out")
    pool.add_argument("--max-vertices", type=int, default=12000)
    pool.add_argument("--assignment", type=Path, help="an earlier receipt.json: rebuild with its donors (no deal)")
    pool.add_argument("--atlas-as-built", action="store_true",
                      help="upload each atlas as mtf_materials built it (the pools before 2026-11-10)")
    sub.add_parser("layouts", help="print the measured per-character slot layouts")
    fin = sub.add_parser("refinish", help="put the donor atlases a built overlay appended through finish_atlas")
    fin.add_argument("--stock", type=Path, required=True, help="the stock RomFS bio4/ folder")
    fin.add_argument("--build", type=Path, required=True, help="the overlay's romfs/bio4/ folder (read only)")
    fin.add_argument("--out", type=Path, required=True)
    for command in (swap, author):
        command.add_argument("--expect", default="", help="what a live round must show; stored in the receipt")
    args = parser.parse_args(argv)
    if args.command == "layouts":
        print(json.dumps({name: layout.__dict__ for name, layout in LAYOUTS.items()}, indent=2, default=list))
        return 0
    if args.command == "refinish":
        result = refinish_overlay(args.stock, args.build, args.out)
        print(json.dumps({"out": str(args.out), "files": result["files"]}, indent=2))
        return 0
    if args.command == "cast-pool":
        from . import re5_donor_pool
        donors = re5_donor_pool.donors_of(json.loads(args.survey.read_text(encoding="utf-8")))
        history = [json.loads(Path(name).read_text(encoding="utf-8"))["assignment"]
                   for name in args.history.split(",") if name]
        pinned = json.loads(args.assignment.read_text(encoding="utf-8"))["assignment"] if args.assignment else None
        result = cast_pool(args.em, args.imagepack, args.library, donors, args.seed, args.out, history=history,
                           avoid_last=args.avoid_last, games=[g for g in args.games.split(",") if g] or None,
                           exclude={s: "left out by the caller" for s in args.exclude.split(",") if s},
                           max_vertices=args.max_vertices, assignment=pinned, opaque_atlas=not args.atlas_as_built)
        print(json.dumps({"out": str(args.out), "assignment": result["assignment"], "files": result["files"]}, indent=2))
        return 0
    target = (args.em / f"{args.target}.udas").read_bytes()
    if args.command == "native-swap":
        donor = (args.em / f"{args.donor}.udas").read_bytes()
        out, receipt = native_body_swap(target, donor, rewrite=args.rewrite)
        name = f"{PACK_DIR}/{args.target}.udas"
        receipt |= {"target_pack": args.target, "donor_pack": args.donor, "donor_pack_sha256": sha256(donor),
                    "expect_live": args.expect}
        result = write_overlay(args.out, {name: out}, receipt, {name: target})
    else:
        layout = LAYOUTS.get(args.target, LAYOUTS["pl08"])
        _pack, dat = A.pack_slots(target)
        archive_name = A.Tpl.parse(dat.slots[layout.table][1]).images[layout.image].archive()
        archive = (args.imagepack / archive_name).read_bytes()
        if args.library and args.slug:
            record = library_donor(args.library, args.slug)
            source_hash = record["donor"]["sha256"]
        elif args.source:
            record, source_hash = load_donor(args.source), sha256(args.source.read_bytes())
        else:
            raise ModelError("author needs --source or --library with --slug")
        out, (written_name, written), receipt = author_body(target, archive, record, layout=layout)
        if written_name != archive_name:
            raise ModelError("the writer grew another archive than the one that was read")
        files = {f"{PACK_DIR}/{args.target}.udas": out, f"{IMAGE_DIR}/{written_name}": written}
        receipt |= {"target_pack": args.target, "source_sha256": source_hash, "expect_live": args.expect}
        result = write_overlay(args.out, files, receipt, {f"{PACK_DIR}/{args.target}.udas": target,
                                                          f"{IMAGE_DIR}/{archive_name}": archive})
    print(json.dumps({"out": str(args.out), "files": result["files"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
