"""PhotoCraft texture drafts and explicitly exported, separate collection donors.

The browser edits bounded PNGs and opaque project files. It never supplies a
filesystem path, native memory address, shell command or replacement model.
Originals and every saved revision remain content-addressed artifacts on Spark.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
from typing import Literal
from urllib.parse import unquote, urlsplit
import uuid

from fastapi import Depends, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

PNG_LIMIT = 16 * 1024**2
PROJECT_LIMIT = 32 * 1024**2
MODEL_LIMIT = 64 * 1024**2
PIXEL_LIMIT = 16 * 1024**2
EDGE_LIMIT = 4096
REVISION_LIMIT = 256
SESSION_LIMIT = 256 * 1024**2
RUNTIME_VERSION = 'v0.9.0'
_RUNTIME_CHECKS = {}
_RUNTIME_LOCK = threading.Lock()
HEX = re.compile(r'^[a-f0-9]{64}$')
SLUG = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def image_png(raw, expected=None):
    """Decode before saving; strip metadata and reject animation/resize surprises."""
    if not isinstance(raw, bytes) or not raw or len(raw) > PNG_LIMIT:
        raise ValueError('The image exceeds the 16 MiB editing budget')
    with Image.open(io.BytesIO(raw)) as image:
        if (image.format not in ('PNG', 'JPEG', 'WEBP') or getattr(image, 'n_frames', 1) != 1
                or not 0 < image.width <= EDGE_LIMIT or not 0 < image.height <= EDGE_LIMIT
                or image.width * image.height > PIXEL_LIMIT):
            raise ValueError('Choose one PNG, JPEG or WebP image up to 4096 pixels per edge and 16 megapixels')
        if expected and image.size != tuple(expected):
            raise ValueError('The edited texture must retain its exact original dimensions')
        image.load()
        result = io.BytesIO()
        image.convert('RGBA').save(result, 'PNG')
        data = result.getvalue()
        if len(data) > PNG_LIMIT:
            raise ValueError('The normalized PNG exceeds the 16 MiB editing budget')
        return data, [image.width, image.height]


def data_bytes(value, limit, image=False):
    if not isinstance(value, str) or len(value) > (limit + 2) // 3 * 4 + 200:
        raise ValueError('The editor export exceeds its size budget')
    try:
        header, encoded = value.split(',', 1)
        if not re.fullmatch(r'data:[A-Za-z0-9.+/-]+;base64', header):
            raise ValueError('Export a base64 data URL')
        if image and header != 'data:image/png;base64':
            raise ValueError('Export the flattened texture as PNG')
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('The editor export is not a valid base64 data URL') from error
    if not raw or len(raw) > limit:
        raise ValueError('The editor export exceeds its size budget')
    if image and not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Export the flattened texture as PNG')
    return raw


def read_artifact(store, sha, limit):
    if not isinstance(sha, str) or not HEX.fullmatch(sha):
        raise ValueError('Select an existing artifact')
    row = store.get('artifact', sha)
    path = store.artifact_path(sha)
    if not row or not path.is_file():
        raise ValueError('The selected artifact is unavailable')
    if path.stat().st_size > limit:
        raise ValueError('The selected artifact exceeds the editing budget')
    raw = store.read_artifact(sha)
    if not raw or digest(raw) != sha:
        raise ValueError('The selected artifact changed')
    return raw


def artifact(store, raw, name, kind, provenance):
    sha = digest(raw)
    # Existing photo/native artifact provenance must never be overwritten by a
    # texture draft containing identical bytes.
    if not store.get('artifact', sha):
        store.put_artifact(raw, name, kind, provenance)
    return sha


def _pack_character(config, slug):
    from . import attachments as A, characters as C
    if not SLUG.fullmatch(slug):
        raise ValueError('Choose a collection model')
    root = C.library_root(config).resolve()
    directory = (root / slug).resolve()
    if directory.parent != root:
        raise ValueError('The model leaves its collection')
    try:
        meta = C.get(root, slug)
    except KeyError as error:
        raise ValueError('The collection model is unavailable') from error
    path = (directory / meta.get('model', '')).resolve()
    if not path.is_relative_to(directory) or not path.is_file() or path.suffix.lower() not in ('.glb', '.gltf'):
        raise ValueError('Choose an existing GLB or glTF collection model')
    budget = path.stat().st_size
    if budget > MODEL_LIMIT:
        raise ValueError('The collection model exceeds 64 MiB')
    gl, _ = A.read_gltf(path)
    for item in [*gl.get('buffers', []), *gl.get('images', [])]:
        uri = item.get('uri', '')
        if not uri:
            continue
        if uri.startswith('data:'):
            if len(uri) > MODEL_LIMIT * 4 // 3 + 200:
                raise ValueError('The model image/buffer exceeds 64 MiB')
            continue
        parsed = urlsplit(uri)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or '\\' in uri:
            raise ValueError('Model resources must stay within the collection folder')
        for relative in (uri, unquote(parsed.path)):
            companion = (path.parent / relative).resolve()
            if not companion.is_relative_to(directory) or not companion.is_file():
                raise ValueError('A model resource leaves its collection folder or is missing')
        budget += companion.stat().st_size
        if budget > MODEL_LIMIT:
            raise ValueError('The packed model exceeds 64 MiB')
    gl, blob = A.pack(path)
    raw = A.glb_bytes(copy.deepcopy(gl), blob)
    if len(raw) > MODEL_LIMIT:
        raise ValueError('The packed model exceeds 64 MiB')
    return C, root, meta, gl, blob, raw


def color_maps(gl):
    rows = {}
    for index, material in enumerate(gl.get('materials', [])):
        ref = material.get('pbrMetallicRoughness', {}).get('baseColorTexture')
        if ref is None:
            continue
        texture = gl['textures'][ref['index']]
        if any(name in texture.get('extensions', {})
               for name in ('KHR_texture_basisu', 'EXT_texture_webp', 'EXT_texture_avif')):
            raise ValueError('This material uses an alternate compressed image binding. Convert it to a standard embedded base-color image before texture editing')
        source = texture.get('source')
        if source is None:
            continue
        row = rows.setdefault(source, {'index': source, 'materials': [], 'material_indices': []})
        row['materials'].append(material.get('name') or f'Material {index + 1}')
        row['material_indices'].append(index)
    return rows


def map_bytes(gl, blob, index):
    image = gl['images'][index]
    view = gl['bufferViews'][image['bufferView']]
    start, size = view.get('byteOffset', 0), view['byteLength']
    if view.get('buffer', 0) != 0 or start < 0 or size < 1 or start + size > len(blob) or size > PNG_LIMIT:
        raise ValueError('The selected map exceeds its image budget')
    return blob[start:start + size]


class OpenIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    character: str = Field(default='', max_length=128)
    image: int = Field(default=0, ge=0, le=4095, validation_alias=AliasChoices('image', 'map_index'))
    artifact: str = Field(default='', pattern='^(?:[a-f0-9]{64})?$')
    png_data_url: str = Field(default='', max_length=PNG_LIMIT * 4 // 3 + 200)
    label: str = Field(default='Texture edit', min_length=1, max_length=120)

    @model_validator(mode='after')
    def one_source(self):
        if sum(bool(v) for v in (self.character, self.artifact, self.png_data_url)) != 1:
            raise ValueError('Choose exactly one collection texture, image artifact or PNG')
        return self


class RevisionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0, le=REVISION_LIMIT)
    png_data_url: str = Field(max_length=PNG_LIMIT * 4 // 3 + 200)
    project_data_url: str | None = Field(default=None, max_length=PROJECT_LIMIT * 4 // 3 + 200)
    project_format: Literal['pcraft', 'psd'] | None = None

    @model_validator(mode='after')
    def project_pair(self):
        if bool(self.project_data_url) != bool(self.project_format):
            raise ValueError('Provide both the project export and its pcraft/psd format')
        return self


class DonorIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1, le=REVISION_LIMIT)
    name: str = Field(default='', max_length=120)


class SessionRevision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern='^[a-f0-9]{32}$')
    revision: int = Field(ge=1, le=REVISION_LIMIT)


class DonorsIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sessions: list[SessionRevision] = Field(min_length=1, max_length=128)
    name: str = Field(default='', max_length=120)


def dto(row):
    result = {k: v for k, v in row.items() if k not in ('owner', 'revisions', 'artifact_sizes')}
    result.update(original_url='/api/artifacts/' + row['original'],
                  current_url='/api/artifacts/' + row['current'],
                  revisions=[{**r, 'url': '/api/artifacts/' + r['image'],
                              **({'project_url': '/api/artifacts/' + r['project']} if r.get('project') else {})}
                             for r in row['revisions']])
    if row.get('project'):
        result['project_url'] = '/api/artifacts/' + row['project']
    if row.get('model'):
        result['model_url'] = '/api/artifacts/' + row['model']
    return result


def storage(store, row, additions=()):
    """Count unique saved bytes; never prune an operator's earlier revisions."""
    sizes = dict(row.get('artifact_sizes') or {})
    if not sizes:
        known = {row['original'], row.get('model')}
        if row.get('source_artifact'):
            known.add(row['source_artifact'])
        for revision in row['revisions']:
            known.update((revision.get('image'), revision.get('project')))
        for sha in known - {None}:
            info = store.get('artifact', sha)
            if not info or type(info.get('size')) is not int or info['size'] < 0:
                raise ValueError('A saved texture draft artifact is unavailable')
            sizes[sha] = info['size']
    for raw in additions:
        if raw is not None:
            sizes[digest(raw)] = len(raw)
    total = sum(sizes.values())
    if total > SESSION_LIMIT:
        raise HTTPException(409, 'This draft reached its 256 MiB saved-data budget. Download its project or export the asset, then open another draft; earlier revisions remain preserved.')
    return {'artifact_sizes': sizes, 'storage_bytes': total, 'storage_limit': SESSION_LIMIT}


def runtime_manifest():
    manifest = json.loads(Path(__file__).with_name('photocraft_runtime.json').read_text(encoding='utf-8'))
    if (manifest.get('tag') != RUNTIME_VERSION or manifest.get('runtime_dir') != 'photocraft/runtime/' + RUNTIME_VERSION
            or not isinstance(manifest.get('files'), dict)):
        raise ValueError('The pinned PhotoCraft runtime manifest is invalid')
    for name, item in manifest['files'].items():
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..')
                or not HEX.fullmatch(item.get('sha256', '')) or type(item.get('size')) is not int
                or not 0 < item['size'] <= 128 * 1024**2):
            raise ValueError('The pinned PhotoCraft runtime file manifest is invalid')
    return manifest


def runtime_file(config, manifest, name):
    item = manifest['files'].get(name)
    if item is None:
        raise ValueError('The PhotoCraft runtime file is not allowlisted')
    directory = (Path(config.data_dir) / manifest['runtime_dir']).resolve()
    path = (directory / name).resolve()
    if path.parent != directory or not path.is_file():
        raise ValueError('The pinned PhotoCraft runtime is not installed')
    stat = path.stat()
    if stat.st_size != item['size']:
        raise ValueError('The installed PhotoCraft runtime differs from its pinned release')
    key = (str(path), stat.st_size, stat.st_mtime_ns, item['sha256'])
    with _RUNTIME_LOCK:
        verified = key in _RUNTIME_CHECKS
    if not verified:
        hasher = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024**2), b''):
                hasher.update(block)
        if hasher.hexdigest() != item['sha256']:
            raise ValueError('The installed PhotoCraft runtime differs from its pinned release')
        with _RUNTIME_LOCK:
            if len(_RUNTIME_CHECKS) > 128:
                _RUNTIME_CHECKS.clear()
            _RUNTIME_CHECKS[key] = True
    return path, item


def routes(app, store, auth, config):
    from fastapi.responses import FileResponse

    def session(sid, actor):
        if not re.fullmatch('[a-f0-9]{32}', sid):
            raise HTTPException(404, 'Texture editing session not found')
        row = store.get('photocraft_session', sid)
        if not row or row.get('owner') != str(actor):
            raise HTTPException(404, 'Texture editing session not found')
        return row

    def checked(fn):
        try:
            return fn()
        except (ValueError, KeyError, IndexError, TypeError, OSError, UnidentifiedImageError,
                Image.DecompressionBombError) as error:
            raise HTTPException(422, str(error)) from error

    @app.get('/api/photocraft/status')
    def status(actor=Depends(auth)):
        try:
            manifest = runtime_manifest()
            files = []
            for name in manifest['files']:
                _, item = runtime_file(config, manifest, name)
                files.append({'name': name, 'url': '/photocraft/runtime/' + name,
                              'size': item['size'], 'mime': item.get('mime', 'application/octet-stream')})
            js = next((f['url'] for f in files if f['name'].endswith('.js')), None)
            wasm = next((f['url'] for f in files if f['name'].endswith('.wasm')), None)
            ready = bool(js and wasm)
            return {'installed': ready, 'ready': ready, 'version': manifest['version'], 'tag': manifest['tag'],
                    'js_url': js, 'wasm_url': wasm, 'runtime_url': '/photocraft/runtime/', 'files': files}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {'installed': False, 'ready': False, 'version': RUNTIME_VERSION.removeprefix('v'),
                    'tag': RUNTIME_VERSION, 'error': str(error), 'files': []}

    @app.get('/photocraft/runtime/{filename}')
    def runtime_asset(filename: str):
        # Public static vendor code carries no application token or user files.
        # Only exact, pinned release files are exposed, including license text.
        try:
            manifest = runtime_manifest()
            path, item = runtime_file(config, manifest, filename)
        except (ValueError, OSError, KeyError, TypeError) as error:
            raise HTTPException(404, 'Pinned PhotoCraft runtime file unavailable') from error
        return FileResponse(path, media_type=item.get('mime', 'application/octet-stream'),
                            headers={'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin',
                                     'Cache-Control': 'public, max-age=3600'})

    @app.get('/api/characters/{slug}/photocraft/maps')
    def maps(slug: str, actor=Depends(auth)):
        def result():
            _, _, meta, gl, blob, raw = _pack_character(config, slug)
            rows = []
            for index, info in sorted(color_maps(gl).items()):
                data, size = image_png(map_bytes(gl, blob, index))
                sha = artifact(store, data, f'photocraft-map-{index}.png', 'image/png',
                               {'photocraft_original': True, 'character': slug, 'image': index})
                label = gl['images'][index].get('name') or ' / '.join(info['materials'])
                rows.append(info | {'label': label, 'name': label,
                                    'width': size[0], 'height': size[1], 'size': size,
                                    'artifact': sha, 'url': '/api/artifacts/' + sha})
            return {'character': {'slug': slug, 'name': meta['name'], 'model': meta['model']},
                    'source_sha256': digest(raw), 'maps': rows}
        return checked(result)

    @app.post('/api/photocraft/sessions')
    def open_session(body: OpenIn, actor=Depends(auth)):
        def result():
            sid = uuid.uuid4().hex
            bound = {}
            if body.character:
                _, _, meta, gl, blob, raw = _pack_character(config, body.character)
                maps = color_maps(gl)
                if body.image not in maps:
                    raise ValueError('Select an existing base-color image; normal and data maps are not paint targets')
                data, size = image_png(map_bytes(gl, blob, body.image))
                model = artifact(store, raw, 'photocraft-original.glb', 'model/gltf-binary',
                                 {'photocraft_session': sid, 'character': body.character})
                bound = {'character': body.character, 'image': body.image, 'materials': maps[body.image]['materials'],
                         'material_indices': maps[body.image]['material_indices'], 'model': model,
                         'source_sha256': digest(raw), 'character_name': meta['name']}
            else:
                raw = (read_artifact(store, body.artifact, PNG_LIMIT) if body.artifact
                       else data_bytes(body.png_data_url, PNG_LIMIT, image=True))
                data, size = image_png(raw)
                bound = {'source_artifact': body.artifact} if body.artifact else {}
            original = artifact(store, data, 'photocraft-original.png', 'image/png', {'photocraft_session': sid})
            now = time.time()
            row = {'id': sid, 'owner': str(actor), 'label': body.label.strip() or 'Texture edit', 'created': now,
                   'updated': now, 'width': size[0], 'height': size[1], 'original': original, 'current': original,
                   'revision': 0, 'project': None, 'revisions': [{'revision': 0, 'image': original, 'at': now}], **bound}
            row.update(storage(store, row))
            store.put('photocraft_session', sid, row)
            store.audit(actor, 'photocraft.open', sid, {'character': body.character, 'image': body.image})
            return dto(row)
        return checked(result)

    @app.get('/api/photocraft/sessions/{sid}')
    def get_session(sid: str, actor=Depends(auth)):
        return dto(session(sid, actor))

    @app.post('/api/photocraft/sessions/{sid}/revisions')
    def save_revision(sid: str, body: RevisionIn, actor=Depends(auth)):
        row = session(sid, actor)
        if row['revision'] != body.expected_revision:
            raise HTTPException(409, 'This texture draft changed; reload it before saving')
        if row['revision'] >= REVISION_LIMIT:
            raise HTTPException(409, 'This draft reached 256 saved revisions; export it and open another draft')
        def prepare():
            data, _ = image_png(data_bytes(body.png_data_url, PNG_LIMIT, image=True), [row['width'], row['height']])
            project = data_bytes(body.project_data_url, PROJECT_LIMIT) if body.project_data_url else None
            return data, project
        data, project = checked(prepare)
        with store.lock:
            row = session(sid, actor)
            if row['revision'] != body.expected_revision:
                raise HTTPException(409, 'This texture draft changed; reload it before saving')
            allocation = checked(lambda: storage(store, row, (data, project)))
            revision, now = row['revision'] + 1, time.time()
            image = artifact(store, data, 'photocraft-texture.png', 'image/png', {'photocraft_session': sid, 'revision': revision})
            history = {'revision': revision, 'image': image, 'at': now}
            if project:
                sha = artifact(store, project, 'photocraft-project.' + body.project_format, 'application/octet-stream',
                               {'photocraft_session': sid, 'revision': revision, 'project_format': body.project_format})
                history.update(project=sha, project_format=body.project_format)
            row.update(current=image, revision=revision, project=history.get('project'),
                       project_format=history.get('project_format'), updated=now, **allocation)
            row['revisions'].append(history)
            store.put('photocraft_session', sid, row)
            store.audit(actor, 'photocraft.save', sid, {'revision': revision, 'image': image})
        return dto(row)

    def export_donor(selections, name, actor):
        bound = []
        for selection in selections:
            row = session(selection.id, actor)
            if not row.get('character'):
                raise HTTPException(422, 'Open collection textures to export an edited model donor')
            saved = next((r for r in row['revisions'] if r['revision'] == selection.revision), None)
            if not saved:
                raise HTTPException(422, 'Save and select the exact reviewed texture revisions first')
            bound.append((row, saved))
        row, saved = bound[0]
        if any(r['character'] != row['character'] or r['source_sha256'] != row['source_sha256'] for r, _ in bound):
            raise HTTPException(422, 'All edited textures must belong to the same unchanged source model')
        if len({r['image'] for r, _ in bound}) != len(bound):
            raise HTTPException(422, 'Select only one reviewed revision per source image')
        bound.sort(key=lambda pair: pair[0]['image'])
        row, saved = bound[0]
        edits = [{'session': r['id'], 'revision': s['revision'], 'image': r['image'], 'texture': s['image']} for r, s in bound]
        key = (row['id'] + ':' + str(saved['revision']) if len(bound) == 1
               else 'batch:' + digest(json.dumps(edits, sort_keys=True).encode()))
        old_export = store.get('photocraft_donor', key)
        if old_export:
            return old_export
        def prepare():
            from . import attachments as A
            C, root, meta, gl, blob, raw = _pack_character(config, row['character'])
            if digest(raw) != row['source_sha256']:
                raise HTTPException(409, 'The original model changed; open a new texture draft before exporting')
            refs = color_maps(gl)
            out = bytearray(blob)
            replacements = {}
            for texture_row, texture_saved in bound:
                index = texture_row['image']
                if index not in refs:
                    raise ValueError('The original base-color image binding changed')
                data = read_artifact(store, texture_saved['image'], PNG_LIMIT)
                image_png(data, [texture_row['width'], texture_row['height']])
                if len(out) + len(data) + 3 > MODEL_LIMIT:
                    raise ValueError('The edited model exceeds 64 MiB')
                out.extend(bytes(-len(out) % 4))
                offset = len(out)
                out.extend(data)
                gl.setdefault('bufferViews', []).append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(data)})
                replacements[index] = len(gl['images'])
                gl['images'].append({'bufferView': len(gl['bufferViews']) - 1, 'mimeType': 'image/png',
                                     'name': gl['images'][index].get('name', '')})
            remapped = {}
            for material in gl.get('materials', []):
                ref = material.get('pbrMetallicRoughness', {}).get('baseColorTexture')
                if ref is None or gl['textures'][ref['index']].get('source') not in replacements:
                    continue
                previous = ref['index']
                if previous not in remapped:
                    remapped[previous] = len(gl['textures'])
                    source = gl['textures'][previous]['source']
                    gl['textures'].append({**gl['textures'][previous], 'source': replacements[source]})
                ref['index'] = remapped[previous]
            result = A.glb_bytes(gl, bytes(out))
            if len(result) > MODEL_LIMIT:
                raise ValueError('The edited model exceeds 64 MiB')
            return C, root, meta, result
        C, root, meta, raw = checked(prepare)
        sha = artifact(store, raw, 'photocraft-edited.glb', 'model/gltf-binary',
                       {'photocraft_edits': edits, 'character': row['character']})
        variant = row['character'][:55] + '_paint_' + sha[:12]
        directory = root / variant
        with store.lock:
            existing = store.get('photocraft_donor', key)
            if existing:
                return existing
            if directory.exists():
                try:
                    prior = C.get(root, variant)
                except KeyError as error:
                    raise HTTPException(409, 'The edited donor folder already exists without matching metadata') from error
                if ((prior.get('photocraft_edit') or {}).get('model') != sha
                        or digest((directory / prior['model']).read_bytes()) != sha):
                    raise HTTPException(409, 'The existing donor does not match this texture revision')
                name = prior['name']
            else:
                directory.mkdir(parents=True, exist_ok=False)
                (directory / 'model.glb').write_bytes(raw)
                new = copy.deepcopy(meta)
                for field in ('targets', 'target_files', 'rigs', 'retarget_profiles', 'readiness', 'native_player',
                            'files', 'preview', 'preview_url', 'verification', 'verified', 'aliases',
                            'texture_approval', 'anims_file', 'animations'):
                    new.pop(field, None)
                name = name.strip() or meta['name'] + ' - painted texture'
                new.update(slug=variant, name=name, model='model.glb', variant_of=meta['slug'], files=['model.glb'],
                           added=time.time(), photocraft_edit={'session': row['id'], 'revision': saved['revision'],
                           'image': row['image'], 'texture': saved['image'], 'source_model': row['source_sha256'],
                           'model': sha, 'edits': edits, 'at': time.time(), 'by': str(actor)},
                           verification={'status': 'unverified', 'reason': 'Edited texture donor; requires a native game build and gameplay verification'})
                # A 3D render is expensive and optional; a real edited texture is
                # an honest preview rather than an unchanged original model shot.
                preview = read_artifact(store, saved['image'], PNG_LIMIT)
                (directory / 'texture-preview.png').write_bytes(preview)
                new.update(preview='texture-preview.png', files=['model.glb', 'texture-preview.png'])
                C.put_meta(root, new)
            result = {'session': row['id'], 'revision': saved['revision'], 'character': row['character'], 'variant': variant,
                      'name': name, 'model': sha, 'model_url': '/api/artifacts/' + sha,
                      'texture': saved['image'], 'image': row['image'], 'edits': edits,
                      'notice': 'Separate edited model donor saved. Select it in mod mapping to build a supported target game; existing models and ROMs are unchanged.'}
            store.put('photocraft_donor', key, result)
            store.audit(actor, 'photocraft.donor', key, {'variant': variant, 'edits': edits})
        return result

    @app.post('/api/photocraft/sessions/{sid}/donor')
    def donor(sid: str, body: DonorIn, actor=Depends(auth)):
        session(sid, actor)
        return export_donor([SessionRevision(id=sid, revision=body.revision)], body.name, actor)

    @app.post('/api/photocraft/donors')
    def donors(body: DonorsIn, actor=Depends(auth)):
        return export_donor(body.sessions, body.name, actor)
