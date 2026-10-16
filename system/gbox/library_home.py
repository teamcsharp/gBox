"""Read-only Home library and per-title history, derived from existing gBox records.

Catalog paging stays in SQLite. A short-lived, narrow metadata snapshot joins the
session archive, build index and character cache without walking ROM/model folders
or decoding the entire catalog. No media is fetched or gameplay started here.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import threading
import time
from collections import defaultdict
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query

TTL = 4.0
COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.~-]{0,159}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
ART_KIND = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
AGENTS = {'agent', 'mcp', 'gbox-agent', 'hermes'}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0 else 0


def _component(value):
    return isinstance(value, str) and bool(COMPONENT.fullmatch(value)) and value not in {'.', '..'}


def _file_url(slug, file):
    if not _component(slug) or not isinstance(file, str) or '\\' in file or ':' in file:
        return None
    parts = PurePosixPath(file).parts
    if not parts or file.startswith('/') or any(not _component(p) for p in parts):
        return None
    return '/api/characters/' + quote(slug, safe='') + '/file/' + '/'.join(quote(p, safe='') for p in parts)


def _artifact(value):
    return '/api/artifacts/' + value if isinstance(value, str) and SHA.fullmatch(value) else None


def _json(value, default=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return default if value is None or isinstance(value, str) else value


def _rows(store, kind, fields):
    """Project only explicitly selected metadata, never full job/attachment bodies."""
    columns = ','.join("json_extract(body,'$." + field + "')" for field in fields)
    with store.lock:
        rows = store.db.execute('SELECT id,' + columns + ' FROM docs WHERE kind=? ORDER BY rowid', (kind,)).fetchall()
    return [dict(zip(('id', *fields), row)) for row in rows]


class HomeData:
    def __init__(self, app, store, config):
        self.app, self.store, self.config = app, store, config
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = 0.0
        self.cached_generation = None
        self.art = {}
        self.attached_art = {}
        self.art_at = 0.0
        self.art_busy = False
        self.characters_at = 0.0
        self.characters_busy = False

    def _local_art(self):
        """Small attached-art index refreshed off the request thread; no library scan."""
        with self.lock:
            if not self.art_busy and time.monotonic() - self.art_at > TTL:
                self.art_busy = True
                threading.Thread(target=self._scan_art, name='home-attached-art', daemon=True).start()
            return self.art

    def cover_changed(self, gid, kind):
        """Publish a just-saved cover immediately, including during a directory scan."""
        with self.lock:
            kinds = self.attached_art.setdefault(gid, set())
            kinds.add(kind)
            self.art = self.art | {gid: self.art.get(gid, set()) | kinds}

    def _scan_art(self):
        out = {}
        try:
            with os.scandir(self.config.data_dir / 'art') as folders:
                for folder in folders:
                    if not _component(folder.name) or not folder.is_dir(follow_symlinks=False):
                        continue
                    kinds = set()
                    try:
                        with os.scandir(folder.path) as files:
                            for file in files:
                                stem, ext = os.path.splitext(file.name)
                                if ART_KIND.fullmatch(stem) and ext.lower() in IMAGE_EXT and file.is_file(follow_symlinks=False):
                                    kinds.add(stem)
                    except OSError:
                        continue
                    if kinds:
                        out[folder.name] = kinds
        except OSError:
            pass
        finally:
            with self.lock:
                for gid, kinds in self.attached_art.items():
                    out[gid] = out.get(gid, set()) | kinds
                self.art, self.art_at, self.art_busy = out, time.monotonic(), False

    def _characters(self):
        from . import characters
        root = characters.library_root(self.config)
        # list_all's first read can spend minutes on a sleeping HDD. Home always
        # serves the existing cache, warming it in the background if necessary.
        with characters._LIST_LOCK:
            cache = characters._LIST_CACHE.get(str(root))
            entries = list((cache or {}).get('entries', {}).values())
            loading = cache is None or bool(cache.get('refreshing'))
        # Reuse the library's existing mtime/TTL refresh logic off the request
        # path. New extraction folders from another worker then appear without
        # requiring the operator to open the old Models screen first.
        with self.lock:
            if not self.characters_busy and time.monotonic() - self.characters_at > TTL:
                self.characters_busy = True
                threading.Thread(target=self._refresh_characters, args=(root,), name='home-character-cache', daemon=True).start()
        out = defaultdict(list)
        for row in entries:
            source = row.get('source') if isinstance(row.get('source'), dict) else {}
            gid, slug, file = source.get('game_id'), row.get('slug'), row.get('model')
            url = _file_url(slug, file)
            if not _component(gid) or not row.get('name') or not url:
                continue
            stats = row.get('stats') if isinstance(row.get('stats'), dict) else {}
            out[gid].append({'slug': slug, 'name': row['name'], 'kind': row.get('kind') or 'character',
                'model_url': url, 'preview_url': f'/api/characters/{quote(slug, safe="")}/preview',
                'format': PurePosixPath(file).suffix.lstrip('.').lower(), 'model': file, 'file': file,
                'vertices': stats.get('vertices'), 'triangles': stats.get('triangles'),
                'source_game_id': gid, 'extracted_at': _number(row.get('added')) or None})
        return out, loading

    def _refresh_characters(self, root):
        from . import characters
        try:
            characters.list_all(root)
        finally:
            with self.lock:
                self.characters_at, self.characters_busy = time.monotonic(), False

    def _sessions(self):
        from .built_mods import session_build
        workers = {w['id']: w.get('name') for w in _rows(self.store, 'worker', ('name',))}
        aliases = {w['id']: w.get('name') for w in _rows(self.store, 'worker_alias', ('name',))}
        columns = ('session_id', 'game_id', 'started', 'ended', 'state', 'mod', 'collection_mod', 'live_mod',
                   'detail.worker_name', 'detail.capture_session', 'agent_use')
        labels = {w['id']: w.get('owner') for w in _rows(self.store, 'slabel', ('owner',))}
        # A native session ID is "worker-launchjob" (tools._launch_game).
        # Point-lookups avoid parsing every unrelated historical build/chat job.
        selected = ','.join("json_extract(s.body,'$." + field + "')" for field in columns)
        with self.store.lock:
            rows = self.store.db.execute('SELECT s.id,' + selected + ",json_extract(j.body,'$.agent_use'),json_extract(j.body,'$.actor') "
                "FROM docs s LEFT JOIN docs j ON j.kind='job' AND j.id=substr(s.id,instr(s.id,'-')+1) WHERE s.kind='session'").fetchall()
        grouped, sessions = defaultdict(list), {}
        for raw in rows:
            row = dict(zip(('id', *columns), raw[:-2]))
            sid, gid = row.get('session_id') or row['id'], row.get('game_id')
            if not _component(gid) or not sid:
                continue
            worker_id = sid.partition('-')[0]
            owner = labels.get(sid)
            agent = bool(row.get('detail.capture_session')) or bool(row.get('agent_use')) or (
                owner != 'you' and (owner == 'agent' or bool(raw[-2]) or raw[-1] in AGENTS))
            value = {'session_id': sid, 'started': _number(row.get('started')) or None,
                'ended': _number(row.get('ended')) or None, 'state': row.get('state') or 'unknown',
                'device': row.get('detail.worker_name') or workers.get(worker_id) or aliases.get(worker_id) or worker_id,
                'mod': session_build(row), 'agent_use': agent}
            grouped[gid].append(value)
            sessions[sid] = gid
        for rows in grouped.values():
            rows.sort(key=lambda s: s['started'] or 0, reverse=True)
        return grouped, sessions

    def _builds(self):
        from . import built_mods as B
        index = getattr(self.app.state, 'built_mods', None)
        records = index.records() if index else []  # memory only: never B.scan()
        cards = {}
        fields = ('game_id', 'game_title', 'title', 'ts', 'verified', 'thumb', 'shots', 'video', 'calls')
        for card in _rows(self.store, 'mod', fields):
            card['calls'] = _json(card.get('calls'), [])
            name = B.card_mod(card)
            if _component(card.get('game_id')) and _component(name):
                cards[(card['game_id'], name)] = card
        entries, devices, device_seen = {}, defaultdict(set), {}
        for worker in _rows(self.store, 'worker', ('name', 'local_builds', 'last_seen')):
            device_name = worker.get('name') or worker['id']
            device_seen[device_name] = max(device_seen.get(device_name, 0), _number(worker.get('last_seen')))
            for build in _json(worker.get('local_builds'), []) or []:
                if not isinstance(build, dict):
                    continue
                staged = build.get('staged_of')
                gid = build.get('game_id')
                name = staged if isinstance(staged, str) else str(build.get('name') or '').split('~', 1)[0]
                if _component(gid) and _component(name):
                    devices[(gid, name)].add(device_name)
                    entries.setdefault((gid, name), {'game_id': gid, 'name': name, 'meta': {'built': build.get('built')}})
        for record in records:
            if _component(record.get('game_id')) and _component(record.get('name')):
                key = (record['game_id'], record['name'])
                entries[key] = record
                devices[key].add('Spark collection')
        for key in cards:
            entries.setdefault(key, {'game_id': key[0], 'name': key[1], 'meta': {}})
        names = {r['id']: r.get('display_name') for r in _rows(self.store, 'build_name', ('display_name',))}
        out = defaultdict(list)
        for (gid, name), record in entries.items():
            card, meta = cards.get((gid, name), {}), record.get('meta') or {}
            images = []
            for path in record.get('images') or []:
                if isinstance(path, str) and not path.startswith('/') and '\\' not in path and ':' not in path and all(_component(p) for p in path.split('/')):
                    images.append({'url': f'/api/mods/built/{gid}/{quote(name, safe="")}/image/' + quote(path, safe='/'), 'label': PurePosixPath(path).name})
            shots = [{'url': url, 'sha256': s} for s in [card.get('thumb'), *(_json(card.get('shots'), []) or [])] if (url := _artifact(s))]
            changes = [{key: str(change[key])[:400] for key in ('slot', 'donor', 'status') if change.get(key) is not None}
                       for change in B.changes_of(meta)[:200] if isinstance(change, dict)]
            donor_previews = []
            for preview in record.get('donor_previews') or []:
                if isinstance(preview, dict) and _component(preview.get('slug')):
                    url = f'/api/characters/{quote(preview["slug"], safe="")}/preview'
                    if preview.get('url') == url:
                        donor_previews.append({'slug': preview['slug'], 'url': url})
            available_on = sorted(devices[(gid, name)])
            launch_node = 'auto' if 'Spark collection' in available_on else next(iter(sorted(
                available_on, key=lambda node: (-device_seen.get(node, 0), node))), None)
            out[gid].append({'name': name, 'title': names.get(f'{gid}/{name}') or card.get('title') or meta.get('title') or name,
                'game_title': card.get('game_title') or meta.get('game_title') or '',
                'built': _number(meta.get('built')) or _number(record.get('marker_mtime')) or _number(card.get('ts')) or None,
                'verified': B.verified_of(meta, card), 'writer': B.writer_of(meta, name), 'changes': changes,
                'images': images[:24], 'shots': shots[:24], 'video': _artifact(card.get('video')),
                'size': record.get('size'), 'available_on': available_on, 'launch_node': launch_node,
                'donor_previews': donor_previews[:24],
                'available': bool(devices[(gid, name)]), 'card_id': card.get('id') or '',
                'tickets': B.tickets_of(meta, card)})
        for rows in out.values():
            rows.sort(key=lambda row: row['built'] or 0, reverse=True)
        return out, bool(index and index.status().get('indexing'))

    def _reports(self, builds):
        tickets = defaultdict(set)
        for gid, rows in builds.items():
            for row in rows:
                for number in row['tickets']:
                    tickets[number].add(gid)
        grouped = defaultdict(list)
        for row in _rows(self.store, 'request', ('number', 'title', 'status', 'created', 'updated', 'completed', 'context.game_id', 'context.hermes_favorite_game')):
            gids = tickets.get(row.get('number'), set()).copy()
            gids.update(g for key in ('context.game_id', 'context.hermes_favorite_game') if _component(g := row.get(key)))
            public = {key: row.get(key) for key in ('id', 'number', 'title', 'status', 'created')}
            public['updated'] = max(_number(row.get(key)) for key in ('created', 'updated', 'completed')) or None
            for gid in gids:
                grouped[gid].append(public)
        for rows in grouped.values():
            rows.sort(key=lambda row: row['updated'] or 0, reverse=True)
        return grouped

    def _media(self):
        # Partition by title AND type so a frame-heavy session never hides its
        # recordings. SQLite discards unrelated binary/trace metadata first.
        with self.store.lock:
            rows = self.store.db.execute("""
                WITH media AS (
                    SELECT a.rowid AS seq,json_extract(a.body,'$.sha256') AS sha,
                      json_extract(a.body,'$.media_type') AS media_type,
                      COALESCE(NULLIF(json_extract(a.body,'$.provenance.game_id'),''),
                               NULLIF(json_extract(a.body,'$.provenance.game'),''),json_extract(s.body,'$.game_id')) AS gid,
                      COALESCE(json_extract(a.body,'$.provenance.ts'),json_extract(a.body,'$.provenance.captured'),
                               json_extract(s.body,'$.started')) AS ts
                    FROM docs a LEFT JOIN docs s ON s.kind='session' AND s.id=COALESCE(
                      json_extract(a.body,'$.provenance.session'),json_extract(a.body,'$.provenance.session_id'))
                    WHERE a.kind='artifact' AND (json_extract(a.body,'$.media_type') LIKE 'image/%'
                      OR json_extract(a.body,'$.media_type') LIKE 'video/%')
                      AND COALESCE(CAST(json_extract(a.body,'$.provenance.covered') AS REAL),0)=0
                ), ranked AS (
                    SELECT *,ROW_NUMBER() OVER(PARTITION BY gid,media_type LIKE 'video/%' ORDER BY seq DESC) AS pos
                    FROM media WHERE gid IS NOT NULL
                ) SELECT sha,media_type,gid,ts FROM ranked WHERE pos<=12 ORDER BY seq DESC
            """).fetchall()
        grouped = defaultdict(list)
        for digest, content_type, gid, ts in rows:
            url = _artifact(digest)
            if not _component(gid) or not url:
                continue
            video = content_type.startswith('video/')
            grouped[gid].append({'kind': 'video' if video else 'image', 'url': url,
                'label': 'Captured gameplay' if video else 'Captured screenshot / mod preview',
                'source': 'capture', 'media_type': content_type, 'ts': _number(ts) or None})
        return grouped

    def snapshot(self):
        from . import characters
        index = getattr(self.app.state, 'built_mods', None)
        generation = (characters.LIST_GENERATION, getattr(index, 'version', 0))
        # Different lock from art refresh: character warmup never waits on Home.
        with self.lock:
            if self.cached is not None and self.cached_generation == generation and time.monotonic() - self.cached_at < TTL:
                return self.cached
        models, models_loading = self._characters()
        builds, builds_loading = self._builds()
        sessions, by_sid = self._sessions()
        reports, media = self._reports(builds), self._media()
        stats = {}
        for gid in set(models) | set(builds) | set(sessions) | set(reports):
            played = [s for s in sessions[gid] if not s['agent_use'] and s['started'] and s['state'] in ('running', 'paused', 'ended', 'stopped', 'completed')]
            devices = {}
            for session in played:
                device = devices.setdefault(session['device'], {'name': session['device'], 'plays': 0, 'last_played': 0})
                device['plays'] += 1
                device['last_played'] = max(device['last_played'], session['started'])
            stats[gid] = {'plays': len(played), 'last_played': max((s['started'] for s in played), default=0),
                'last_device': played[0]['device'] if played else None,
                'devices': sorted(devices.values(), key=lambda d: -d['last_played']),
                'models_count': len(models[gid]), 'mods_count': len(builds[gid]), 'reports_count': len(reports[gid]),
                'updated': max([0, *(_number(s['ended']) or _number(s['started']) for s in sessions[gid]),
                    *(_number(m['extracted_at']) for m in models[gid]), *(_number(b['built']) for b in builds[gid]),
                    *(_number(r['updated']) for r in reports[gid])])}
        with self.store.lock:
            platforms = self.store.db.execute('SELECT platform,COUNT(*) FROM catalog GROUP BY platform ORDER BY platform').fetchall()
        result = {'stats': stats, 'models': models, 'builds': builds, 'reports': reports, 'sessions': sessions,
                  'by_sid': by_sid, 'media': media, 'indexing': models_loading or builds_loading,
                  'platforms': [{'platform': p or '', 'count': n} for p, n in platforms]}
        with self.lock:
            self.cached, self.cached_at, self.cached_generation = result, time.monotonic(), generation
        return result

    def game(self, row, snapshot, local_art):
        gid = row['game_id']
        stats = snapshot['stats'].get(gid, {})
        last_played = max(_number(row.get('last_played')), _number(stats.get('last_played'))) or None
        kinds = {k for k, values in (row.get('media') or {}).items() if ART_KIND.fullmatch(k) and values}
        kinds.update(local_art.get(gid, set()))
        # Library video stems use a different codec/media resolver. Only captured
        # artifact video is exposed; /api/media is the existing image-only route.
        kinds -= {'video', 'videos', 'movie', 'movies'}
        order = {'snap': 0, 'fanart': 1, 'poster': 2, 'flyer': 3, 'cabinet': 4, 'boxart': 5, 'wheel': 6, 'cartart': 7}
        art = [{'kind': 'image', 'url': f'/api/media/{quote(gid, safe="")}/{kind}', 'label': kind.replace('_', ' ').title(), 'source': 'art'}
               for kind in sorted(kinds, key=lambda k: (order.get(k, 8), k))]
        public = {key: row.get(key) for key in ('game_id', 'title', 'platform', 'system', 'year', 'manufacturer', 'category', 'players', 'region', 'playable')}
        return public | {'favorite': bool(row.get('favorite')), 'last_played': last_played,
            'plays': stats.get('plays', 0), 'last_device': stats.get('last_device'), 'devices': stats.get('devices', []),
            'models_count': stats.get('models_count', 0), 'mods_count': stats.get('mods_count', 0), 'reports_count': stats.get('reports_count', 0),
            'updated': max(_number(stats.get('updated')), last_played or 0) or None,
            'poster_url': f'/api/media/{quote(gid, safe="")}/best?w=360', 'media': art + snapshot['media'].get(gid, [])}

    def games(self, q='', sort='recent', favorites=False, has_mods=False, platform='', limit=60, offset=0):
        snapshot, art = self.snapshot(), self._local_art()
        args, clauses = [json.dumps(snapshot['stats'], separators=(',', ':'))], []
        if q.strip():
            terms = ' '.join('"' + word.replace('"', '') + '"*' for word in q.split() if word.replace('"', ''))
            if terms:
                clauses.append('c.rowid IN (SELECT rowid FROM catalog_fts WHERE catalog_fts MATCH ?)')
                args.append(terms)
        if favorites:
            clauses.append("json_extract(c.body,'$.favorite')=1")
        if has_mods:
            clauses.append("COALESCE(json_extract(h.value,'$.mods_count'),0)>0")
        if platform:
            clauses.append('c.platform=?')
            args.append(platform)
        recent = "MAX(COALESCE(json_extract(c.body,'$.last_played'),0),COALESCE(json_extract(h.value,'$.last_played'),0))"
        ordering = {'recent': recent + ' DESC', 'title': 'c.title COLLATE NOCASE',
                    'plays': "COALESCE(json_extract(h.value,'$.plays'),0) DESC",
                    'updated': "MAX(COALESCE(json_extract(h.value,'$.updated'),0)," + recent + ') DESC'}
        # Materialization lets SQLite index the small metadata relation. Joining
        # directly to the json_each virtual table is quadratic on a large library.
        cte = 'WITH home_stats AS MATERIALIZED (SELECT key,value FROM json_each(?)) '
        base = 'FROM catalog c LEFT JOIN home_stats h ON h.key=c.game_id' + (' WHERE ' + ' AND '.join(clauses) if clauses else '')
        with self.store.lock:
            total = self.store.db.execute(cte + 'SELECT COUNT(*) ' + base, args).fetchone()[0]
            rows = self.store.db.execute(cte + 'SELECT c.body ' + base + ' ORDER BY ' + ordering[sort] + ',c.title COLLATE NOCASE,c.game_id LIMIT ? OFFSET ?', args + [limit, offset]).fetchall()
        return {'total': total, 'offset': offset, 'limit': limit, 'has_more': offset + len(rows) < total,
            'items': [self.game(json.loads(row[0]), snapshot, art) for row in rows],
            'platforms': snapshot['platforms'], 'indexing': snapshot['indexing']}

    def mods(self, q='', sort='recent', favorites=False, platform='', limit=60, offset=0):
        """Individual playable build cards, newest build first, across every node.

        Historical cards whose files are no longer indexed stay in title history.
        Only small catalog headers are read to filter/sort; full catalog rows are
        decoded after paging, once per selected title rather than per build.
        """
        snapshot, art = self.snapshot(), self._local_art()
        available = [(gid, build) for gid, builds in snapshot['builds'].items()
                     for build in builds if build['available']]
        gids = sorted({gid for gid, _ in available})
        with self.store.lock:
            headers = self.store.db.execute("SELECT game_id,title,platform,system,json_extract(body,'$.favorite') "
                "FROM catalog WHERE game_id IN (SELECT value FROM json_each(?))", (json.dumps(gids),)).fetchall()
        catalog = {gid: {'game_id': gid, 'title': title, 'platform': plat, 'system': system, 'favorite': bool(favorite)}
                   for gid, title, plat, system, favorite in headers}
        sessions = defaultdict(list)
        for gid in gids:
            for session in snapshot['sessions'].get(gid, []):
                if not session['agent_use'] and session['started'] and session['state'] in ('running', 'paused', 'ended', 'stopped', 'completed'):
                    sessions[(gid, session['mod'])].append(session)
        words = q.casefold().split()
        platforms, selected = defaultdict(int), []
        for gid, build in available:
            header = catalog.get(gid, {'game_id': gid, 'title': build.get('game_title') or gid, 'platform': '', 'favorite': False})
            platforms[header.get('platform') or ''] += 1
            haystack = ' '.join(str(value or '') for value in (build['title'], build['name'], header['title'])).casefold()
            if (favorites and not header['favorite']) or (platform and header.get('platform') != platform) or not all(word in haystack for word in words):
                continue
            played = sessions[(gid, build['name'])]
            selected.append((gid, build, header, played))
        if sort == 'title':
            selected.sort(key=lambda row: (row[1]['title'].casefold(), row[2]['title'].casefold(), row[0], row[1]['name']))
        elif sort == 'plays':
            selected.sort(key=lambda row: (-len(row[3]), -_number(row[1]['built']), row[0], row[1]['name']))
        else:  # Both recent and updated refer to build creation, not base-title recency.
            selected.sort(key=lambda row: (-_number(row[1]['built']), row[0], row[1]['name']))
        total, page, rows, decoded = len(selected), selected[offset:offset + limit], [], {}
        known_models = {model['slug']: model for models in snapshot['models'].values() for model in models}
        for gid, build, header, played in page:
            if gid not in decoded:
                decoded[gid] = self.store.catalog_get(gid) or header
            base = self.game(decoded[gid], snapshot, art)
            media, seen = [], set()

            def add(kind, url, label, source):
                if url and url not in seen:
                    seen.add(url)
                    media.append({'kind': kind, 'url': url, 'label': label, 'source': source, 'ts': build['built']})

            for image in build['images'] + build['shots']:
                add('image', image['url'], build['title'], 'build')
            add('video', build['video'], build['title'], 'capture')
            for preview in build['donor_previews']:
                add('image', preview['url'], preview['slug'], 'model')
            for change in build['changes']:
                for slug in str(change.get('donor') or '').split(','):
                    model = known_models.get(slug.strip())
                    if model:
                        add('image', model['preview_url'], model['name'], 'model')
            # Parent artwork is relevant; captures of another build are not.
            for image in base['media']:
                if image['source'] == 'art':
                    add('image', image['url'], image['label'], 'art')
            devices = {}
            for session in played:
                device = devices.setdefault(session['device'], {'name': session['device'], 'plays': 0, 'last_played': 0})
                device['plays'] += 1
                device['last_played'] = max(device['last_played'], session['started'])
            last = max(played, key=lambda session: session['started'], default=None)
            rows.append(base | {'key': gid + '/' + build['name'], 'is_mod': True, 'mod_name': build['name'],
                'game_title': base['title'], 'title': build['title'], 'built': build['built'], 'updated': build['built'],
                'plays': len(played), 'last_played': last['started'] if last else None,
                'last_device': last['device'] if last else None,
                'devices': sorted(devices.values(), key=lambda device: -device['last_played']),
                'poster_url': next((item['url'] for item in media if item['kind'] == 'image'), base['poster_url']),
                'media': media[:100], 'mods_count': 0, 'available': True, 'available_on': build['available_on'],
                'launch_node': build['launch_node'] or 'auto', 'verified': build['verified'], 'writer': build['writer'],
                'size': build['size'], 'changes': build['changes'], 'images': build['images'], 'shots': build['shots'],
                'card_id': build['card_id']})
        return {'total': total, 'offset': offset, 'limit': limit, 'has_more': offset + len(page) < total,
                'items': rows, 'platforms': [{'platform': key, 'count': count} for key, count in sorted(platforms.items())],
                'indexing': snapshot['indexing'], 'feed': 'mods'}

    def detail(self, gid):
        row = self.store.catalog_get(gid)
        if row is None:
            raise HTTPException(404, 'Unknown game')
        snapshot = self.snapshot()
        game = self.game(row, snapshot, self._local_art())
        models = snapshot['models'].get(gid, [])
        builds = snapshot['builds'].get(gid, [])
        reports = snapshot['reports'].get(gid, [])
        activity = snapshot['sessions'].get(gid, [])
        timeline = []
        for kind, rows, ts_key, title_key, ref_key in (
            ('model', models, 'extracted_at', 'name', 'slug'), ('build', builds, 'built', 'title', 'name'),
            ('report', reports, 'created', 'title', 'id')):
            timeline += [{'kind': kind, 'ts': item[ts_key], 'title': item[title_key], 'ref': item[ref_key],
                          'state': item.get('status') or ('verified' if item.get('verified') else '')}
                         for item in rows if item.get(ts_key)]
        timeline += [{'kind': 'session', 'ts': s['started'], 'title': ('Automated session' if s['agent_use'] else 'Played') + ' on ' + s['device'],
                      'ref': s['session_id'], 'state': s['state']} for s in activity if s['started']]
        timeline.sort(key=lambda item: item['ts'], reverse=True)
        with self.store.lock:
            jobs = self.store.db.execute("SELECT id,json_extract(body,'$.tool'),json_extract(body,'$.state'),"
                "json_extract(body,'$.created'),json_extract(body,'$.started'),json_extract(body,'$.progress.pct'),"
                "json_extract(body,'$.input.game_id'),json_extract(body,'$.input.game'),json_extract(body,'$.input.session_id') "
                "FROM docs INDEXED BY docs_queued_jobs WHERE kind='job' AND json_extract(body,'$.state') IN ('queued','running') "
                "AND (json_extract(body,'$.input.game_id')=? OR json_extract(body,'$.input.game')=? OR "
                "json_extract(body,'$.input.session_id') IN (SELECT id FROM docs WHERE kind='session' AND json_extract(body,'$.game_id')=?)) "
                "ORDER BY rowid DESC LIMIT 20", (gid, gid, gid)).fetchall()
        active = [{'id': j[0], 'tool': j[1], 'state': j[2], 'created': j[3], 'started': j[4],
                   'progress': min(100, max(0, j[5])) if isinstance(j[5], (int, float)) and math.isfinite(j[5]) else None,
                   'stage': (j[1] or 'Task') + ' · ' + j[2]}
                  for j in jobs if j[6] == gid or j[7] == gid or snapshot['by_sid'].get(j[8]) == gid]
        visual = next((m for m in models if m['format'] in ('glb', 'gltf')), None)
        media = list(game['media'])
        known = {item['url'] for item in media}
        for build in builds:
            for item in build['images'] + build['shots']:
                if item['url'] not in known:
                    known.add(item['url'])
                    media.append({'kind': 'image', 'url': item['url'], 'label': build['title'], 'source': 'build', 'ts': build['built']})
            if build['video'] and build['video'] not in known:
                known.add(build['video'])
                media.append({'kind': 'video', 'url': build['video'], 'label': build['title'], 'source': 'capture', 'ts': build['built']})
        return {'game': game, 'models': copy.deepcopy(models[:200]), 'builds': copy.deepcopy(builds[:200]),
            'reports': reports[:30], 'activity': activity[:50], 'timeline': timeline[:150], 'media': media[:100],
            'counts': {'models': len(models), 'builds': len(builds), 'reports': len(reports), 'sessions': len(activity)},
            'progress': {'status': 'running' if any(j['state'] == 'running' for j in active) else 'queued' if active else 'idle',
                         'active_jobs': active[:20], 'model_url': visual['model_url'] if visual else None},
            'indexing': snapshot['indexing']}


def routes(app, store, config, auth):
    data = HomeData(app, store, config)
    app.state.library_home = data

    @app.get('/api/home/games')
    def home_games(q: str = Query('', max_length=300), sort: str = Query('recent', pattern='^(recent|title|plays|updated)$'),
                   favorites: bool = False, has_mods: bool = False, platform: str = Query('', max_length=120),
                   limit: int = Query(60, ge=1, le=120), offset: int = Query(0, ge=0), actor=Depends(auth)):
        return data.games(q, sort, favorites, has_mods, platform, limit, offset)

    @app.get('/api/home/mods')
    def home_mods(q: str = Query('', max_length=300), sort: str = Query('recent', pattern='^(recent|title|plays|updated)$'),
                  favorites: bool = False, platform: str = Query('', max_length=120),
                  limit: int = Query(60, ge=1, le=120), offset: int = Query(0, ge=0), actor=Depends(auth)):
        return data.mods(q, sort, favorites, platform, limit, offset)

    @app.get('/api/home/games/{gid}')
    def home_detail(gid: str, actor=Depends(auth)):
        if not _component(gid):
            raise HTTPException(404, 'Unknown game')
        return data.detail(gid)
