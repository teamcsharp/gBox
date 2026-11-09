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
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import zlib
from pathlib import Path

from . import mt_arc, mt_model, re6_switch_models as M

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
