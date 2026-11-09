"""RE4 (Switch) Mercenaries stage greybox: the room's albedos redrawn as Unreal-style grids, the RE5 look and label rule.

An offline writer for the room texture archives `imagepackhd/440004XX.pack.fen` of RE4 Switch (title 010099A00BC1E000).
It changes one file per stage - the archive - and nothing in the room pack itself. Nothing here launches a game or talks
to the gBox API; every output is a candidate with a receipt that says `live_verified: false`.

**What a room is** (measured on `st4/r400.udas`, `r402`, `r403`, `r404`, 2026-11-09): a UDAS pack whose DAT slot 4 is
`SMD`, the scene. The SMD holds a 0x40 header (`u16 0x40, u16 instance count, u32 A, u32 B, u32 C`, floats), the
instance table at 0x40 (0x48 bytes each: `+0x14 flags, +0x18 f32[3] position, +0x24 f32[3] rotation in radians,
+0x30 f32[3] scale, +0x3c u16 model index`), then three regions: A (unread), B (the GameCube-era TPL with its pixels,
magic 0x0020AF30), C (the scene models in the GameCube BIN layout, 0x60 header, unread), then the HD models - one
HD BIN per model (`re4_switch_assets.HdBin`: one bone, no weight sets, version 0x20010801) - and last an HD TPL whose
images name `44000400.pack.fen` entry k (115 images for r400). The instance's model index counts the HD models in file
order (inferred: the distinct index count equals the HD model count in all four rooms; the GC-layout models in C have
the same count). Every scene material binds the room TPL's image by index (byte 12 diffuse, byte 14 opacity).

**The look** (`build`): every archive entry a scene material binds as a diffuse is replaced by a grid of the same
pixel size, DXT format and mip count, drawn with the RE5 rule (`re5_stage_greybox.grid_image`): a blue "1024" grid
on floors with the metre span in a corner, a grey metre grid on walls, a checker elsewhere; the native alpha channel
is kept (cut-out fences and foliage). Floor / wall / other is decided by the geometry alone - RE4 textures have no
names - from the area shares of up-, side- and down-facing world-space triangles that sample the texture, and the
grid has one cell per metre of the span one UV tile covers (the UV-to-world Jacobian; positions are millimetres, 1
unit = 1 mm, Leon stands 1,837 high). Opacity maps and entries no scene material binds stay native.
"""
from __future__ import annotations

import collections
import hashlib
import io
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import re4_switch_assets as A
from . import re5_stage_greybox as R5

TITLE_ID = "010099A00BC1E000"
GAME_ID = "270a15eb98dab4d7"
IMAGE_DIR = "bio4/imagepackhd"
SMD_SLOT, SMX_SLOT = 4, 5
INSTANCE_AT, INSTANCE_BYTES = 0x40, 0x48
GC_TPL_MAGIC = 0x0020AF30
MM_PER_CM = 10.0
#: The Mercenaries rooms (re4_menus.STAGE_ROOMS) and their texture archives (the HD TPL of each room names it).
STAGES = {"Village": ("r400", "44000400.pack.fen"), "Castle": ("r402", "44000402.pack.fen"),
          "Base": ("r403", "44000403.pack.fen"), "Waterworld": ("r404", "44000404.pack.fen")}
UP, SIDE = R5.UP, R5.SIDE


class GreyboxError(ValueError):
    """The room is not the measured layout, or a check the writer relies on failed."""


# --- the scene -------------------------------------------------------------------------------------------------------

@dataclass
class Instance:
    index: int
    model: int
    flags: int
    position: np.ndarray
    rotation: np.ndarray
    scale: np.ndarray

    def matrix(self) -> np.ndarray:
        """Scale, then rotate about x, y, z in that order (an assumption: most instances rotate about y only, which
        every order agrees on; the receipt counts the others)."""
        sx, sy, sz = self.scale
        rx, ry, rz = self.rotation
        cx, sxn = math.cos(rx), math.sin(rx)
        cy, syn = math.cos(ry), math.sin(ry)
        cz, szn = math.cos(rz), math.sin(rz)
        mx = np.array([[1, 0, 0], [0, cx, -sxn], [0, sxn, cx]])
        my = np.array([[cy, 0, syn], [0, 1, 0], [-syn, 0, cy]])
        mz = np.array([[cz, -szn, 0], [szn, cz, 0], [0, 0, 1]])
        return mz @ my @ mx @ np.diag([sx, sy, sz])


@dataclass
class Scene:
    """A room's SMD: its instances, its HD models and the HD texture table."""
    count: int
    regions: tuple
    instances: list[Instance]
    models: list[A.HdBin]
    model_offsets: list[int]
    tpl: A.Tpl
    tpl_offset: int
    notes: dict = field(default_factory=dict)

    def archive(self) -> str:
        names = {image.archive() for image in self.tpl.images}
        if len(names) != 1:
            raise GreyboxError(f"the room TPL names several archives: {sorted(names)}")
        return names.pop()


def parse_scene(smd: bytes) -> Scene:
    if len(smd) < INSTANCE_AT + 4:
        raise GreyboxError("SMD too short")
    head, count, a, b, c = struct.unpack_from("<HHIII", smd, 0)
    if head != INSTANCE_AT or not (INSTANCE_AT <= a <= b <= c <= len(smd)):
        raise GreyboxError("not the measured SMD header (0x40, instance count, three ascending region offsets)")
    # The header's count is one more than the entries the table holds (measured on the four rooms: the entry at
    # count - 1 would overlap region A and reads as region A's offset words); the table is padded to 32 bytes.
    count -= 1
    if count < 1 or INSTANCE_AT + INSTANCE_BYTES * count > a:
        raise GreyboxError("the instance table runs into region A")
    tpl_at = next((i for i in range(len(smd) - 4 - (len(smd) % 4), c, -4)
                   if struct.unpack_from("<I", smd, i)[0] == A.TPL_MAGIC), None)
    if tpl_at is None:
        raise GreyboxError("no HD TPL after the models")
    tpl = A.Tpl.parse(smd[tpl_at:])
    offsets = [i for i in range(c, tpl_at, 32)
               if struct.unpack_from("<Q", smd, i)[0] == A.BIN_HEAD
               and struct.unpack_from("<I", smd, i + 0x5C)[0] in (0x20010801, 0x20030818)]
    if not offsets:
        raise GreyboxError("no HD BIN model between region C and the HD TPL")
    models = []
    for k, at in enumerate(offsets):
        end = offsets[k + 1] if k + 1 < len(offsets) else tpl_at
        try:
            models.append(A.HdBin.parse(smd[at:end]))
        except A.AssetError as exc:
            raise GreyboxError(f"scene model {k} at {at:#x}: {exc}") from exc
    instances = []
    for k in range(count):
        at = INSTANCE_AT + INSTANCE_BYTES * k
        flags = struct.unpack_from("<I", smd, at + 0x14)[0]
        position = np.array(struct.unpack_from("<3f", smd, at + 0x18))
        rotation = np.array(struct.unpack_from("<3f", smd, at + 0x24))
        scale = np.array(struct.unpack_from("<3f", smd, at + 0x30))
        model = struct.unpack_from("<H", smd, at + 0x3C)[0]
        instances.append(Instance(k, model, flags, position, rotation, scale))
    indexed = {inst.model for inst in instances}
    notes = {"instances": count, "models": len(models), "distinct_model_indices": len(indexed),
             "instances_past_the_model_list": sum(inst.model >= len(models) for inst in instances),
             "instances_with_x_or_z_rotation": sum(bool(abs(inst.rotation[0]) > 1e-4 or abs(inst.rotation[2]) > 1e-4)
                                                   for inst in instances),
             "instances_with_zero_scale": sum(bool((inst.scale == 0).any()) for inst in instances),
             "gc_tpl_in_B": any(struct.unpack_from("<I", smd, b + at)[0] == GC_TPL_MAGIC
                                for at in range(0, min(0x40, c - b - 3), 4)),
             "tpl_images": len(tpl.images)}
    return Scene(count, (a, b, c), instances, models, offsets, tpl, tpl_at, notes)


def room_scene(udas: bytes) -> Scene:
    """The scene of a room pack (`st4/rNNN.udas`): DAT slot 4 must be the SMD."""
    _pack, dat = A.pack_slots(udas)
    if len(dat.slots) <= SMD_SLOT or dat.slots[SMD_SLOT][0] != "SMD":
        raise GreyboxError("the room pack's slot 4 is not the SMD scene")
    return parse_scene(dat.slots[SMD_SLOT][1])


# --- measurement -------------------------------------------------------------------------------------------------------

@dataclass
class Surface:
    """Everything measured about one archive entry the scene draws."""
    entry: int
    image: int                     # index in the room TPL
    width: int
    height: int
    fourcc: str
    mipmaps: int
    nominal: tuple
    roles: set = field(default_factory=set)        # 'diffuse', 'opacity', ...
    materials: int = 0
    instances: int = 0
    area_cm2: float = 0.0
    up_cm2: float = 0.0
    side_cm2: float = 0.0
    down_cm2: float = 0.0
    triangles: int = 0
    tile_u_cm: float | None = None
    tile_v_cm: float | None = None
    tile_u_quartiles: tuple | None = None
    tile_v_quartiles: tuple | None = None
    _u: list = field(default_factory=list, repr=False)
    _v: list = field(default_factory=list, repr=False)
    _w: list = field(default_factory=list, repr=False)

    def shares(self) -> dict:
        total = self.area_cm2 or 1.0
        return {"up": self.up_cm2 / total, "side": self.side_cm2 / total, "down": self.down_cm2 / total}

    def settle(self) -> None:
        for axis, samples in (("u", self._u), ("v", self._v)):
            if not samples:
                continue
            values, weights = np.asarray(samples, float), np.asarray(self._w, float)
            order = np.argsort(values)
            values, weights = values[order], weights[order]
            cumulative = np.cumsum(weights) / weights.sum()
            q = tuple(float(values[min(len(values) - 1, int(np.searchsorted(cumulative, p)))]) for p in (0.25, 0.5, 0.75))
            setattr(self, f"tile_{axis}_cm", q[1])
            setattr(self, f"tile_{axis}_quartiles", (q[0], q[2]))

    def report(self) -> dict:
        return {"entry": self.entry, "image": self.image, "width": self.width, "height": self.height,
                "fourcc": self.fourcc, "mips": self.mipmaps, "nominal": list(self.nominal), "roles": sorted(self.roles),
                "materials": self.materials, "instances": self.instances, "triangles": self.triangles,
                "area_m2": round(self.area_cm2 / 1e4, 2), "shares": {k: round(v, 3) for k, v in self.shares().items()},
                "tile_u_cm": None if self.tile_u_cm is None else round(self.tile_u_cm, 1),
                "tile_v_cm": None if self.tile_v_cm is None else round(self.tile_v_cm, 1),
                "tile_u_quartiles_cm": None if self.tile_u_quartiles is None else [round(v, 1) for v in self.tile_u_quartiles],
                "tile_v_quartiles_cm": None if self.tile_v_quartiles is None else [round(v, 1) for v in self.tile_v_quartiles]}


def surfaces_of(scene: Scene, archive: A.ImagePack) -> dict[int, Surface]:
    """One Surface per archive entry the room TPL names, before any geometry is charged."""
    out = {}
    infos = archive.textures()
    for k, image in enumerate(scene.tpl.images):
        if image.index >= len(infos):
            raise GreyboxError(f"TPL image {k} names entry {image.index}, the archive has {len(infos)}")
        info = infos[image.index]
        if image.index in out:
            raise GreyboxError(f"two TPL images name entry {image.index}")
        out[image.index] = Surface(image.index, k, info["width"], info["height"], info["fourcc"], info["mipmaps"],
                                   (image.width, image.height))
    return out


def _charge(surface: Surface, positions, uvs, faces) -> None:
    p0, p1, p2 = (positions[faces[:, i]] for i in range(3))
    e1, e2 = p1 - p0, p2 - p0
    cross = np.cross(e1, e2)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    keep = area > 1e-3
    if not keep.any():
        return
    area = area[keep]
    normal = cross[keep] / (2.0 * area)[:, None]
    ny = normal[:, 1]
    surface.triangles += int(keep.sum())
    surface.area_cm2 += float(area.sum())
    surface.up_cm2 += float(area[ny > UP].sum())
    surface.down_cm2 += float(area[ny < -UP].sum())
    surface.side_cm2 += float(area[np.abs(ny) <= SIDE].sum())
    t0, t1, t2 = (uvs[faces[keep, i]] for i in range(3))
    d1, d2 = t1 - t0, t2 - t0
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    ok = np.abs(det) > 1e-9
    if not ok.any():
        return
    e1k, e2k = e1[keep][ok], e2[keep][ok]
    tangent = (e1k * d2[ok, 1:2] - e2k * d1[ok, 1:2]) / det[ok, None]
    bitangent = (e2k * d1[ok, 0:1] - e1k * d2[ok, 0:1]) / det[ok, None]
    u_cm, v_cm = np.linalg.norm(tangent, axis=1), np.linalg.norm(bitangent, axis=1)
    sane = (u_cm > 0.1) & (u_cm < 1e5) & (v_cm > 0.1) & (v_cm < 1e5)
    surface._u.extend(u_cm[sane].tolist())
    surface._v.extend(v_cm[sane].tolist())
    surface._w.extend(area[ok][sane].tolist())


def measure(scene: Scene, archive: A.ImagePack) -> tuple[dict[int, Surface], dict]:
    """Charge every world-space triangle of every placed model to the archive entry its material binds as diffuse
    (and note the opacity bindings); returns ({entry: Surface}, notes). Positions become centimetres."""
    surfaces = surfaces_of(scene, archive)
    by_image = {s.image: s for s in surfaces.values()}
    notes = dict(scene.notes) | {"triangles": 0, "materials_without_diffuse": 0, "images_out_of_table": 0,
                                 "instances_skipped": 0}
    per_model: list[list[tuple[int, np.ndarray]]] = []
    for model in scene.models:
        faces_by_material = A.triangles(model.materials())
        rows = []
        for material, faces in zip(model.materials(), faces_by_material):
            for slot, role in ((12, "diffuse"), (13, "bump"), (14, "opacity"), (15, "specular"), (23, "custom")):
                image = material.header[slot]
                if image == 0xFF:
                    continue
                if image not in by_image:
                    notes["images_out_of_table"] += 1
                    continue
                by_image[image].roles.add(role)
                if role == "diffuse":
                    by_image[image].materials += 1
                    rows.append((image, faces))
            if material.header[12] == 0xFF:
                notes["materials_without_diffuse"] += 1
        per_model.append(rows)
    for inst in scene.instances:
        if inst.model >= len(scene.models) or (inst.scale == 0).any():
            notes["instances_skipped"] += 1
            continue
        model = scene.models[inst.model]
        world = (model.positions().astype(np.float64) @ inst.matrix().T + inst.position) / MM_PER_CM
        uvs = model.uvs().astype(np.float64)
        for image, faces in per_model[inst.model]:
            if not len(faces):
                continue
            by_image[image].instances += 1
            notes["triangles"] += len(faces)
            _charge(by_image[image], world, uvs, faces)
    for surface in surfaces.values():
        surface.settle()
    return surfaces, notes


def classify(surface: Surface) -> tuple[str, str]:
    """(variant, rule) from the geometry alone: up >= 0.6 floor, side >= 0.6 wall, down >= 0.6 other; mixed = other.
    An entry no diffuse material samples, or one that is only an opacity / bump map, is not rewritten."""
    if "diffuse" not in surface.roles:
        return "keep", "not a diffuse" if surface.roles else "unbound"
    if surface.area_cm2 <= 0:
        return "other", "diffuse without placed geometry"
    shares = surface.shares()
    if shares["up"] >= 0.6:
        return "floor", "geometry:up"
    if shares["side"] >= 0.6:
        return "wall", "geometry:side"
    if shares["down"] >= 0.6:
        return "other", "geometry:down"
    return "other", "geometry:mixed"


def plan(surfaces: dict[int, Surface], overrides: dict[int, str] | None = None) -> list[dict]:
    """One row per archive entry the room draws: the variant, the rule, the cells and labels (the RE5 label rule:
    floors carry the pixel width and the span in a corner, walls and the checker carry the span)."""
    rows = []
    for entry in sorted(surfaces):
        surface = surfaces[entry]
        variant, rule = classify(surface)
        if overrides and entry in overrides:
            variant, rule = overrides[entry], "override"
            if variant not in R5.VARIANTS and variant != "keep":
                raise GreyboxError(f"override {variant!r} for entry {entry} is not a variant")
        cells_u, cells_v = R5.grid_cells(surface.tile_u_cm), R5.grid_cells(surface.tile_v_cm)
        if variant == "floor":
            label, corner = str(surface.width), R5.span_label(surface.tile_u_cm)
        else:
            u, v = R5.span_label(surface.tile_u_cm), R5.span_label(surface.tile_v_cm)
            label, corner = (u if cells_u == cells_v else f"{u} x {v}"), ""
        rows.append({"variant": variant, "rule": rule, "cells": [cells_u, cells_v], "label": label, "corner": corner,
                     **surface.report()})
    return rows


# --- the textures --------------------------------------------------------------------------------------------------------

def decode_dds(dds: bytes) -> np.ndarray:
    """Mip 0 of a DXT DDS as RGBA (Pillow's DDS reader)."""
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(dds)).convert("RGBA"), np.uint8)


def greybox_entry(native: bytes, variant: str, cells_u: int, cells_v: int, label: str, corner: str = "",
                  *, keep_alpha: bool = True) -> tuple[bytes, dict]:
    """`native` (a DDS) redrawn as a grid of the same size, fourcc and mip count, its header byte for byte; the
    native alpha channel is kept under the grid. Returns (dds, report)."""
    info = A.dds_info(native)
    image = R5.grid_image(info["width"], info["height"], variant, cells_u, cells_v, label, corner).convert("RGBA")
    pixels = np.asarray(image, np.uint8).copy()
    alpha_note = "opaque"
    if keep_alpha:
        alpha = decode_dds(native)[..., 3]
        pixels[..., 3] = alpha
        alpha_note = f"native alpha kept (min {int(alpha.min())}, max {int(alpha.max())})"
    out = A.replace_dds_pixels(native, pixels)
    return out, {"variant": variant, "cells": [cells_u, cells_v], "label": label, "corner": corner,
                 "alpha": alpha_note, "width": info["width"], "height": info["height"], "fourcc": info["fourcc"],
                 "mips": info["mipmaps"]}


def build(room: bytes, archive: bytes, *, stage: str = "", overrides: dict[int, str] | None = None,
          progress=lambda *_: None) -> tuple[bytes, dict]:
    """The room's texture archive with every scene albedo drawn as a greybox grid; returns (archive bytes, receipt).
    The room pack is read for the measurement and never written."""
    scene = room_scene(room)
    pack = A.ImagePack.parse(archive)
    if pack.build() != archive:
        raise GreyboxError("the archive does not rebuild byte-identically; refusing to write on top of it")
    if scene.archive() != f"{pack.pack_id:08x}.pack.fen":
        raise GreyboxError(f"the room names {scene.archive()}, the archive is {pack.pack_id:08x}")
    surfaces, notes = measure(scene, pack)
    rows = plan(surfaces, overrides)
    changed = []
    for row in rows:
        if row["variant"] == "keep":
            continue
        wrapper, native, tail = pack.entries[row["entry"]]
        progress(row["entry"], row["variant"])
        out, report = greybox_entry(native, row["variant"], *row["cells"], row["label"], row["corner"])
        if len(out) != len(native):
            raise GreyboxError(f"entry {row['entry']}: the rewritten DDS is {len(out)} bytes, the native {len(native)}")
        pack.entries[row["entry"]] = (wrapper, out, tail)
        row.update(report, payload_sha256=hashlib.sha256(out).hexdigest())
        changed.append(row["entry"])
    written = pack.build()
    original, final = A.ImagePack.parse(archive), A.ImagePack.parse(written)
    untouched = [i for i in range(len(original.entries)) if i not in set(changed)]
    if any(original.entries[i] != final.entries[i] for i in untouched):
        raise GreyboxError("an entry outside the albedo list changed")
    if len(final.body()) != len(original.body()):
        raise GreyboxError("the archive body changed size")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["variant"]] = counts.get(row["variant"], 0) + 1
    receipt = {
        "title_id": TITLE_ID, "game_id": GAME_ID, "stage": stage, "archive": scene.archive(),
        "route": "re4_stage_greybox.build",
        "room_sha256": hashlib.sha256(room).hexdigest(), "source_sha256": hashlib.sha256(archive).hexdigest(),
        "written_sha256": hashlib.sha256(written).hexdigest(), "bytes": len(written), "entries": len(final.entries),
        "changed_entries": sorted(changed), "unchanged_entries": len(untouched), "variants": counts,
        "measurement": notes, "textures": rows,
        "kept_native": ["the room pack (geometry, collision, lights, effects, items, enemy lists, animations)",
                        "every archive entry the scene does not bind as a diffuse (opacity maps, item and effect "
                        "textures, the entries other TPLs of the room name)", "the alpha channel of every albedo",
                        "each DDS header, fourcc, size and mip count"],
        "live_verified": False, "gameplay_verified": False,
        "what_must_be_seen": ["the whole stage drawn in grey and blue grid tiles with metre labels, lit as before (the "
                              "lighting is the room's own)", "floors blue with the pixel size and a metre tag, walls "
                              "grey with the metre label, props and mixed pieces checkered",
                              "fences, foliage and wires still cut out (native alpha)",
                              "Ganados, the player, items and effects unchanged"],
        "failure_signs": ["black screen or hang at stage load: a DDS the game rejects (bisect by variant; every entry "
                          "keeps its native header, size and mip count)",
                          "a surface still showing a photo texture: an entry bound by a material the measurement "
                          "did not see (an opacity-only binding, another TPL of the room, or the GC-layout models)",
                          "solid slabs where fences or foliage were: alpha was not kept",
                          "grid lines of very different size on one surface class: the UV measurement is off for "
                          "that texture; its tile quartiles are in the receipt",
                          "every texture the same grid scale: the instance scale or the mm unit assumption is wrong"],
        "acceptance": "experimental; offline structural checks only"}
    return written, receipt


def verify(original: bytes, candidate: bytes, receipt: dict | None = None) -> dict:
    """Structural checks a greybox candidate must pass; raises GreyboxError with the first failure."""
    before, after = A.ImagePack.parse(original), A.ImagePack.parse(candidate)
    if after.build() != candidate:
        raise GreyboxError("the candidate does not rebuild byte-identically")
    if len(before.entries) != len(after.entries) or before.pack_id != after.pack_id:
        raise GreyboxError("entry count or pack id changed")
    changed = []
    for index, (a, b) in enumerate(zip(before.entries, after.entries)):
        if a == b:
            continue
        changed.append(index)
        if a[0] != b[0] or a[2] != b[2] or len(a[1]) != len(b[1]) or a[1][:128] != b[1][:128]:
            raise GreyboxError(f"entry {index}: wrapper, padding, size or DDS header changed")
        if receipt is not None:
            row = next((r for r in receipt.get("textures", []) if r["entry"] == index), None)
            if row is None or row.get("payload_sha256") != hashlib.sha256(b[1]).hexdigest():
                raise GreyboxError(f"entry {index}: payload does not match the receipt")
    if receipt is not None and sorted(receipt.get("changed_entries", [])) != changed:
        raise GreyboxError("the receipt lists other changed entries than the archive shows")
    return {"entries": len(after.entries), "changed": changed, "unchanged": len(after.entries) - len(changed),
            "sha256": hashlib.sha256(candidate).hexdigest()}


# --- previews (the written bytes on the CPU, not the game) -------------------------------------------------------------

def contact_sheet(candidate: bytes, rows: list[dict], png: Path, *, thumb: int = 96, columns: int = 12) -> None:
    from PIL import Image, ImageDraw

    pack = A.ImagePack.parse(candidate)
    rows = sorted((r for r in rows if r["variant"] != "keep"), key=lambda r: (r["variant"], r["entry"]))
    lines = max(1, -(-len(rows) // columns))
    sheet = Image.new("RGB", (columns * thumb, lines * (thumb + 14)), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    font = R5._font(9)
    for n, row in enumerate(rows):
        image = Image.fromarray(decode_dds(pack.entries[row["entry"]][1]), "RGBA").convert("RGB").resize((thumb, thumb))
        x, y = (n % columns) * thumb, (n // columns) * (thumb + 14)
        sheet.paste(image, (x, y))
        draw.text((x + 2, y + thumb), f"{row['entry']} {row['variant'][:5]} {row['label']}"[:18], fill=(220, 220, 220), font=font)
    sheet.save(png)


def render_stage(room: bytes, candidate: bytes, png: Path, *, size: int = 1024, yaw_deg: float = 30.0,
                 pitch_deg: float = 55.0, max_triangles: int = 1_500_000, percentile: float = 1.0) -> dict:
    """An orthographic CPU view of the placed scene textured with the candidate's entries (flat shade; not the game)."""
    from PIL import Image

    scene = room_scene(room)
    pack = A.ImagePack.parse(candidate)
    textures: dict[int, np.ndarray] = {}
    for image in scene.tpl.images:
        try:
            rgb = decode_dds(pack.entries[image.index][1])[..., :3]
        except Exception:                                   # noqa: BLE001 - a texture that will not decode is skipped
            continue
        while max(rgb.shape[:2]) > 256:
            rgb = rgb[::2, ::2]
        textures[image.index] = np.ascontiguousarray(rgb)
    by_image = {k: image.index for k, image in enumerate(scene.tpl.images)}
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    rot_y = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rot_x = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    rotation = rot_x @ rot_y
    pieces = []
    for inst in scene.instances:
        if inst.model >= len(scene.models) or (inst.scale == 0).any():
            continue
        model = scene.models[inst.model]
        world = (model.positions().astype(np.float64) @ inst.matrix().T + inst.position) @ rotation.T
        uvs = model.uvs().astype(np.float64)
        for material, faces in zip(model.materials(), A.triangles(model.materials())):
            entry = by_image.get(material.header[12])
            if entry is None or entry not in textures or not len(faces):
                continue
            pieces.append((world, uvs, faces, textures[entry]))
    if not pieces:
        raise GreyboxError("nothing to draw")
    everything = np.concatenate([p for p, *_ in pieces])
    low = np.percentile(everything, percentile, axis=0)
    high = np.percentile(everything, 100 - percentile, axis=0)
    span = max(high[0] - low[0], high[1] - low[1]) or 1.0
    scale = (size - 8) / span
    canvas = np.full((size, size, 3), 24, np.uint8)
    zbuf = np.full((size, size), np.inf)
    drawn = 0
    for positions, uvs, faces, texture in pieces:
        screen = np.empty((len(positions), 2))
        screen[:, 0] = (positions[:, 0] - low[0]) * scale + 4
        screen[:, 1] = (high[1] - positions[:, 1]) * scale + 4
        depth = -positions[:, 2]
        for tri in faces:
            if drawn >= max_triangles:
                break
            p = positions[tri]
            n = np.cross(p[1] - p[0], p[2] - p[0])
            length = np.linalg.norm(n)
            if length == 0:
                continue
            n = n / length
            shade = 0.55 + 0.45 * max(0.0, float(n[1]) * 0.6 + float(n[2]) * 0.8)
            R5._rasterise(canvas, zbuf, screen[tri], depth[tri], uvs[tri], np.clip(texture * shade, 0, 255).astype(np.uint8))
            drawn += 1
    Image.fromarray(canvas, "RGB").save(png)
    return {"png": str(png), "triangles": drawn, "view": f"orthographic, yaw {yaw_deg}, pitch {pitch_deg}",
            "shows": "the candidate's entries on the placed HD scene models with a flat directional shade; not the game"}


# --- CLI ------------------------------------------------------------------------------------------------------------------

def write_overlay(out_dir: Path, archive_name: str, data: bytes, receipt: dict) -> Path:
    folder = Path(out_dir) / "romfs" / Path(IMAGE_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / archive_name
    path.write_bytes(data)
    (Path(out_dir) / "receipt.json").write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="RE4 Switch Mercenaries stage greybox writer (offline)")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("survey", help="measure a room's albedos and print the plan as JSON")
    s.add_argument("room", type=Path, help="st4/rNNN.udas")
    s.add_argument("archive", type=Path, help="the imagepackhd/440004NN.pack.fen the room names")
    b = sub.add_parser("build", help="write the greybox overlay of one stage")
    b.add_argument("room", type=Path)
    b.add_argument("archive", type=Path)
    b.add_argument("--stage", default="")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--override", action="append", default=[], help="entry=variant (floor|wall|other|sky|keep)")
    b.add_argument("--no-preview", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--original", type=Path, required=True)
    v.add_argument("--candidate", type=Path, required=True)
    v.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    if args.command == "survey":
        scene = room_scene(args.room.read_bytes())
        surfaces, notes = measure(scene, A.ImagePack.parse(args.archive.read_bytes()))
        print(json.dumps({"archive": scene.archive(), "measurement": notes, "textures": plan(surfaces)}, indent=1))
        return 0
    if args.command == "build":
        if (args.out / "receipt.json").exists():
            raise GreyboxError(f"{args.out} already holds an overlay; candidates are never overwritten")
        overrides = {int(k): v for k, v in (item.split("=", 1) for item in args.override)}
        room, archive = args.room.read_bytes(), args.archive.read_bytes()
        written, receipt = build(room, archive, stage=args.stage, overrides=overrides or None,
                                 progress=lambda entry, variant: print(f"  {variant:5} entry {entry}"))
        receipt["files"] = [{"path": f"romfs/{IMAGE_DIR}/{receipt['archive']}", "bytes": len(written),
                             "sha256": receipt["written_sha256"], "source_bytes": len(archive),
                             "source_sha256": receipt["source_sha256"]}]
        path = write_overlay(args.out, receipt["archive"], written, receipt)
        verify(archive, written, receipt)
        if not args.no_preview:
            contact_sheet(written, receipt["textures"], args.out / "textures.png")
            receipt["previews"] = [{"png": str(args.out / "textures.png"), "shows": "every written entry, mip 0"},
                                   render_stage(room, written, args.out / "stage-view.png")]
            (args.out / "receipt.json").write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"written": str(path), "sha256": receipt["written_sha256"], "bytes": receipt["bytes"],
                          "variants": receipt["variants"], "changed_entries": len(receipt["changed_entries"])}, indent=1))
        return 0
    receipt = json.loads(args.receipt.read_text(encoding="utf-8")) if args.receipt else None
    print(json.dumps(verify(args.original.read_bytes(), args.candidate.read_bytes(), receipt), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
