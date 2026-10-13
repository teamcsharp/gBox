"""Unified, paginated index of extracted files and the operator's asset clipboard."""
import hashlib
import html
import json
import logging
import mimetypes
import os
import sqlite3
import stat
import sys
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
    ext = os.path.splitext(str(path))[1].lower()
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


REFRESH_S = 60.0          # background re-check of every folder's mtimes (files added inside an existing folder)
INDEX_TTL_S = 1800.0      # a full background rescan at most this often (catches in-place file edits)
FRESH_WAIT_S = 1.0        # how long a request waits for a rebuild after a detected change before serving the old copy
SETTLE_S = 2.0            # a folder modified this recently may still be written to: not cached, its mtimes watched


def _rid(identifier):
    # IDs contain no slash; API resolution never accepts arbitrary filesystem paths.
    return hashlib.sha256(identifier.encode()).hexdigest()[:32]


def _format(path):
    return os.path.splitext(str(path))[1].lstrip('.').upper() or 'FILE'


def _mtime_ns(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _inside(path, real_root):
    target = os.path.realpath(path)
    return target == real_root or target.startswith(real_root.rstrip(os.sep) + os.sep)


def _scan_folder(folder, exts, skip_name):
    """Supported files under folder, one directory listing per directory and at most one stat per file.

    rglob + is_file + resolve + stat per file cost ~6 syscalls each and dominated the old 40 s index build on the
    Spark's NTFS HDD. DirEntry answers is_file from the listing (and stat for free on Windows). Like rglob,
    symlinked directories are not followed; a symlinked file counts only when it resolves inside the folder.
    Returns (files [(rel posix, path, size, mtime)], dirs {rel: mtime_ns}) - dirs key the incremental cache."""
    files, dirs, real, stack = [], {'': os.stat(folder).st_mtime_ns}, None, [(folder, '')]
    while stack:
        directory, prefix = stack.pop()
        with os.scandir(directory) as listing:
            for entry in listing:
                rel = prefix + entry.name
                try:
                    link = entry.is_symlink()
                    if not link and entry.is_dir():
                        dirs[rel] = os.stat(entry.path).st_mtime_ns   # not the listing's copy: compared to os.stat later
                        stack.append((entry.path, rel + '/'))
                        continue
                    if os.path.splitext(entry.name)[1].lower() not in exts or entry.name == skip_name or not entry.is_file():
                        continue
                    if link:
                        real = real or os.path.realpath(folder)
                        if not _inside(entry.path, real):
                            continue
                    st = entry.stat()
                except OSError:
                    continue
                files.append((rel, entry.path, st.st_size, st.st_mtime))
    files.sort()
    return files, dirs


class AssetLibrary:
    """The asset index, kept in memory and rebuilt off the request path.

    A request never rescans the store. It compares a cheap signature (artifact/copy row counts in the metadata DB,
    the mtimes of the three asset roots, the character library's write counter, explicit invalidations) with the
    snapshot's; on a change it starts an incremental rebuild (unchanged folders and immutable artifacts reuse their
    cached scan) and waits up to `wait_s` for it, else answers with the previous snapshot. In the background, every
    `refresh_s` the folders' mtimes are re-checked (new files inside an existing folder) and every `ttl_s` everything
    is rescanned. Until the very first snapshot exists, page() answers indexing=True with no items."""

    def __init__(self, store, config):
        self.store, self.config = store, config
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.preview_lock = threading.Lock()
        self.entries, self.signature, self.built_at, self.full_at, self.build_s = None, None, 0.0, 0.0, None
        self.wait_s, self.ttl_s, self.refresh_s = FRESH_WAIT_S, INDEX_TTL_S, REFRESH_S
        self.dirty = 0                      # bumped by invalidate(); part of the signature
        self.requested = self.completed = 0
        self.building, self.inflight, self.full, self.error = False, None, False, None
        self._folders = {}                  # (prefix, folder) -> (key, scan); builder thread only
        self._artifact_files = {}           # sha256 -> [size, mtime, glb magic]; content-addressed, never changes
        self.watch = ()                     # (path, mtime_ns) of folders that were incomplete or still changing
        self._cutoff_ns, self._watch, self._scanned, self._changed = 0, [], set(), False

    def _recent(self, ns):
        # Within SETTLE_S of the build start, either side (a clock-skewed future mtime must not rebuild forever).
        return ns is not None and self._cutoff_ns <= ns <= self._cutoff_ns + 2 * SETTLE_S * 1e9

    def roots(self):
        from . import characters
        return (characters.library_root(self.config), characters.env_root(self.config), self.config.data_dir / 'uap')

    def _signature(self, metadata):
        from . import characters
        rows = metadata.db.execute("SELECT kind, COUNT(*), MAX(rowid) FROM docs WHERE kind IN ('artifact','asset_copy') GROUP BY kind").fetchall()
        return (tuple(sorted(rows)), tuple(_mtime_ns(r) for r in self.roots()), characters.LIST_GENERATION, self.dirty)

    def invalidate(self, full=False):
        """Something changed that the signature may not see (a clipboard copy, a job's edit); full=True rescans every file."""
        with self.lock:
            self.dirty += 1
            self.full = self.full or full

    def _request_build(self):
        with self.lock:
            self.requested += 1
            if not self.building:
                self.building = True
                threading.Thread(target=self._builder, name='asset-index', daemon=True).start()
            return self.requested

    def warm(self):
        """Build the first snapshot in the background (server startup) so the first sidebar load finds it ready."""
        with self.lock:
            if self.entries is None and not self.building:
                self._request_build()

    def wait_for_build(self, timeout=None):
        with self.lock:
            return self.changed.wait_for(lambda: not self.building, timeout)

    def _builder(self):
        while True:
            with self.lock:
                if self.completed >= self.requested:
                    self.building, self.inflight = False, None
                    self.changed.notify_all()
                    return
                target, full, self.full = self.requested, self.full, False
            full = full or self.entries is None
            started = time.monotonic()
            try:
                signature, entries = self._build_now(full, target)
                error = None
            except Exception as e:
                logging.getLogger(__name__).exception('asset index build failed')
                signature = entries = None
                error = f'{type(e).__name__}: {e}'
            with self.lock:
                self.error = error
                if entries is not None:
                    self.entries, self.signature, self.watch = entries, signature, tuple(self._watch)
                    self.built_at, self.build_s = time.monotonic(), time.monotonic() - started
                    if full:
                        self.full_at = started
                self.completed = max(self.completed, target)
                self.changed.notify_all()

    def _build_now(self, full=False, target=None):
        with _IndexMetadata(self.store.dir) as metadata:
            self._cutoff_ns = (time.time() - SETTLE_S) * 1e9
            began = time.perf_counter()
            signature = self._signature(metadata)    # read first: changes made during the scan trigger the next build
            self._watch = []
            if target is not None:
                with self.lock:
                    self.inflight = (signature, target, began)
            if full:
                self._folders, self._artifact_files = {}, {}
            with self.lock:
                reuse = self.entries if not full and signature == self.signature else None
            return signature, self._build_index(metadata, reuse)

    def index(self, wait=None):
        """The current entries, or None while the very first snapshot is still being built."""
        asked = time.perf_counter()
        with _IndexMetadata(self.store.dir) as metadata:
            signature = self._signature(metadata)
        # A folder seen without its meta.json, or still being written, is re-checked on every request until it settles.
        watched = any(_mtime_ns(path) != ns for path, ns in self.watch)
        with self.lock:
            if self.entries is not None and signature == self.signature and not watched:
                now = time.monotonic()
                if not self.building and (now - self.full_at > self.ttl_s or now - self.built_at > self.refresh_s):
                    self.full = now - self.full_at > self.ttl_s
                    self._request_build()                  # stale-while-revalidate: this request keeps the old copy
                return self.entries
            # Join a running build only when it started after this request: an earlier one may predate changes
            # inside a folder, which the signature does not show.
            inflight = self.inflight
            joinable = self.building and inflight and inflight[0] == signature and inflight[2] >= asked
            target = inflight[1] if joinable else self._request_build()
            self.changed.wait_for(lambda: self.completed >= target, self.wait_s if wait is None else wait)
            return self.entries

    def _folders_in(self, root, marker):
        """(folder, marker stat) per <root>/<name>/<marker>, as root.glob('*/<marker>') found them."""
        try:
            listing = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError:
            return
        for entry in listing:
            try:
                if not entry.is_dir():
                    continue
                folder = Path(os.path.realpath(entry.path)) if entry.is_symlink() else Path(entry.path)
                folder_ns = os.stat(folder).st_mtime_ns           # before the marker: a marker written later changes it
            except OSError:
                continue
            try:
                marker_stat = os.stat(folder / marker)
            except OSError:
                self._watch.append((str(folder), folder_ns))      # not (yet) an entry: rebuild when it gets one
                continue
            yield folder, marker_stat

    def _scan(self, prefix, folder, marker_stat, exts, skip_name):
        """The folder's parsed marker + file scan, reused while the marker and every directory mtime are unchanged."""
        cached = self._folders.get((prefix, folder))
        if cached:
            key, result = cached
            if key[0] == (marker_stat.st_mtime_ns, marker_stat.st_size) and all(
                    _mtime_ns(os.path.join(folder, rel)) == ns for rel, ns in key[1].items()):
                return result
        marker_name = 'manifest.json' if prefix == 'package' else 'meta.json'
        marker = json.loads((folder / marker_name).read_text())
        files, dirs = _scan_folder(folder, exts, skip_name(marker) if callable(skip_name) else skip_name)
        # Per-file ID, kind and format are fixed by the path: computed once per scan, not per rebuild.
        # Package file IDs keep the OS separator (str of the relative path), as the IDs already handed out did.
        ident = f'package-file:{folder.name}:' if prefix == 'package' else f'{prefix}:{folder.name}:'
        files = [(rel, path, size, mtime, _rid(ident + (rel.replace('/', os.sep) if prefix == 'package' else rel)),
                  file_kind(path), _format(path)) for rel, path, size, mtime in files]
        result = (marker, files)
        self._changed = True
        if any(map(self._recent, (marker_stat.st_mtime_ns, *dirs.values()))):
            # Still being written: watch it (a later file changes these mtimes) and rescan it next time.
            self._watch += [(str(folder / marker_name), marker_stat.st_mtime_ns),
                            *((os.path.join(folder, rel), ns) for rel, ns in dirs.items())]
            self._folders.pop((prefix, folder), None)
        else:
            self._folders[(prefix, folder)] = ((marker_stat.st_mtime_ns, marker_stat.st_size), dirs), result
        return result

    def _scan_all(self):
        """Every collection and package folder: [(prefix, folder, marker stat, marker, files)]. Sets self._changed when
        any folder was (re)read, appeared or disappeared since the last build."""
        scans, seen = [], set()
        for prefix, root, marker, exts, skip in (
                ('character', self.roots()[0], 'meta.json', ASSET_EXT, lambda m: m.get('preview', 'preview.png')),
                ('environment', self.roots()[1], 'meta.json', ASSET_EXT, lambda m: m.get('preview', 'preview.png')),
                ('package', self.roots()[2], 'manifest.json', ASSET_EXT - MODEL_EXT, 'preview.png')):
            for folder, marker_stat in self._folders_in(root, marker):
                try:
                    m, files = self._scan(prefix, folder, marker_stat, exts, skip)
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
                seen.add((prefix, folder))
                scans.append((prefix, folder, marker_stat, m, files))
        if seen != self._scanned:
            self._changed = True
        for key in set(self._folders) - seen:
            del self._folders[key]                          # deleted folders
        self._scanned = seen
        return scans

    def _build_index(self, metadata, reuse=None):
        """All entries. With `reuse` (the current snapshot, whose signature still holds) and no folder changed on disk,
        that snapshot is returned as is: a periodic refresh then costs a few stats, not a rebuild of every entry."""
        self._changed = False
        scans = self._scan_all()
        if reuse is not None and not self._changed:
            return reuse
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

        def add(rid, path, name, kind, game='', added=0, preview=None, aliases=(), size=0, mtime=0, **extra):
            entries[rid] = dict(id=rid, name=name, kind=kind, game=game or 'Unknown title',
                added=added or mtime, copied=max([copied_ids.get(rid, 0), copied.get(extra.get('sha256'), 0), *[copied_names.get(a, 0) for a in aliases]]),
                size=size, format=extra.pop('format', None) or _format(path),
                preview_url=f'/api/assets/{rid}/preview', file_url=f'/api/assets/{rid}/file',
                _path=str(path), _preview=preview, **extra)   # str: a Path per entry cost seconds

        for prefix, folder, meta_stat, m, files in scans:
            if prefix == 'package':
                continue
            try:
                source = m.get('source') or {}; model = m.get('model', '')
                game = source.get('game_title') or source.get('title') or source.get('game_id') or ''
                aliases = (m.get('slug', folder.name), m.get('name', ''), model)
                if game:
                    for alias in (*aliases[:2], *m.get('aliases', [])):
                        model_titles[str(alias).casefold()] = game
                for rel, path, size, mtime, rid, kind, fmt in files:
                    primary = rel == model
                    add(rid, path, m.get('name', folder.name) if primary else f"{m.get('name', folder.name)} · {rel}",
                        m.get('kind', prefix) if primary else kind, game, m.get('added', 0) if primary else mtime,
                        folder / m.get('preview', 'preview.png') if primary else None, aliases=aliases if primary else (),
                        size=size, mtime=mtime, format=fmt, origin='collection', slug=folder.name, collection=prefix, primary=primary)
            except (OSError, ValueError, TypeError, AttributeError):
                continue

        catalog_titles, sessions = {}, {}

        def catalog_title(gid):
            if gid not in catalog_titles:
                catalog_titles[gid] = metadata.catalog_get(gid)
            return catalog_titles[gid]

        def source_title(source):
            title = source.get('game_title') or source.get('title') or source.get('game')
            gid = source.get('game_id')
            if gid:
                title = (catalog_title(gid) or {}).get('title') or title
            if not title:
                # Historical PSO packages record the configured disc alias instead of a catalog ID.
                disc = Path(source.get('game_disc') or '').name.lower()
                family = {'psov2.gdi': 'Phantasy Star Online Ver. 2', 'psogc.iso': 'Phantasy Star Online Episode I & II'}.get(disc)
                if family:
                    matches = {a['game'] for a in entries.values() if a['game'].startswith(family)}
                    title = next(iter(matches)) if len(matches) == 1 else family
            return title if isinstance(title, str) else ''

        for prefix, folder, manifest_stat, m, files in scans:
            if prefix != 'package':
                continue
            try:
                source = m.get('source', {})
                game = source_title(source)
                # The package itself is one model, plus bounded supported companion files.
                add(_rid(f'package:{folder.name}'), folder / 'manifest.json', m.get('name', folder.name), 'model', game,
                    manifest_stat.st_mtime, folder / 'preview.png', aliases=(folder.name,), size=manifest_stat.st_size,
                    origin='package', package=folder.name, format='UAP')
                for rel, path, size, mtime, rid, kind, fmt in files:
                    add(rid, path, os.path.basename(path), kind, game, size=size, mtime=mtime, format=fmt,
                        origin='package-file', package=folder.name)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        artifacts = metadata.all('artifact')
        previews = {a.get('provenance', {}).get('job'): a['sha256'] for a in artifacts
                    if a.get('name', '').lower().startswith(('preview', 'frame')) and a.get('media_type', '').startswith('image/') and a.get('provenance', {}).get('job')}
        jobs = {}
        for a in artifacts:
            prov = a.get('provenance', {}); name = a.get('name', 'Asset'); ext = os.path.splitext(name)[1].lower(); sha = a['sha256']
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
            catalog = catalog_title(gid) if gid else None
            nested = prov.get('source') if isinstance(prov.get('source'), dict) else {}
            sid = prov.get('session') or inp.get('session_id') or ''
            if sid not in sessions:
                sessions[sid] = metadata.get('session', sid) or {}
            sess = sessions[sid]
            title = prov.get('title') or prov.get('game_title') or (catalog or {}).get('title') or game.get('title') or prov.get('game') or source_title(nested) or sess.get('title')
            if not title:
                title = model_titles.get(str(prov.get('base') or prov.get('character') or '').casefold(), '')
            if not isinstance(title, str): title = str(title)
            path = self.store.artifact_path(sha)
            stored = self._artifact_files.get(sha)
            if stored is None:
                try:
                    st = os.stat(path)
                except OSError:
                    continue                                # not on disk (yet): the next rebuild looks again
                if not stat.S_ISREG(st.st_mode):
                    continue
                stored = self._artifact_files[sha] = [st.st_size, st.st_mtime, None]
            size, mtime = stored[:2]
            media = a.get('media_type', '')
            fmt = ext.lstrip('.').upper() or ('GLB' if media == 'model/gltf-binary' else 'GLTF' if media == 'model/gltf+json' else media.split('/')[-1].upper() if media.startswith('image/') else 'FILE')
            if is_model and fmt == 'GLTF':
                if stored[2] is None:
                    try:
                        with open(path, 'rb') as stream:
                            stored[2] = stream.read(4) == b'glTF'
                    except OSError:
                        continue
                if stored[2]: fmt = 'GLB'
            add(_rid(f'artifact:{sha}'), path, name, 'model' if is_model else 'texture' if media.startswith('image/') else file_kind(name), title,
                j.get('finished') or 0, aliases=(name,), size=size, mtime=mtime, origin='artifact', sha256=sha,
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
        entries = self.index()
        if entries is None:
            raise HTTPException(503, 'The asset index is still being built; retry in a few seconds.')
        item = entries.get(rid)
        if not item:
            raise HTTPException(404, 'Asset is no longer available; refresh the asset list.')
        return item

    def page(self, q='', kind='', game='', sort='newest', offset=0, limit=60, nest=True, owner='', raw=False):
        """One page of the index. indexing=True (and no items) until the first snapshot exists; updating=True while a
        rebuild runs. raw=True returns the internal entries uncopied (read-only callers)."""
        if sort not in {'newest', 'oldest', 'copied', 'name', 'game', 'kind', 'size'}:
            raise HTTPException(422, 'Unknown asset sort')
        entries = self.index()
        if entries is None and self.error:
            raise HTTPException(500, 'Could not index the assets: ' + self.error)
        if entries is None:
            return dict(total=0, total_all=0, nested=0, hidden_textures=0, hidden_assets=0, offset=offset, has_more=False,
                        kinds=[], games=[], items=[], indexing=True, updating=True)
        all_items = list(entries.values())
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
            indexing=False, updating=self.building,
            items=items[offset:offset + limit] if raw else [{**{k: v for k, v in a.items() if not k.startswith('_')}, **({'texture_count': counts[a['id']]} if a['id'] in counts else {}),
                      **({'file_count': file_counts[a['id']]} if a['id'] in file_counts else {})}
                   for a in items[offset:offset + limit]])

    def file(self, item):
        if item['origin'] == 'package':
            from . import uap
            folder = Path(item['_path']).parent; out = self.config.data_dir / 'asset-previews' / (item['id'] + '.glb')
            if not out.exists() or out.stat().st_mtime < os.stat(item['_path']).st_mtime:
                out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(uap.to_glb(uap.load(folder), folder))
            return out
        return Path(item['_path'])

    def preview(self, item):
        p = item.get('_preview')
        if p and p.is_file(): return FileResponse(p, media_type='image/png')
        if item.get('thumb_sha'): return FileResponse(self.store.artifact_path(item['thumb_sha']), media_type='image/png')
        if item['kind'] == 'texture' and item['format'] in {'PNG', 'JPG', 'JPEG', 'WEBP', 'BMP'}:
            return FileResponse(Path(item['_path']), media_type=mimetypes.guess_type('x.' + item['format'].lower())[0])
        if item['format'] in {'GLB', 'GLTF', 'UAP'}:
            out = self.config.data_dir / 'asset-previews' / (item['id'] + '.png')
            with self.preview_lock:
                failed = out.with_suffix('.failed')
                stamp = str(os.stat(item['_path']).st_mtime_ns)
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

    @app.on_event('startup')
    def _warm_asset_index():
        # The first snapshot reads every asset folder; build it in the background, not on the first sidebar request.
        if os.environ.get('GBOX_ASSET_WARM', '1') != '0':
            assets.warm()

    @app.get('/api/assets')
    def asset_list(q: str = '', kind: str = '', game: str = '', sort: str = 'newest',
                   offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=200), nest: bool = True,
                   owner: str = '', fresh: bool = False, actor=Depends(auth)):
        if fresh:
            assets.invalidate(full=True)
        return assets.page(q, kind, game, sort, offset, limit, nest, owner)

    @app.get('/api/assets/{rid}/preview')
    def asset_preview(rid: str, actor=Depends(auth)):
        return assets.preview(assets.get(rid))

    @app.get('/api/asset-groups')
    def asset_groups(q: str = '', kind: str = '', game: str = '', sort: str = 'newest', fresh: bool = False, actor=Depends(auth)):
        """Per-title counts for the sidebar. fresh=1 rescans every asset file in the background (the refresh button)."""
        if fresh:
            assets.invalidate(full=True)
        page = assets.page(q, kind, game, sort, limit=sys.maxsize, raw=True)
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
