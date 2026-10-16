"""Exact-title reusable exports and bounded, explicitly advanced extraction jobs.

Raw native bundles never become character-library models or playable-build proof.
The existing job scheduler retains permission, idle and operator-session admission.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
import zipfile
from typing import Literal

from pydantic import BaseModel, Field, StrictInt, model_validator

from .models import Permission as P
from .registry import tool

CATEGORIES = ('characters', 'props', 'textures', 'animations')
ARTIFACT = 'title-assets.json'
BUNDLE = 'title-assets-native.zip'
CHUNK_BYTES = 24 * 1024**2
MAX_BUNDLE_BYTES = 32 * 1024**2
ACTIVE = {'queued', 'running'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def catalog_key(game):
    """Catalog identity is an invalidation hint, not a claim of verified source bytes."""
    return digest({key: game.get(key) for key in
                   ('game_id', 'platform', 'library', 'rel_path', 'hashes', 'size', 'format', 'launch')})


def native_reader(game):
    from .doa3_native import supports_game
    return supports_game(game)


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_directory(game, config, *, allow_unpack=False, progress=lambda *_: None):
    """Use an exact existing owned view first; never copy a play disc or touch saves."""
    from . import doa3_native as native, rom_archives
    if not native_reader(game):
        raise ValueError('No native raw reader registered for this exact catalog title')
    # This app-created view is tied to the curated title and checked against its
    # receipt. Only the two required files are read; .recomp-storage is untouched.
    home = Path(config.runtime) / 'xbox' / 'doa3-native-play' / game['game_id']
    marker, disc = home / 'disc-receipt.json', home / 'disc'
    if marker.exists():
        native._plain_path(marker)
        if marker.stat().st_size > 32 * 1024**2:
            raise ValueError('Owned DOA3 disc receipt is too large')
        receipt = json.loads(marker.read_text(encoding='utf8'))
        if receipt.get('format') != 1 or receipt.get('game_id') != game['game_id']:
            raise ValueError('Owned DOA3 disc receipt belongs to another title')
        files = {row['name'].lower(): row for row in receipt.get('files', [])}
        for name in ('default.xbe', 'loadfile.afs'):
            path, expected = disc / name, files.get(name) or {}
            native._plain_path(path)
            if not path.is_file() or path.stat().st_size != expected.get('size') or _sha(path) != expected.get('sha256'):
                raise ValueError('Owned DOA3 source view differs from its receipt')
        return disc, 'validated_native_play_disc'
    from .models import CatalogEntry
    from .tools import rom_path
    source = rom_path(CatalogEntry.model_validate(game), config)
    if source.suffix.lower() in ('.7z', '.zip'):
        entries = rom_archives.members(source)
        names = [row['name'] for row in entries if Path(row['name']).name.lower() == 'default.xbe']
        if len(names) != 1:
            raise ValueError('Archive needs a unique default.xbe; prepare an owned Xbox disc view first')
        identity = rom_archives._source_identity(source, config, names[0])
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        folder = Path(config.runtime) / 'extract' / ('rom-' + key)
        receipt = folder / '.gbox-extracted.json'
        if not allow_unpack and not (receipt.is_file() and json.loads(receipt.read_text()) == identity):
            raise ValueError('No reusable owned extraction on this worker; allow_unpack must be explicit')
        source = rom_archives.prepare(source, config, names[0], progress)
    if source.is_dir():
        source = source / 'default.xbe'
    if source.name.lower() != 'default.xbe':
        raise ValueError('Prepare an owned Xbox disc view first; this tool does not install image extractors')
    native._plain_path(source)
    native._plain_path(source.parent / 'loadfile.afs')
    return source.parent, 'owned_catalog_source'


class TitleAssetsIn(BaseModel):
    op: Literal['inventory', 'export'] = 'inventory'
    game_id: str = Field(pattern=r'^[0-9a-f]{16}$')
    entry_ids: list[StrictInt] = Field(default_factory=list, max_length=128)
    expected_source: dict = Field(default_factory=dict)
    expected_catalog_key: str = Field(default='', pattern=r'^(?:[0-9a-f]{64})?$')
    allow_unpack: bool = False

    @model_validator(mode='after')
    def bounded_selection(self):
        if any(type(i) is not int or i < 0 or i >= 8192 for i in self.entry_ids) or len(set(self.entry_ids)) != len(self.entry_ids):
            raise ValueError('Native member indices must be unique and bounded')
        if (self.op == 'export') != bool(self.entry_ids):
            raise ValueError('Export requires explicit member indices; inventory has no selection')
        if self.op == 'export' and not self.expected_source:
            raise ValueError('Export requires its inventory source revision')
        return self


class TitleAssetsOut(BaseModel):
    result: dict
    manifest_sha256: str


def _bundle_bytes(result):
    """Portable native bytes, with no executable extraction or local-path dependency."""
    from .doa3_native import _plain_path
    folder = Path(result['bundle_dir'])
    _plain_path(folder)
    manifest_path = folder / 'manifest.json'
    _plain_path(manifest_path)
    if manifest_path.stat().st_size > 2 * 1024**2:
        raise ValueError('Native export metadata exceeds its upload budget')
    metadata = manifest_path.read_bytes()
    if len(metadata) > 2 * 1024**2:
        raise ValueError('Native export metadata exceeds its upload budget')
    manifest = json.loads(metadata)
    if any(manifest.get(k) != result.get(k) for k in ('game_id', 'source', 'members', 'capabilities')):
        raise ValueError('Native export manifest differs from its result')
    if sum(row['size'] for row in manifest['members']) > CHUNK_BYTES:
        raise ValueError('Native export exceeds the bounded artifact budget')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, data in [('manifest.json', metadata), *[(row['path'], None) for row in manifest['members']]]:
            if data is None:
                if not re.fullmatch(r'members/[0-9]{6}_[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', name):
                    raise ValueError('Native bundle member path is invalid')
                path = folder / name
                _plain_path(path)
                row = next(row for row in manifest['members'] if row['path'] == name)
                if path.stat().st_size != row['size'] or _sha(path) != row['sha256']:
                    raise ValueError('Native bundle changed before upload')
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != row['sha256']:
                    raise ValueError('Native bundle changed during upload')
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=1)
    payload = output.getvalue()
    if len(payload) > MAX_BUNDLE_BYTES:
        raise ValueError('Native bundle upload exceeds 32 MiB')
    return payload


def _validate(out, arts):
    data = arts.get(ARTIFACT)
    if not data or hashlib.sha256(data).hexdigest() != out.manifest_sha256:
        return ['Title asset manifest artifact is missing or changed']
    try:
        same = json.loads(data) == out.result
    except (ValueError, TypeError):
        same = False
    r = out.result
    if not same or not re.fullmatch(r'[0-9a-f]{16}', str(r.get('game_id', ''))) or not r.get('worker_id'):
        return ['Title asset manifest identity is invalid']
    caps = r.get('capabilities') or {}
    if caps.get('raw') is not True or any(caps.get(k) is not False for k in
            ('decoded', 'writable', 'reimportable', 'full_character_replacement')):
        return ['Raw native exports cannot claim decoded or replacement capabilities']
    source = r.get('source') or {}
    if not re.fullmatch(r'[0-9a-f]{64}', str(source.get('archive_sha256') or '')):
        return ['Native source archive revision is missing']
    from .doa3_native import XBE_SHA256, PATCHED_XBE_SHA256
    if r.get('schema') != 'gbox-doa3-native-assets-v1' or r.get('op') not in ('inventory', 'export') or source.get('xbe_sha256') not in (XBE_SHA256, PATCHED_XBE_SHA256):
        return ['Native title or reader revision is unsupported']
    if r.get('op') == 'export':
        payload = arts.get(BUNDLE, b'')
        if not payload or len(payload) > MAX_BUNDLE_BYTES or hashlib.sha256(payload).hexdigest() != r.get('bundle_sha256'):
            return ['Portable native bundle artifact is missing or changed']
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = r.get('members') or []
                expected = {'manifest.json', *(row['path'] for row in members)}
                infos = archive.infolist()
                if not members or len(members) > 128 or len(infos) != len(expected) or {i.filename for i in infos} != expected:
                    raise ValueError('unexpected members')
                if len({row['index'] for row in members}) != len(members) or len(expected) != len(members) + 1:
                    raise ValueError('duplicate member identity')
                if sum(i.file_size for i in infos) > CHUNK_BYTES + 2 * 1024**2:
                    raise ValueError('oversized members')
                if archive.getinfo('manifest.json').file_size > 2 * 1024**2:
                    raise ValueError('oversized manifest')
                for info in infos:
                    if info.is_dir() or info.flag_bits & 1 or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('unsupported member type')
                metadata = json.loads(archive.read('manifest.json'))
                if any(metadata.get(k) != r.get(k) for k in ('game_id', 'source', 'members', 'capabilities')):
                    raise ValueError('manifest mismatch')
                for row in members:
                    if not re.fullmatch(r'members/[0-9]{6}_[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', row['path']):
                        raise ValueError('unsafe member path')
                    data = archive.read(row['path'])
                    if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                        raise ValueError('member hash mismatch')
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError):
            return ['Portable native bundle contents failed independent validation']
    return []


def _accept(store, out, actor):
    r = out.result
    key = digest({'game_id': r['game_id'], 'source': r['source'], 'selection': r.get('selection'), 'op': r['op']})
    store.put('title_asset_manifest', key, r | {'manifest_sha256': out.manifest_sha256, 'id': key})


@tool('title_assets', '1.0', TitleAssetsIn, TitleAssetsOut, capabilities=['asset', 'extract'],
      permissions=[P.READ, P.STAGE, P.EXECUTE], timeout_s=1800,
      artifacts=[ARTIFACT, BUNDLE], validate=_validate, on_accept=_accept,
      side_effects=['Writes only bounded content-addressed raw exports below data_dir/title-assets'])
def title_assets(inp, ctx):
    """Inventory or export selected native members from the exact owned title; never builds or launches a game."""
    from .characters import _api
    from . import doa3_assets
    game = _api(ctx, 'GET', f'/api/catalog/{inp.game_id}')
    if game.get('game_id') != inp.game_id:
        raise ValueError('Catalog response belongs to another title')
    if inp.expected_catalog_key and catalog_key(game) != inp.expected_catalog_key:
        raise ValueError('Catalog source changed after this extraction was queued')
    source, source_kind = source_directory(game, ctx.config, allow_unpack=inp.allow_unpack, progress=ctx.progress)
    result = doa3_assets.inventory(source, game_id=inp.game_id)
    if inp.op == 'export':
        if result.get('source') != inp.expected_source:
            raise ValueError('Native source changed since inventory; refresh the title inventory first')
        members = {row['index']: row for row in result.get('members', [])}
        if any(i not in members for i in inp.entry_ids) or sum(members[i]['size'] for i in inp.entry_ids) > CHUNK_BYTES:
            raise ValueError('Native selection exceeds the bounded artifact budget or references missing members')
        result = doa3_assets.export_selected(source, Path(ctx.config.data_dir) / 'title-assets' / inp.game_id,
                    game_id=inp.game_id, entry_ids=inp.entry_ids, progress=ctx.progress)
        if result.get('source') != inp.expected_source:
            raise ValueError('Native source changed during export')
        payload = _bundle_bytes(result)
        result['bundle_sha256'] = hashlib.sha256(payload).hexdigest()
        ctx.artifact(BUNDLE, payload, 'application/zip', game_id=inp.game_id, category='native_raw',
                     source=result['source'], decoded=False)
    result = result | {'game_id': inp.game_id, 'game_title': game['title'], 'catalog_platform': game['platform'],
                       'worker_id': ctx.worker, 'job_id': ctx.job_id, 'op': inp.op,
                       'source_kind': source_kind, 'catalog_key': catalog_key(game)}
    data = json.dumps(result, sort_keys=True).encode()
    ctx.artifact(ARTIFACT, data, 'application/json', game_id=inp.game_id, category='native_raw',
                 source=result['source'], decoded=False)
    return {'result': result, 'manifest_sha256': hashlib.sha256(data).hexdigest()}


class CollectIn(BaseModel):
    categories: list[Literal['characters', 'props', 'textures', 'animations']] = Field(default_factory=lambda: list(CATEGORIES), min_length=1, max_length=4)
    worker_id: str = Field(default='', max_length=100)
    parent_request_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{16}$')
    request_ids: list[str] = Field(default_factory=list, max_length=8)
    retry_failed: bool = False
    allow_unpack: bool = False
    refresh_inventory: bool = False


class TitleAssets:
    def __init__(self, store, config, workers, submit):
        self.store, self.config, self.workers, self.submit = store, config, workers, submit
        self.lock = threading.RLock()

    def _game(self, gid):
        game = self.store.catalog_get(gid)
        if not game:
            raise KeyError('Unknown exact catalog game_id')
        return game

    def status(self, gid):
        from . import char_coverage as coverage
        game = self._game(gid)
        record = self.store.get('title_asset_pipeline', gid) or {}
        key = catalog_key(game)
        epoch = record.get('inventory_epoch', 0)
        tasks = []
        for task in (record.get('tasks') or {}).values():
            if task.get('catalog_key') != key or task.get('inventory_epoch', 0) != epoch:
                continue
            job = self.store.get('job', task['job_id']) or {}
            tasks.append(task | {'state': job.get('state', 'missing'), 'error': job.get('error'),
                                 'result': (job.get('output') or {}).get('result') if job.get('state') == 'succeeded' else None})
        extractor, roster = coverage.extractor_for(game)
        writer = coverage.writer_for(game)
        valid_native = lambda t: (t['result'] or {}).get('game_id') == gid and (t['result'] or {}).get('catalog_key') == key and (t['result'] or {}).get('worker_id') == t['worker_id']
        inventory = next((t['result'] for t in reversed(tasks) if t['kind'] == 'inventory' and t['state'] == 'succeeded' and valid_native(t)), None)
        exports = [t['result'] for t in tasks if t['kind'] == 'export' and t['state'] == 'succeeded' and
                   valid_native(t) and inventory and (t['result'] or {}).get('source') == inventory.get('source')]
        exports = [row | {'bundle_url': '/api/artifacts/' + row['bundle_sha256']} if row.get('bundle_sha256') else row for row in exports]
        categories = {category: {'state': 'pending_reader', 'scope': 'decoded_native_assets',
                         'full_source_verified': False} for category in CATEGORIES}
        if extractor:
            categories['characters'].update(state='registered_subset', extractor=extractor, registered=len(roster),
                collection=self.store.get('character_collection', gid) or {'state': 'not_started'})
        if native_reader(game):
            for category in CATEGORIES:
                categories[category]['raw_state'] = 'exported_subset' if exports else ('inventoried' if inventory else 'pending_inventory')
        expected = {row['index'] for row in (inventory or {}).get('members', []) if not row.get('placeholder') and row.get('kind') != 'placeholder'}
        exported = {row['index'] for result in exports for row in result.get('members', [])}
        return {'game_id': gid, 'title': game['title'], 'platform': game['platform'], 'catalog_key': key,
                'categories': categories, 'tasks': tasks, 'inventory': inventory, 'exports': exports,
                'request_ids': record.get('request_ids', []), 'writer': writer,
                'requested_categories': record.get('categories', []), 'blocked_reason': record.get('blocked_reason'),
                'inventory_epoch': epoch, 'historical_tasks_count': len(record.get('tasks') or {}) - len(tasks),
                'raw_coverage': {'scope': 'non-placeholder loadfile.afs members', 'expected': len(expected) if inventory else None,
                                 'exported': len(expected & exported), 'complete': bool(inventory and expected and expected <= exported),
                                 'oversized_members': [row['index'] for row in (inventory or {}).get('members', []) if row['index'] in expected and row['size'] > CHUNK_BYTES]},
                'playable_build_verified': False,
                'scope': 'Registered roster subsets and native raw bundles only; decoded props, textures, animations and cross-title replacement require separate validation.'}

    def _worker(self, game, tool_name, selected, os_required=None):
        candidates = [w for w in self.workers() if w.get('online') and tool_name in (w.get('tools') or []) and
                      (not os_required or w.get('os') == os_required)]
        if selected:
            seen = set()
            for _ in range(20):
                alias = self.store.get('worker_alias', selected)
                if not alias:
                    break
                if selected in seen or not isinstance(alias.get('to'), str):
                    raise ValueError('The source worker alias chain is invalid')
                seen.add(selected)
                selected = alias['to']
            else:
                raise ValueError('The source worker alias chain is too long')
            candidates = [w for w in candidates if selected in (w.get('id'), w.get('name'))]
        library = next((lib for lib in self.config.libraries if lib.id == game.get('library')), None)
        if library:
            candidates = [w for w in candidates if library.paths.get(w.get('os'))]
        elif not selected:
            raise ValueError('A title without configured library paths requires an explicit source worker')
        if not candidates:
            raise ValueError('No online worker has this tool and a configured source library for the required OS')
        return sorted(candidates, key=lambda w: (w.get('os') != 'windows', w['id']))[0]

    @staticmethod
    def _next_chunk(inventory, completed):
        done = {row['index'] for result in completed for row in result.get('members', [])}
        selected, size = [], 0
        for row in inventory.get('members', []):
            n = int(row.get('size') or 0)
            if row['index'] in done or row.get('placeholder') or row.get('kind') == 'placeholder':
                continue
            if n > CHUNK_BYTES:
                continue  # Explicit pending coverage, never silently complete.
            if selected and (len(selected) >= 128 or size + n > CHUNK_BYTES):
                break
            selected.append(row['index'])
            size += n
        return selected

    def collect(self, gid, inp, actor):
        with self.lock:
            game = self._game(gid)
            ids = list(dict.fromkeys([*(inp.request_ids or []), *([inp.parent_request_id] if inp.parent_request_id else [])]))
            for rid in ids:
                if not re.fullmatch(r'[0-9a-f]{16}', rid) or not self.store.get('request', rid):
                    raise ValueError('Every dependency must reference an existing request_id')
            record = self.store.get('title_asset_pipeline', gid) or {'tasks': {}, 'request_ids': []}
            if inp.refresh_inventory:
                if not native_reader(game):
                    raise ValueError('This title has no registered native inventory to refresh')
                if any((self.store.get('job', task['job_id']) or {}).get('state') in ACTIVE
                       for task in (record.get('tasks') or {}).values()):
                    raise ValueError('Wait for this title’s queued or running extraction jobs before refreshing inventory')
                record['inventory_epoch'] = record.get('inventory_epoch', 0) + 1
            record['request_ids'] = list(dict.fromkeys(record.get('request_ids', []) + ids))
            record['categories'] = sorted(set(record.get('categories', []) + inp.categories))
            record['game_id'], record['updated'] = gid, time.time()
            record.pop('blocked_reason', None)
            self.store.put('title_asset_pipeline', gid, record)
            current = self.status(gid)
            kind, tool_name, data, required_os = None, None, None, None
            if native_reader(game):
                if not current['inventory']:
                    kind, data = 'inventory', {'op': 'inventory', 'game_id': gid, 'allow_unpack': inp.allow_unpack}
                else:
                    chosen = self._next_chunk(current['inventory'], current['exports'])
                    if chosen:
                        kind, data = 'export', {'op': 'export', 'game_id': gid, 'entry_ids': chosen,
                            'expected_source': current['inventory']['source'], 'allow_unpack': inp.allow_unpack}
                tool_name = 'title_assets'
            elif current['categories']['characters']['state'] == 'registered_subset' and 'characters' in inp.categories:
                kind, tool_name, data, required_os = 'registered_roster', 'characters', {'op': 'collect', 'game_id': gid}, 'linux'
            if data:
                if tool_name == 'title_assets':
                    data['expected_catalog_key'] = current['catalog_key']
                task_key = digest({'catalog_key': current['catalog_key'], 'inventory_epoch': current['inventory_epoch'], 'tool': tool_name, 'input': data})
                previous = (record.get('tasks') or {}).get(task_key)
                previous_job = self.store.get('job', previous['job_id']) if previous else None
                if not previous_job or (inp.retry_failed and previous_job.get('state') not in ACTIVE | {'succeeded'}):
                    selected = inp.worker_id or ((current.get('inventory') or {}).get('worker_id') if tool_name == 'title_assets' else '')
                    try:
                        worker = self._worker(game, tool_name, selected, required_os)
                    except ValueError as error:
                        record['blocked_reason'] = str(error)
                        self.store.put('title_asset_pipeline', gid, record)
                        raise
                    job = self.submit({'tool': tool_name, 'input': data, 'require_worker': worker['id'],
                        'require_os': required_os or worker['os'], 'parent_request_id': inp.parent_request_id or (ids[0] if ids else None),
                        'agent_use': True, 'low_priority': True}, actor)
                    record.setdefault('tasks', {})[task_key] = {'kind': kind, 'job_id': job['id'],
                        'worker_id': worker['id'], 'catalog_key': current['catalog_key'], 'categories': inp.categories,
                        'inventory_epoch': current['inventory_epoch']}
            self.store.put('title_asset_pipeline', gid, record)
            self.store.audit(actor, 'title_assets.collect', gid, {'request_ids': ids, 'categories': inp.categories,
                'refresh_inventory': inp.refresh_inventory, 'inventory_epoch': current['inventory_epoch']})
            return self.status(gid)


def routes(app, store, config, auth, workers, submit):
    from fastapi import Depends, HTTPException
    manager = TitleAssets(store, config, workers, submit)
    app.state.title_assets = manager

    @app.get('/api/title-assets/{gid}')
    def status(gid: str, actor=Depends(auth)):
        try:
            return manager.status(gid)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.post('/api/title-assets/{gid}/collect')
    def collect(gid: str, body: CollectIn, actor=Depends(auth)):
        try:
            return manager.collect(gid, body, actor)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
