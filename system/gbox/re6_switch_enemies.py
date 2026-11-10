"""RE6 Switch enemies for MercMode: which classes the Mercenaries stages place, and library donors on their bodies.

Offline only: nothing here launches a game or writes outside the folder it is given. Every receipt says
`live_verified: false`.

**Which archives.** Each Mercenaries stage `s120N` has two per-mode sets, `s120NSoft.arc` (THE MERCENARIES) and
`s121NSoft.arc` (NO MERCY), whose enemy layouts (`soft\\stage\\s12xN\\s12xN_emNN`, XFS `15302ef4`, one `mSetInfos`
row per placement: `mInfoClass` `cSetInfoEm1000`, `mUnitClass` `uEmNNNN`) name the enemy class of every spawn. The
class is the archive: `uEm1400` is `nativeNXx64/arc/NX/uEm1400.arc`. `stage_census` counts the rows per class (measured
on all 20 sets, 2026-11-09; the table is in docs/research/re6-parity.md). Mining the Depths' No Mercy set (`s1218`)
places `uEm1400` 284 times, `uEm1000` 160, `uEm5210` 19, `uEm3200` 5 and `uEm4300` once.

**Can the player writer take an enemy body?** Yes for the humanoid J'avo, measured on `uEm1000` and `uEm1400`: each
archive holds one skinned MOD (`data\\chara\\em\\em1000\\model\\em1000`, 27 bones; `em1400`, 35 bones; one root each),
both carry all 18 role ids the player writer anchors on (hip 1 ... left foot 22, the same RE6 global bone ids), the
position transform is a uniform scale (266.6 / 268.5), the bind is a T-pose (bounds 173 cm wide at the hands) and the
body meshes are in the player's four-weight format `0x2000D414`. So `re6_switch_models.build_body` runs unchanged on
them (`keep` for a donor within 20 degrees of the native bind, `pose` above, as for the players); what differs is
picked here, not assumed: the material the donor is drawn with (the J'avo's own `..._ID2_Body`, vetted opaque and
without displacement through the archive's own MRL) and the template mesh record (the first LOD-0 four-weight mesh on
that material). The donor replaces every mesh of the MOD, so the J'avo's damage pieces (`Dbody`, `Bugbody`, `Death`)
are not drawn either; mutations spawned from other archives are untouched.

`uEm1000Base.arc` is not a second body: it holds the J'avo family's motions (`soft\\chara\\em\\em1000\\motsoft\\*`
LMT), hit shapes and effects and no `data\\chara\\em\\em1000\\model\\em1000` MOD, so the body is only in `uEm1000.arc`.
Not measured, and the reason a boot must look: whether the game hides the template mesh's group on a damage state (the
donor would then vanish when hurt).

**The group-aware writer (`build_class`, 2026-11-10).** `build_enemy` above replaces the whole mesh table with one
record in one group. The class bodies are not one group: `em1000` is 298 records in 95 groups (torso skin 3, arms 4/5,
legs, two heads, four gas masks, 15 shirts / pants / shoes, the damaged `Dbody` 103-115, `Bugbody` 120-124, the
`Death` body 126-130, five `Shadow` meshes 131-135, the body sections 403-463), the zombies 37-136 groups, and no table
in the class archives says which a spawn shows (RE6 has no `MTG` montage resource beside the model, unlike RE5: the
layouts carry `mModelType` / `mMontageNo` and the selection is in code). `build_class` therefore follows the RE5
enemy writer (`re5_enemy_writer.graft_pieces`, the shape RE5's live series builds play): every native record stays in
the table, its 56 bytes, vertices and envelopes as shipped, with its index words collapsed so it draws nothing; the
donor - authored once by the RE6 player writer in `keep` mode on the class's own skeleton
(`re6_switch_models.build_body`, the live-proven bind) - is appended once per **carrier group**: every non-shadow group
whose LOD-0 vertices cover half of the chest band (`carrier_groups`). Whatever outfit, damage state or death body a
spawn shows, a standing body is drawn there; two carriers on screen draw the same surface twice (identical depth).
The class keeps its skeleton, motions (`uEm1000Base` / `uEm5000Base` untouched), hit shapes and FSM.

The donor is drawn with one native material chosen by `donor_material_choice` and its atlas goes into that material's
albedo in the same archive through the Y'CbCr model (`re6_switch_tex.replace_albedo`, chroma on: the encoding that
showed Sonic in his own blue live on 2026-11-10). Every donor passes `fit_report` (fitted bind-pose box against the
native one, rest pose, rig shape, skin spread, library kind) before it is written; the report goes into the receipt.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import struct
import zlib
from pathlib import Path

import numpy as np

from . import mt_arc, mt_model, mtf_author, re6_switch_models as M

ARCHIVE_DIR = M.ARCHIVE_DIR
FOUR_WEIGHTS = 0x2000D414
LAYOUT_TYPE = 0x15302EF4                    # the enemy / item layouts' XFS type (sNNNN_emNN, sNNNN_itNN)
_CLASS = re.compile(rb"(?<![A-Za-z0-9])(uEm[0-9a-fA-F]{4})(?![0-9A-Za-z])")


class EnemyError(ValueError):
    """The archive is not a body the writer measured, or the pool cannot fill the classes."""


def _raw(entry) -> bytes:
    try:
        return zlib.decompress(entry.data)
    except zlib.error:
        return entry.data


def stage_census(soft_archive: bytes) -> dict:
    """{class: placements} over a stage set's enemy layouts (every `mUnitClass` row naming a `uEmNNNN`), plus the
    layouts read. One row is one placement; a class's archive is `uEm<NNNN>.arc`."""
    arc = mt_arc.parse(bytes(soft_archive))
    classes: dict[str, int] = {}
    layouts = []
    for entry in arc.entries:
        if entry.hash != LAYOUT_TYPE or not re.search(r'_em\d+$', entry.name):
            continue
        raw = _raw(entry)
        if raw[:4] != b"XFS\0":
            continue
        layouts.append(entry.name.rsplit("\\", 1)[-1])
        for match in _CLASS.finditer(raw):
            name = match.group(1).decode()
            classes[name] = classes.get(name, 0) + 1
    return {"classes": dict(sorted(classes.items(), key=lambda kv: -kv[1])), "layouts": sorted(layouts)}


def body_material(arc: mt_arc.Arc, model) -> dict:
    """The material a one-mesh donor is drawn with: the body material (`_Body` in its name) when it is opaque
    (`BSSolid`, plain `FTransparency`) and not displaced, else the first such material, else index 0 unvetted."""
    from .re6_switch_tex import material_bindings

    rows = []
    for index, name in enumerate(M.body_materials(model)):
        binding = material_bindings(arc, name)
        if binding is None:
            continue
        functions = binding["functions"]
        rows.append({"index": index, "name": name,
                     "opaque": binding.get("blend") == "BSSolid" and functions.get("FTransparency") == "FTransparency",
                     "displaced": functions.get("FVertexDisplacement") != "FVertexDisplacement",
                     "albedo": binding["slots"].get("tAlbedoMap")})
    still = [row for row in rows if row["opaque"] and not row["displaced"]]
    body = [row for row in still if re.search(r"_body$", row["name"], re.IGNORECASE)]
    if body:
        return {**body[0], "vetted": True, "why": "the body material, opaque and without displacement",
                "candidates": len(rows)}
    if still:
        return {**still[0], "vetted": True, "why": "first opaque material without displacement", "candidates": len(rows)}
    names = M.body_materials(model)
    return {"index": 0, "name": names[0] if names else None, "vetted": False, "albedo": None,
            "why": "no vetted material in the archive's MRL: material 0 taken unvetted", "candidates": len(rows)}


def template_mesh(model, material_index: int) -> int:
    """The mesh record the donor's is cloned from (its group, LOD mask and the other fields `build_one_mesh` does not
    name; the vertex format is always written as four-weight): among the LOD-0 meshes on the body material the one in
    the lowest group, a four-weight one first. Measured: both J'avo bodies draw their body material in group 3 at
    every LOD; `em1000` also has it in groups 100 and 403-463 (sections the game can sever or mutate - a donor cloned
    from one of those could vanish with it). With no LOD-0 mesh on the material, the first LOD-0 four-weight mesh."""
    meshes = model.meshes()
    body = [(record["vertex_format"] != FOUR_WEIGHTS, record["group_index"], index)
            for index, record in enumerate(meshes)
            if record["material_index"] == material_index and record.get("level_of_detail", 1) & 1]
    if body:
        return min(body)[2]
    return next((index for index, record in enumerate(meshes)
                 if record["vertex_format"] == FOUR_WEIGHTS and record.get("level_of_detail", 1) & 1), 0)


def body_check(archive: bytes) -> dict:
    """What an enemy archive's body is and how a donor would be written onto it; raises EnemyError when the writer
    cannot take it (no skinned MOD, a role missing, a non-uniform transform, no four-weight mesh)."""
    arc = mt_arc.parse(bytes(archive))
    try:
        index, mrl, raw = M._find_model(arc)
        model = mt_model.parse_mod(raw)
        roles = M.roles_for(model)
    except M.SwitchModelError as exc:
        raise EnemyError(str(exc)) from exc
    table = model.bone_table()
    roots = sum(1 for parent in table.get("parents", []) if parent == 255)
    transform = list(model.position_transform())
    if not (abs(transform[0] - transform[5]) < 1e-4 * abs(transform[0]) and abs(transform[0] - transform[10]) < 1e-4
            * abs(transform[0])):
        raise EnemyError("the body's position transform is not a uniform scale")
    formats = {record["vertex_format"] for record in model.meshes()}
    if FOUR_WEIGHTS not in formats:
        raise EnemyError("the body has no mesh in the four-weight format the writer authors")
    material = body_material(arc, model)
    bounds = model.bounds()
    template = template_mesh(model, material["index"])
    record = model.meshes()[template]
    return {"entry": arc.entries[index].name, "entry_index": index, "mrl_index": mrl,
            "bones": model.header()["bone_count"], "roots": roots,
            "roles": roles, "material": material, "template_index": template,
            "template": {"group": record["group_index"], "lod": record.get("level_of_detail"),
                         "format": f"0x{record['vertex_format']:08X}", "material_index": record["material_index"]},
            "height_cm": round(bounds["max"]["y"] - bounds["min"]["y"], 1),
            "width_cm": round(bounds["max"]["x"] - bounds["min"]["x"], 1),
            "formats": sorted(f"0x{f:08X}" for f in formats), "meshes": len(model.meshes())}


def build_enemy(archive: bytes, source: Path, roles: dict[str, str], *, height: float | None = None,
                bind_mode: str = "auto", textures: bool = False, chroma: bool = True) -> tuple[bytes, dict]:
    """(archive, receipt): the enemy body rewritten with the donor's surface on the native skeleton (`build_body`),
    drawn with the vetted body material; with `textures` the donor's atlas also goes onto that material's albedo
    (in the same archive: the enemy archives carry their own textures and MRL)."""
    check = body_check(archive)
    native = bytes(archive)
    deviation = M.pose_deviation(native, Path(source), roles)
    mode = bind_mode
    if bind_mode == "auto":
        mode = "keep" if deviation["max_degrees"] <= M.POSE_TOLERANCE_DEGREES else "pose"
    payload, receipt = M.build_body(native, Path(source), source_roles=roles,
                                    height=float(height or check["height_cm"]), textures=textures,
                                    material_index=check["material"]["index"],
                                    template_index=check["template_index"], bind_mode=mode)
    texture_rows = []
    if textures and check["material"].get("albedo"):
        from PIL import Image

        from .re6_switch_tex import replace_albedo
        atlas = M.donor_atlas(Path(source))

        def writer(surface, _image=atlas):
            scaled = _image if _image.size == (surface.width, surface.height) else _image.resize(
                (surface.width, surface.height), Image.LANCZOS)
            return replace_albedo(surface.data, scaled, chroma=chroma)
        payload, texture_rows = M.replace_textures(payload, {check["material"]["albedo"]: writer})
    before, after = mt_arc.parse(native), mt_arc.parse(payload)
    changed = [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if a.data != b.data]
    allowed = {check["entry_index"]} | {row["entry"] for row in texture_rows if "entry" in row}
    if len(before.entries) != len(after.entries) or set(changed) - allowed:
        raise EnemyError(f"entries other than the body MOD (and its albedo) changed: {sorted(set(changed) - allowed)}")
    receipt = {"body": {k: v for k, v in check.items() if k != "roles"}, "rest_pose_deviation": deviation,
               "bind_mode_requested": bind_mode, "textures": texture_rows or "native (geometry only)",
               "changed_entries": changed, "unchanged_entries": len(after.entries) - len(changed),
               "source_sha256": hashlib.sha256(native).hexdigest(), **receipt}
    receipt["archive_sha256"] = hashlib.sha256(payload).hexdigest()
    return payload, receipt


def plan_pool(classes: list[str], pool: list[dict], *, seed: int = 7, mix: bool = True) -> dict[str, dict]:
    """{class: donor meta}: one donor per enemy class, a seeded draw with no character twice and the source games
    taken in turn (re6_switch_cast's own draw)."""
    from .re6_switch_cast import _draw

    donors = _draw(pool, len(classes), random.Random(seed), mix)
    if len(donors) < len(classes):
        raise EnemyError(f"{len(donors)} donors cannot fill {len(classes)} classes")
    return {cls: donors[i] for i, cls in enumerate(classes)}


def build_pool(archives: dict[str, Path], library: Path, assignment: dict[str, dict], out_dir: Path, *,
               name: str, textures: bool = False, extra: dict | None = None) -> dict:
    """Write an enemy-pool overlay: every class's archive (and, for a class listed under `extra`, the other archive
    names that carry the same body, e.g. `uEm1000Base`) rewritten with its donor, into
    out_dir/romfs/nativeNXx64/arc/NX, with receipt.json. Returns the receipt."""
    out_dir = Path(out_dir)
    folder = out_dir / "romfs" / ARCHIVE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    rows, files = [], {}
    for cls, meta in assignment.items():
        source = Path(library) / meta["slug"] / meta["model"]
        for arc_name in [f"{cls}.arc"] + list((extra or {}).get(cls, ())):
            path = archives.get(arc_name[:-4]) if arc_name[:-4] in archives else archives.get(arc_name)
            if path is None:
                rows.append({"class": cls, "archive": arc_name, "skipped": "not in the inputs"})
                continue
            payload, receipt = build_enemy(Path(path).read_bytes(), source, meta["rig"]["roles"], textures=textures)
            (folder / arc_name).write_bytes(payload)
            files[f"romfs/{ARCHIVE_DIR.as_posix()}/{arc_name}"] = receipt["archive_sha256"]
            rows.append({"class": cls, "archive": arc_name, "donor": meta["slug"], "donor_name": meta.get("name"),
                         "donor_source": (meta.get("source") or {}).get("game_title"), **receipt})
    receipt = {"name": name, "title_id": M.TITLE_ID, "route": "re6_switch_enemies.build_pool", "files": files,
               "classes": rows, "live_verified": False, "gameplay_verified": False,
               "what_must_be_seen": ["on a stage that spawns these classes, the J'avo drawn as the listed donors at "
                                     "J'avo height, animating with the J'avo motions (walk, attack, stagger, death)",
                                     "the donors in the J'avo's own textures mapped through the donor UVs "
                                     "(geometry-only) unless textures were written",
                                     "players, other classes and the stage unchanged"],
               "failure_signs": ["native J'avo: the overlay did not load, or Mercenaries loads another archive name "
                                 "for the class (uEm1000Base?)", "a donor that vanishes when shot: the template "
                                 "mesh's group is hidden on a damage state - pick another template",
                                 "a hang at stage load: the rewritten MOD (bisect with one class at a time)",
                                 "stretched limbs: the donor's rest pose (see each receipt's rest_pose_deviation)"]}
    (out_dir / "receipt.json").write_text(json.dumps(receipt, indent=1, default=str), encoding="utf-8")
    return receipt


# --- the group-aware writer: the RE5 graft on the RE6 class bodies (2026-11-10) ------------------------------------

#: Vertex formats whose position is three signed shorts at +0 that `mt_model.decode_positions` does not list. Measured
#: 2026-11-10: every sampled vertex of these formats lands inside its model's own box through the position transform
#: (0x23305964 on uEm1000 4,523 / 4,523, uEm5000 22,168 / 22,168, uEm5400 11,195 / 11,195; 0x1B8077D8 and 0x1F1092B3
#: on uEm1400, uEm5000, uEm5400, uEm5500 likewise).
SHORT_POSITION_EXTRA = frozenset({0x23305964, 0x1B8077D8, 0x1F1092B3})
#: The chest band (shares of the native height above its floor) a carrier group's LOD-0 vertices must cover.
TORSO_BAND = (0.62, 0.75)
CARRIER_OVERLAP = 0.5             # the share of the band a carrier covers
CARRIER_MIN_VERTICES = 100        # straps (em1000's gun belt groups 227-230: 58-62), buckles, patches
PLAIN_ALBEDO = ("FAlbedoMap", "FAlbedoMap2")
COLOUR_MASK_ALBEDO = ("FColorMaskAlbedoMap", "FColorMaskAlbedoMapModulate")
#: Transparency functions a donor material may have: the plain one, then two whose clip is inferred to pass at rest
#: (the alpha clip reads the albedo's opacity channel, written opaque; the colour-mask transparency map is the damage
#: holes, zero thresholds at rest). The zombies' skins and the BSAA zombies' gear only have these.
OPAQUE_AT_REST = ("FTransparency", "FTransparencyAlphaClip", "FColorMaskTransparencyMap")
ALBEDO_FORMAT = 0x2B
MIN_DIFFUSE = 0.75                  # CBMaterial.fDiffuseColor multiplies the albedo: uEm5210's lenses are 0.075
MIN_ALBEDO_TEXELS = 256 * 256       # the donor's whole atlas is resampled into the one albedo
#: The donor fit gate (operator 2026-11-10: "oversized and stretched out of proportion ... models that I don't even want
#: to see"). Ratios are to the native class body, so they hold for any class; the RE4 failures it is built against were
#: donors 3.3 m wide, 80 m exploded (another unit scale), 7.6 cm deep (flattened) and a pistol used as a body.
FIT = {"height": (0.85, 1.20),         # fitted height / native height
       "min_depth_cm": 15.0,           # a body has depth
       "floor": 0.10,                  # |fitted floor - native floor| / native height
       "wide": 1.60,                   # fitted width / native width (the native T-pose span)
       "wide_to_height": 1.35,         # fitted width / native height: a weapon held out (Ubistvo's own 262 cm span
                                       # let a 2.8 m polearm pass the ratio above)
       "deep": 0.80,                   # fitted depth / native height
       "rest_degrees": M.POSE_TOLERANCE_DEGREES,   # keep-bind only: the live-proven mode
       "joint_span": 0.60,             # (head - lowest foot) / the donor's vertex height: no stray far vertices
       "min_bones": 6,                 # native bones the donor skin uses: a prop binds to one or two
       "max_vertices": 16000}          # one donor record (the carriers multiply it)
NON_CHARACTER_KINDS = ("prop", "object", "item", "weapon", "vehicle", "stage", "scenery", "effect", "sprites")


class DonorRefused(EnemyError):
    """The donor was authored but does not fit the class (`report` holds the fit report)."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def class_body(arc: mt_arc.Arc, cls: str | None = None) -> tuple[int, int, bytes]:
    """(MOD entry, MRL entry, MOD bytes) of an enemy class's own body: the skinned MOD named after the class
    (`uEm3200` -> `...\\em3200`) when the archive has one, else the largest skeleton (the player writer's rule).

    Measured 2026-11-10: `uEm3200` / `uEm3300` also embed the 57-bone `em1370` pupa (larger than Napad's own 41-bone
    `em3200`) and `uEm1370` the 63-bone `em2120` arm, which the largest-skeleton rule takes."""
    rows = M.model_entries(arc)
    if cls and re.fullmatch(r"uEm[0-9A-Fa-f]{4}\w*", cls):
        stem = "em" + cls[3:7].lower()
        own = [row for row in rows if row["bones"] and row["name"].rsplit("\\", 1)[-1].lower() == stem]
        if own:
            row = own[0]
            mrl = row["mrl"]
            if mrl < 0:
                mrl = next((i for i, e in enumerate(arc.entries) if _raw(e)[:4] == b"MRL\0"), -1)
            return row["index"], mrl, row["raw"]
    return M._find_model(arc)


def record_points(model, index: int, limit: int = 0) -> list[tuple[float, float, float]]:
    """A record's dequantised positions (model space, cm), including the short-position formats measured above."""
    data, record = model.mesh_bytes(index)
    if not data:
        return []
    if record["vertex_format"] not in SHORT_POSITION_EXTRA:
        return model.positions(index, limit)
    transform = model.position_transform()
    stride, count = record["vertex_stride"], record["vertex_count"]
    take = count if not limit else min(count, limit)
    out = []
    for k in range(take):
        if k * stride + 6 > len(data):
            break
        sx, sy, sz = struct.unpack_from("<3h", data, k * stride)
        out.append(tuple(mt_model._transform_point((sx / 32767.0, sy / 32767.0, sz / 32767.0), transform)))
    return out


def group_table(model, *, sample: int = 800) -> dict[int, dict]:
    """{group: records, LOD masks, material names, vertex counts and the LOD-0 extent (y / x, cm)} of a class body."""
    names = M.body_materials(model)
    out: dict[int, dict] = {}
    for index, record in enumerate(model.meshes()):
        row = out.setdefault(record["group_index"], {"records": 0, "lod_masks": set(), "materials": set(),
                                                      "vertices": 0, "lod0_vertices": 0, "y": None, "x": None})
        row["records"] += 1
        row["lod_masks"].add(record["level_of_detail"])
        material = record["material_index"]
        row["materials"].add(names[material] if material < len(names) else f"#{material}")
        row["vertices"] += record["vertex_count"]
        if not record["level_of_detail"] & 1:
            continue
        row["lod0_vertices"] += record["vertex_count"]
        points = record_points(model, index, sample)
        if not points:
            continue
        ys, xs = [p[1] for p in points], [p[0] for p in points]
        for key, values in (("y", ys), ("x", xs)):
            low, high = min(values), max(values)
            row[key] = [low, high] if row[key] is None else [min(row[key][0], low), max(row[key][1], high)]
    for row in out.values():
        row["lod_masks"] = sorted(row["lod_masks"])
        row["materials"] = sorted(row["materials"])
        for key in ("y", "x"):
            if row[key] is not None:
                row[key] = [round(v, 1) for v in row[key]]
    return dict(sorted(out.items()))


def carrier_groups(model, *, band=TORSO_BAND, table: dict | None = None) -> dict:
    """The option groups the donor is written into: every group with LOD-0 records (at least `CARRIER_MIN_VERTICES`)
    whose vertices cover at least `CARRIER_OVERLAP` of the chest band (`band` of the native height above the native
    floor), groups whose every material is a `Shadow` one left out.

    Why the chest: whatever a spawn shows of the class (an outfit's skin and clothes, the damaged or mutated body, the
    death body), a standing body is drawn there, so at least one carrier is on screen whenever the enemy is. Covering
    half the band, not all of it, takes the torso pieces an outfit splits it into (`em1400`'s skin is 109-161 cm, the
    belt below it 100-119; `em1000`'s upper-chest skin 403 is 134-156). Inferred, not measured: which groups a spawn
    shows (the selection is in code, see the module note). A group that carries only a head, a limb or a buckle is not
    a carrier: the game can hide it alone (a mutation, a lost limb) and the donor - the whole character - would go
    with it."""
    table = table if table is not None else group_table(model)
    bounds = model.bounds()
    floor, top = bounds["min"]["y"], bounds["max"]["y"]
    height = top - floor
    low, high = floor + band[0] * height, floor + band[1] * height
    shadow = [g for g, row in table.items() if row["materials"] and all("shadow" in m.lower() for m in row["materials"])]
    groups, why = [], {}
    for group, row in table.items():
        if group in shadow or row["lod0_vertices"] < CARRIER_MIN_VERTICES or row["y"] is None:
            continue
        cover = (min(row["y"][1], high) - max(row["y"][0], low)) / max(high - low, 1e-6)
        if cover >= CARRIER_OVERLAP:
            groups.append(group)
            why[group] = {"y": row["y"], "cover": round(cover, 2), "materials": row["materials"],
                          "records": row["records"], "lod_masks": row["lod_masks"]}
    return {"groups": groups, "band_cm": [round(low, 1), round(high, 1)], "height_cm": round(height, 1),
            "shadow_groups": shadow, "groups_total": len(table), "carriers": why,
            "rule": f"non-shadow groups with {CARRIER_MIN_VERTICES}+ LOD-0 vertices covering {CARRIER_OVERLAP:.0%} of "
                    f"{band[0]:.2f}-{band[1]:.2f} of the height"}


def humanoid_gate(arc: mt_arc.Arc, cls: str) -> dict:
    """Whether a class body is an upright humanoid the keep-bind writer can dress: its own MOD is the archive's
    largest skeleton (the one `build_body` authors), one root, the 18 role ids, a uniform position transform, a
    standing T-pose 150-215 cm tall (head over the hip over the feet, the hands spread to opposite sides)."""
    index, _mrl, raw = class_body(arc, cls)
    codes, measurement = [], {}
    if M._find_model(arc)[0] != index:
        codes.append("not the largest skeleton (build_body would author another model)")
    model = mt_model.parse_mod(raw)
    table = model.bone_table()
    roots = sum(1 for parent in table.get("parents", []) if parent == 255)
    if roots != 1:
        codes.append(f"{roots} roots")
    try:
        roles = M.roles_for(model)
    except M.SwitchModelError as exc:
        return {"passed": False, "codes": [str(exc)], "measurement": {}}
    transform = list(model.position_transform() or [])
    if not transform or not (abs(transform[0] - transform[5]) < 1e-4 * abs(transform[0])
                             and abs(transform[0] - transform[10]) < 1e-4 * abs(transform[0])):
        codes.append("the position transform is not a uniform scale")
    bounds = model.bounds()
    height = bounds["max"]["y"] - bounds["min"]["y"]
    world = {i: np.array((x, y, z)) for i, x, y, z in model.bone_world()}
    joint = {role: world[i] for role, i in roles.items()}
    measurement = {"bones": model.header()["bone_count"], "height_cm": round(height, 1),
                   "width_cm": round(bounds["max"]["x"] - bounds["min"]["x"], 1),
                   "depth_cm": round(bounds["max"]["z"] - bounds["min"]["z"], 1),
                   "joints": {role: [round(float(v), 1) for v in joint[role]] for role in
                              ("hip", "head", "l_hand", "r_hand", "l_foot", "r_foot")}}
    if not 150.0 <= height <= 215.0:
        codes.append(f"{height:.0f} cm tall (a person is 150-215)")
    feet = max(joint["l_foot"][1], joint["r_foot"][1])
    if not joint["head"][1] > joint["hip"][1] > feet:
        codes.append("not standing (head, hip and feet out of order)")
    if feet - bounds["min"]["y"] > 0.15 * height:
        codes.append("the feet are off the floor")
    spread = abs(joint["l_hand"][0] - joint["r_hand"][0])
    if (joint["l_hand"][0] - joint["hip"][0]) * (joint["r_hand"][0] - joint["hip"][0]) >= 0 or spread < 0.6 * height:
        codes.append(f"no T-pose (hands {spread:.0f} cm apart)")
    return {"passed": not codes, "codes": codes, "measurement": measurement}


def _material_rows(arc: mt_arc.Arc, mrl_index: int) -> dict[int, dict]:
    from .re6_switch_tex import texture_set_materials

    if mrl_index < 0:
        return {}
    sets = texture_set_materials(mt_arc.Arc(version=arc.version, entries=[arc.entries[mrl_index]]))
    return {row["name_hash"]: row for row in sets[0]["materials"]} if sets else {}


def _neutral_mask(constants: dict) -> bool:
    mask = constants.get("CBColorMask")
    if not mask:
        return True
    return all(abs(v - 1.0) < 1e-4 for key in ("fColorMaskColor", "fColorMask2Color") for v in mask[key][:3])


def _blood_mask(row: dict) -> bool:
    """A colour mask that is the blood overlay: its blend map is one of the shared `*_blood_CH_BM` masks and its
    colour is a dark red, with zero thresholds at rest. Measured on the zombie skins, shirts and pants (uEm5000,
    uEm5200: `fColorMaskColor` 0.1125 / 0.0375 / 0.0375 and 0.0875 / 0.0125 / 0.0125 over `Body_blood_CH_BM`,
    `Upper_blood_CH_BM`, `Pants_blood_CH_BM`). Inferred: the mask is the wounds the enemy takes, so at rest the
    donor shows its own colours and a shot one bleeds over them."""
    blend = (row.get("slots", {}).get("tAlbedoBlendMap") or "").lower()
    mask = (row.get("constants") or {}).get("CBColorMask") or {}
    colour = mask.get("fColorMaskColor") or [1.0, 1.0, 1.0]
    thresholds = [abs(v) for key in ("fColorMaskThreshold", "fColorMaskOffset") for v in mask.get(key, [0.0])]
    return "blood" in blend and colour[0] >= colour[1] and colour[0] >= colour[2] and max(thresholds or [0.0]) < 1e-6


def donor_material_choice(arc: mt_arc.Arc, model, mrl_index: int, *, others: dict | None = None,
                          path_check=None) -> dict:
    """The native material the donor records are drawn with and the albedo its atlas is written into.

    A candidate is a material of the class body that its own MRL binds with `BSSolid`, no vertex displacement, an
    albedo function that is plain (`FAlbedoMap`, `FAlbedoMap2` - the player material Sonic was proven on) or the
    colour mask with white mask colours (the mask then changes nothing; the J'avo body materials) or the blood overlay
    (`_blood_mask`; the zombie skins and clothes), a diffuse colour of at least `MIN_DIFFUSE`, and a `0x2B` albedo of
    at least 256x256 in this archive. Transparency: plain `FTransparency` first; `FTransparencyAlphaClip` (clips on the
    albedo's opacity channel, which the writer fills opaque) and `FColorMaskTransparencyMap` (the damage-hole map,
    zero thresholds at rest) are taken after it - both inferred opaque at rest, never booted.

    Shared paths: MT Framework keeps one resource per path, so the albedo's path decides who sees the atlas. With
    `others` ({path: other archive stems that may load beside this class}) a shared path is refused; `path_check(path)`
    -> (ok, why, shared_with) replaces that rule (the cast's: a path is usable when every archive that can load beside
    it is dressed too - their native records are collapsed - and no other donor claimed it; the cast then writes the
    same atlas into each copy). The largest albedo of at least 512x512 wins, a plain or neutral mask before the blood
    overlay, then plain transparency, then the diffuse colour, then the most LOD-0 vertices.
    Returns {index, name, albedo, albedo_entry, size, function, transparency, mask, shared_with, ..., candidates,
    refused}."""
    from .re6_switch_tex import TexError, from_arc_entry

    rows = _material_rows(arc, mrl_index)
    names = M.body_materials(model)
    entries = {entry.name.lower(): (i, entry) for i, entry in enumerate(arc.entries) if entry.hash == 0x241F5DEB}
    lod0: dict[int, int] = {}
    for record in model.meshes():
        if record["level_of_detail"] & 1:
            lod0[record["material_index"]] = lod0.get(record["material_index"], 0) + record["vertex_count"]
    candidates, refused = [], []
    for index, name in enumerate(names):
        row = rows.get(zlib.crc32(name.encode()) ^ 0xFFFFFFFF)
        if row is None:
            refused.append({"index": index, "name": name, "why": "not in the class's MRL"})
            continue
        functions, constants = row["functions"], row.get("constants") or {}
        albedo = row["slots"].get("tAlbedoMap")
        transparency = functions.get("FTransparency")
        why, surface, shared_with, position = None, None, [], None
        if row.get("blend") != "BSSolid" or transparency not in OPAQUE_AT_REST:
            why = f"not opaque ({row.get('blend')}, {transparency})"
        elif functions.get("FVertexDisplacement") not in (None, "FVertexDisplacement"):
            why = f"vertex displacement ({functions.get('FVertexDisplacement')})"
        elif functions.get("FAlbedo") not in PLAIN_ALBEDO + COLOUR_MASK_ALBEDO:
            why = f"albedo function {functions.get('FAlbedo')}"
        elif functions.get("FAlbedo") in COLOUR_MASK_ALBEDO and not _neutral_mask(constants) \
                and not _blood_mask(row):
            why = "a coloured colour mask that is not the blood overlay (it would tint the donor)"
        elif not albedo or albedo.lower() not in entries:
            why = "its albedo is not in this archive"
        if why is None:
            position, entry = entries[albedo.lower()]
            try:
                surface = from_arc_entry(entry)
            except TexError as exc:
                why = f"albedo unreadable: {exc}"
            if surface is not None and surface.format != ALBEDO_FORMAT:
                why = f"albedo format 0x{surface.format:02X} (the writer encodes 0x2B)"
        diffuse = (constants.get("CBMaterial") or {}).get("fDiffuseColor") or [1.0, 1.0, 1.0]
        if why is None and min(diffuse) < MIN_DIFFUSE:
            why = f"a dark diffuse colour {[round(v, 3) for v in diffuse]} (it would darken the donor)"
        if why is None and surface.width * surface.height < MIN_ALBEDO_TEXELS:
            why = f"a {surface.width}x{surface.height} albedo is too small for a whole character's atlas"
        if why is None:
            if path_check is not None:
                ok, reason, shared_with = path_check(albedo)
                if not ok:
                    why = reason
            elif (others or {}).get(albedo):
                why = f"albedo also loaded from {', '.join(sorted(others[albedo])[:6])}"
        if why is not None:
            refused.append({"index": index, "name": name, "albedo": (albedo or "").rsplit("\\", 1)[-1] or None,
                            "why": why})
            continue
        candidates.append({"index": index, "name": name, "albedo": albedo, "albedo_entry": position,
                           "size": [surface.width, surface.height], "mips": surface.mip_count,
                           "function": functions.get("FAlbedo"), "transparency": transparency,
                           "diffuse": [round(v, 3) for v in diffuse],
                           "colour_mask": constants.get("CBColorMask"), "lod0_vertices": lod0.get(index, 0),
                           "mask": ("none" if functions.get("FAlbedo") in PLAIN_ALBEDO else
                                    "neutral" if _neutral_mask(constants) else "blood overlay (inferred)"),
                           "shared_with": sorted(shared_with or ()),
                           "blend_map": (row["slots"].get("tAlbedoBlendMap") or "").rsplit("\\", 1)[-1] or None,
                           "normal": (row["slots"].get("tNormalMap") or "").rsplit("\\", 1)[-1] or None,
                           "specular": (row["slots"].get("tSpecularMap") or "").rsplit("\\", 1)[-1] or None})
    if not candidates:
        error = EnemyError(f"no material of the class can carry a donor ({len(refused)} refused; first: "
                           f"{refused[:2]})")
        error.refused = refused
        raise error
    candidates.sort(key=lambda c: (c["size"][0] * c["size"][1] < 512 * 512, c["mask"].startswith("blood"),
                                   c["transparency"] != "FTransparency", -c["size"][0] * c["size"][1],
                                   -min(c["diffuse"]), -c["lod0_vertices"], c["index"]))
    best = dict(candidates[0])
    best["candidates"] = [{k: c[k] for k in ("index", "name", "size", "function", "transparency", "mask")}
                          for c in candidates]
    best["refused"] = refused
    return best

def _dims(bounds: dict) -> dict:
    return {"height_cm": round(bounds["max"]["y"] - bounds["min"]["y"], 1),
            "width_cm": round(bounds["max"]["x"] - bounds["min"]["x"], 1),
            "depth_cm": round(bounds["max"]["z"] - bounds["min"]["z"], 1),
            "floor_cm": round(bounds["min"]["y"], 1)}


def donor_shape(source: Path, roles: dict[str, str], geometry=None) -> dict:
    """The donor's rig in its own space: whether it stands (head over hip over feet, feet apart to the sides the
    hands are), and how much of its vertex height the head-to-foot span is (`joint_span`: a stray vertex far away, as
    the FF7 field models in another unit scale had, makes it small)."""
    _gltf, names, _parents, joints = M._source_rig(Path(source), roles)
    point = {role: np.asarray(joints[names[name]], float) for role, name in roles.items() if name in names}
    out: dict = {"codes": []}
    needed = ("hip", "head", "l_foot", "r_foot", "l_hand", "r_hand")
    if any(role not in point for role in needed):
        out["codes"].append("rig")
        return out
    if geometry is not None:
        ys = [v["position"][1] for v in geometry[0]]
        vertex_height = max(ys) - min(ys)
    else:
        vertex_height = point["head"][1] - min(point["l_foot"][1], point["r_foot"][1])
    span = point["head"][1] - min(point["l_foot"][1], point["r_foot"][1])
    out["joint_span"] = round(float(span / vertex_height), 3) if vertex_height > 1e-9 else 0.0
    if not point["head"][1] > point["hip"][1] > max(point["l_foot"][1], point["r_foot"][1]):
        out["codes"].append("rig")
        out["rig"] = "head, hip and feet are not stacked as a standing person's"
    side = point["l_foot"] - point["r_foot"]
    hands = point["l_hand"] - point["r_hand"]
    side[1] = hands[1] = 0.0
    if np.linalg.norm(side) > 1e-9 and np.linalg.norm(hands) > 1e-9 and float(side @ hands) <= 0:
        out["codes"].append("rig")
        out["rig"] = "the left hand is on the right foot's side"
    if out["joint_span"] < FIT["joint_span"]:
        out["codes"].append("exploded")
    return out


def fit_report(native_bounds: dict, donor_bounds: dict, *, rest_degrees: float | None = None, shape: dict | None = None,
               skin_bones: int | None = None, kind: str | None = None, vertices: int | None = None) -> dict:
    """The donor's fitted bind-pose box against the native class body, and every reason to refuse it.

    Codes: `tall` / `short` (height outside FIT["height"] of the native), `flat` (under 15 cm deep), `floats` / `sinks`
    (the box floor off the native floor by more than a tenth of the height), `wide` / `deep` (the audit's limits;
    `wide` also past 1.35 of the native height, whatever the native width),
    `box` (wider and deeper than tall: not a standing person), `stretched` (rests off the native bind past the keep
    tolerance), `rig` / `exploded` (`donor_shape`), `few_bones` (the skin uses fewer native bones than a body),
    `heavy` (more vertices than one record takes), `prop` (the library says it is not a character)."""
    native, fitted = _dims(native_bounds), _dims(donor_bounds)
    nh = max(native["height_cm"], 1e-6)
    ratios = {"height": round(fitted["height_cm"] / nh, 3),
              "width": round(fitted["width_cm"] / max(native["width_cm"], 1e-6), 3),
              "depth_to_height": round(fitted["depth_cm"] / nh, 3),
              "floor_offset": round((fitted["floor_cm"] - native["floor_cm"]) / nh, 3)}
    codes = []
    if ratios["height"] > FIT["height"][1]:
        codes.append("tall")
    if ratios["height"] < FIT["height"][0]:
        codes.append("short")
    if fitted["depth_cm"] < FIT["min_depth_cm"]:
        codes.append("flat")
    if ratios["floor_offset"] > FIT["floor"]:
        codes.append("floats")
    if ratios["floor_offset"] < -FIT["floor"]:
        codes.append("sinks")
    ratios["width_to_height"] = round(fitted["width_cm"] / nh, 3)
    if ratios["width"] > FIT["wide"] or ratios["width_to_height"] > FIT["wide_to_height"]:
        codes.append("wide")
    if ratios["depth_to_height"] > FIT["deep"]:
        codes.append("deep")
    if fitted["width_cm"] > fitted["height_cm"] and fitted["depth_cm"] > fitted["height_cm"]:
        codes.append("box")
    if rest_degrees is not None and rest_degrees > FIT["rest_degrees"]:
        codes.append("stretched")
    for code in (shape or {}).get("codes", ()):
        if code not in codes:
            codes.append(code)
    if skin_bones is not None and skin_bones < FIT["min_bones"]:
        codes.append("few_bones")
    if vertices is not None and vertices > FIT["max_vertices"]:
        codes.append("heavy")
    if kind and str(kind).lower() in NON_CHARACTER_KINDS:
        codes.append("prop")
    return {"passed": not codes, "codes": codes, "native": native, "fitted": fitted, "ratios": ratios,
            "rest_degrees": rest_degrees, "joint_span": (shape or {}).get("joint_span"),
            "rig": (shape or {}).get("rig"), "skin_bones": skin_bones, "vertices": vertices, "kind": kind,
            "limits": {k: list(v) if isinstance(v, tuple) else v for k, v in FIT.items()}}


def skin_bone_count(donor_model) -> int:
    """Distinct native bones the donor record's four-weight skin names with a weight (w0 SNORM16 at +6, joints at +16,
    w1 / w2 half at +24, w3 the remainder; `mtf_author.build_one_mesh`'s layout)."""
    data, record = donor_model.mesh_bytes(0)
    stride = record["vertex_stride"]
    used = set()
    for k in range(record["vertex_count"]):
        base = k * stride
        w0 = struct.unpack_from("<h", data, base + 6)[0] / 32767.0
        w1, w2 = struct.unpack_from("<2e", data, base + 24)
        weights = (w0, float(w1), float(w2), max(0.0, 1.0 - w0 - float(w1) - float(w2)))
        for bone, weight in zip(data[base + 16:base + 20], weights):
            if weight > 1e-3:
                used.add(bone)
    return len(used)


def opaque_atlas(image, *, threshold: float = 0.5):
    """The donor atlas as the opaque RGB the enemy material draws: a texel's colour composited over the colour bled
    in from the nearest opaque texels (normalised Gaussian fills at growing radii), never over the RGB a transparent
    texel happens to hold. Measured 2026-11-10: `stranglehold_teahouse_boss`'s atlas is 80 % transparent and its face
    cell holds red / yellow speckle under alpha 0, which a plain RGB conversion wrote onto the zombie's head."""
    from PIL import Image

    rgba = np.asarray(image.convert("RGBA"), np.float32) / 255.0
    alpha = rgba[..., 3:4]
    rgb = rgba[..., :3]
    if float(alpha.min()) >= 0.999:
        return image.convert("RGB")
    weight = (alpha >= threshold).astype(np.float32)
    if not weight.any():
        return image.convert("RGB")

    def box(plane: np.ndarray, radius: int, axis: int) -> np.ndarray:
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius + 1, radius)
        total = np.cumsum(np.pad(plane, pad, mode="edge"), axis=axis, dtype=np.float64)
        upper = np.take(total, np.arange(2 * radius + 1, total.shape[axis]), axis=axis)
        lower = np.take(total, np.arange(0, total.shape[axis] - 2 * radius - 1), axis=axis)
        return ((upper - lower) / (2 * radius + 1)).astype(np.float32)

    def blur(plane: np.ndarray, radius: float) -> np.ndarray:
        """Three box passes per axis: close to a Gaussian of `radius`."""
        size = max(1, int(round(radius / 1.7)))
        out = plane
        for _ in range(3):
            out = box(box(out, size, 0), size, 1)
        return out

    fill = np.zeros_like(rgb)
    have = np.zeros(alpha.shape[:2], bool)
    for radius in (3, 12, 48, 192):
        den = blur(weight[..., 0], radius)
        take = ~have & (den > 1e-3)
        if take.any():
            for channel in range(3):
                num = blur(rgb[..., channel] * weight[..., 0], radius)
                fill[..., channel][take] = num[take] / den[take]
            have |= take
    if (~have).any():
        fill[~have] = (rgb * weight).reshape(-1, 3).sum(0) / max(float(weight.sum()), 1.0)
    out = rgb * alpha + fill * (1.0 - alpha)
    return Image.fromarray(np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8), "RGB")


def graft(native_raw: bytes, donor_raw: bytes, groups, material_index: int, template_index: int) -> tuple[bytes, dict]:
    """The class body with every native record collapsed and the one-mesh donor added once per carrier group
    (`re5_enemy_writer.graft_pieces`, the RE5 writer's own function, with the RE6 template record)."""
    from . import re5_enemy_writer as R5

    try:
        return R5.graft_pieces(mt_model.parse_mod(native_raw), [(mt_model.parse_mod(donor_raw), list(groups),
                                                                  int(material_index))], template=template_index)
    except R5.EnemyWriterError as exc:
        raise EnemyError(f"graft: {exc}") from exc


def build_class(archive: bytes, cls: str, source: Path, roles: dict[str, str], *, choice: dict, carriers: list[int],
                geometry=None, atlas=None, kind: str | None = "character", chroma: bool = True,
                vertex_budget: int | None = None, deviation: dict | None = None) -> tuple[bytes, dict]:
    """(archive, receipt): one class body dressed as one library donor, or DonorRefused with the fit report.

    The donor is authored by `re6_switch_models.build_body` in `keep` mode (the native bind untouched, the fitted
    surface in that pose, atlas UVs) on the class's own skeleton, measured by `fit_report`, then grafted into every
    carrier group (`graft`); its atlas goes into `choice["albedo"]` as Y'CbCr (`replace_albedo`, chroma on). Only the
    body MOD entry and that albedo change; everything else of the archive is byte for byte the shipped one."""
    from PIL import Image

    from .re6_switch_tex import replace_albedo

    native = bytes(archive)
    arc = mt_arc.parse(native)
    index, mrl, raw = class_body(arc, cls)
    if M._find_model(arc)[0] != index:
        raise EnemyError(f"{cls}: its body is not the largest skeleton, so build_body would author another model")
    model = mt_model.parse_mod(raw)
    template = template_mesh(model, choice["index"])
    deviation = deviation or M.pose_deviation(native, Path(source), roles)
    shape = donor_shape(Path(source), roles, geometry)
    bounds = model.bounds()
    if deviation["max_degrees"] > FIT["rest_degrees"]:
        report = fit_report(bounds, bounds, rest_degrees=deviation["max_degrees"], shape=shape, kind=kind)
        report["fitted"] = None
        raise DonorRefused(f"rests {deviation['max_degrees']:.0f} degrees off the bind pose (keep only)", report)
    height = bounds["max"]["y"] - bounds["min"]["y"]
    payload, body = M.build_body(native, Path(source), source_roles=roles, height=float(height), textures=True,
                                 source_geometry=geometry, material_index=choice["index"], template_index=template,
                                 bind_mode="keep")
    donor_raw = mt_arc.parse(payload).entries[index]
    donor_raw = _raw(donor_raw)
    donor = mt_model.parse_mod(donor_raw)
    vertices = donor.meshes()[0]["vertex_count"]
    report = fit_report(bounds, donor.bounds(), rest_degrees=deviation["max_degrees"], shape=shape,
                        skin_bones=skin_bone_count(donor), kind=kind, vertices=vertices)
    budget = vertex_budget or max(60000, int(1.5 * model.header()["vertex_count"]))
    report["copies"] = len(carriers)
    report["vertex_budget"] = budget
    if vertices * len(carriers) > budget and "heavy" not in report["codes"]:
        report["codes"].append("heavy")
        report["passed"] = False
    if not report["passed"]:
        raise DonorRefused(f"does not fit {cls}: {', '.join(report['codes'])}", report)
    grafted, graft_report = graft(raw, donor_raw, carriers, choice["index"], template)
    out = mtf_author.replace_archive_model(native, index, grafted)
    texture_rows = []
    if atlas is not None:
        def writer(surface, _image=atlas):
            scaled = _image if _image.size == (surface.width, surface.height) else _image.resize(
                (surface.width, surface.height), Image.LANCZOS)
            return replace_albedo(surface.data, scaled, chroma=chroma)
        out, texture_rows = M.replace_textures(out, {choice["albedo"]: writer})
        if any(row.get("missing") for row in texture_rows):
            raise EnemyError(f"{cls}: the albedo {choice['albedo']} is not a TEX of the archive")
    before, after = mt_arc.parse(native), mt_arc.parse(out)
    changed = [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if a.data != b.data]
    allowed = {index} | {row["entry"] for row in texture_rows}
    if len(before.entries) != len(after.entries) or set(changed) - allowed or \
            [e.name for e in before.entries] != [e.name for e in after.entries]:
        raise EnemyError(f"{cls}: entries other than the body MOD and its albedo changed: {sorted(set(changed) - allowed)}")
    check = mt_model.parse_mod(_raw(after.entries[index]))
    if not check.split_valid() or check.header()["mesh_count"] != model.header()["mesh_count"] + len(carriers):
        raise EnemyError(f"{cls}: the written body does not read back")
    receipt = {"class": cls, "body_entry": arc.entries[index].name, "body_index": index, "mrl_index": mrl,
               "material": {k: v for k, v in choice.items() if k not in ("candidates", "refused")},
               "template_record": template, "carrier_groups": list(carriers), "fit": report,
               "rest_pose_deviation": deviation, "bind_mode": "keep", "pose_mode": body.get("pose_mode"),
               "fitted_height": body.get("fitted_height"), "height_clamped": body.get("height_clamped"),
               "uniform_scale": body.get("uniform_scale"), "donor_vertices": vertices,
               "donor_triangles": body.get("triangle_count"), "graft": graft_report,
               "textures": texture_rows or "native (geometry only)", "changed_entries": changed,
               "unchanged_entries": len(after.entries) - len(changed),
               "source_sha256": hashlib.sha256(native).hexdigest(), "archive_sha256": hashlib.sha256(out).hexdigest(),
               "archive_bytes": len(out), "live_verified": False}
    return out, receipt


def verify_class(original: bytes, candidate: bytes, cls: str, *, carriers: list[int], material_index: int,
                 albedos: tuple[str, ...] = ()) -> dict:
    """Re-read a written class archive against the shipped one (no state from the writer): the entry table is the
    native one (names, types, order); only the body MOD and the named albedos differ; the skeleton, group and material
    blocks are byte for byte native; every native record keeps its 56 bytes (matched by mesh id) and draws no
    triangle; each carrier group holds exactly one donor record (all LODs, the donor material) and every donor record
    holds the same vertices and triangles; each named albedo is still an `0x2B` TEX of the native size and mip count.
    Raises EnemyError on the first failure; returns the counts."""
    from .re6_switch_tex import from_arc_entry

    before, after = mt_arc.parse(bytes(original)), mt_arc.parse(bytes(candidate))
    if [(e.name, e.hash) for e in before.entries] != [(e.name, e.hash) for e in after.entries]:
        raise EnemyError("the entry table is not the native one")
    index, _mrl, raw = class_body(before, cls)
    wanted = {name.lower() for name in albedos}
    changed = [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if a.data != b.data]
    stray = [i for i in changed if i != index and before.entries[i].name.lower() not in wanted]
    if stray:
        raise EnemyError(f"entries other than the body and its albedos changed: {stray[:5]}")
    native, model = mt_model.parse_mod(raw), mt_model.parse_mod(_raw(after.entries[index]))
    no, nn = native.header()["offsets"], model.header()["offsets"]
    if native.raw[no["bones"]:no["meshes"]] != model.raw[nn["bones"]:nn["meshes"]]:
        raise EnemyError("the skeleton, group or material block changed")
    if not model.split_valid():
        raise EnemyError("the written mesh table does not account for its vertices")
    old = {r["mesh_id"]: i for i, r in enumerate(native.meshes())}
    records = model.meshes()
    donors = [i for i, r in enumerate(records) if r["mesh_id"] not in old]
    for i, record in enumerate(records):
        if record["mesh_id"] not in old:
            continue
        o = old[record["mesh_id"]]
        a = native.raw[no["meshes"] + 56 * o:no["meshes"] + 56 * o + 56]
        b = model.raw[nn["meshes"] + 56 * i:nn["meshes"] + 56 * i + 56]
        if a != b:
            raise EnemyError(f"native record {o} (mesh id {record['mesh_id']}) changed")
        if mtf_author.mesh_triangles(model, i):
            raise EnemyError(f"native record {o} still draws triangles")
    groups = sorted(records[i]["group_index"] for i in donors)
    if groups != sorted(carriers):
        raise EnemyError(f"donor records sit in groups {groups}, not the carriers {sorted(carriers)}")
    if {(records[i]["level_of_detail"], records[i]["material_index"]) for i in donors} != {(0xFF, material_index)}:
        raise EnemyError("a donor record is not on every LOD with the donor material")
    first = donors[0]
    shape = (model.mesh_bytes(first)[0], mtf_author.mesh_triangles(model, first))
    if not shape[1]:
        raise EnemyError("the donor record has no triangles")
    for i in donors[1:]:
        if (model.mesh_bytes(i)[0], mtf_author.mesh_triangles(model, i)) != shape:
            raise EnemyError(f"donor record {i} differs from the first")
    for name in albedos:
        entry_before = next(e for e in before.entries if e.name.lower() == name.lower() and e.hash == 0x241F5DEB)
        entry_after = next(e for e in after.entries if e.name.lower() == name.lower() and e.hash == 0x241F5DEB)
        a, b = from_arc_entry(entry_before), from_arc_entry(entry_after)
        if (b.format, b.width, b.height, b.mip_count) != (a.format, a.width, a.height, a.mip_count) or \
                b.format != ALBEDO_FORMAT or len(b.data) != len(a.data) or b.data[:8] != a.data[:8]:
            raise EnemyError(f"{name} is not the native TEX shape")
    return {"changed_entries": changed, "native_records": len(old), "donor_records": len(donors),
            "donor_vertices": records[first]["vertex_count"], "donor_triangles": len(shape[1]),
            "albedos_checked": len(albedos), "sha256": hashlib.sha256(bytes(candidate)).hexdigest()}
