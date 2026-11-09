"""RE5 Switch stage greybox: the Mercenaries stage drawn like an Unreal blockout, and a prop replaced by a grid box.

Two offline writers for the stage archives `sNNN.arc` of RE5 Switch (title 010018100CD46000) and the object archives
`uOm*.arc` the stage places. Nothing here launches a game or talks to the gBox API; every output is a candidate with a
receipt that says `live_verified: false`.

**1. The greybox look** (`build`). Every albedo (`_BM`) of the stage geometry under `stage\\sNNN\\scr\\scr01\\` is
replaced by a generated Unreal-style grid texture of the same dimensions, BC7 format and mip count: a blue "1024" grid
on floors, a grey metre grid on walls, a checker on everything else, a flat tint on the sky. Normal maps, mask maps,
light maps, alpha maps, cube maps, the MRLs and the MODs stay byte for byte native, and each generated texture keeps
the native texture's own alpha channel (the alpha-tested fences, wires and foliage keep their cut-outs).

The surface class and the grid scale are measured, not guessed: the stage MODs are decoded (positions, vertex normals
and the albedo UV of every triangle), each triangle is charged to the albedo its material binds, and per texture the
area shares of up-, side- and down-facing triangles decide floor / wall / other while the UV→world Jacobian gives the
centimetres one UV tile spans along u and along v. The grid then has one cell per metre of that span, so the grid is
consistent per surface class even though the native textures tile at very different scales. Names (`jimen` = ground,
`kabe` = wall, …) are only a tie-breaker where the geometry is mixed; the receipt records which rule decided.

**2. The prop path** (`build_prop_textures`, `build_prop_box`). Every albedo an object archive's models bind is drawn
as the orange prop grid with the object's reading as its label (geometry native). One native object model (the wooden
crate `om0889` of `uOm0889.arc`) can also have its LOD-0 and LOD-1 geometry rewritten in place as a box of the
model's native bounds (`build_prop_box`); every other entry is native. The geometry is written inside the native
vertex and index allocations (the measured lesson of `mt_model.replace_part`: a moved buffer hangs the game even when
the bytes agree).

**3. The whole set** (`build_all`, CLI `all`): every stage archive and every object archive its layouts place
(`placed_objects`), one overlay folder, one receipt (`stage-greybox-all-v1`). `blueprint_look` in MercMode plays it:
`switch_mods op=blueprint` writes these archives over a copy of a build (`<build>-blueprint`), and the scheduler
plays that companion while the setting is on (docs/research/blueprint-look.md).

Live, 2026-11-09 (session ae02be4bd9974915-32e89a55f69c46db, build recovery-greybox-s400-pool-test-20261109): the
s400 overlay `f26d2836…` boots and renders - grids, metre labels, native lighting - with several wall labels reading
mirrored. The UV handedness of every texture is now measured (`Surface.mirror_share`) and the glyphs are drawn
flipped where the mapping is mirrored, both ways where a texture's surfaces are of both hands.

Measured on `s400.arc` (SHA-256 246e3dd4…, 2026-11-09), see `docs/research/re5-stage-greybox.md`; the s401..s407
survey is in `docs/research/blueprint-look.md`:

* 590 entries, all wrapped zlib streams that recompress byte-identically at level 6; `mt_arc.build(parse(x)) == x`;
  every tag is `0x40000000 | uncompressed length`.
* 264 TEX: 174 BC7 (`0x30`), 38 BC1 (`0x13`: the `_LM` light maps and the cube maps), 29 BC4 masks, 20 BC5 normals,
  2 of `0x15` and 1 of `0x07`. 159 BC7 `_BM` under `scr01` are the stage albedos; `mtf_tex.parse` accepts every one
  (header `TEX\\0 a1 80 00 20`, power-of-two, measured Tegra block-linear mips).
* 57 MOD (bone count 0 for the stage pieces) in eight vertex formats, all float32 positions at +0, a signed-byte normal
  at +12 (face-normal agreement 97.8–100 %), a tangent at +16 and the albedo UV as two half floats at +20. The
  lightmapped formats carry the light-map UV at +24 (`0x2AE06DB8`, 523 meshes) or +28 (`0x2FC0B663`, `0x32305512`);
  the vertex-coloured formats carry an RGBA8 colour at +24 (`0x29F0B449`, 686 meshes) or +28 (`0x2ED06F92`).
  `0x37607D20` (3 meshes) does not follow this layout and is skipped.
* The MRL texture slots: `0xCD06F` albedo, `0xAA6F0` light map, `0x22660` normal, `0x0ED1B` mask, `0x1698A` alpha
  map, `0x64C43` environment cube. Shader families from the material names: `XfB_L*` lightmapped, `XfB_W*`
  vertex-lit, `XfBA*` alpha-tested, `XfB_N__E*` normal-mapped with environment.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

from . import mt_arc, mt_model, mtf_author, mtf_mrl, mtf_tex

TITLE_ID = '010018100CD46000'
ARCHIVE_DIR = 'nativeNXx64/ImgNX/Archive'
STAGES = ('s400', 's401', 's402', 's403', 's404', 's405', 's406', 's407')
ALBEDO_HASH = mtf_mrl.ALBEDO_HASH          # 0xCD06F  tAlbedoMap
LIGHTMAP_HASH = 0xAA6F0
NORMAL_HASH = 0x22660
MASK_HASH = 0x0ED1B
ALPHA_MAP_HASH = 0x1698A
BC7 = (0x30, 0x31)
#: Measured component offsets of the stage (bone-less) vertex formats: float3 position at 0, s8x4 normal, half2 UV.
STAGE_LAYOUT = {
    0x287029D8: {'normal': 12, 'uv': 20},                       # 24 bytes
    0x29F0B449: {'normal': 12, 'uv': 20, 'colour': 24},         # 28: vertex-lit (W) family
    0x2AE06DB8: {'normal': 12, 'uv': 20, 'lightmap_uv': 24},    # 32: lightmapped (L) family
    0x2ED06F92: {'normal': 12, 'uv': 20, 'uv2': 24, 'colour': 28},
    0x2FC0B663: {'normal': 12, 'uv': 20, 'uv2': 24, 'lightmap_uv': 28},
    0x32305512: {'normal': 12, 'uv': 20, 'uv2': 24, 'lightmap_uv': 28},
    # the s401..s407 survey (2026-11-09, docs/research/blueprint-look.md): the same first 24 bytes (normal of unit
    # length on 100 % of the vertices, finite UVs under 64), a half2 second UV at +24; 0x33C09993 adds RGBA8 at +28
    0x2C207F5E: {'normal': 12, 'uv': 20, 'uv2': 24},            # 28: s401 (2 meshes), s407 (32)
    0x2D30A6AF: {'normal': 12, 'uv': 20, 'uv2': 24},            # 28: s405, s407 (a mesh each)
    0x33C09993: {'normal': 12, 'uv': 20, 'uv2': 24, 'colour': 28},   # 32: s405 (one 12,493-vertex piece)
}
#: Scenery folders inside a stage archive: `stage\sNNN\scr\scrNN\`. s400 draws from scr01, s402 from scr00, s405 from
#: scr01..scr07 and a piece borrowed from chapter s314 (its own folder inside s405.arc) - measured 2026-11-09.
SCENE_FOLDER = re.compile(r'stage\\s\d{3}\\scr\\scr\d{2}\\')
#: An albedo's name: `_BM`, or `_BM-NN` (s401's `_BM-62`, s405's `_BM-00` .. `_BM-97` - the same BC7 TEX container)
ALBEDO_NAME = re.compile(r'_BM(-\d+)?$')
#: Where a texture's label glyphs read mirrored: the share of its drawn area whose UV handedness is flipped must pass
#: this for the glyphs to be drawn flipped (above MIXED_LOW and below MIXED_HIGH both readings are drawn)
MIRROR_SHARE, MIXED_LOW, MIXED_HIGH = 0.5, 0.25, 0.75
UP, SIDE = 0.5, 0.5                        # |normal.y| above UP counts as floor/ceiling, below SIDE as wall
FLOOR_WORDS = ('jimen', 'jime', 'yuka', 'miti', 'michi', 'doro', 'suna', 'dobu', 'soko', 'jiso', 'asiba', 'tatami',
               'kaidan', 'road', 'floor', 'ground', 'dote')
WALL_WORDS = ('kabe', 'heki', 'totan', 'renga', 'block', 'wall', 'saku', 'hei', 'mon', 'tobira', 'door', 'mado',
              'window', 'yatai', 'biru', 'bill', 'ie', 'koya')
SKY_WORDS = ('sky', 'sora')
ROOF_WORDS = ('yane',)                     # a roof faces up like a floor; a blockout does not paint it as one
#: An albedo no measured scenery material binds and whose name says sprite / light / shadow: left native. A grid on a
#: smoke puff or a light-bulb glow would read as a bug, not a blockout (s404 `g-s404-dummysmoke_BM`, s401 `s103_denkyu01`).
EFFECT_WORDS = ('smoke', 'kemuri', 'shadow', 'kage', 'dummy', 'denkyu', 'flare', 'glow', 'hikari', 'light', 'nuki')
MIN_CELLS, MAX_CELLS = 1, 32
#: Thin cut-out surfaces (fences, wires, leaves) keep their alpha whatever the class; a solid texture keeps it too.
VARIANTS = ('floor', 'wall', 'other', 'sky', 'prop')


class GreyboxError(ValueError):
    """The input is not the measured RE5 Switch stage layout, or a check the writer relies on failed."""


# --- archive reading ---------------------------------------------------------------------------------------------

def _raw(entry) -> bytes:
    try:
        return zlib.decompress(entry.data)
    except zlib.error:
        return entry.data


def _wrap(raw: bytes) -> bytes:
    return zlib.compress(raw, 6)


def stage_scope(stage: str) -> str:
    """The folder s400 draws from (`stage\\s400\\scr\\scr01\\`); `scene_folders` finds every stage's own folders."""
    if not re.fullmatch(r's\d{3}', stage):
        raise GreyboxError(f'{stage!r} is not a stage code like s400')
    return f'stage\\{stage}\\scr\\scr01\\'


def scene_folders(arc: mt_arc.Arc) -> tuple[str, ...]:
    """Every `stage\\sNNN\\scr\\scrNN\\` folder of the archive that holds a MOD (the scenery, wherever this stage keeps
    it), sorted. Empty when the archive has no such geometry."""
    found = set()
    for entry in arc.entries:
        match = SCENE_FOLDER.match(entry.name)
        if match and _raw(entry)[:4] == b'MOD\0':
            found.add(match.group(0))
    return tuple(sorted(found))


def _in_scope(name: str, scope) -> bool:
    prefixes = (scope,) if isinstance(scope, str) else tuple(scope)
    return any(name.startswith(prefix) for prefix in prefixes)


def stage_models(arc: mt_arc.Arc, scope) -> list[tuple[str, int, int]]:
    """(name, MOD entry index, MRL entry index) for every scene piece in `scope` (one folder prefix, or several) that
    has both."""
    kinds: dict[str, dict[bytes, int]] = {}
    for index, entry in enumerate(arc.entries):
        if not _in_scope(entry.name, scope):
            continue
        magic = _raw(entry)[:4]
        if magic in (b'MOD\0', b'MRL\0'):
            kinds.setdefault(entry.name, {})[magic] = index
    return [(name, found[b'MOD\0'], found[b'MRL\0']) for name, found in sorted(kinds.items())
            if b'MOD\0' in found and b'MRL\0' in found]


def material_family(name: str) -> str:
    """The shader token of a Maya-style material name (`miti.None.XfBAL_596` -> `XfBAL`)."""
    token = name.split('.')[-1]
    return token.rstrip('0123456789_')


def alpha_tested(family: str) -> bool:
    return family.startswith('XfBA') or family.startswith('a_XfBA')


def material_bindings(mod_raw: bytes, mrl_raw: bytes) -> list[dict]:
    """Per MOD material: name, family and the paths bound to the albedo, light-map, normal, mask and alpha slots."""
    rows = []
    for record in mtf_mrl.inspect_bindings(mrl_raw, mod_raw):
        slots: dict[int, str] = {}
        for binding in record['bindings']:
            slots.setdefault(binding['shader_hash'], binding['path'])
        family = material_family(record['name'])
        rows.append({'index': record['mod_index'], 'name': record['name'], 'family': family,
                     'alpha_tested': alpha_tested(family), 'albedo': slots.get(ALBEDO_HASH),
                     'lightmap': slots.get(LIGHTMAP_HASH), 'normal': slots.get(NORMAL_HASH),
                     'mask': slots.get(MASK_HASH), 'alpha_map': slots.get(ALPHA_MAP_HASH)})
    return rows


def mesh_geometry(model: mt_model.ModFile, index: int):
    """(positions (n,3) cm, vertex normals (n,3), albedo UV (n,2), triangles (m,3) local) of one stage mesh, or None
    when the mesh is in a format whose layout is not measured or has no triangles."""
    data, record = model.mesh_bytes(index)
    layout = STAGE_LAYOUT.get(record['vertex_format'])
    if layout is None or not data or record['vertex_count'] < 3:
        return None
    stride = record['vertex_stride']
    table_stride = mt_model.fvf_stride(record['vertex_format'])      # 0x32305512 is measured here, not in the table
    if (table_stride not in (None, stride)) or len(data) != record['vertex_count'] * stride or stride < 24:
        raise GreyboxError(f'mesh {index}: stride {stride} disagrees with format {record["vertex_format"]:08x}')
    array = np.frombuffer(data, np.uint8).reshape(-1, stride)
    positions = array[:, :12].copy().view('<f4').reshape(-1, 3).astype(np.float64)
    normals = array[:, layout['normal']:layout['normal'] + 3].view(np.int8).astype(np.float64) / 127.0
    uvs = array[:, layout['uv']:layout['uv'] + 4].copy().view('<f2').reshape(-1, 2).astype(np.float64)
    triangles = np.asarray(mtf_author.mesh_triangles(model, index), np.int64).reshape(-1, 3)
    if not len(triangles):
        return None
    triangles = triangles - record['vertex_index']
    if triangles.min() < 0 or triangles.max() >= record['vertex_count']:
        raise GreyboxError(f'mesh {index}: indices leave the vertex window')
    if not (np.isfinite(positions).all() and np.isfinite(uvs).all()):
        raise GreyboxError(f'mesh {index}: positions or UVs are not finite')
    return positions, normals, uvs, triangles


# --- measurement: which texture is drawn on what, and at which scale ----------------------------------------------

@dataclass
class Surface:
    """Everything measured about one albedo texture of the stage."""
    name: str
    entry: int
    width: int
    height: int
    format: int
    mips: int
    materials: list[str] = field(default_factory=list)
    families: list[str] = field(default_factory=list)
    alpha_tested: bool = False
    area_cm2: float = 0.0
    up_cm2: float = 0.0
    side_cm2: float = 0.0
    down_cm2: float = 0.0
    triangles: int = 0
    tile_u_cm: float | None = None
    tile_v_cm: float | None = None
    tile_u_quartiles: tuple[float, float] | None = None
    tile_v_quartiles: tuple[float, float] | None = None
    #: UV handedness (2026-11-09 live frame: labels read mirrored on several walls). Of the area with a usable UV
    #: Jacobian (`handed_cm2`), `mirrored_cm2` is drawn with (T x B) . N > 0: seen from outside, the texture's u/v
    #: basis is the mirror image of the screen's right/down, so glyphs read backwards there.
    handed_cm2: float = 0.0
    mirrored_cm2: float = 0.0
    bound: bool = True             # a scenery material binds it (False: found by name only, nothing measured)
    _u_samples: list = field(default_factory=list, repr=False)
    _v_samples: list = field(default_factory=list, repr=False)
    _w_samples: list = field(default_factory=list, repr=False)

    @property
    def basename(self) -> str:
        return self.name.rsplit('\\', 1)[-1]

    def shares(self) -> dict:
        total = self.area_cm2 or 1.0
        return {'up': self.up_cm2 / total, 'side': self.side_cm2 / total, 'down': self.down_cm2 / total}

    def mirror_share(self) -> float | None:
        """The share of the measured area where the texture appears mirrored (None: no UV Jacobian measured)."""
        return None if self.handed_cm2 <= 0 else self.mirrored_cm2 / self.handed_cm2

    def settle(self) -> None:
        """Area-weighted medians and quartiles of the centimetres one UV tile spans along u and along v."""
        for axis, samples in (('u', self._u_samples), ('v', self._v_samples)):
            if not samples:
                continue
            values = np.asarray(samples, np.float64)
            weights = np.asarray(self._w_samples, np.float64)
            order = np.argsort(values)
            values, weights = values[order], weights[order]
            cumulative = np.cumsum(weights) / weights.sum()
            quartiles = tuple(float(values[min(len(values) - 1, int(np.searchsorted(cumulative, q)))])
                              for q in (0.25, 0.5, 0.75))
            setattr(self, f'tile_{axis}_cm', quartiles[1])
            setattr(self, f'tile_{axis}_quartiles', (quartiles[0], quartiles[2]))

    def report(self) -> dict:
        mirrored = self.mirror_share()
        return {'name': self.name, 'entry': self.entry, 'width': self.width, 'height': self.height,
                'format': self.format, 'mips': self.mips, 'materials': self.materials, 'families': self.families,
                'alpha_tested': self.alpha_tested, 'triangles': self.triangles, 'area_m2': round(self.area_cm2 / 1e4, 2),
                'shares': {k: round(v, 3) for k, v in self.shares().items()},
                'mirror_share': None if mirrored is None else round(mirrored, 3), 'bound': self.bound,
                'tile_u_cm': None if self.tile_u_cm is None else round(self.tile_u_cm, 1),
                'tile_v_cm': None if self.tile_v_cm is None else round(self.tile_v_cm, 1),
                'tile_u_quartiles_cm': None if self.tile_u_quartiles is None else
                [round(v, 1) for v in self.tile_u_quartiles],
                'tile_v_quartiles_cm': None if self.tile_v_quartiles is None else
                [round(v, 1) for v in self.tile_v_quartiles]}


def albedo_surfaces(arc: mt_arc.Arc, scope, extra: Iterable[str] = ()) -> dict[str, Surface]:
    """Every BC7 albedo TEX in `scope` (`_BM` / `_BM-NN` names), plus the `extra` entry names (albedos the scenery
    materials bind from elsewhere under `stage\\`), keyed by full path, before any geometry is charged to them.
    Returns the surfaces; the names that are not a BC7 TEX `mtf_tex` parses are reported by `measure`."""
    out: dict[str, Surface] = {}
    wanted = set(extra)
    for index, entry in enumerate(arc.entries):
        named = _in_scope(entry.name, scope) and bool(ALBEDO_NAME.search(entry.name))
        if not named and entry.name not in wanted:
            continue
        raw = _raw(entry)
        if raw[:4] != b'TEX\0':
            continue
        try:
            tex = mtf_tex.parse(raw)
        except ValueError:
            continue
        if tex.format not in BC7:
            continue
        if entry.name in out:
            raise GreyboxError(f'two TEX entries share the name {entry.name!r}; the writer addresses by name')
        out[entry.name] = Surface(name=entry.name, entry=index, width=tex.width, height=tex.height,
                                  format=tex.format, mips=len(tex.mips), bound=False)
    return out


def measure(arc: mt_arc.Arc, scope) -> tuple[dict[str, Surface], dict]:
    """Charge every triangle of every stage mesh to the albedo its material binds; returns (surfaces, notes).

    `scope` is one folder prefix or several (`scene_folders`). The albedos are the BC7 TEX the scenery materials bind
    in the albedo slot (wherever they live under `stage\\`) and the BC7 `_BM` TEX named in the folders; a bound
    albedo that is not a BC7 TEX `mtf_tex` parses (s403's `_NUKI`) is listed in `albedo_unparsed` and left native.
    """
    notes = {'models': 0, 'meshes': 0, 'meshes_skipped_format': 0, 'triangles': 0, 'unbound_materials': 0,
             'mrl_unparsed': [], 'albedo_unparsed': [], 'formats_skipped': {}}
    models = []
    bound_names: set[str] = set()
    for name, mod_index, mrl_index in stage_models(arc, scope):
        mod_raw, mrl_raw = _raw(arc.entries[mod_index]), _raw(arc.entries[mrl_index])
        try:
            bindings = material_bindings(mod_raw, mrl_raw)
        except mtf_mrl.MaterialBindingError as exc:
            notes['mrl_unparsed'].append({'name': name, 'reason': str(exc)})
            continue
        models.append((name, mod_raw, bindings))
        bound_names.update(b['albedo'] for b in bindings if b['albedo'] and b['albedo'].startswith('stage\\'))
    surfaces = albedo_surfaces(arc, scope, bound_names)
    notes['albedo_unparsed'] = sorted(n for n in bound_names if n not in surfaces)
    for name, mod_raw, bindings in models:
        model = mt_model.parse_mod(mod_raw)
        notes['models'] += 1
        for k, record in enumerate(model.meshes()):
            geometry = mesh_geometry(model, k)
            if geometry is None:
                notes['meshes_skipped_format'] += 1
                key = f'{record["vertex_format"]:08X}'
                notes['formats_skipped'][key] = notes['formats_skipped'].get(key, 0) + 1
                continue
            material = bindings[record['material_index']] if record['material_index'] < len(bindings) else None
            albedo = material and material['albedo']
            surface = surfaces.get(albedo) if albedo else None
            if surface is None:
                notes['unbound_materials'] += 1
                continue
            surface.bound = True
            notes['meshes'] += 1
            positions, normals, uvs, triangles = geometry
            notes['triangles'] += len(triangles)
            if material['name'] not in surface.materials:
                surface.materials.append(material['name'])
                surface.families.append(material['family'])
            surface.alpha_tested = surface.alpha_tested or material['alpha_tested']
            _charge(surface, positions, normals, uvs, triangles)
    for surface in surfaces.values():
        surface.settle()
    return surfaces, notes


def _charge(surface: Surface, positions, normals, uvs, triangles) -> None:
    p0, p1, p2 = (positions[triangles[:, i]] for i in range(3))
    e1, e2 = p1 - p0, p2 - p0
    cross = np.cross(e1, e2)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    keep = area > 1e-6
    if not keep.any():
        return
    area = area[keep]
    normal = (normals[triangles[keep, 0]] + normals[triangles[keep, 1]] + normals[triangles[keep, 2]])
    length = np.linalg.norm(normal, axis=1)
    geometric = cross[keep] / (2.0 * area)[:, None]
    normal = np.where((length > 1e-6)[:, None], normal / np.maximum(length, 1e-6)[:, None], geometric)
    ny = normal[:, 1]
    surface.triangles += int(keep.sum())
    surface.area_cm2 += float(area.sum())
    surface.up_cm2 += float(area[ny > UP].sum())
    surface.down_cm2 += float(area[ny < -UP].sum())
    surface.side_cm2 += float(area[np.abs(ny) <= SIDE].sum())
    # UV -> world Jacobian: T = cm per unit u, B = cm per unit v.
    t0, t1, t2 = (uvs[triangles[keep, i]] for i in range(3))
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
    surface._u_samples.extend(u_cm[sane].tolist())
    surface._v_samples.extend(v_cm[sane].tolist())
    surface._w_samples.extend(area[ok][sane].tolist())
    # Handedness: the image is upright to a viewer outside the surface when (T, B) turns like the screen's (right,
    # down), whose cross product points into the screen, i.e. along -N. (T x B) . N > 0 is therefore a mirrored
    # mapping; N is the geometric normal of the winding (the measured convention: CCW seen from outside).
    handed = np.einsum('ij,ij->i', np.cross(tangent, bitangent), geometric[ok])[sane]
    weights = area[ok][sane]
    surface.handed_cm2 += float(weights.sum())
    surface.mirrored_cm2 += float(weights[handed > 0].sum())


# --- classification ------------------------------------------------------------------------------------------------

def classify(surface: Surface) -> tuple[str, str]:
    """(variant, rule): the geometry decides where it is clear, the name where it is mixed, else `other`."""
    lower = surface.basename.lower()
    if any(word in lower for word in SKY_WORDS):
        return 'sky', 'name:sky'
    if any(word in lower for word in ROOF_WORDS):
        return 'other', 'name:roof'
    if surface.area_cm2 > 0:
        shares = surface.shares()
        if shares['up'] >= 0.6:
            return 'floor', 'geometry:up'
        if shares['side'] >= 0.6:
            return 'wall', 'geometry:side'
        if shares['down'] >= 0.6:
            return 'other', 'geometry:down'
    for word in FLOOR_WORDS:
        if word in lower:
            return 'floor', f'name:{word}'
    for word in WALL_WORDS:
        if word in lower:
            return 'wall', f'name:{word}'
    if surface.area_cm2 > 0:
        return 'other', 'default'
    if any(word in lower for word in EFFECT_WORDS):
        return 'keep', 'unbound:effect'               # left native: nothing measured draws it, the name says sprite
    return 'other', 'unbound'


def grid_cells(tile_cm: float | None) -> int:
    """One cell per metre of the span one UV tile covers, clamped so every texture gets a readable grid."""
    if tile_cm is None or not math.isfinite(tile_cm) or tile_cm <= 0:
        return MIN_CELLS
    return max(MIN_CELLS, min(MAX_CELLS, int(round(tile_cm / 100.0)) or MIN_CELLS))


def span_label(tile_cm: float | None) -> str:
    if tile_cm is None or not math.isfinite(tile_cm) or tile_cm <= 0:
        return '?? m'
    metres = tile_cm / 100.0
    if metres >= 0.95:
        return f'{int(round(metres)):02d} m'
    if metres >= 0.095:
        return f'{metres:.1f} m'
    return f'{tile_cm:.0f} cm'


# --- the grid textures -----------------------------------------------------------------------------------------------

PALETTE = {
    'floor': {'base': (52, 86, 140), 'minor': (70, 108, 166), 'major': (214, 224, 240), 'text': (236, 240, 248)},
    'wall': {'base': (124, 124, 124), 'minor': (142, 142, 142), 'major': (214, 214, 214), 'text': (240, 240, 240)},
    'other': {'base': (112, 112, 112), 'alt': (150, 150, 150), 'minor': (128, 128, 128), 'major': (206, 206, 206),
              'text': (240, 240, 240)},
    'prop': {'base': (176, 118, 64), 'alt': (206, 150, 92), 'minor': (190, 134, 80), 'major': (250, 236, 210),
             'text': (255, 248, 232)},
    'sky': {'base': (158, 176, 196)},
}


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                   # Pillow < 10.1 has no sized default font
        return ImageFont.load_default()


def _glyphs(text: str, font, fill, *, mirror: bool) -> 'Image.Image':
    """The text as an RGBA image, flipped left-right when `mirror` (so it reads forwards on a mirrored mapping)."""
    from PIL import Image, ImageDraw, ImageOps

    left, top, right, bottom = font.getbbox(text)
    image = Image.new('RGBA', (max(1, right - left), max(1, bottom - top)), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((-left, -top), text, fill=fill, font=font)
    return ImageOps.mirror(image) if mirror else image


def _label(image, draw, text: str, size: int, colours: dict, centre: tuple[float, float], *, mirror: bool,
           box: bool = True) -> None:
    glyphs = _glyphs(text, _font(size), colours['text'], mirror=mirror)
    x, y = round(centre[0] - glyphs.width / 2), round(centre[1] - glyphs.height / 2)
    if box:
        pad = max(2, size // 6)
        draw.rectangle([x - pad, y - pad, x + glyphs.width + pad, y + glyphs.height + pad], fill=colours['base'])
    image.paste(glyphs, (x, y), glyphs)


def grid_image(width: int, height: int, variant: str, cells_u: int = 1, cells_v: int = 1, label: str = '',
               corner: str = '', *, mirror: bool = False, both: bool = False) -> 'Image.Image':
    """An RGB grid texture: `cells_u` x `cells_v` major cells (one per metre), four minor cells per major cell where
    they stay readable, the `label` across the middle and `corner` small in the top-left.

    `mirror` draws the glyphs flipped left-right: on a surface whose UV mapping is the mirror image of the screen
    (measured per texture, `Surface.mirror_share`) they then read forwards. `both` adds the other reading below the
    label at 0.6 size, for a texture whose surfaces are of both hands (one of the two always reads).
    """
    from PIL import Image, ImageDraw

    if variant not in VARIANTS:
        raise GreyboxError(f'unknown grid variant {variant!r}')
    if width < 1 or height < 1 or cells_u < 1 or cells_v < 1:
        raise GreyboxError('grid dimensions and cell counts must be positive')
    colours = PALETTE[variant]
    image = Image.new('RGB', (width, height), colours['base'])
    if variant == 'sky':
        return image
    draw = ImageDraw.Draw(image)
    cell_w, cell_h = width / cells_u, height / cells_v
    if variant in ('other', 'prop'):
        for j in range(cells_v):
            for i in range(cells_u):
                if (i + j) % 2:
                    draw.rectangle([round(i * cell_w), round(j * cell_h), round((i + 1) * cell_w) - 1,
                                    round((j + 1) * cell_h) - 1], fill=colours['alt'])
    minor = 4 if min(cell_w, cell_h) >= 32 else (2 if min(cell_w, cell_h) >= 12 else 1)
    if minor > 1:
        for i in range(cells_u * minor):
            x = round(i * cell_w / minor)
            draw.line([(x, 0), (x, height - 1)], fill=colours['minor'], width=1)
        for j in range(cells_v * minor):
            y = round(j * cell_h / minor)
            draw.line([(0, y), (width - 1, y)], fill=colours['minor'], width=1)
    thick = max(1, min(width, height) // 256)
    for i in range(cells_u):
        x = round(i * cell_w)
        draw.line([(x, 0), (x, height - 1)], fill=colours['major'], width=thick)
    for j in range(cells_v):
        y = round(j * cell_h)
        draw.line([(0, y), (width - 1, y)], fill=colours['major'], width=thick)
    if label and min(width, height) >= 32:
        size = max(8, min(width, height) // 6)
        if both and height >= 64:
            # a texture drawn on surfaces of both hands: the dominant reading above the middle, the other below it
            _label(image, draw, label, size, colours, (width / 2, height / 2 - size * 0.55), mirror=mirror)
            _label(image, draw, label, max(8, int(size * 0.6)), colours, (width / 2, height / 2 + size * 0.5),
                   mirror=not mirror)
        else:
            _label(image, draw, label, size, colours, (width / 2, height / 2), mirror=mirror)
    if corner and min(width, height) >= 64:
        size = max(8, min(width, height) // 14)
        glyphs = _glyphs(corner, _font(size), colours['text'], mirror=mirror)
        # the corner tag stays top-left in texture space; mirrored glyphs read forwards on a mirrored surface
        image.paste(glyphs, (max(2, width // 64), max(2, height // 64)), glyphs)
    return image


def greybox_texture(native: bytes, variant: str, cells_u: int, cells_v: int, label: str, corner: str = '',
                    *, keep_alpha: bool = True, mirror: bool = False, both: bool = False) -> tuple[bytes, dict]:
    """A TEX with `native`'s container, dimensions, format and mip chain, drawn as a grid; the native alpha is kept.

    Returns (bytes, report). The report carries what was drawn so a receipt can say it without decoding the result.
    """
    from PIL import Image

    tex = mtf_tex.parse(native)
    if tex.format not in BC7:
        raise GreyboxError(f'only BC7 albedos are rewritten (format 0x{tex.format:02x})')
    image = grid_image(tex.width, tex.height, variant, cells_u, cells_v, label, corner, mirror=mirror,
                       both=both).convert('RGBA')
    alpha_note = 'opaque'
    if keep_alpha:
        source = mtf_tex.decode(native, 0)
        alpha = np.asarray(source, np.uint8)[..., 3]
        pixels = np.asarray(image, np.uint8).copy()
        pixels[..., 3] = alpha
        image = Image.fromarray(pixels, 'RGBA')
        alpha_note = f'native alpha kept (min {int(alpha.min())}, max {int(alpha.max())})'
    out = mtf_tex.replace_image(native, image)
    if len(out) != len(native) or out[:8] != native[:8] or out[8:20 + len(tex.mips) * 4] != native[8:20 + len(tex.mips) * 4]:
        raise GreyboxError('the rewritten TEX does not keep the native header and mip table')
    return out, {'variant': variant, 'cells': [cells_u, cells_v], 'label': label, 'corner': corner,
                 'alpha': alpha_note, 'width': tex.width, 'height': tex.height, 'format': tex.format,
                 'mips': len(tex.mips), 'glyphs': ('both ways' if both else 'mirrored' if mirror else 'upright')}


# --- the stage overlay -----------------------------------------------------------------------------------------------

def plan(surfaces: dict[str, Surface], overrides: dict[str, str] | None = None) -> list[dict]:
    """One row per albedo: the variant, the rule that chose it, the cells and labels the grid will carry, and how the
    glyphs are drawn (`mirror`: flipped for a mapping of mirrored handedness; `both`: both readings, mixed surfaces).
    A `keep` row names a texture left native."""
    rows = []
    for name in sorted(surfaces):
        surface = surfaces[name]
        variant, rule = classify(surface)
        if overrides and surface.basename in overrides:
            variant, rule = overrides[surface.basename], 'override'
            if variant not in VARIANTS and variant != 'keep':
                raise GreyboxError(f'override {variant!r} for {surface.basename} is not a variant')
        cells_u, cells_v = grid_cells(surface.tile_u_cm), grid_cells(surface.tile_v_cm)
        if variant == 'floor':
            label, corner = str(surface.width), span_label(surface.tile_u_cm)
        else:
            u, v = span_label(surface.tile_u_cm), span_label(surface.tile_v_cm)
            label, corner = (u if cells_u == cells_v else f'{u} x {v}'), ''
        share = surface.mirror_share()
        mirror = share is not None and share > MIRROR_SHARE
        both = share is not None and MIXED_LOW <= share <= MIXED_HIGH
        rows.append({'variant': variant, 'rule': rule, 'cells': [cells_u, cells_v], 'label': label,
                     'corner': corner, 'mirror': mirror, 'both': both, **surface.report()})
    return rows


def build(archive: bytes, *, stage: str = 's400', overrides: dict[str, str] | None = None,
          progress=lambda *_: None, scope=None) -> tuple[bytes, dict]:
    """The stage archive with every scenery albedo drawn as a greybox grid; returns (archive, receipt).

    The scenery folders are found in the archive (`scene_folders`: s400's scr01, s402's scr00, s405's scr01..07 and
    the s314 piece); `scope` overrides them with one folder prefix or several.
    """
    arc = mt_arc.parse(archive)
    if mt_arc.build(arc) != archive:
        raise GreyboxError('the archive does not rebuild byte-identically; refusing to write on top of it')
    folders = scope if scope is not None else scene_folders(arc)
    if not folders:
        raise GreyboxError('no scenery folder (stage\\sNNN\\scr\\scrNN\\ with a MOD) in the archive')
    surfaces, notes = measure(arc, folders)
    if not surfaces:
        raise GreyboxError(f'no BC7 albedo under {folders}')
    rows = plan(surfaces, overrides)
    changed = []
    kept = []
    for row in rows:
        if row['variant'] == 'keep':
            kept.append(row)
            continue
        entry = arc.entries[row['entry']]
        native = _raw(entry)
        if entry.data != _wrap(native):
            raise GreyboxError(f'{entry.name}: the native stream is not a level-6 zlib wrap; cannot rewrite it faithfully')
        progress(row['name'], row['variant'])
        out, report = greybox_texture(native, row['variant'], *row['cells'], row['label'], row['corner'],
                                      mirror=row['mirror'], both=row['both'])
        entry.data = _wrap(out)
        entry.size = len(entry.data)
        if entry.tag != (0x40000000 | len(out)):
            raise GreyboxError(f'{entry.name}: the tag is not the measured 0x40000000 | length form')
        row.update(report, payload_sha256=hashlib.sha256(out).hexdigest())
        changed.append(row['entry'])
    written = mt_arc.build(arc)
    original = mt_arc.parse(archive)
    final = mt_arc.parse(written)
    untouched = [i for i in range(len(original.entries)) if i not in set(changed)]
    if any(original.entries[i].data != final.entries[i].data for i in untouched):
        raise GreyboxError('an entry outside the albedo list changed')
    counts = {}
    glyphs = {'upright': 0, 'mirrored': 0, 'both ways': 0}
    for row in rows:
        if row['variant'] == 'keep':
            continue
        counts[row['variant']] = counts.get(row['variant'], 0) + 1
        glyphs[row['glyphs']] += 1
    receipt = {
        'title_id': TITLE_ID, 'stage': stage, 'archive': f'{stage}.arc', 'route': 're5_stage_greybox.build',
        'scene_folders': list(folders) if not isinstance(folders, str) else [folders],
        'source_sha256': hashlib.sha256(archive).hexdigest(), 'written_sha256': hashlib.sha256(written).hexdigest(),
        'bytes': len(written), 'entries': len(final.entries), 'changed_entries': sorted(changed),
        'unchanged_entries': len(untouched), 'variants': counts, 'glyphs': glyphs, 'measurement': notes,
        'textures': [row for row in rows if row['variant'] != 'keep'],
        'kept_native_textures': [{'name': row['name'], 'rule': row['rule']} for row in kept],
        'kept_native': ['every MOD, MRL, _NM normal map, _MM mask, _LM light map, _AM alpha map, _CM cube map, the '
                        'layouts, sounds, effects and the navigation mesh', 'the alpha channel of every albedo',
                        'albedos no measured material binds whose name says sprite / light / shadow (kept_native_textures)',
                        'albedos mtf_tex does not parse (measurement.albedo_unparsed)'],
        'live_verified': False, 'gameplay_verified': False,
        'what_must_be_seen': ['the whole stage drawn in grey and blue grid tiles with metre labels, lit as before '
                              '(light maps are native)', 'floors blue with the pixel size and a metre tag, walls grey '
                              'with the metre label, props and foliage checkered', 'labels read forwards (glyphs are '
                              'flipped on textures whose mapping is mirrored; a texture of mixed hands shows both)',
                              'fences, wires and leaves still cut out (native alpha)', 'enemies and players unchanged'],
        'failure_signs': ['black screen or hang at stage load: a TEX the game rejects (bisect by variant)',
                          'a surface still showing a photo texture: an albedo bound by a material outside the scenery '
                          'folders, by an effect, or listed in albedo_unparsed / kept_native_textures',
                          'solid slabs where fences or wires were: alpha was not kept',
                          'a label still reading backwards: that texture\'s mirror_share is on the wrong side of 0.5 '
                          '(a per-mesh UV edit would be exact; the receipt row says the share)',
                          'grid lines of very different size on one surface class: the UV measurement is off for '
                          'that texture; its tile quartiles are in the receipt'],
        'acceptance': 'experimental; offline structural checks only'}
    return written, receipt


def verify(original: bytes, candidate: bytes, receipt: dict | None = None) -> dict:
    """Structural checks a greybox candidate must pass; raises GreyboxError with the first failure."""
    before, after = mt_arc.parse(original), mt_arc.parse(candidate)
    if mt_arc.build(after) != candidate:
        raise GreyboxError('the candidate does not rebuild byte-identically')
    if len(before.entries) != len(after.entries):
        raise GreyboxError('entry count changed')
    changed = []
    for index, (a, b) in enumerate(zip(before.entries, after.entries)):
        if (a.name, a.hash, a.tag) != (b.name, b.hash, b.tag):
            raise GreyboxError(f'entry {index} changed its name, hash or tag')
        if a.data == b.data:
            continue
        changed.append(index)
        if not ALBEDO_NAME.search(a.name):
            raise GreyboxError(f'entry {index} {a.name} is not an albedo but changed')
        raw_a, raw_b = _raw(a), _raw(b)
        if b.data != _wrap(raw_b):
            raise GreyboxError(f'entry {index}: not a level-6 zlib wrap')
        ta, tb = mtf_tex.parse(raw_a), mtf_tex.parse(raw_b)
        if (ta.width, ta.height, ta.format, len(ta.mips)) != (tb.width, tb.height, tb.format, len(tb.mips)):
            raise GreyboxError(f'entry {index}: dimensions, format or mip count changed')
        if len(raw_a) != len(raw_b) or raw_a[:20 + 4 * len(ta.mips)] != raw_b[:20 + 4 * len(tb.mips)]:
            raise GreyboxError(f'entry {index}: TEX header or size changed')
        if receipt is not None:
            row = next((r for r in receipt.get('textures', []) if r['entry'] == index), None)
            if row is None or row.get('payload_sha256') != hashlib.sha256(raw_b).hexdigest():
                raise GreyboxError(f'entry {index}: payload does not match the receipt')
    if receipt is not None and sorted(receipt.get('changed_entries', [])) != changed:
        raise GreyboxError('the receipt lists other changed entries than the archive shows')
    return {'entries': len(after.entries), 'changed': changed, 'unchanged': len(after.entries) - len(changed),
            'sha256': hashlib.sha256(candidate).hexdigest()}


# --- preview: the written textures, and the stage drawn with them on the CPU -------------------------------------

def contact_sheet(candidate: bytes, rows: list[dict], png: Path, *, thumb: int = 96, columns: int = 12) -> None:
    """Thumbnails of every written albedo (decoded from the candidate) with its variant and label."""
    from PIL import Image, ImageDraw

    arc = mt_arc.parse(candidate)
    rows = sorted(rows, key=lambda r: (r['variant'], r['name']))
    count = len(rows)
    lines = -(-count // columns)
    sheet = Image.new('RGB', (columns * thumb, lines * (thumb + 14)), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    font = _font(9)
    for n, row in enumerate(rows):
        image = mtf_tex.decode(_raw(arc.entries[row['entry']]), 0).convert('RGB').resize((thumb, thumb))
        x, y = (n % columns) * thumb, (n // columns) * (thumb + 14)
        sheet.paste(image, (x, y))
        draw.text((x + 2, y + thumb), row['name'].rsplit('\\', 1)[-1][:18], fill=(220, 220, 220), font=font)
    sheet.save(png)


def _rasterise(canvas, zbuf, xy, depth, uv, texture):
    """One textured triangle into an RGB canvas with a z-buffer (nearest texel, wrapping UVs, flat light)."""
    height, width = zbuf.shape
    x0, y0 = int(max(0, np.floor(xy[:, 0].min()))), int(max(0, np.floor(xy[:, 1].min())))
    x1, y1 = int(min(width - 1, np.ceil(xy[:, 0].max()))), int(min(height - 1, np.ceil(xy[:, 1].max())))
    if x1 < x0 or y1 < y0:
        return
    (ax, ay), (bx, by), (cx, cy) = xy
    det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
    if abs(det) < 1e-9:
        return
    ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    px, py = xs + 0.5, ys + 0.5
    w1 = ((bx - px) * (cy - py) - (cx - px) * (by - py)) / det
    w2 = ((cx - px) * (ay - py) - (ax - px) * (cy - py)) / det
    w3 = 1.0 - w1 - w2
    inside = (w1 >= -1e-6) & (w2 >= -1e-6) & (w3 >= -1e-6)
    if not inside.any():
        return
    z = w1 * depth[0] + w2 * depth[1] + w3 * depth[2]
    window = zbuf[y0:y1 + 1, x0:x1 + 1]
    hit = inside & (z < window)
    if not hit.any():
        return
    u = w1 * uv[0, 0] + w2 * uv[1, 0] + w3 * uv[2, 0]
    v = w1 * uv[0, 1] + w2 * uv[1, 1] + w3 * uv[2, 1]
    th, tw = texture.shape[:2]
    tx = (np.floor(u * tw).astype(np.int64) % tw)[hit]
    ty = (np.floor(v * th).astype(np.int64) % th)[hit]
    window[hit] = z[hit]
    canvas[y0:y1 + 1, x0:x1 + 1][hit] = texture[ty, tx]


def render_stage(candidate: bytes, png: Path, *, stage: str = 's400', size: int = 1024, yaw_deg: float = 30.0,
                 pitch_deg: float = 55.0, max_triangles: int = 2_000_000, window_cm: float | None = None,
                 percentile: float = 1.0) -> dict:
    """An orthographic CPU view of the stage geometry textured with the candidate's albedos: not the game's shading,
    light maps, alpha test or sky, only the written surfaces on the written geometry.

    The frame fits the `percentile`..`100 - percentile` span of the vertices (the outer ground plane of a stage is
    hundreds of metres wide and would shrink the arena to a dot), or a `window_cm` square around their median.
    """
    from PIL import Image

    arc = mt_arc.parse(candidate)
    scope = scene_folders(arc) or stage_scope(stage)
    textures: dict[str, np.ndarray] = {}
    for index, entry in enumerate(arc.entries):
        if entry.name.startswith('stage\\') and ALBEDO_NAME.search(entry.name):
            raw = _raw(entry)
            try:
                mip = 0
                tex = mtf_tex.parse(raw)
                while mip + 1 < len(tex.mips) and max(tex.mips[mip].width, tex.mips[mip].height) > 256:
                    mip += 1
                textures[entry.name] = np.asarray(mtf_tex.decode(raw, mip).convert('RGB'), np.uint8)
            except ValueError:
                continue
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    rot_y = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rot_x = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    rotation = rot_x @ rot_y
    pieces = []
    for name, mod_index, mrl_index in stage_models(arc, scope):
        mod_raw, mrl_raw = _raw(arc.entries[mod_index]), _raw(arc.entries[mrl_index])
        try:
            bindings = material_bindings(mod_raw, mrl_raw)
        except mtf_mrl.MaterialBindingError:
            continue
        model = mt_model.parse_mod(mod_raw)
        for k, record in enumerate(model.meshes()):
            if not record['level_of_detail'] & 1:
                continue
            geometry = mesh_geometry(model, k)
            if geometry is None or record['material_index'] >= len(bindings):
                continue
            albedo = bindings[record['material_index']]['albedo']
            if albedo not in textures or 'sky' in albedo.lower():
                continue
            positions, normals, uvs, triangles = geometry
            pieces.append((positions @ rotation.T, normals @ rotation.T, uvs, triangles, textures[albedo]))
    if not pieces:
        raise GreyboxError('nothing to draw')
    everything = np.concatenate([p for p, *_ in pieces])
    if window_cm:
        middle = np.median(everything, axis=0)
        low, high = middle - window_cm / 2, middle + window_cm / 2
    else:
        low = np.percentile(everything, percentile, axis=0)
        high = np.percentile(everything, 100 - percentile, axis=0)
    span = max(high[0] - low[0], high[1] - low[1]) or 1.0
    scale = (size - 8) / span
    canvas = np.full((size, size, 3), 24, np.uint8)
    zbuf = np.full((size, size), np.inf)
    drawn = 0
    for positions, normals, uvs, triangles, texture in pieces:
        screen = np.empty((len(positions), 2))
        screen[:, 0] = (positions[:, 0] - low[0]) * scale + 4
        screen[:, 1] = (high[1] - positions[:, 1]) * scale + 4
        depth = -positions[:, 2]
        inside = ((screen[:, 0] > -size) & (screen[:, 0] < 2 * size) & (screen[:, 1] > -size) & (screen[:, 1] < 2 * size))
        for tri in triangles:
            if drawn >= max_triangles:
                break
            if not inside[tri].any():
                continue
            n = normals[tri].mean(0)
            shade = 0.55 + 0.45 * max(0.0, float(n[1]) * 0.6 + float(n[2]) * 0.8)
            _rasterise(canvas, zbuf, screen[tri], depth[tri], uvs[tri], np.clip(texture * shade, 0, 255).astype(np.uint8)
                       if shade != 1.0 else texture)
            drawn += 1
    Image.fromarray(canvas, 'RGB').save(png)
    return {'png': str(png), 'triangles': drawn, 'view': f'orthographic, yaw {yaw_deg}, pitch {pitch_deg}',
            'shows': 'written albedos on the native LOD-0 geometry with a flat directional shade; not the game'}


def render_model(archive: bytes, model_name: str, png: Path, *, size: int = 320, yaw_deg: float = 35.0,
                 pitch_deg: float = 30.0, lod: int = 0) -> dict:
    """One object model of an archive drawn on the CPU with the albedo each of its materials binds (three-quarter
    orthographic view, flat shade): the written bytes, not the game."""
    from PIL import Image

    arc = mt_arc.parse(archive)
    mods = [i for i, e in enumerate(arc.entries) if e.name == model_name and _raw(e)[:4] == b'MOD\0']
    mrls = [i for i, e in enumerate(arc.entries) if e.name == model_name and _raw(e)[:4] == b'MRL\0']
    if len(mods) != 1 or len(mrls) != 1:
        raise GreyboxError(f'{model_name} needs exactly one MOD and one MRL entry')
    mod_raw, mrl_raw = _raw(arc.entries[mods[0]]), _raw(arc.entries[mrls[0]])
    model = mt_model.parse_mod(mod_raw)
    bindings = material_bindings(mod_raw, mrl_raw)
    textures: dict[str, np.ndarray] = {}
    for entry in arc.entries:
        if entry.name.endswith('_BM'):
            try:
                textures[entry.name] = np.asarray(mtf_tex.decode(_raw(entry), 0).convert('RGB'), np.uint8)
            except ValueError:
                continue
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    rot_y = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rot_x = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    rotation = rot_x @ rot_y
    pieces = []
    for k, record in enumerate(model.meshes()):
        if not record['level_of_detail'] & (1 << lod) or record['mesh_type'] != 0xFFFF:
            continue
        positions = np.asarray(model.positions(k), np.float64)
        uvs = np.asarray(model.uvs(k), np.float64)
        normals = np.asarray(model.normals(k), np.float64)
        triangles = np.asarray(mtf_author.mesh_triangles(model, k), np.int64).reshape(-1, 3) - record['vertex_index']
        if not len(positions) or not len(uvs) or not len(triangles):
            continue
        albedo = bindings[record['material_index']]['albedo'] if record['material_index'] < len(bindings) else None
        texture = textures.get(albedo, np.full((4, 4, 3), 160, np.uint8))
        pieces.append((positions @ rotation.T, normals @ rotation.T if len(normals) else None, uvs, triangles, texture))
    if not pieces:
        raise GreyboxError('nothing to draw')
    everything = np.concatenate([p for p, *_ in pieces])
    low, high = everything.min(0), everything.max(0)
    span = max(high[0] - low[0], high[1] - low[1]) or 1.0
    scale = (size - 16) / span
    canvas = np.full((size, size, 3), 24, np.uint8)
    zbuf = np.full((size, size), np.inf)
    drawn = 0
    for positions, normals, uvs, triangles, texture in pieces:
        screen = np.empty((len(positions), 2))
        screen[:, 0] = (positions[:, 0] - low[0]) * scale + 8 + ((span - (high[0] - low[0])) * scale) / 2
        screen[:, 1] = (high[1] - positions[:, 1]) * scale + 8 + ((span - (high[1] - low[1])) * scale) / 2
        depth = -positions[:, 2]
        for tri in triangles:
            if normals is not None and len(normals) == len(positions):
                n = normals[tri].mean(0)
            else:
                p = positions[tri]
                n = np.cross(p[1] - p[0], p[2] - p[0])
                n = n / (np.linalg.norm(n) or 1.0)
            shade = 0.55 + 0.45 * max(0.0, float(n[1]) * 0.6 + float(n[2]) * 0.8)
            _rasterise(canvas, zbuf, screen[tri], depth[tri], uvs[tri], np.clip(texture * shade, 0, 255).astype(np.uint8))
            drawn += 1
    Image.fromarray(canvas, 'RGB').save(png)
    return {'png': str(png), 'triangles': drawn, 'model': model_name,
            'shows': 'the archive\'s LOD-0 drawn parts with the albedo each material binds; flat shade, not the game'}


# --- the objects a stage places ------------------------------------------------------------------------------------

def placed_objects(arc: mt_arc.Arc) -> dict[str, list[str]]:
    """{`uOmNNNN.arc`: [layout entries]} of the object archives the stage's layouts place: the static scenery rows
    (`*_IDo00_Ins`, class `uIm`, `mpInfo.mName` = `om0816_IDo00_U001`, `om083fF_…`, `OM100C_…`) and the interactive
    objects (`soft\\<mode>\\*_IDF00/01_Ins`, `mUnitClass` = `uOm0886`). File names carry lower-case hex, as the
    host's archives do. Measured on s400..s407 (2026-11-09); s400 gives the 32 archives of the research note."""
    from .re5_stage_enemies import read_xfs, XfsError

    found: dict[str, set] = {}
    for entry in arc.entries:
        if not re.search(r'_ID[oF]\d\d_Ins$', entry.name):
            continue
        raw = _raw(entry)
        if raw[:4] != b'XFS\0':
            continue
        try:
            tree = read_xfs(raw)
        except XfsError:
            continue
        infos = tree.get('mSetInfos') or []
        for info in infos if isinstance(infos, list) else [infos]:
            if not isinstance(info, dict):
                continue
            unit = info.get('mUnitClass') or ''
            extra = info.get('mpInfo') if isinstance(info.get('mpInfo'), dict) else {}
            name = extra.get('mName') if isinstance(extra.get('mName'), str) else ''
            match = re.fullmatch(r'uOm([0-9a-fA-F]{4})', unit) or re.match(r'(?i)om([0-9a-f]{4})', name)
            if match:
                found.setdefault(f'uOm{match.group(1).lower()}.arc', set()).add(entry.name)
    return {key: sorted(value) for key, value in sorted(found.items())}


# --- the prop path, textures only: every object albedo as the orange grid, geometry native ------------------------

#: What an object's texture name says it is (romaji, from the s400 object table of docs/research/re5-stage-greybox.md
#: and the s401..s407 archives); the label the grid carries. Unknown names are labelled with their romaji.
PROP_READINGS = {
    'kibako': 'CRATE', 'taru': 'BARREL', 'reddrum': 'DRUM', 'takarabako': 'CHEST', 'sunadokei': 'HOURGLASS',
    'danboll': 'BOX', 'desk': 'TABLE', 'kabe': 'WALL', 'door': 'DOOR', 'window': 'WINDOW', 'car': 'CAR', 'tv': 'TV',
    'parasol': 'PARASOL', 'bananatree': 'TREE', 'satoukibi': 'CANE', 'yatai': 'STALL', 'sentaku': 'LAUNDRY',
    'polytank': 'CAN', 'grapefruit': 'FRUIT', 'tomato': 'FRUIT', 'kago': 'BASKET', 'gaikotu': 'SKULL',
    'chikuden': 'BATTERY', 'oil': 'TANK', 'hikidashi': 'DRAWERS', 'nuno': 'CLOTH', 'hashigo': 'LADDER',
    'hashigoshort': 'LADDER', 'tsukue': 'TABLE', 'isu': 'CHAIR', 'tana': 'SHELF', 'bin': 'BOTTLE', 'hako': 'BOX',
    'doramu': 'DRUM', 'drum': 'DRUM', 'tire': 'TYRE', 'taiya': 'TYRE', 'fence': 'FENCE', 'saku': 'FENCE',
}


def prop_label(texture_name: str) -> str:
    """`pawn\\om\\om0889\\model\\om_kibakoC01_01_BM` -> `CRATE`; an unknown romaji is the label itself, upper-cased."""
    base = texture_name.rsplit('\\', 1)[-1]
    base = ALBEDO_NAME.sub('', base)
    base = re.sub(r'^(om|s\d{3}_[a-z]_|[a-z]_)', '', base, count=1).lstrip('_')
    base = re.sub(r'_\d{2}$', '', base)                     # om_kibakoC01_01 -> om_kibakoC01
    base = re.sub(r'[A-Z]?\d{2,}$', '', base)                # kibakoC01 -> kibako, reddrumA01 -> reddrum, door100C -> door
    base = re.sub(r'\d+$', '', base)
    word = base.lower()
    for key in sorted(PROP_READINGS, key=len, reverse=True):
        if key in word:
            return PROP_READINGS[key]
    return (word.upper() or 'PROP')[:10]


def object_models(arc: mt_arc.Arc) -> list[tuple[str, int, int]]:
    """(name, MOD index, MRL index) of every object model (`pawn\\...`) with both entries: the intact model and its
    broken form; effect models (`effect\\mod\\...`) are not objects and keep their sheets."""
    return stage_models(arc, 'pawn\\')


def measure_objects(arc: mt_arc.Arc) -> tuple[dict[str, Surface], dict]:
    """Charge every drawn triangle of every object model to the albedo its material binds (the object formats have
    quantised positions, decoded through the model's own transform); returns (surfaces, notes)."""
    notes = {'models': 0, 'meshes': 0, 'meshes_skipped': 0, 'triangles': 0, 'unbound_materials': 0,
             'mrl_unparsed': [], 'albedo_unparsed': []}
    models = []
    bound_names: set[str] = set()
    for name, mod_index, mrl_index in object_models(arc):
        mod_raw, mrl_raw = _raw(arc.entries[mod_index]), _raw(arc.entries[mrl_index])
        try:
            bindings = material_bindings(mod_raw, mrl_raw)
        except mtf_mrl.MaterialBindingError as exc:
            notes['mrl_unparsed'].append({'name': name, 'reason': str(exc)})
            continue
        models.append((name, mod_raw, bindings))
        bound_names.update(b['albedo'] for b in bindings if b['albedo'])
    surfaces = albedo_surfaces(arc, (), bound_names)
    notes['albedo_unparsed'] = sorted(n for n in bound_names if n not in surfaces)
    for name, mod_raw, bindings in models:
        model = mt_model.parse_mod(mod_raw)
        notes['models'] += 1
        for k, record in enumerate(model.meshes()):
            if record['mesh_type'] != 0xFFFF or record['material_index'] >= len(bindings):
                notes['meshes_skipped'] += 1                 # depth proxies and shadow parts draw no albedo
                continue
            try:
                positions = np.asarray(model.positions(k), np.float64)
                uvs = np.asarray(model.uvs(k), np.float64)
                normals = np.asarray(model.normals(k), np.float64)
                triangles = np.asarray(mtf_author.mesh_triangles(model, k), np.int64).reshape(-1, 3) - record['vertex_index']
            except (ValueError, KeyError, struct.error):
                notes['meshes_skipped'] += 1
                continue
            if not len(positions) or len(uvs) != len(positions) or not len(triangles) \
                    or triangles.min() < 0 or triangles.max() >= len(positions):
                notes['meshes_skipped'] += 1
                continue
            if len(normals) != len(positions):
                normals = np.zeros_like(positions)           # the geometric normal of each triangle stands in
            albedo = bindings[record['material_index']]['albedo']
            surface = surfaces.get(albedo) if albedo else None
            if surface is None:
                notes['unbound_materials'] += 1
                continue
            surface.bound = True
            notes['meshes'] += 1
            notes['triangles'] += len(triangles)
            material = bindings[record['material_index']]
            if material['name'] not in surface.materials:
                surface.materials.append(material['name'])
                surface.families.append(material['family'])
            surface.alpha_tested = surface.alpha_tested or material['alpha_tested']
            _charge(surface, positions, normals, uvs, triangles)
    for surface in surfaces.values():
        surface.settle()
    return surfaces, notes


def build_prop_textures(archive: bytes, *, archive_name: str = '', progress=lambda *_: None) -> tuple[bytes, dict]:
    """An object archive with every albedo its models bind drawn as the orange prop grid (one cell per metre of the
    measured tile span, the object's reading as the label, native alpha kept); geometry, normal and mask maps, the
    effect sheets, sounds, collision and motions byte-identical. Returns (bytes, receipt)."""
    arc = mt_arc.parse(archive)
    if mt_arc.build(arc) != archive:
        raise GreyboxError('the archive does not rebuild byte-identically; refusing to write on top of it')
    surfaces, notes = measure_objects(arc)
    rows = []
    changed = []
    for name in sorted(surfaces):
        surface = surfaces[name]
        if not surface.bound:
            continue
        cells_u, cells_v = grid_cells(surface.tile_u_cm), grid_cells(surface.tile_v_cm)
        u, v = span_label(surface.tile_u_cm), span_label(surface.tile_v_cm)
        share = surface.mirror_share()
        mirror = share is not None and share > MIRROR_SHARE
        both = share is not None and MIXED_LOW <= share <= MIXED_HIGH
        row = {'variant': 'prop', 'rule': 'object albedo', 'cells': [cells_u, cells_v], 'label': prop_label(name),
               'corner': u if cells_u == cells_v else f'{u} x {v}', 'mirror': mirror, 'both': both, **surface.report()}
        entry = arc.entries[row['entry']]
        native = _raw(entry)
        if entry.data != _wrap(native):
            raise GreyboxError(f'{entry.name}: the native stream is not a level-6 zlib wrap; cannot rewrite it faithfully')
        progress(name, 'prop')
        out, report = greybox_texture(native, 'prop', cells_u, cells_v, row['label'], row['corner'], mirror=mirror,
                                      both=both)
        entry.data = _wrap(out)
        entry.size = len(entry.data)
        if entry.tag != (0x40000000 | len(out)):
            raise GreyboxError(f'{entry.name}: the tag is not the measured 0x40000000 | length form')
        row.update(report, payload_sha256=hashlib.sha256(out).hexdigest())
        rows.append(row)
        changed.append(row['entry'])
    if not rows:
        raise GreyboxError('no object model of the archive binds a BC7 albedo')
    written = mt_arc.build(arc)
    before, after = mt_arc.parse(archive), mt_arc.parse(written)
    for i, (a, b) in enumerate(zip(before.entries, after.entries)):
        if i not in set(changed) and a.data != b.data:
            raise GreyboxError('an entry outside the albedo list changed')
        if (a.name, a.hash, a.tag) != (b.name, b.hash, b.tag):
            raise GreyboxError('an entry changed its name, hash or tag')
    receipt = {
        'title_id': TITLE_ID, 'archive': archive_name, 'route': 're5_stage_greybox.build_prop_textures',
        'source_sha256': hashlib.sha256(archive).hexdigest(), 'written_sha256': hashlib.sha256(written).hexdigest(),
        'bytes': len(written), 'entries': len(after.entries), 'changed_entries': sorted(changed),
        'unchanged_entries': len(after.entries) - len(changed), 'variants': {'prop': len(rows)},
        'measurement': notes, 'textures': rows,
        'kept_native': ['every MOD (geometry untouched), MRL, _NM normal map, _MM mask, effect models and their '
                        'sheets, motions, collision and sounds', 'the alpha channel of every albedo'],
        'live_verified': False, 'gameplay_verified': False,
        'what_must_be_seen': ['the object in the orange grid with its label, the native shape, shadow and breakage',
                              'its broken form and debris in the same grid (they sample the same albedos)'],
        'failure_signs': ['the object still shows a photo texture: a material binds an albedo outside the measured '
                          'list (measurement.unbound_materials / albedo_unparsed)',
                          'a hang at stage load: a TEX the game rejects (the TEX header and mips are native)'],
        'acceptance': 'experimental; offline structural checks only'}
    return written, receipt


# --- the prop path, geometry: one object model rewritten as a grid box ---------------------------------------------

@dataclass(frozen=True)
class PropTarget:
    """One native object archive and the model inside it that becomes a box."""
    archive: str                 # file name, e.g. uOm0889.arc
    model: str                   # full entry name of the intact model
    albedos: tuple[str, ...]     # albedo entry names the box materials sample (all are redrawn)
    label: str                   # what the box says
    what: str                    # human reading of the object, from its texture names


CRATE = PropTarget(archive='uOm0889.arc', model='pawn\\om\\om0889\\model\\om0889',
                   albedos=('pawn\\om\\om0889\\model\\om_kibakoC01_01_BM', 'pawn\\om\\om0889\\model\\om_kibakoC01_02_BM'),
                   label='CRATE', what='wooden crate (kibako), 66 x 63 x 96 cm, breakable; om0889_01 is its debris')
DESK = PropTarget(archive='uOm0857.arc', model='pawn\\om\\om0857\\model\\om0857',
                  albedos=('pawn\\om\\om0857\\model\\om_deskB01_01_BM',),
                  label='TABLE', what='desk (deskB), 200 x 100 x 150 cm; om0857_01 is its broken form')


def box_geometry(bounds: dict, *, inset: float = 0.0):
    """24 vertices and 12 triangles of an axis-aligned box over `bounds`, CCW from outside, one UV tile per metre."""
    lo = np.array([bounds['min'][a] for a in 'xyz'], np.float64) + inset
    hi = np.array([bounds['max'][a] for a in 'xyz'], np.float64) - inset
    if not (hi > lo).all():
        raise GreyboxError('the bounds have no volume')
    faces = [  # (axis, sign, u axis, v axis)
        (0, +1, 2, 1), (0, -1, 2, 1), (1, +1, 0, 2), (1, -1, 0, 2), (2, +1, 0, 1), (2, -1, 0, 1)]
    vertices, triangles, quads = [], [], []
    for axis, sign, ua, va in faces:
        normal = np.zeros(3)
        normal[axis] = sign
        corners = []
        for su, sv in ((0, 0), (1, 0), (1, 1), (0, 1)):
            point = np.array([0.0, 0.0, 0.0])
            point[axis] = hi[axis] if sign > 0 else lo[axis]
            point[ua] = lo[ua] + su * (hi[ua] - lo[ua])
            point[va] = lo[va] + sv * (hi[va] - lo[va])
            # one UV tile per metre, the tile centred on the face so the label sits mid-face on a sub-metre box
            corners.append((point, (0.5 + (su - 0.5) * (hi[ua] - lo[ua]) / 100.0,
                                    0.5 + (sv - 0.5) * (hi[va] - lo[va]) / 100.0)))
        base = len(vertices)
        a, b, c = corners[0][0], corners[1][0], corners[2][0]
        if np.dot(np.cross(b - a, c - a), normal) < 0:
            corners = [corners[0], corners[3], corners[2], corners[1]]
        tangent = corners[1][0] - corners[0][0]
        tangent /= np.linalg.norm(tangent)
        for point, uv in corners:
            vertices.append({'position': tuple(float(v) for v in point), 'normal': tuple(float(v) for v in normal),
                             'tangent': tuple(float(v) for v in tangent), 'uv': uv})
        triangles += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
        quads.append((base, base + 1, base + 3, base + 2))        # strip order: decodes to the two triangles above
    return vertices, triangles, quads


def _strip_words(quads) -> list[int]:
    words = []
    for n, quad in enumerate(quads):
        if n:
            words.append(0xFFFF)
        words.extend(quad)
    return words


def box_model(mod_raw: bytes, *, lods=(0, 1)) -> tuple[bytes, dict]:
    """The model with every part of the given LODs rewritten in place as the bounds box; nothing else moves."""
    model = mt_model.parse_mod(mod_raw)
    header = model.header()
    bounds = model.bounds()
    if bounds is None:
        raise GreyboxError('the model has no bounds to box')
    vertices, triangles, quads = box_geometry(bounds)
    words = _strip_words(quads)
    out = bytearray(mod_raw)
    offsets = header['offsets']
    parts = []
    for index, record in enumerate(model.meshes()):
        if not any(record['level_of_detail'] & (1 << lod) for lod in lods):
            continue
        fmt, stride = record['vertex_format'], record['vertex_stride']
        if fmt not in mt_model.MOD_SHORT_POSITION | mt_model.MOD_FLOAT_POSITION:
            raise GreyboxError(f'part {index}: format {fmt:08x} has no measured position layout')
        if record['vertex_count'] < len(vertices) or record['face_count'] < len(words):
            raise GreyboxError(f'part {index}: the native allocation ({record["vertex_count"]} vertices, '
                               f'{record["face_count"]} index words) is smaller than the box')
        if record['vertex_index'] + len(vertices) - 1 > 0xFFFE:
            raise GreyboxError(f'part {index}: indices would collide with the restart marker')
        vstart = offsets['vertex_buffer'] + record['vertex_offset'] + record['vertex_index'] * stride
        vend = vstart + record['vertex_count'] * stride
        istart = offsets['index_buffer'] + 2 * record['face_index']
        iend = istart + 2 * record['face_count']
        if not offsets['vertex_buffer'] <= vstart < vend <= offsets['index_buffer'] <= istart < iend <= len(mod_raw):
            raise GreyboxError(f'part {index}: allocation outside the buffers')
        base = mod_raw[vstart:vend]
        packed = mt_model.pack_vertices([v | {'bounds': bounds} for v in vertices], fmt, stride,
                                        base=base[:len(vertices) * stride],
                                        position_transform=model.position_transform())
        # Unused vertex slots repeat the box's last vertex so no stale native position survives in the window.
        filler = packed[-stride:] * (record['vertex_count'] - len(vertices))
        out[vstart:vend] = packed + filler
        local = [w if w == 0xFFFF else w + record['vertex_index'] for w in words]
        indices = struct.pack(f'<{len(local)}H', *local)
        out[istart:iend] = indices + b'\xff' * (iend - istart - len(indices))
        parts.append({'part': index, 'format': f'{fmt:08x}', 'lod_mask': record['level_of_detail'],
                      'vertices_used': len(vertices), 'vertices_allocated': record['vertex_count'],
                      'index_words_used': len(words), 'index_words_allocated': record['face_count']})
    if not parts:
        raise GreyboxError('no part of the requested LODs')
    result = bytes(out)
    check = mt_model.parse_mod(result)
    if len(result) != len(mod_raw) or check.header() != header or check.meshes() != model.meshes():
        raise GreyboxError('the boxed model changed its header or part table')
    for row in parts:
        decoded = np.asarray(mtf_author.mesh_triangles(check, row['part']), np.int64) - \
            model.meshes()[row['part']]['vertex_index']
        if len(decoded) != len(triangles):
            raise GreyboxError(f'part {row["part"]}: {len(decoded)} triangles decode, {len(triangles)} expected')
        points = np.asarray(check.positions(row['part']), np.float64)[:len(vertices)]
        for tri in decoded:
            a, b, c = points[tri]
            centre = (a + b + c) / 3.0
            mid = np.array([(bounds['min'][k] + bounds['max'][k]) / 2 for k in 'xyz'])
            if np.dot(np.cross(b - a, c - a), centre - mid) <= 0:
                raise GreyboxError(f'part {row["part"]}: a box face is wound inwards')
        expected = np.asarray([v['position'] for v in vertices])
        if np.abs(points - expected).max() > 0.6:
            raise GreyboxError(f'part {row["part"]}: positions did not survive quantisation')
    return result, {'parts': parts, 'box': {'min': bounds['min'], 'max': bounds['max']},
                    'vertices': len(vertices), 'triangles': len(triangles), 'uv': 'one tile per metre per face'}


def build_prop_box(archive: bytes, target: PropTarget = CRATE, *, lods=(0, 1)) -> tuple[bytes, dict]:
    """The object archive with `target.model` boxed and its albedos drawn as the prop grid; returns (bytes, receipt)."""
    arc = mt_arc.parse(archive)
    if mt_arc.build(arc) != archive:
        raise GreyboxError('the archive does not rebuild byte-identically; refusing to write on top of it')
    names = [e.name for e in arc.entries]
    models = [i for i, e in enumerate(arc.entries) if e.name == target.model and _raw(e)[:4] == b'MOD\0']
    if len(models) != 1:
        raise GreyboxError(f'{target.model} is not exactly one MOD entry of the archive')
    mod_index = models[0]
    native_mod = _raw(arc.entries[mod_index])
    boxed, box_report = box_model(native_mod, lods=lods)
    changed = {mod_index}
    arc.entries[mod_index].data = _wrap(boxed)
    arc.entries[mod_index].size = len(arc.entries[mod_index].data)
    textures = []
    for name in target.albedos:
        found = [i for i, e in enumerate(arc.entries) if e.name == name]
        if len(found) != 1:
            raise GreyboxError(f'{name} is not exactly one entry')
        index = found[0]
        native = _raw(arc.entries[index])
        out, report = greybox_texture(native, 'prop', 1, 1, target.label, '01 m')
        arc.entries[index].data = _wrap(out)
        arc.entries[index].size = len(arc.entries[index].data)
        changed.add(index)
        textures.append({'entry': index, 'name': name, **report, 'payload_sha256': hashlib.sha256(out).hexdigest()})
    written = mt_arc.build(arc)
    before, after = mt_arc.parse(archive), mt_arc.parse(written)
    for i, (a, b) in enumerate(zip(before.entries, after.entries)):
        if i not in changed and a.data != b.data:
            raise GreyboxError('an entry outside the target changed')
        if (a.name, a.hash, a.tag) != (b.name, b.hash, b.tag):
            raise GreyboxError('an entry changed its name, hash or tag')
    receipt = {
        'title_id': TITLE_ID, 'archive': target.archive, 'route': 're5_stage_greybox.build_prop_box',
        'what': target.what, 'model': {'entry': mod_index, 'name': target.model, **box_report,
                                       'payload_sha256': hashlib.sha256(boxed).hexdigest()},
        'textures': textures, 'source_sha256': hashlib.sha256(archive).hexdigest(),
        'written_sha256': hashlib.sha256(written).hexdigest(), 'bytes': len(written),
        'changed_entries': sorted(changed), 'unchanged_entries': len(names) - len(changed),
        'kept_native': ['the part table, bounds, skeleton, materials and every unused byte of the model', 'the debris '
                        'model, its MRLs, normal and mask maps, the effect models, sounds, collision and layouts'],
        'live_verified': False, 'gameplay_verified': False,
        'what_must_be_seen': [f'an orange-grey grid box labelled {target.label} where the native object stood, the '
                              'same size, casting the same shadow', 'shooting it still breaks it (the debris is the '
                              'native model with the grid albedo)'],
        'failure_signs': ['the object is invisible: index words or winding the game rejects (the part table is native, '
                          'so the allocation is the suspect)', 'the object shows its photo texture: the material samples '
                          'an albedo this writer did not redraw', 'a hang at stage load: the in-place MOD edit itself'],
        'acceptance': 'experimental; offline structural checks only'}
    return written, receipt


def preview_set(out: Path, *, stage: str | None = None, objects: bool = False, size: int = 768,
                max_triangles: int = 120_000, merge: bool = False) -> dict:
    """PNGs for a written overlay set (`build_all` output): a stage's texture sheet and CPU view, or one sheet of every
    object albedo written. Each call writes a `<name>-preview.json` sidecar; `merge` folds the sidecars into
    receipt.json (`previews` per stage, `object_previews`). Separate from the build so that the slow CPU rasteriser
    (about a millisecond a triangle) can run per stage, in parallel, after the archives exist."""
    out = Path(out)
    receipt_path = out / 'receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    done = []
    if stage:
        row = receipt['stages'][stage]
        archive = (out / 'romfs' / Path(ARCHIVE_DIR) / f'{stage}.arc').read_bytes()
        arc = mt_arc.parse(archive)
        entries = {row_['name']: row_ for row_ in row['textures']}
        rows = [{'entry': i, 'name': e.name, 'variant': entries[e.name]['variant']}
                for i, e in enumerate(arc.entries) if e.name in entries]
        contact_sheet(archive, rows, out / f'{stage}-textures.png')
        view = render_stage(archive, out / f'{stage}-view.png', stage=stage, size=size, max_triangles=max_triangles)
        view['png'] = f'{stage}-view.png'
        (out / f'{stage}-preview.json').write_text(json.dumps(
            [{'png': f'{stage}-textures.png', 'shows': 'every written albedo, mip 0'}, view], indent=1), encoding='utf-8')
        done.append(stage)
    if merge:
        for name in list(receipt['stages']):
            sidecar = out / f'{name}-preview.json'
            if sidecar.is_file():
                receipt['stages'][name]['previews'] = json.loads(sidecar.read_text(encoding='utf-8'))
        sidecar = out / 'objects-preview.json'
        if sidecar.is_file():
            receipt['object_previews'] = json.loads(sidecar.read_text(encoding='utf-8'))
        receipt_path.write_text(json.dumps(receipt, indent=1), encoding='utf-8')
        done.append('merged')
    if objects:
        from PIL import Image, ImageDraw
        tiles = []
        for name, row in receipt['objects'].items():
            if 'skipped' in row:
                continue
            arc = mt_arc.parse((out / 'romfs' / Path(ARCHIVE_DIR) / name).read_bytes())
            for tex in row['textures']:
                index = next(i for i, e in enumerate(arc.entries) if e.name == tex['name'])
                tiles.append((name[:-4] + ' ' + tex['label'], mtf_tex.decode(_raw(arc.entries[index]), 0).convert('RGB')))
        columns, thumb = 10, 96
        lines = -(-len(tiles) // columns) or 1
        sheet = Image.new('RGB', (columns * thumb, lines * (thumb + 14)), (30, 30, 30))
        draw = ImageDraw.Draw(sheet)
        font = _font(9)
        for n, (label, image) in enumerate(tiles):
            x, y = (n % columns) * thumb, (n // columns) * (thumb + 14)
            sheet.paste(image.resize((thumb, thumb)), (x, y))
            draw.text((x + 2, y + thumb), label[:20], fill=(220, 220, 220), font=font)
        sheet.save(out / 'objects-textures.png')
        (out / 'objects-preview.json').write_text(json.dumps(
            [{'png': 'objects-textures.png', 'shows': f'{len(tiles)} object albedos, mip 0'}], indent=1), encoding='utf-8')
        done.append('objects')
    return {'rendered': done}


# --- CLI ------------------------------------------------------------------------------------------------------------

def write_overlay(out_dir: Path, archive_name: str, data: bytes, receipt: dict | None) -> Path:
    folder = Path(out_dir) / 'romfs' / Path(ARCHIVE_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / archive_name
    path.write_bytes(data)
    if receipt is not None:
        (Path(out_dir) / 'receipt.json').write_text(json.dumps(receipt, indent=1), encoding='utf-8')
    return path


def build_all(inputs: Path, uom_dir: Path, out: Path, *, stages: Iterable[str] = STAGES, box_crate: bool = True,
              preview: bool = True, rebuild_check: bool = False, log=print) -> dict:
    """The whole overlay set: every stage archive of `stages` found in `inputs` through `build`, every object archive
    their layouts place (found in `uom_dir`) through `build_prop_textures`, the crate boxed when `box_crate`
    (build_prop_box, the one in-place geometry edit the research note proved offline), all under
    `out/romfs/nativeNXx64/ImgNX/Archive/`, with one receipt.json (SHA-256 per file, per-stage counts, what must be
    seen, failure signs) and the preview PNGs. `rebuild_check` builds everything a second time in this process and
    refuses a difference (a second run in another process compared by hash is the cheaper evidence). Nothing is
    launched. Returns the receipt."""
    inputs, uom_dir, out = Path(inputs), Path(uom_dir), Path(out)
    files: dict[str, dict] = {}
    stage_rows = {}
    objects_needed: dict[str, dict] = {}
    for stage in stages:
        src = inputs / f'{stage}.arc'
        if not src.is_file():
            stage_rows[stage] = {'skipped': f'{src} not present'}
            continue
        archive = src.read_bytes()
        log(f'{stage}: measuring and writing')
        written, receipt = build(archive, stage=stage, progress=lambda *_: None)
        verify(archive, written, receipt)
        if rebuild_check and build(archive, stage=stage)[0] != written:
            raise GreyboxError(f'{stage}: two builds in one process differ; the writer is not deterministic')
        path = write_overlay(out, f'{stage}.arc', written, None)
        for name, layouts in placed_objects(mt_arc.parse(archive)).items():
            objects_needed.setdefault(name, {})[stage] = layouts
        row = {k: receipt[k] for k in ('source_sha256', 'written_sha256', 'bytes', 'entries', 'unchanged_entries',
                                       'variants', 'glyphs', 'scene_folders', 'kept_native_textures')}
        row |= {'changed_entries': len(receipt['changed_entries']), 'textures_written': len(receipt['textures']),
                'measurement': receipt['measurement'], 'rebuild_identical': True if rebuild_check else 'see the second run',
                'textures': [{k: r.get(k) for k in ('name', 'variant', 'rule', 'cells', 'label', 'glyphs',
                                                     'mirror_share', 'tile_u_cm', 'tile_v_cm', 'payload_sha256')}
                             for r in receipt['textures']]}
        if preview:
            contact_sheet(written, receipt['textures'], out / f'{stage}-textures.png')
            row['previews'] = [{'png': f'{stage}-textures.png', 'shows': 'every written albedo, mip 0'},
                               render_stage(written, out / f'{stage}-view.png', stage=stage)]
            row['previews'][1]['png'] = f'{stage}-view.png'
        stage_rows[stage] = row
        files[f'romfs/{ARCHIVE_DIR}/{stage}.arc'] = {'sha256': receipt['written_sha256'], 'bytes': len(written),
                                                     'source_sha256': receipt['source_sha256'], 'kind': 'stage'}
    object_rows = {}
    for name in sorted(objects_needed):
        src = uom_dir / name
        if not src.is_file():
            object_rows[name] = {'skipped': 'archive not present locally', 'stages': sorted(objects_needed[name])}
            continue
        archive = src.read_bytes()
        try:
            if box_crate and name == CRATE.archive:
                boxed, box_receipt = build_prop_box(archive, CRATE)
                written, receipt = build_prop_textures(boxed, archive_name=name)
                receipt['box'] = {k: box_receipt[k] for k in ('model', 'route')}
                receipt['source_sha256'] = hashlib.sha256(archive).hexdigest()
                receipt['route'] = 're5_stage_greybox.build_prop_box + build_prop_textures'
                receipt['changed_entries'] = sorted(set(receipt['changed_entries']) | set(box_receipt['changed_entries']))
                receipt['unchanged_entries'] = receipt['entries'] - len(receipt['changed_entries'])
            else:
                written, receipt = build_prop_textures(archive, archive_name=name)
        except GreyboxError as exc:
            object_rows[name] = {'skipped': str(exc), 'stages': sorted(objects_needed[name])}
            continue
        if rebuild_check:
            rebuilt, _ = (build_prop_textures(build_prop_box(archive, CRATE)[0], archive_name=name)
                          if box_crate and name == CRATE.archive else build_prop_textures(archive, archive_name=name))
            if rebuilt != written:
                raise GreyboxError(f'{name}: two builds in one process differ; the writer is not deterministic')
        write_overlay(out, name, written, None)
        object_rows[name] = {'stages': sorted(objects_needed[name]), 'layouts': objects_needed[name],
                             **{k: receipt[k] for k in ('route', 'source_sha256', 'written_sha256', 'bytes', 'entries',
                                                        'changed_entries', 'unchanged_entries', 'measurement')},
                             'textures': [{k: r.get(k) for k in ('name', 'label', 'cells', 'corner', 'glyphs',
                                                                  'mirror_share', 'payload_sha256')}
                                          for r in receipt['textures']],
                             **({'box': receipt['box']} if 'box' in receipt else {}),
                             'rebuild_identical': True if rebuild_check else 'see the second run'}
        files[f'romfs/{ARCHIVE_DIR}/{name}'] = {'sha256': receipt['written_sha256'], 'bytes': len(written),
                                                'source_sha256': receipt['source_sha256'], 'kind': 'object'}
    combined = {
        'title_id': TITLE_ID, 'overlay': out.name, 'route': 're5_stage_greybox.build_all',
        'files': files, 'stages': stage_rows, 'objects': object_rows,
        'manifest_note': 'files maps each RomFS path to the SHA-256 of the written archive: upload each as an artifact '
                         'and pass {path: {"artifact": sha256}} to switch_mods op=blueprint (or op=write)',
        'live_verified': False, 'gameplay_verified': False,
        'proven_live_before_this_set': ['stage-greybox-s400-v1 (s400.arc f26d2836…) booted and rendered on lilspark '
                                        '2026-11-09 (session ae02be4bd9974915-32e89a55f69c46db): grids, labels, '
                                        'lighting; several wall labels read mirrored - fixed here by handedness'],
        'what_must_be_seen': ['every Mercenaries stage in blue / grey grid tiles with metre labels under native light',
                              'labels reading forwards on walls that read mirrored in the s400-v1 frame',
                              'every placed object (barrels, crates, drums, chests, hourglasses, stalls, cars) in the '
                              'orange grid with its label; shooting them still breaks them',
                              'enemies, players, effects and the sky untouched except the flat sky tint'],
        'failure_signs': ['black screen or hang on one stage only: that stage\'s archive (bisect by variant there)',
                          'a photo surface left: see that stage\'s kept_native_textures / albedo_unparsed, or a '
                          'material outside the scenery folders', 'a backwards label: that texture\'s mirror_share',
                          'an object still photo-textured: its archive is in objects with skipped, or a variant '
                          'archive the host names differently (uOm08b8 / uOm0912 on this host)'],
        'acceptance': 'experimental; offline structural checks only'}
    (out / 'receipt.json').write_text(json.dumps(combined, indent=1), encoding='utf-8')
    return combined


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='RE5 Switch stage greybox and prop box writer (offline)')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('survey', help='measure the stage albedos and print the plan as JSON')
    s.add_argument('archive')
    s.add_argument('--stage', default='s400')
    b = sub.add_parser('build', help='write the greybox overlay of one stage archive')
    b.add_argument('archive')
    b.add_argument('--stage', default='s400')
    b.add_argument('--out', required=True, help='overlay folder; romfs/... and receipt.json are written inside')
    b.add_argument('--override', action='append', default=[], help='basename=variant (floor|wall|other|sky)')
    b.add_argument('--no-preview', action='store_true')
    p = sub.add_parser('prop', help='write the prop box candidate of one object archive')
    p.add_argument('archive')
    p.add_argument('--target', default='crate', choices=('crate', 'desk'))
    p.add_argument('--out', required=True)
    t = sub.add_parser('props', help='redraw the albedos of one object archive as the prop grid (geometry native)')
    t.add_argument('archive')
    t.add_argument('--out', required=True)
    a = sub.add_parser('all', help='every stage in --inputs and every object its layouts place: one overlay set')
    a.add_argument('--inputs', required=True, help='folder with s400.arc .. s407.arc')
    a.add_argument('--uom', required=True, help='folder with the uOm*.arc object archives')
    a.add_argument('--out', required=True)
    a.add_argument('--stages', default=','.join(STAGES))
    a.add_argument('--no-box-crate', action='store_true', help='keep the crate geometry native (textures only)')
    a.add_argument('--no-preview', action='store_true')
    a.add_argument('--rebuild-check', action='store_true', help='build everything twice in this process and compare')
    pv = sub.add_parser('preview', help='render the PNGs of a written overlay set (one stage per call, or the objects)')
    pv.add_argument('--out', required=True, help='the overlay set folder (receipt.json inside is updated)')
    pv.add_argument('--stage', help='s400 .. s407: its texture sheet and stage view')
    pv.add_argument('--objects', action='store_true', help='one sheet of every written object albedo')
    pv.add_argument('--size', type=int, default=768)
    pv.add_argument('--max-triangles', type=int, default=120_000)
    pv.add_argument('--merge', action='store_true', help='fold the rendered sidecars into receipt.json')
    v = sub.add_parser('verify', help='check a written stage overlay against its original')
    v.add_argument('--original', required=True)
    v.add_argument('--candidate', required=True)
    v.add_argument('--receipt')
    args = parser.parse_args(argv)
    if args.command == 'preview':
        print(json.dumps(preview_set(Path(args.out), stage=args.stage, objects=args.objects, size=args.size,
                                     max_triangles=args.max_triangles, merge=args.merge), indent=1))
        return 0
    if args.command == 'survey':
        arc = mt_arc.parse(Path(args.archive).read_bytes())
        folders = scene_folders(arc) or stage_scope(args.stage)
        surfaces, notes = measure(arc, folders)
        print(json.dumps({'scene_folders': list(folders) if not isinstance(folders, str) else [folders],
                          'measurement': notes, 'objects': placed_objects(arc), 'textures': plan(surfaces)}, indent=1))
        return 0
    if args.command == 'props':
        archive = Path(args.archive).read_bytes()
        written, receipt = build_prop_textures(archive, archive_name=Path(args.archive).name)
        out = Path(args.out)
        path = write_overlay(out, Path(args.archive).name, written, receipt)
        print(json.dumps({'written': str(path), 'sha256': receipt['written_sha256'], 'bytes': receipt['bytes'],
                          'textures': [(r['name'].rsplit(chr(92), 1)[-1], r['label']) for r in receipt['textures']]}, indent=1))
        return 0
    if args.command == 'all':
        receipt = build_all(Path(args.inputs), Path(args.uom), Path(args.out), stages=args.stages.split(','),
                            box_crate=not args.no_box_crate, preview=not args.no_preview,
                            rebuild_check=args.rebuild_check)
        print(json.dumps({'files': {k: v['sha256'] for k, v in receipt['files'].items()},
                          'stages': {k: v.get('variants', v.get('skipped')) for k, v in receipt['stages'].items()},
                          'objects_skipped': {k: v['skipped'] for k, v in receipt['objects'].items() if 'skipped' in v}},
                         indent=1))
        return 0
    if args.command == 'build':
        overrides = dict(item.split('=', 1) for item in args.override)
        archive = Path(args.archive).read_bytes()
        written, receipt = build(archive, stage=args.stage, overrides=overrides or None,
                                 progress=lambda name, variant: print(f'  {variant:5} {name.rsplit(chr(92), 1)[-1]}'))
        out = Path(args.out)
        path = write_overlay(out, f'{args.stage}.arc', written, receipt)
        verify(archive, written, receipt)
        if not args.no_preview:
            contact_sheet(written, receipt['textures'], out / 'textures.png')
            receipt['previews'] = [{'png': str(out / 'textures.png'), 'shows': 'every written albedo, mip 0'},
                                   render_stage(written, out / 'stage-view.png', stage=args.stage),
                                   render_stage(written, out / 'stage-close.png', stage=args.stage, pitch_deg=35.0,
                                                window_cm=4000.0)]
            (out / 'receipt.json').write_text(json.dumps(receipt, indent=1), encoding='utf-8')
        print(json.dumps({'written': str(path), 'sha256': receipt['written_sha256'], 'bytes': receipt['bytes'],
                          'variants': receipt['variants'], 'changed_entries': len(receipt['changed_entries'])}, indent=1))
        return 0
    if args.command == 'prop':
        target = {'crate': CRATE, 'desk': DESK}[args.target]
        archive = Path(args.archive).read_bytes()
        written, receipt = build_prop_box(archive, target)
        out = Path(args.out)
        receipt['previews'] = [render_model(archive, target.model, out / 'native.png'),
                               render_model(written, target.model, out / 'candidate.png')]
        path = write_overlay(out, target.archive, written, receipt)
        print(json.dumps({'written': str(path), 'sha256': receipt['written_sha256'], 'bytes': receipt['bytes']}, indent=1))
        return 0
    if args.command == 'verify':
        receipt = json.loads(Path(args.receipt).read_text(encoding='utf-8')) if args.receipt else None
        print(json.dumps(verify(Path(args.original).read_bytes(), Path(args.candidate).read_bytes(), receipt), indent=1))
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
