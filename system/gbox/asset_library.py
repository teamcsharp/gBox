"""Unified, paginated index of extracted files and the operator's asset clipboard."""
import hashlib
import html
import json
import mimetypes
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

MODEL_EXT = {'.glb', '.gltf', '.obj', '.fbx', '.abc', '.dae', '.ply', '.stl', '.usd', '.usdz'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.dds', '.tga', '.bmp', '.ktx', '.ktx2'}
ASSET_EXT = MODEL_EXT | IMAGE_EXT | {'.wav', '.ogg', '.mp3', '.flac', '.anim', '.bin'}
NESTED_KINDS = {'texture', 'audio', 'data'}
ASSET_TOOLS = {'characters', 'scene_capture', 'export_asset', 'asset_convert', 'rom_export',
               'extract_pso_model', 'extract_pso_area', 'oot_models', 'pick'}


def file_kind(path):
    ext = Path(path).suffix.lower()
    return 'model' if ext in MODEL_EXT else 'texture' if ext in IMAGE_EXT else 'audio' if ext in {'.wav', '.ogg', '.mp3', '.flac'} else 'data'


class _IndexMetadata:
    """Read committed metadata without waiting behind emulator/job writes."""
    def __init__(self, data_dir):
        self.path = (Path(data_dir) / 'gbox.sqlite3').resolve()

    def __enter__(self):
        self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.db.execute('BEGIN')
        return self

    def __exit__(self, *exc):
        self.db.close()

    def all(self, kind):
        return [json.loads(row[0]) for row in self.db.execute('SELECT body FROM docs WHERE kind=? ORDER BY rowid', (kind,))]

    def get(self, kind, rid):
        row = self.db.execute('SELECT body FROM docs WHERE kind=? AND id=?', (kind, rid)).fetchone()
        return json.loads(row[0]) if row else None

    def catalog_get(self, gid):
        row = self.db.execute('SELECT body FROM catalog WHERE game_id=?', (gid,)).fetchone()
        return json.loads(row[0]) if row else None


class AssetLibrary:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.lock = threading.RLock()
        self.preview_lock = threading.Lock()
        self.entries, self.expiry = {}, 0

    def invalidate(self):
        with self.lock:
            self.expiry = 0

    def index(self):
        with self.lock:
            if time.monotonic() < self.expiry:
                return self.entries
            with _IndexMetadata(self.store.dir) as metadata:
                entries = self._build_index(metadata)
            self.entries, self.expiry = entries, time.monotonic() + 10
            return entries

    def _build_index(self, metadata):
        from . import characters
        entries = {}
        model_titles = {}
        copied, copied_names = {}, {}
        copied_ids = {k['id']: k.get('ts', 0) for k in metadata.all('asset_copy')}
        history = metadata.db.execute("SELECT ts,subject,data FROM audit WHERE action='clipboard.copy'").fetchall()
        copy_jobs = metadata.db.execute("SELECT body FROM docs WHERE kind='job' AND json_extract(body,'$.tool')='blender_copy' AND json_extract(body,'$.state')='succeeded'").fetchall()
        for ts, sha, data in history:
            copied[sha] = max(ts, copied.get(sha, 0))
            name = json.loads(data).get('name', '')
            copied_names[name] = max(ts, copied_names.get(name, 0))
        for (body,) in copy_jobs:
            j = json.loads(body); inp = j.get('input', {}); ts = j.get('finished') or 0
            for key in ('artifact', 'character', 'environment'):
                value = inp.get(key)
                if value:
                    target = copied if key == 'artifact' else copied_names
                    target[value] = max(ts, target.get(value, 0))

        def add(identifier, path, name, kind, game='', added=0, preview=None, aliases=(), **extra):
            path = Path(path)
            if not path.is_file():
                return
            # IDs contain no slash; API resolution never accepts arbitrary filesystem paths.
            rid = hashlib.sha256(identifier.encode()).hexdigest()[:32]
            entries[rid] = dict(id=rid, name=name, kind=kind, game=game or 'Unknown title',
                added=added or path.stat().st_mtime, copied=max([copied_ids.get(rid, 0), copied.get(extra.get('sha256'), 0), *[copied_names.get(a, 0) for a in aliases]]),
                size=path.stat().st_size, format=extra.pop('format', path.suffix.lstrip('.').upper() or 'FILE'),
                preview_url=f'/api/assets/{rid}/preview', file_url=f'/api/assets/{rid}/file',
                _path=path, _preview=preview, **extra)

        for prefix, root in [('character', characters.library_root(self.config)), ('environment', characters.env_root(self.config))]:
            for meta_path in root.glob('*/meta.json'):
                try:
                    m = json.loads(meta_path.read_text()); folder = meta_path.parent.resolve()
                    source = m.get('source') or {}; model = m.get('model', '')
                    game = source.get('game_title') or source.get('title') or source.get('game_id') or ''
                    aliases = (m.get('slug', folder.name), m.get('name', ''), model)
                    if game:
                        for alias in (*aliases[:2], *m.get('aliases', [])):
                            model_titles[str(alias).casefold()] = game
                    for path in folder.rglob('*'):
                        if not path.is_file() or path.suffix.lower() not in ASSET_EXT or path.name == m.get('preview', 'preview.png'):
                            continue
                        if not path.resolve().is_relative_to(folder):
                            continue
                        rel = path.relative_to(folder).as_posix(); primary = rel == model
                        add(f'{prefix}:{folder.name}:{rel}', path, m.get('name', folder.name) if primary else f"{m.get('name', folder.name)} · {rel}",
                            m.get('kind', prefix) if primary else file_kind(path), game, m.get('added', 0) if primary else path.stat().st_mtime,
                            folder / m.get('preview', 'preview.png') if primary else None, aliases=aliases if primary else (),
                            origin='collection', slug=folder.name, collection=prefix, primary=primary)
                except (OSError, ValueError, TypeError):
                    continue
        def source_title(source):
            title = source.get('game_title') or source.get('title') or source.get('game')
            gid = source.get('game_id')
            if gid:
                title = (metadata.catalog_get(gid) or {}).get('title') or title
            if not title:
                # Historical PSO packages record the configured disc alias instead of a catalog ID.
                disc = Path(source.get('game_disc') or '').name.lower()
                family = {'psov2.gdi': 'Phantasy Star Online Ver. 2', 'psogc.iso': 'Phantasy Star Online Episode I & II'}.get(disc)
                if family:
                    matches = {a['game'] for a in entries.values() if a['game'].startswith(family)}
                    title = next(iter(matches)) if len(matches) == 1 else family
            return title if isinstance(title, str) else ''

        for manifest in (self.config.data_dir / 'uap').glob('*/manifest.json'):
            try:
                m = json.loads(manifest.read_text()); folder = manifest.parent.resolve(); source = m.get('source', {})
                game = source_title(source)
                # The package itself is one model, plus bounded supported companion files.
                add(f'package:{folder.name}', manifest, m.get('name', folder.name), 'model', game,
                    manifest.stat().st_mtime, folder / 'preview.png', aliases=(folder.name,), origin='package', package=folder.name, format='UAP')
                for path in folder.rglob('*'):
                    if path.suffix.lower() in (ASSET_EXT - MODEL_EXT) and path.name != 'preview.png' and path.resolve().is_relative_to(folder):
                        add(f'package-file:{folder.name}:{path.relative_to(folder)}', path, path.name, file_kind(path), game, origin='package-file', package=folder.name)
            except (OSError, ValueError, TypeError):
                continue
        artifacts = metadata.all('artifact')
        previews = {a.get('provenance', {}).get('job'): a['sha256'] for a in artifacts
                    if a.get('name', '').lower().startswith(('preview', 'frame')) and a.get('media_type', '').startswith('image/') and a.get('provenance', {}).get('job')}
        jobs = {}
        for a in artifacts:
            prov = a.get('provenance', {}); name = a.get('name', 'Asset'); ext = Path(name).suffix.lower(); sha = a['sha256']
            if prov.get('asset_id') in entries:
                entries[prov['asset_id']]['copied'] = max(entries[prov['asset_id']]['copied'], copied.get(sha, 0))
                continue
            is_model = ext in MODEL_EXT or a.get('media_type', '').startswith('model/')
            if not (is_model or sha in copied or (ext in ASSET_EXT and prov.get('tool') in ASSET_TOOLS and not name.lower().startswith(('preview', 'frame')))):
                continue
            jid = prov.get('job')
            if jid and jid not in jobs:
                jobs[jid] = metadata.get('job', jid) or {}
            j = jobs.get(jid, {}); inp = j.get('input') or {}; game = inp.get('game') or {}
            if not isinstance(game, dict): game = {}
            gid = prov.get('game_id') or game.get('game_id') or inp.get('game_id')
            catalog = metadata.catalog_get(gid) if gid else None
            nested = prov.get('source') if isinstance(prov.get('source'), dict) else {}
            sess = metadata.get('session', prov.get('session') or inp.get('session_id') or '') or {}
            title = prov.get('title') or prov.get('game_title') or (catalog or {}).get('title') or game.get('title') or prov.get('game') or source_title(nested) or sess.get('title')
            if not title:
                title = model_titles.get(str(prov.get('base') or prov.get('character') or '').casefold(), '')
            if not isinstance(title, str): title = str(title)
            path = self.store.artifact_path(sha)
            media = a.get('media_type', '')
            fmt = ext.lstrip('.').upper() or ('GLB' if media == 'model/gltf-binary' else 'GLTF' if media == 'model/gltf+json' else media.split('/')[-1].upper() if media.startswith('image/') else 'FILE')
            if is_model and fmt == 'GLTF' and path.is_file():
                with path.open('rb') as stream:
                    if stream.read(4) == b'glTF': fmt = 'GLB'
            add(f'artifact:{sha}', path, name, 'model' if is_model else 'texture' if media.startswith('image/') else file_kind(name), title,
                j.get('finished') or 0, aliases=(name,), origin='artifact', sha256=sha,
                media_type=a.get('media_type'), format=fmt,
                thumb_sha=previews.get(jid) if is_model else None)
        canonical = {a['game'].strip().casefold(): a['game'].strip() for a in entries.values() if a['origin'] == 'collection'}
        for item in entries.values():
            item['game'] = canonical.get(item['game'].strip().casefold(), item['game'].strip())
        # Textures, raw data and audio shipped with a model belong to that model.
        # The sidebar lists them in a collapsed tree under the owner instead of as top-level cards.
        owners = {}
        for item in entries.values():
            if item['origin'] == 'collection' and item.get('primary'):
                owners[('collection', item['collection'], item['slug'])] = item['id']
            elif item['origin'] == 'package':
                owners[('package', item['package'])] = item['id']
        for item in entries.values():
            if item['kind'] not in NESTED_KINDS:
                continue
            key = (('collection', item['collection'], item['slug']) if item['origin'] == 'collection'
                   else ('package', item.get('package')) if item['origin'] == 'package-file' else None)
            if key in owners:
                item['owner'] = owners[key]
        return entries

    def get(self, rid):
        item = self.index().get(rid)
        if not item:
            raise HTTPException(404, 'Asset is no longer available; refresh the asset list.')
        return item

    def page(self, q='', kind='', game='', sort='newest', offset=0, limit=60, nest=True, owner=''):
        if sort not in {'newest', 'oldest', 'copied', 'name', 'game', 'kind', 'size'}:
            raise HTTPException(422, 'Unknown asset sort')
        all_items = list(self.index().values())
        words = q.casefold().split()
        pool = [a for a in all_items if (not game or a['game'] == game) and (not owner or a.get('owner') == owner)
                and all(w in f"{a['name']} {a['game']} {a['kind']} {a['format']}".casefold() for w in words)]
        items = [a for a in pool if not kind or a['kind'] == kind]
        counts, file_counts, hidden, nested_count = {}, {}, set(), 0
        if nest and not owner:
            # Companions are nested when their owner is listed; explicit file filters
            # and searches still expose standalone results. Owner counts use the
            # entire index so a model search retains its complete companion tree.
            listed = {a['id'] for a in items}
            nested = [a for a in all_items if a.get('owner') in listed]
            for a in nested:
                target = counts if a['kind'] == 'texture' else file_counts
                target[a['owner']] = target.get(a['owner'], 0) + 1
            nested_ids = {a['id'] for a in nested}
            hidden = {a['id'] for a in items if a['id'] in nested_ids}
            nested_count = len(nested_ids)
            if not kind and not words:
                # The default browser shows characters, models and environments.
                # Other files remain available through explicit filters and searches.
                hidden.update(a['id'] for a in items if a['kind'] not in {'character', 'model', 'environment'})
            items = [a for a in items if a['id'] not in hidden]
        key = {'newest': lambda a: (-a['added'], a['id']), 'oldest': lambda a: (a['added'], a['id']),
               'copied': lambda a: (-a['copied'], -a['added'], a['id']), 'name': lambda a: (a['name'].casefold(), a['id']),
               'game': lambda a: (a['game'].casefold(), a['name'].casefold(), a['id']),
               'kind': lambda a: (a['kind'], a['name'].casefold(), a['id']), 'size': lambda a: (-a['size'], a['id'])}[sort]
        items.sort(key=key)
        return dict(total=len(items), total_all=len(all_items), nested=nested_count,
            hidden_textures=sum(a['id'] in hidden and a['kind'] == 'texture' for a in all_items), hidden_assets=len(hidden),
            offset=offset, has_more=offset + limit < len(items),
            kinds=sorted({a['kind'] for a in all_items}), games=sorted({a['game'] for a in all_items}),
            items=[{**{k: v for k, v in a.items() if not k.startswith('_')}, **({'texture_count': counts[a['id']]} if a['id'] in counts else {}),
                      **({'file_count': file_counts[a['id']]} if a['id'] in file_counts else {})}
                   for a in items[offset:offset + limit]])

    def file(self, item):
        if item['origin'] == 'package':
            from . import uap
            folder = item['_path'].parent; out = self.config.data_dir / 'asset-previews' / (item['id'] + '.glb')
            if not out.exists() or out.stat().st_mtime < item['_path'].stat().st_mtime:
                out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(uap.to_glb(uap.load(folder), folder))
            return out
        return item['_path']

    def preview(self, item):
        p = item.get('_preview')
        if p and p.is_file(): return FileResponse(p, media_type='image/png')
        if item.get('thumb_sha'): return FileResponse(self.store.artifact_path(item['thumb_sha']), media_type='image/png')
        if item['kind'] == 'texture' and item['format'] in {'PNG', 'JPG', 'JPEG', 'WEBP', 'BMP'}:
            return FileResponse(item['_path'], media_type=mimetypes.guess_type('x.' + item['format'].lower())[0])
        if item['format'] in {'GLB', 'GLTF', 'UAP'}:
            out = self.config.data_dir / 'asset-previews' / (item['id'] + '.png')
            with self.preview_lock:
                failed = out.with_suffix('.failed')
                stamp = str(item['_path'].stat().st_mtime_ns)
                if not out.exists() and (not failed.exists() or failed.read_text() != stamp):
                    try:
                        from .characters import render_preview
                        out.parent.mkdir(parents=True, exist_ok=True)
                        model = self.file(item)
                        # Artifacts are stored without extensions; the reader requires one.
                        if model.suffix.lower() not in {'.glb', '.gltf'}:
                            temporary = out.with_suffix('.' + item['format'].lower())
                            temporary.write_bytes(model.read_bytes()); model = temporary
                        render_preview(model, out, size=192)
                    except Exception:
                        out.parent.mkdir(parents=True, exist_ok=True); failed.write_text(stamp)
                if out.exists(): return FileResponse(out, media_type='image/png')
        label = html.escape(item['format'])
        return Response(f'<svg xmlns="http://www.w3.org/2000/svg" width="192" height="144"><rect width="192" height="144" rx="12" fill="#252733"/><path d="M70 25h40l20 20v55H70z" fill="#7c96ff"/><text x="96" y="127" text-anchor="middle" fill="white" font-family="sans-serif">{label}</text></svg>', media_type='image/svg+xml')


def routes(app, store, config, auth):
    from fastapi import Depends, Query
    assets = AssetLibrary(store, config)
    app.state.assets = assets

    @app.get('/api/assets')
    def asset_list(q: str = '', kind: str = '', game: str = '', sort: str = 'newest',
                   offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=200), nest: bool = True,
                   owner: str = '', actor=Depends(auth)):
        return assets.page(q, kind, game, sort, offset, limit, nest, owner)

    @app.get('/api/assets/{rid}/preview')
    def asset_preview(rid: str, actor=Depends(auth)):
        return assets.preview(assets.get(rid))

    @app.get('/api/asset-groups')
    def asset_groups(q: str = '', kind: str = '', game: str = '', sort: str = 'newest', actor=Depends(auth)):
        page = assets.page(q, kind, game, sort, limit=max(1, len(assets.index())))
        groups = {}
        for item in page.pop('items'):
            if item['game'] not in groups:
                groups[item['game']] = {'title': item['game'], 'count': 0, 'preview_url': item['preview_url'],
                                       'added': item['added'], 'copied': item['copied']}
            groups[item['game']]['count'] += 1
            groups[item['game']]['added'] = max(groups[item['game']]['added'], item['added'])
            groups[item['game']]['copied'] = max(groups[item['game']]['copied'], item['copied'])
        return {**page, 'groups': list(groups.values())}

    @app.get('/api/assets/{rid}/file')
    def asset_file(rid: str, actor=Depends(auth)):
        item = assets.get(rid)
        filename = item['name'].replace('/', '_').replace('\\', '_')
        suffix = '.glb' if item['origin'] == 'package' else '.' + item['format'].lower() if item['format'] != 'FILE' else ''
        if suffix and not filename.lower().endswith(suffix): filename += suffix
        return FileResponse(assets.file(item), filename=filename,
                            media_type=item.get('media_type') or mimetypes.guess_type(str(assets.file(item)))[0] or 'application/octet-stream')

    @app.post('/api/assets/{rid}/copy')
    def asset_copy(rid: str, actor=Depends(auth)):
        item = assets.get(rid); path = assets.file(item)
        data = path.read_bytes(); kind = 'gltf' if item['format'] in {'GLB', 'GLTF', 'UAP'} else 'image' if item['kind'] == 'texture' else 'bytes'
        if item['format'] == 'GLTF':
            m = json.loads(data)
            import base64
            for field in ('buffers', 'images'):
                for entry in m.get(field, []):
                    uri = entry.get('uri', '')
                    if uri and not uri.startswith('data:'):
                        linked = (path.parent / unquote(uri)).resolve()
                        if not linked.is_relative_to(path.parent.resolve()):
                            raise HTTPException(422, 'Model dependency must stay inside its asset folder')
                        entry['uri'] = 'data:' + (mimetypes.guess_type(uri)[0] or 'application/octet-stream') + ';base64,' + base64.b64encode(linked.read_bytes()).decode()
            data = json.dumps(m).encode()
        from .models import ArtifactRef
        digest = hashlib.sha256(data).hexdigest()
        existing = store.get('artifact', digest)
        ref = ArtifactRef.model_validate(existing) if existing else store.put_artifact(data, item['name'], item.get('media_type') or ('model/gltf-binary' if data[:4] == b'glTF' else 'model/gltf+json' if kind == 'gltf' else mimetypes.guess_type(str(path))[0] or 'application/octet-stream'),
                                 {'clipboard': True, 'asset_id': rid, 'game_title': item['game'], 'by': actor})
        with store.lock:
            current = store.get('clipboard', 'current') or {'seq': 0}
            clip = dict(seq=current['seq'] + 1, kind=kind, name=item.get('slug') if item.get('primary') else item['name'], sha256=ref.sha256,
                        meta={'asset_id': rid, 'binary': data[:4] == b'glTF'}, ts=time.time(), by=actor)
            store.put('clipboard', 'current', clip)
            store.audit(actor, 'clipboard.copy', ref.sha256, {'kind': kind, 'name': clip['name']})
            store.put('asset_copy', rid, {'id': rid, 'ts': clip['ts']})
        assets.invalidate()
        return clip

    return assets
