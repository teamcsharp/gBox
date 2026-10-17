"""Reviewed native face texture editing, with immutable preview-to-build lineage.

The worker extracts one owned DOA2 head. The control plane edits only that
bound texture and round-trips the native codec before an operator saves it.
Build jobs name exact approved recipes, never mutable editor defaults.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import re
import time
from typing import Literal
import uuid

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from .models import Permission as P
from .registry import tool

GAME = '1de2e7634f3161ff'
FORMAT = 'native-face-editor-v1'
EDITABLE = {'crop', 'bounds', 'opacity', 'feather', 'deformation'}
SOURCE_FILES = ('native_face_editor.py', 'native_face_projection.py', 'face_warp.py', 'doa2_faces.py',
                'doa2_textures.py', 'doa2_geometry.py', 'doa2_bindings.py')
# Frozen at import, like worker build_sources. A rolling disk update must not
# silently let an older interpreter build a newer editor's reviewed recipe.
IMPLEMENTATION = {'gbox/' + name: hashlib.sha256(Path(__file__).with_name(name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                  for name in SOURCE_FILES}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def profiles():
    return json.loads(Path(__file__).with_name('doa2_face_profiles.json').read_text())['profiles']


def settings_for(profile, edits=None):
    from .face_warp import normalize_deformation
    edits = edits or {}
    if not isinstance(edits, dict) or set(edits) - EDITABLE:
        raise ValueError('Only face placement, blend and deformation settings are editable')
    merged = {k: profile[k] for k in EDITABLE if k in profile}
    merged.update(edits)
    merged.setdefault('crop', [.22, .035, .79, .7])
    merged.setdefault('opacity', 1.)
    merged.setdefault('feather', .12)
    merged['deformation'] = normalize_deformation(merged.get('deformation'))
    # Projection validates bounds/crop and finite values before allocating work.
    for k in ('crop', 'bounds'):
        if k in merged:
            a = np.asarray(merged[k], dtype=float)
            if a.shape != (4,) or not np.isfinite(a).all():
                raise ValueError('Face bounds/crop need four finite coordinates')
            merged[k] = a.tolist()
    for k in ('opacity', 'feather'):
        v = merged[k]
        if type(v) not in (int, float) or not np.isfinite(v):
            raise ValueError('Face blend settings must be finite')
        if not (0 <= v <= 1 if k == 'opacity' else 0 < v <= 1):
            raise ValueError('Face blend settings are outside their range')
    return merged


def extract_surface(disc, key):
    """Read one exact owned material; no image, model or session is modified."""
    from . import doa2_bindings as B, doa2_geometry as G, doa2_textures as T
    profile = profiles().get(key)
    if profile is None:
        raise ValueError('Choose a face from the reviewed native DOA2 catalog')
    executable = disc.read('1ST_READ.BIN')
    binding = B.resolve_archive_binding(executable, key)
    head = binding['sections']['primary'][1]
    if head != profile['head_model']:
        raise ValueError('The native actor head binding changed')
    raw = disc.read(key)
    bank = disc.read(key[:-4] + '.BIN')
    tex = T.descriptors(raw, bank)[int(profile['texture'])]
    payload = bank[tex.offset:tex.offset + tex.size]
    if digest(payload) != profile['sha256']:
        raise ValueError('The reviewed native face texture changed; inspect the original owned title')
    if tex.width > 1024 or tex.height > 1024 or len(payload) > 2 * 1024**2:
        raise ValueError('This native face exceeds the editor size limit')
    primitives = []
    for mesh in G.decode_chr(raw)['models'][head]['meshes']:
        if mesh['texture_id'] != tex.index or not mesh['triangles']:
            continue
        a = np.asarray(mesh['vertices'], dtype=float)
        primitives.append({'pos': a[:, :3].tolist(), 'nrm': a[:, 3:6].tolist(),
                           'uv': a[:, 6:8].tolist(), 'tris': mesh['triangles']})
    descriptor = asdict(tex) | {'offset': 0, 'capacity': len(payload)}
    return {'format': FORMAT, 'game_id': GAME, 'profile_key': key,
            'profile_sha256': digest(canonical(profile)), 'source_texture_sha256': digest(payload),
            'source_geometry_sha256': digest(raw), 'source_executable_sha256': digest(executable),
            'texture': descriptor, 'payload': base64.b64encode(payload).decode(), 'primitives': primitives}


def validate_surface(bundle):
    from . import doa2_textures as T
    if not isinstance(bundle, dict) or bundle.get('format') != FORMAT or bundle.get('game_id') != GAME:
        raise ValueError('Unsupported native face inspection')
    profile = profiles().get(bundle.get('profile_key'))
    if not profile or bundle.get('profile_sha256') != digest(canonical(profile)):
        raise ValueError('The reviewed native profile changed; inspect again')
    encoded = bundle.get('payload')
    if not isinstance(encoded, str) or len(encoded) > 3 * 1024**2:
        raise ValueError('Native texture inspection exceeds its payload limit')
    payload = base64.b64decode(encoded, validate=True)
    tex = T.Texture(**bundle['texture'])
    if (any(type(v) is not int for v in asdict(tex).values()) or tex.width <= 0 or tex.height <= 0
            or tex.width & (tex.width - 1) or tex.height & (tex.height - 1)
            or tex.pixel not in (0, 1, 2) or tex.format not in (1, 3, 0x0D)
            or tex.format == 3 and (tex.width != tex.height or tex.width < 2)
            or tex.index != profile['texture'] or not 0 <= tex.address <= 0xFFFFFFFF
            or not 0 <= tex.descriptor_offset <= 64 * 1024**2):
        raise ValueError('Invalid native face texture descriptor')
    if (tex.offset != 0 or tex.size != len(payload) or tex.capacity != len(payload)
            or tex.width > 1024 or tex.height > 1024 or len(payload) > 2 * 1024**2
            or tex.size != T.texture_size(tex.width, tex.height, tex.pixel, tex.format)
            or digest(payload) != profile['sha256'] or digest(payload) != bundle['source_texture_sha256']):
        raise ValueError('Native texture inspection lineage does not match its catalog')
    for name in ('source_geometry_sha256', 'source_executable_sha256'):
        if not isinstance(bundle.get(name), str) or not re.fullmatch('[a-f0-9]{64}', bundle[name]):
            raise ValueError('The native source binding is incomplete')
    primitives = bundle.get('primitives')
    if not isinstance(primitives, list) or not 1 <= len(primitives) <= 128:
        raise ValueError('Native face primitive count exceeds the editor limit')
    vertices = triangles = raster_cost = 0
    for primitive in primitives:
        pos = np.asarray(primitive['pos'], dtype=float)
        nrm = np.asarray(primitive['nrm'], dtype=float)
        uv = np.asarray(primitive['uv'], dtype=float)
        tri = np.asarray(primitive['tris'])
        if (pos.ndim != 2 or pos.shape[1] != 3 or nrm.shape != pos.shape or uv.shape != (len(pos), 2)
                or tri.ndim != 2 or tri.shape[1] != 3 or tri.dtype.kind not in 'iu'
                or not all(np.isfinite(a).all() for a in (pos, nrm, uv))
                or (tri.size and (tri.min() < 0 or tri.max() >= len(pos))) or np.max(np.abs(uv), initial=0) > 16):
            raise ValueError('Invalid bounded native face geometry')
        vertices += len(pos);triangles += len(tri)
        if vertices > 32768 or triangles > 32768:
            raise ValueError('Native face geometry exceeds the editor limit')
        if len(tri):
            spans = np.ptp(uv[tri], axis=1)
            if np.any(spans > 4):
                raise ValueError('Native face UV repeat span exceeds the editor limit')
            raster_cost += int(np.ceil(spans * [tex.width, tex.height] + 2).prod(axis=1).sum())
            if raster_cost > 20_000_000:
                raise ValueError('Native face raster work exceeds the editor limit')
    if len(canonical(bundle)) > 8 * 1024**2:
        raise ValueError('Native face inspection exceeds its size limit')
    return profile, tex, payload


def png(image):
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def read_surface(source, key):
    from .gdrom import GDRom
    disc = GDRom(source)
    try:
        return extract_surface(disc, key)
    finally:
        if getattr(disc, '_cdi', False):
            disc._cdi.close()
        else:
            for handle in disc._fh.values():
                handle.close()


def render(bundle, photo, edits=None):
    """The preview and build share projection and exact native encoding."""
    from . import doa2_textures as T
    from .native_face_projection import project
    profile, tex, payload = validate_surface(bundle)
    settings = settings_for(profile, edits)
    base = T.decode(tex, payload)
    candidate = project(base, photo, bundle['primitives'], **settings)
    if candidate.report['masked_pixels'] < 4:
        raise ValueError('The adjusted face has an empty native mask')
    encoded = T.encode(tex, candidate.image)
    if len(encoded) != len(payload):
        raise ValueError('The edited face changed its native allocation size')
    decoded = T.decode(tex, encoded)
    coverage = np.zeros((tex.height, tex.width, 4), dtype=np.uint8)
    coverage[..., :3] = 255
    coverage[..., 3] = np.asarray(candidate.coverage, dtype=np.uint8) * 255
    # The layer is intentionally undeformed, so reopening never applies edits twice.
    return {'settings': settings, 'native': encoded, 'original': png(base),
            'layer': png(candidate.layer), 'coverage': png(Image.fromarray(coverage)),
            'image': png(decoded), 'report': candidate.report}


class EditorIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    op: Literal['inspect', 'build'] = 'inspect'
    game_id: str = Field(pattern='^[a-f0-9]{16}$')
    profile_key: str = Field(default='', max_length=96)
    photo: str = Field(default='', pattern='^(?:[a-f0-9]{64})?$')
    recipes: list[str] = Field(default_factory=list, max_length=256)
    label: str = Field(default='Bla', min_length=1, max_length=80)


class EditorOut(BaseModel):
    result: dict


def _validate(out, arts):
    if out.result.get('op') != 'inspect':
        return []
    try:
        raw = arts.get('native-face-surface.json')
        if not raw or len(raw) > 8 * 1024**2 or digest(raw) != out.result.get('inspection'):
            raise ValueError('The native face inspection artifact is missing or changed')
        bundle = json.loads(raw)
        _, tex, payload = validate_surface(bundle)
        from . import doa2_textures as T
        original = png(T.decode(tex, payload))
        if arts.get('native-face-original.png') != original or out.result.get('original') != digest(original):
            raise ValueError('The original face preview differs from the inspected native texture')
        if (bundle['game_id'], bundle['profile_key']) != (out.result.get('game_id'), out.result.get('profile_key')):
            raise ValueError('The face output differs from its bound inspection')
        return []
    except (ValueError, KeyError, TypeError) as error:
        return [str(error)]


def _accept(store, out, actor):
    if out.result.get('op') == 'inspect':
        inspection = out.result['inspection']
        store.put('native_face_inspection', inspection, out.result | {'by': str(actor), 'created': time.time()})


@tool('native_face_editor', '1.0', EditorIn, EditorOut, permissions=[P.READ, P.EXECUTE, P.STAGE],
      timeout_s=1800, retries=0, validate=_validate, on_accept=_accept,
      side_effects=['extracts an owned face reference; builds only exact operator-approved face recipes in a separate image'])
def run(inp, ctx):
    from .characters import _api, _dc_gdi
    from . import doa2_faces as D, filemods
    if inp.game_id != GAME:
        raise ValueError('The native face deformation editor currently supports the owned DOA2 LE Japan disc')
    game = _api(ctx, 'GET', '/api/catalog/' + inp.game_id)
    source = _dc_gdi(ctx, game)
    if inp.op == 'inspect':
        bundle = read_surface(source, inp.profile_key)
        raw = canonical(bundle)
        _, tex, payload = validate_surface(bundle)
        from . import doa2_textures as T
        reference = png(T.decode(tex, payload))
        ctx.artifact('native-face-surface.json', raw, 'application/json', native_face_surface=True)
        ctx.artifact('native-face-original.png', reference, 'image/png', native_face_original=digest(raw))
        return {'result': {'op': 'inspect', 'inspection': digest(raw), 'game_id': GAME,
                           'profile_key': inp.profile_key, 'original': digest(reference),
                           'settings': settings_for(profiles()[inp.profile_key]), 'dimensions': [tex.width, tex.height],
                           'notice': 'Original native face material. Adjust the photo, preview native encoding, then accept the exact result before building.'}}
    if not inp.photo or not inp.recipes or len(set(inp.recipes)) != len(inp.recipes):
        raise ValueError('Choose a photo and exact saved reviewed face recipes')
    photo_bytes = _api(ctx, 'GET', '/api/artifacts/' + inp.photo)
    if not isinstance(photo_bytes, bytes) or digest(photo_bytes) != inp.photo or len(photo_bytes) > 8 * 1024**2:
        raise ValueError('The selected source photo is missing or changed')
    im = Image.open(io.BytesIO(photo_bytes))
    if im.width * im.height > 16 * 1024**2:
        raise ValueError('Photo dimensions exceed 16 megapixels')
    photo = im.convert('RGBA')
    selected = {}
    accepted = {}
    for recipe_id in inp.recipes:
        if len(recipe_id) != 64 or any(c not in '0123456789abcdef' for c in recipe_id):
            raise ValueError('A saved face recipe must be an immutable recipe ID')
        row = _api(ctx, 'GET', '/api/native-faces/recipes/' + recipe_id)
        if (not row.get('approved') or row.get('game_id') != inp.game_id or row.get('photo') != inp.photo
                or row.get('id') != recipe_id or row.get('format') != FORMAT or row.get('implementation') != IMPLEMENTATION):
            raise ValueError('The face recipe is not approved for this game and photo')
        key = row['profile_key']
        if key in selected:
            raise ValueError('Choose only one reviewed recipe per native face')
        bundle = read_surface(source, key)
        if digest(canonical(bundle)) != row['inspection']:
            raise ValueError('The native source changed since the face was reviewed')
        preview = render(bundle, photo, row['settings'])
        if digest(preview['native']) != row['native_sha256'] or preview['settings'] != row['settings']:
            raise ValueError('The native projection/codec changed since review; preview and accept again')
        selected[key] = profiles()[key] | preview['settings']
        accepted[key] = row
    name = 'doa2_edited_faces_' + inp.photo[:8] + '_' + uuid.uuid4().hex[:10]
    result = D.build(source, filemods.mod_dir(ctx.config, GAME, name), name, photo, selected,
                     game_id=GAME, photo_sha256=inp.photo, label=inp.label, progress=ctx.progress,
                     expected_payloads={key: row['native_sha256'] for key, row in accepted.items()})
    folder = filemods.mod_dir(ctx.config, GAME, name)
    report_path = folder / 'build-report.json'
    report = json.loads(report_path.read_text())
    for face in report['faces']:
        if face['result_texture_sha256'] != accepted[face['archive']]['native_sha256']:
            raise ValueError('The built native face differs from its exact reviewed preview')
    review = {'format': FORMAT, 'approved_recipes': inp.recipes,
              'profiles': {key: {'recipe': row['id'], 'settings': row['settings'],
                                 'candidate': row['candidate'], 'native_sha256': row['native_sha256']}
                           for key, row in accepted.items()}}
    report['face_editor'] = review
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    marker_path = folder / '.gbox-mod.json'
    marker = json.loads(marker_path.read_text())
    marker['face_editor'] = review
    marker['report'] = report
    marker_path.write_text(json.dumps(marker), encoding='utf-8')
    ctx.artifact('native-face-build.json', canonical(result | {'face_editor': review}), 'application/json')
    return {'result': result | {'op': 'build', 'face_editor': review}}


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    inspection: str = Field(pattern='^[a-f0-9]{64}$')
    photo: str = Field(pattern='^[a-f0-9]{64}$')
    settings: dict = Field(default_factory=dict)


class SaveIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate: str = Field(pattern='^[a-f0-9]{64}$')


def routes(app, store, auth, config=None):
    from fastapi import Depends, HTTPException

    def photo_image(sha):
        source = store.get('artifact', sha) or {}
        raw = store.read_artifact(sha)
        if not source.get('provenance', {}).get('photo_skin_source') or not raw or len(raw) > 8 * 1024**2 or digest(raw) != sha:
            raise ValueError('Choose a saved face photo or upload a source photo')
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > 16 * 1024**2:
            raise ValueError('Photo dimensions exceed 16 megapixels')
        return image.convert('RGBA')

    @app.get('/api/native-faces/catalog')
    def catalog(game_id: str, actor=Depends(auth)):
        if game_id != GAME:
            raise HTTPException(422, 'Native DOA2 face editing requires the owned DOA2 LE Japan title')
        from .doa2_chars import FIGHTERS
        names = {key: name for key, name, _ in FIGHTERS}
        return {'game_id': GAME, 'implementation': IMPLEMENTATION, 'faces': [{'key': key, 'name': names.get(Path(key).stem[:-2], Path(key).stem) + ' · ' + Path(key).stem,
                    'settings': settings_for(profile)} for key, profile in sorted(profiles().items())],
                'notice': 'Each costume/material is edited separately. Original bodies, rigs and animations stay intact.'}

    @app.post('/api/native-faces/preview')
    def preview(body: PreviewIn, actor=Depends(auth)):
        row = store.get('native_face_inspection', body.inspection)
        if not row:
            raise HTTPException(422, 'Inspect this owned native face first')
        try:
            raw = store.read_artifact(body.inspection)
            if not raw or len(raw) > 8 * 1024**2 or digest(raw) != body.inspection:
                raise ValueError('The bound native inspection is unavailable')
            bundle = json.loads(raw)
            result = render(bundle, photo_image(body.photo), body.settings)
            record = {'format': FORMAT, 'game_id': GAME, 'profile_key': bundle['profile_key'],
                      'inspection': body.inspection, 'photo': body.photo, 'settings': result['settings'],
                      'native_sha256': digest(result['native']), 'report': result['report'], 'implementation': IMPLEMENTATION}
            candidate = digest(canonical(record))
            for key, kind in (('native', 'application/octet-stream'), ('original', 'image/png'), ('layer', 'image/png'), ('coverage', 'image/png'), ('image', 'image/png')):
                store.put_artifact(result[key], 'native-face-' + key + ('.bin' if key == 'native' else '.png'), kind, {'native_face_candidate': candidate})
            record.update({'candidate': candidate, 'image': digest(result['image']),
                           'original': digest(result['original']), 'layer': digest(result['layer']), 'coverage': digest(result['coverage'])})
            store.put('native_face_candidate', candidate, record)
            return record | {'native_quantized': True, 'notice': 'Preview decoded from the exact native texture encoding. Native palette/compression can also quantize other pixels within this selected texture; inspect this result. Save accepts this exact mapping; only saved faces are included in the new build.'}
        except (ValueError, KeyError, TypeError, OSError, np.linalg.LinAlgError) as error:
            raise HTTPException(422, str(error)) from error

    @app.post('/api/native-faces/recipes')
    def save(body: SaveIn, actor=Depends(auth)):
        row = store.get('native_face_candidate', body.candidate)
        if not row:
            raise HTTPException(422, 'Preview the adjusted native face before accepting it')
        # Candidate IDs bind both settings and source. Approval is a distinct,
        # explicit editor action and never inferred from generating a preview.
        saved = row | {'id': body.candidate, 'approved': True, 'approved_by': str(actor), 'approved_at': time.time()}
        store.put('native_face_recipe', body.candidate, saved)
        store.put('native_face_recipe_latest', row['game_id'] + ':' + row['photo'] + ':' + row['profile_key'],
                  {'id': body.candidate, 'game_id': row['game_id'], 'photo': row['photo'], 'profile_key': row['profile_key']})
        return saved | {'notice': 'Exact reviewed face mapping saved on Spark. Existing ROMs remain unchanged.'}

    @app.get('/api/native-faces/recipes')
    def recipes_for(game_id: str, photo: str, actor=Depends(auth)):
        rows = [store.get('native_face_recipe', r['id']) for r in store.all('native_face_recipe_latest')
                if r.get('game_id') == game_id and r.get('photo') == photo]
        return {'game_id': game_id, 'photo': photo, 'recipes': [r for r in rows if r]}

    @app.get('/api/native-faces/recipes/{recipe_id}')
    def recipe(recipe_id: str, actor=Depends(auth)):
        row = store.get('native_face_recipe', recipe_id)
        if not row:
            raise HTTPException(404, 'The exact approved native face recipe was not found')
        return row
