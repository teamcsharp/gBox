"""RE6 Switch stage greybox: a Mercenaries stage drawn like an Unreal blockout, with RE5's grid and label rules.

The RE6 counterpart of `gbox.re5_stage_greybox` for the stage archives `s120N.arc` of RE6 Switch (title
01002A000CD48000). Nothing here launches a game or talks to the gBox API; every output is a candidate with a receipt
that says `live_verified: false`. The grid generator, the label rule (floors carry the pixel width and a metre tag,
walls and the checker their metre span), the measurement dataclass and the triangle charging are RE5's own
(`re5_stage_greybox.grid_image`, `plan`'s rule, `Surface`, `_charge`); what differs is measured here:

* **Which archives.** The ten Mercenaries stages are `s1200.arc` .. `s1209.arc` (the geometry, 28-63 MB each) with a
  per-mode set beside each: `s120NSoft.arc` (THE MERCENARIES: `Attack_Control_*` up to 150 kills) and `s121NSoft.arc`
  (NO MERCY: up to 300). The two Soft archives of one stage carry the same stage NAV (`soft\\stage\\s12xN\\s12xN`,
  identical sizes), the enemy layouts (`s12xN_emNN`), items, cameras and the FSM; the geometry is shared. The stage
  select's names are not in these archives; one is measured: the live nav mesh `s1218` (2005 vertices, 3434 triangles)
  was read during Mining the Depths (re6_switch's NavMesh note) and the host's learned stage book for `s1218` holds the
  same counts - so `s1208.arc` is **Mining the Depths**. Its content agrees (an undersea facility: the sky dome is
  `kaityuu` / `kaimennaka` - undersea, the sea surface from below - with sharks, a manta and fish schools).
* **The scene.** Every piece is under `data\\stage\\sNNNN\\scr\\` (`scr00` and `scr01`): bone-less MOD v `0xD3` with
  an MRL v36 of the same name. Measured on s1208 (21 MOD, 117 materials): 116 materials bind an albedo through
  `re6_switch_tex.texture_set_materials` (`tAlbedoMap`; one, `XfB_W_0__m00_167`, carries the command with texture
  index 0 - unbound) and all sample the primary UV (`FUVAlbedoMap` -> `FUVPrimary`). `mtf_mrl.inspect_bindings`
  refuses these MRLs (RE5's 64-bit shader word), so the RE6 decoder is the path.
* **The vertex formats** (`STAGE_LAYOUT`, all `float32` positions at +0): on every format that carries a signed-byte
  normal it sits at +12 with `w = -1` (agreement with the geometric face normal 99.97-100 %), the tangent at +16 and the
  albedo UV (half2) at +20 - RE5's layout. `0x37607D20` (24 bytes, the most common here: 248 meshes) and `0x36D0D7A7`
  (20 bytes) carry no signed-byte normal and their only UV at +16 (`0x37607D20` has an RGBA8 colour at +20); for them the
  geometric face normal decides up / side / down, with the winding the measured formats agree on.
* **The albedos** are `0x2B`: BC3 holding Y'CbCr + opacity (`re6_switch_tex`, handover section 0.1), written through
  `re6_switch_tex.replace_albedo`; each keeps its native dimensions, mip count, TEX header and size, and its native
  **opacity** (the colour block's green). The `0x14` `_NUKI` cut-out albedos (5 on s1208) are a format no writer here
  encodes: they stay native and are listed. Normal maps, masks, the light map, the MRLs, the MODs, the NAV, the layouts,
  sounds and effects stay byte for byte native.

The colour of a grid (blue floors, grey walls) goes through the Y'CbCr model, which no boot has confirmed yet (the
probes of handover section 0.5 are the test). The luma - the lines and the labels - does not depend on it, and
`chroma=False` (`build --luma`) writes the grids in greyscale with the native neutral colour block: the fallback that
is correct whatever the chroma model turns out to be.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zlib
from pathlib import Path

import numpy as np

from . import mt_arc, mt_model, mtf_author, re6_switch_tex as T
from . import re5_stage_greybox as R5

TITLE_ID = '01002A000CD48000'
ARCHIVE_DIR = 'nativeNXx64/arc/NX'
MERCS_STAGES = tuple(f's120{n}' for n in range(10))          # the geometry archives
MERCS_SETS = {code: (f'{code}Soft', f's121{code[-1]}Soft') for code in MERCS_STAGES}   # (Mercenaries, No Mercy)
#: The stage select's names, where measured (see the module text); the others are listed as unmeasured.
STAGE_NAMES = {'s1208': 'Mining the Depths'}
ALBEDO_FORMAT = 0x2B
#: Measured component offsets of the RE6 stage (bone-less) vertex formats: float3 position at 0; `normal` None means the
#: format carries no signed-byte normal (the geometric face normal is used).
STAGE_LAYOUT = {
    0x37607D20: {'normal': None, 'uv': 16},                    # 24: + RGBA8 colour at +20
    0x2ED06F92: {'normal': 12, 'uv': 20},                      # 32: tangent +16, uv2 +24, colour +28
    0x29F0B449: {'normal': 12, 'uv': 20},                      # 28: colour +24
    0x36D0D7A7: {'normal': None, 'uv': 16},                    # 20
    0x33C09993: {'normal': 12, 'uv': 20},                      # 32: colour +28
    0x2C207F5E: {'normal': 12, 'uv': 20},                      # 28: uv2 +24
    0x341068B6: {'normal': 12, 'uv': 20},                      # 36: light-map uv +24, colour +28, uv2 +32
    0x2AE06DB8: {'normal': 12, 'uv': 20},                      # 32: light-map uv +24
}
FLOOR_WORDS = R5.FLOOR_WORDS + ('tuuro', 'kowareasiba')       # (tuuro: a passage)
WALL_WORDS = R5.WALL_WORDS + ('hasira', 'madowaku')            # (hasira: a pillar; madowaku: a window frame)
SKY_MODELS = ('sky',)                                          # scene pieces whose albedos are the sky dome


class GreyboxError(ValueError):
    """The input is not the measured RE6 Switch stage layout, or a check the writer relies on failed."""


def _raw(entry) -> bytes:
    try:
        return zlib.decompress(entry.data)
    except zlib.error:
        return entry.data


def _wrap(raw: bytes) -> bytes:
    return zlib.compress(raw, 6)


def stage_scope(stage: str) -> str:
    if not re.fullmatch(r's\d{4}', stage):
        raise GreyboxError(f'{stage!r} is not an RE6 stage code like s1208')
    return f'data\\stage\\{stage}\\scr\\'


def stage_models(arc: mt_arc.Arc, scope: str) -> list[tuple[str, int, int]]:
    """(name, MOD entry index, MRL entry index) for every scene piece in `scope` that has both."""
    kinds: dict[str, dict[bytes, int]] = {}
    for index, entry in enumerate(arc.entries):
        if entry.name.startswith(scope):
            magic = _raw(entry)[:4]
            if magic in (b'MOD\0', b'MRL\0'):
                kinds.setdefault(entry.name, {})[magic] = index
    return [(name, found[b'MOD\0'], found[b'MRL\0']) for name, found in sorted(kinds.items())
            if b'MOD\0' in found and b'MRL\0' in found]


def material_family(name: str) -> str:
    """The shader token of an RE6 stage material name (`XfB_N__EW__m00_15` -> `XfB_N__EW`)."""
    return re.sub(r'__m\d+_\d*$', '', name)


def material_bindings(mod_raw: bytes, mrl_entry) -> list[dict]:
    """Per MOD material (by index): its name, family, whether it is alpha-tested (`FTransparencyAlpha`) and the path
    bound to `tAlbedoMap`, matched to the MRL by the material name's hash."""
    model = mt_model.parse_mod(mod_raw)
    header = model.header()
    if (header['version'], header['revision']) != (0xD3, 0):
        raise GreyboxError('expected the measured RE6 Switch stage MOD revision (0xD3, 0)')
    offsets, count = header['offsets'], header['material_count']
    if offsets['materials'] + count * 128 != offsets['meshes']:
        raise GreyboxError('the MOD material name table does not match its count')
    sets = T.texture_set_materials(mt_arc.Arc(version=7, entries=[mrl_entry]))
    if not sets:
        raise GreyboxError('the MRL does not parse')
    by_hash = {m['name_hash']: m for m in sets[0]['materials']}
    rows = []
    for index in range(count):
        name = model.raw[offsets['materials'] + index * 128:offsets['materials'] + (index + 1) * 128].split(b'\0', 1)[0]
        text = name.decode('ascii', 'replace')
        record = by_hash.get(zlib.crc32(name) ^ 0xFFFFFFFF)
        rows.append({'index': index, 'name': text, 'family': material_family(text),
                     'alpha_tested': bool(record) and record['functions'].get('FTransparency') == 'FTransparencyAlpha',
                     'albedo': (record or {}).get('slots', {}).get('tAlbedoMap')})
    return rows


def mesh_geometry(model: mt_model.ModFile, index: int):
    """(positions (n,3) cm, vertex normals (n,3) - zeros where the format has none, albedo UV (n,2), triangles (m,3)
    local) of one stage mesh, or None when its format is not measured or it has no triangles."""
    data, record = model.mesh_bytes(index)
    layout = STAGE_LAYOUT.get(record['vertex_format'])
    if layout is None or not data or record['vertex_count'] < 3:
        return None
    stride = record['vertex_stride']
    if mt_model.fvf_stride(record['vertex_format']) not in (None, stride) or len(data) != record['vertex_count'] * stride:
        raise GreyboxError(f'mesh {index}: stride {stride} disagrees with format {record["vertex_format"]:08x}')
    array = np.frombuffer(data, np.uint8).reshape(-1, stride)
    positions = array[:, :12].copy().view('<f4').reshape(-1, 3).astype(np.float64)
    if layout['normal'] is None:
        normals = np.zeros_like(positions)
    else:
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


# --- measurement --------------------------------------------------------------------------------------------------

def albedo_surfaces(arc: mt_arc.Arc, scope: str) -> dict[str, R5.Surface]:
    """Every `0x2B` `_BM` TEX in `scope`, keyed by its full path, before any geometry is charged to it."""
    out: dict[str, R5.Surface] = {}
    for index, entry in enumerate(arc.entries):
        if not entry.name.startswith(scope) or not entry.name.endswith('_BM'):
            continue
        raw = _raw(entry)
        if raw[:4] != b'TEX\0':
            continue
        try:
            tex = T.Surface(raw)
        except T.TexError:
            continue
        if tex.format != ALBEDO_FORMAT:
            continue
        if entry.name in out:
            raise GreyboxError(f'two TEX entries share the name {entry.name!r}; the writer addresses by name')
        out[entry.name] = R5.Surface(name=entry.name, entry=index, width=tex.width, height=tex.height,
                                     format=tex.format, mips=tex.mip_count)
    return out


def measure(arc: mt_arc.Arc, scope: str) -> tuple[dict[str, R5.Surface], dict]:
    """Charge every triangle of every stage mesh to the albedo its material binds; returns (surfaces, notes)."""
    surfaces = albedo_surfaces(arc, scope)
    notes = {'models': 0, 'meshes': 0, 'meshes_skipped_format': 0, 'formats_skipped': {}, 'triangles': 0,
             'geometric_normal_meshes': 0, 'unbound_materials': 0, 'albedos_kept_native': {}, 'sky_models': [],
             'mrl_unparsed': []}
    sky_only: dict[str, bool] = {}
    for name, mod_index, mrl_index in stage_models(arc, scope):
        mod_raw = _raw(arc.entries[mod_index])
        try:
            bindings = material_bindings(mod_raw, arc.entries[mrl_index])
        except (GreyboxError, T.TexError, struct.error) as exc:
            notes['mrl_unparsed'].append({'name': name, 'reason': str(exc)})
            continue
        model = mt_model.parse_mod(mod_raw)
        notes['models'] += 1
        sky = name.rsplit('\\', 1)[-1].lower().startswith(SKY_MODELS)
        if sky:
            notes['sky_models'].append(name)
        for k, record in enumerate(model.meshes()):
            material = bindings[record['material_index']] if record['material_index'] < len(bindings) else None
            albedo = material and material['albedo']
            if albedo and albedo not in surfaces:
                notes['albedos_kept_native'].setdefault(albedo, _format_of(arc, albedo))
            geometry = mesh_geometry(model, k)
            if geometry is None:
                notes['meshes_skipped_format'] += 1
                key = f"{record['vertex_format']:08X}"
                notes['formats_skipped'][key] = notes['formats_skipped'].get(key, 0) + 1
                continue
            surface = surfaces.get(albedo) if albedo else None
            if surface is None:
                if not albedo:
                    notes['unbound_materials'] += 1
                continue
            notes['meshes'] += 1
            if STAGE_LAYOUT[record['vertex_format']]['normal'] is None:
                notes['geometric_normal_meshes'] += 1
            positions, normals, uvs, triangles = geometry
            notes['triangles'] += len(triangles)
            if material['name'] not in surface.materials:
                surface.materials.append(material['name'])
                surface.families.append(material['family'])
            surface.alpha_tested = surface.alpha_tested or material['alpha_tested']
            sky_only[surface.name] = sky_only.get(surface.name, True) and sky
            R5._charge(surface, positions, normals, uvs, triangles)
    for surface in surfaces.values():
        surface.settle()
    notes['sky_textures'] = sorted(n for n, only in sky_only.items() if only)
    return surfaces, notes


def _format_of(arc: mt_arc.Arc, name: str) -> str:
    entry = arc.find(name)
    if entry is None:
        return 'not in this archive'
    try:
        return f'0x{T.Surface(_raw(entry)).format:02x}'
    except T.TexError as exc:
        return f'unparsed ({exc})'


def classify(surface: R5.Surface, sky_textures=()) -> tuple[str, str]:
    """(variant, rule): the sky dome by its scene piece, then RE5's order - the geometry where it is clear, the name
    where it is mixed, else `other`."""
    lower = surface.basename.lower()
    if surface.name in sky_textures:
        return 'sky', 'model:sky'
    if any(word in lower for word in R5.SKY_WORDS):
        return 'sky', 'name:sky'
    if any(word in lower for word in R5.ROOF_WORDS):
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
    return 'other', 'default' if surface.area_cm2 > 0 else 'unbound'


def plan(surfaces: dict[str, R5.Surface], sky_textures=(), overrides: dict[str, str] | None = None) -> list[dict]:
    """One row per albedo: the variant, the rule that chose it, the cells and labels (RE5's rule)."""
    rows = []
    for name in sorted(surfaces):
        surface = surfaces[name]
        variant, rule = classify(surface, sky_textures)
        if overrides and surface.basename in overrides:
            variant, rule = overrides[surface.basename], 'override'
            if variant not in R5.VARIANTS:
                raise GreyboxError(f'override {variant!r} for {surface.basename} is not a variant')
        cells_u, cells_v = R5.grid_cells(surface.tile_u_cm), R5.grid_cells(surface.tile_v_cm)
        if variant == 'floor':
            label, corner = str(surface.width), R5.span_label(surface.tile_u_cm)
        else:
            u, v = R5.span_label(surface.tile_u_cm), R5.span_label(surface.tile_v_cm)
            label, corner = (u if cells_u == cells_v else f'{u} x {v}'), ''
        rows.append({'variant': variant, 'rule': rule, 'cells': [cells_u, cells_v], 'label': label,
                     'corner': corner, **surface.report()})
    return rows


# --- the grid textures ----------------------------------------------------------------------------------------------

def greybox_texture(native: bytes, variant: str, cells_u: int, cells_v: int, label: str, corner: str = '',
                    *, chroma: bool = True) -> tuple[bytes, dict]:
    """A `0x2B` TEX with `native`'s header, dimensions and mip chain, drawn as RE5's grid; the native opacity (the
    colour block's green) is kept. Returns (bytes, report)."""
    from PIL import Image

    tex = T.Surface(native)
    if tex.format != ALBEDO_FORMAT:
        raise GreyboxError(f'only 0x2B albedos are rewritten (format 0x{tex.format:02x})')
    image = R5.grid_image(tex.width, tex.height, variant, cells_u, cells_v, label, corner).convert('RGBA')
    _rgb, opacity = tex.albedo(0)
    pixels = np.asarray(image, np.uint8).copy()
    pixels[..., 3] = opacity
    out = T.replace_albedo(native, Image.fromarray(pixels, 'RGBA'), chroma=chroma, opacity=True)
    head = 20 + 4 * tex.mip_count
    if len(out) != len(native) or out[:head] != native[:head]:
        raise GreyboxError('the rewritten TEX does not keep the native header and mip table')
    return out, {'variant': variant, 'cells': [cells_u, cells_v], 'label': label, 'corner': corner,
                 'opacity': f'native kept (min {int(opacity.min())}, max {int(opacity.max())})',
                 'chroma': chroma, 'width': tex.width, 'height': tex.height, 'format': tex.format,
                 'mips': tex.mip_count}


# --- the overlay ----------------------------------------------------------------------------------------------------

def build(archive: bytes, *, stage: str = 's1208', overrides: dict[str, str] | None = None, chroma: bool = True,
          progress=lambda *_: None) -> tuple[bytes, dict]:
    """The stage archive with every `scr` albedo drawn as a greybox grid; returns (archive, receipt)."""
    arc = mt_arc.parse(archive)
    if mt_arc.build(arc) != archive:
        raise GreyboxError('the archive does not rebuild byte-identically; refusing to write on top of it')
    scope = stage_scope(stage)
    surfaces, notes = measure(arc, scope)
    if not surfaces:
        raise GreyboxError(f'no 0x2B albedo under {scope}')
    rows = plan(surfaces, notes['sky_textures'], overrides)
    changed = []
    for row in rows:
        entry = arc.entries[row['entry']]
        native = _raw(entry)
        if entry.data != _wrap(native):
            raise GreyboxError(f'{entry.name}: the native stream is not a level-6 zlib wrap; cannot rewrite it faithfully')
        if entry.tag != (0x40000000 | len(native)):
            raise GreyboxError(f'{entry.name}: the tag is not the measured 0x40000000 | length form')
        progress(row['name'], row['variant'])
        out, report = greybox_texture(native, row['variant'], *row['cells'], row['label'], row['corner'], chroma=chroma)
        entry.data = _wrap(out)
        entry.size = len(entry.data)
        row.update(report, payload_sha256=hashlib.sha256(out).hexdigest())
        changed.append(row['entry'])
    written = mt_arc.build(arc)
    original, final = mt_arc.parse(archive), mt_arc.parse(written)
    untouched = [i for i in range(len(original.entries)) if i not in set(changed)]
    if any(original.entries[i].data != final.entries[i].data for i in untouched):
        raise GreyboxError('an entry outside the albedo list changed')
    counts: dict[str, int] = {}
    for row in rows:
        counts[row['variant']] = counts.get(row['variant'], 0) + 1
    receipt = {
        'title_id': TITLE_ID, 'stage': stage, 'stage_name': STAGE_NAMES.get(stage, 'not measured'),
        'archive': f'{stage}.arc', 'route': 're6_stage_greybox.build', 'chroma': chroma,
        'source_sha256': hashlib.sha256(archive).hexdigest(), 'written_sha256': hashlib.sha256(written).hexdigest(),
        'bytes': len(written), 'source_bytes': len(archive), 'entries': len(final.entries),
        'changed_entries': sorted(changed), 'unchanged_entries': len(untouched), 'variants': counts,
        'measurement': notes, 'textures': rows,
        'kept_native': ['every MOD, MRL, _NM normal map, _MM / _AM mask, the _LM light map, the 0x14 _NUKI cut-out '
                        'albedos, the light and effect entries, layouts, sounds', 'the opacity of every albedo'],
        'live_verified': False, 'gameplay_verified': False,
        'what_must_be_seen': ['the stage drawn in grey and blue grid tiles with metre labels under the native '
                              'lighting', 'floors blue with the pixel size and a metre tag, walls grey with the metre '
                              'label, pipes, rails and clutter checkered', 'the undersea dome a flat pale tone',
                              'the sharks, the manta and the fish schools (the _NUKI cut-outs) still in their own '
                              'textures', 'enemies and players unchanged'] if chroma else
                             ['the same, in greyscale: every grid line and label in luma, no colour'],
        'failure_signs': ['black screen or hang at stage load: a TEX the game rejects (bisect by variant)',
                          'the grids right but in odd colours (teal / pink / orange): the Y\'CbCr chroma model is off - '
                          'boot the --luma build (it does not depend on it)',
                          'a surface still showing a photograph: an albedo bound from outside data\\stage\\<stage>\\scr '
                          '(effects, the light folder) or a _NUKI cut-out',
                          'holes where a surface was opaque: the opacity (green) was not kept',
                          'the native stage textures everywhere: the overlay did not load, or the 1.0.2 update '
                          'replaces this archive (its BKTR RomFS is not extracted - see docs/research/re6-parity.md)'],
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
        if not a.name.endswith('_BM'):
            raise GreyboxError(f'entry {index} {a.name} is not an albedo but changed')
        raw_a, raw_b = _raw(a), _raw(b)
        if b.data != _wrap(raw_b):
            raise GreyboxError(f'entry {index}: not a level-6 zlib wrap')
        ta, tb = T.Surface(raw_a), T.Surface(raw_b)
        if (ta.width, ta.height, ta.format, ta.mip_count) != (tb.width, tb.height, tb.format, tb.mip_count):
            raise GreyboxError(f'entry {index}: dimensions, format or mip count changed')
        head = 20 + 4 * ta.mip_count
        if len(raw_a) != len(raw_b) or raw_a[:head] != raw_b[:head]:
            raise GreyboxError(f'entry {index}: TEX header or size changed')
        if receipt is not None:
            row = next((r for r in receipt.get('textures', []) if r['entry'] == index), None)
            if row is None or row.get('payload_sha256') != hashlib.sha256(raw_b).hexdigest():
                raise GreyboxError(f'entry {index}: payload does not match the receipt')
    if receipt is not None and sorted(receipt.get('changed_entries', [])) != changed:
        raise GreyboxError('the receipt lists other changed entries than the archive shows')
    return {'entries': len(after.entries), 'changed': changed, 'unchanged': len(after.entries) - len(changed),
            'sha256': hashlib.sha256(candidate).hexdigest()}


# --- previews (the written bytes decoded on the CPU, through the Y'CbCr model; not the game) ------------------------

def _decoded(raw: bytes, limit: int = 0) -> np.ndarray:
    tex = T.Surface(raw)
    mip = 0
    while limit and mip + 1 < tex.mip_count and max(tex.mip_size(mip)) > limit:
        mip += 1
    return np.asarray(tex.decode(mip).convert('RGB'), np.uint8)


def contact_sheet(candidate: bytes, rows: list[dict], png: Path, *, thumb: int = 96, columns: int = 10) -> None:
    """Thumbnails of every written albedo (decoded from the candidate) with its name."""
    from PIL import Image, ImageDraw

    arc = mt_arc.parse(candidate)
    rows = sorted(rows, key=lambda r: (r['variant'], r['name']))
    lines = -(-len(rows) // columns)
    sheet = Image.new('RGB', (columns * thumb, lines * (thumb + 14)), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    font = R5._font(9)
    for n, row in enumerate(rows):
        image = Image.fromarray(_decoded(_raw(arc.entries[row['entry']]), 512)).resize((thumb, thumb))
        x, y = (n % columns) * thumb, (n // columns) * (thumb + 14)
        sheet.paste(image, (x, y))
        draw.text((x + 2, y + thumb), row['name'].rsplit('\\', 1)[-1][:18], fill=(220, 220, 220), font=font)
    sheet.save(png)


def render_stage(candidate: bytes, png: Path, *, stage: str = 's1208', size: int = 1024, yaw_deg: float = 30.0,
                 pitch_deg: float = 55.0, max_triangles: int = 400_000, window_cm: float | None = None,
                 percentile: float = 2.0) -> dict:
    """An orthographic CPU view of the stage's LOD-0 geometry textured with the archive's albedos (no lighting, alpha
    test or sky): the written surfaces on the native geometry."""
    from PIL import Image

    arc = mt_arc.parse(candidate)
    scope = stage_scope(stage)
    textures: dict[str, np.ndarray] = {}
    for entry in arc.entries:
        if entry.name.startswith(scope) and entry.name.endswith('_BM'):
            try:
                textures[entry.name] = _decoded(_raw(entry), 256)
            except T.TexError:
                continue
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    rot_y = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rot_x = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    rotation = rot_x @ rot_y
    pieces = []
    for name, mod_index, mrl_index in stage_models(arc, scope):
        if name.rsplit('\\', 1)[-1].lower().startswith(SKY_MODELS):
            continue
        mod_raw = _raw(arc.entries[mod_index])
        try:
            bindings = material_bindings(mod_raw, arc.entries[mrl_index])
        except (GreyboxError, T.TexError, struct.error):
            continue
        model = mt_model.parse_mod(mod_raw)
        for k, record in enumerate(model.meshes()):
            if not record['level_of_detail'] & 1 or record['material_index'] >= len(bindings):
                continue
            albedo = bindings[record['material_index']]['albedo']
            geometry = mesh_geometry(model, k) if albedo in textures else None
            if geometry is None:
                continue
            positions, _normals, uvs, triangles = geometry
            p0, p1, p2 = (positions[triangles[:, i]] for i in range(3))
            face = np.cross(p1 - p0, p2 - p0)
            face /= np.maximum(np.linalg.norm(face, axis=1), 1e-9)[:, None]
            pieces.append((positions @ rotation.T, face @ rotation.T, uvs, triangles, textures[albedo]))
    if not pieces:
        raise GreyboxError('nothing to draw')
    everything = np.concatenate([p for p, *_ in pieces])
    if window_cm:
        middle = np.median(everything, axis=0)
        low, high = middle - window_cm / 2, middle + window_cm / 2
    else:
        low = np.percentile(everything, percentile, axis=0)
        high = np.percentile(everything, 100 - percentile, axis=0)
    scale = (size - 8) / (max(high[0] - low[0], high[1] - low[1]) or 1.0)
    canvas = np.full((size, size, 3), 24, np.uint8)
    zbuf = np.full((size, size), np.inf)
    drawn = 0
    for positions, faces, uvs, triangles, texture in pieces:
        screen = np.empty((len(positions), 2))
        screen[:, 0] = (positions[:, 0] - low[0]) * scale + 4
        screen[:, 1] = (high[1] - positions[:, 1]) * scale + 4
        depth = -positions[:, 2]
        inside = (screen[:, 0] > -size) & (screen[:, 0] < 2 * size) & (screen[:, 1] > -size) & (screen[:, 1] < 2 * size)
        for t, tri in enumerate(triangles):
            if drawn >= max_triangles:
                break
            if not inside[tri].any():
                continue
            n = faces[t]
            shade = 0.55 + 0.45 * abs(float(n[1]) * 0.6 + float(n[2]) * 0.8)
            R5._rasterise(canvas, zbuf, screen[tri], depth[tri], uvs[tri], np.clip(texture * shade, 0, 255).astype(np.uint8))
            drawn += 1
    Image.fromarray(canvas, 'RGB').save(png)
    return {'png': str(png), 'triangles': drawn, 'view': f'orthographic, yaw {yaw_deg}, pitch {pitch_deg}',
            'shows': 'the albedos of this archive on its LOD-0 geometry, flat shade; not the game'}


# --- CLI ------------------------------------------------------------------------------------------------------------

def write_overlay(out_dir: Path, archive_name: str, data: bytes, receipt: dict) -> Path:
    folder = Path(out_dir) / 'romfs' / Path(ARCHIVE_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / archive_name
    path.write_bytes(data)
    (Path(out_dir) / 'receipt.json').write_text(json.dumps(receipt, indent=1), encoding='utf-8')
    return path


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='RE6 Switch stage greybox writer (offline)')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('survey', help='measure the stage albedos and print the plan as JSON')
    s.add_argument('archive')
    s.add_argument('--stage', default='s1208')
    b = sub.add_parser('build', help='write the greybox overlay of one stage archive')
    b.add_argument('archive')
    b.add_argument('--stage', default='s1208')
    b.add_argument('--out', required=True, help='overlay folder; romfs/... and receipt.json are written inside')
    b.add_argument('--override', action='append', default=[], help='basename=variant (floor|wall|other|sky)')
    b.add_argument('--luma', action='store_true', help='greyscale grids (the neutral colour block): no chroma model')
    b.add_argument('--no-preview', action='store_true')
    v = sub.add_parser('verify', help='check a written stage overlay against its original')
    v.add_argument('--original', required=True)
    v.add_argument('--candidate', required=True)
    v.add_argument('--receipt')
    args = parser.parse_args(argv)
    if args.command == 'survey':
        arc = mt_arc.parse(Path(args.archive).read_bytes())
        surfaces, notes = measure(arc, stage_scope(args.stage))
        print(json.dumps({'measurement': notes, 'textures': plan(surfaces, notes['sky_textures'])}, indent=1))
        return 0
    if args.command == 'build':
        overrides = dict(item.split('=', 1) for item in args.override)
        archive = Path(args.archive).read_bytes()
        written, receipt = build(archive, stage=args.stage, overrides=overrides or None, chroma=not args.luma,
                                 progress=lambda name, variant: print(f'  {variant:5} {name.rsplit(chr(92), 1)[-1]}'))
        out = Path(args.out)
        path = write_overlay(out, f'{args.stage}.arc', written, receipt)
        verify(archive, written, receipt)
        if not args.no_preview:
            contact_sheet(written, receipt['textures'], out / 'textures.png')
            receipt['previews'] = [{'png': str(out / 'textures.png'), 'shows': 'every written albedo, decoded'},
                                   render_stage(archive, out / 'stage-native.png', stage=args.stage),
                                   render_stage(written, out / 'stage-view.png', stage=args.stage),
                                   render_stage(written, out / 'stage-close.png', stage=args.stage, pitch_deg=35.0,
                                                window_cm=3000.0)]
            (out / 'receipt.json').write_text(json.dumps(receipt, indent=1), encoding='utf-8')
        print(json.dumps({'written': str(path), 'sha256': receipt['written_sha256'], 'bytes': receipt['bytes'],
                          'variants': receipt['variants'], 'changed_entries': len(receipt['changed_entries'])}, indent=1))
        return 0
    if args.command == 'verify':
        receipt = json.loads(Path(args.receipt).read_text(encoding='utf-8')) if args.receipt else None
        print(json.dumps(verify(Path(args.original).read_bytes(), Path(args.candidate).read_bytes(), receipt), indent=1))
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
