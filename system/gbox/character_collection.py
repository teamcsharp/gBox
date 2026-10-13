"""One background roster job per game; collection never creates a top-level inbox request."""
import threading
import time

from . import characters as C


class AutoCollection:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.lock = threading.RLock()

    def policy(self):
        return self.store.get('setting', 'auto_character_collection') or {'enabled': True, 'parent_request_id': None}

    def status(self, gid):
        record = self.store.get('character_collection', gid) or {'state': 'not_started'}
        if record.get('job_id'):
            job = self.store.get('job', record['job_id']) or {}
            record = record | {'state': job.get('state', 'not_started'),
                               'result': (job.get('output') or {}).get('result'), 'error': job.get('error')}
            result = record['result'] or {}
            # A partial roster is re-checked against the collection as it is now (roles backfilled by a fixed reader,
            # #1485) instead of re-queueing the job on every launch; the stored job output stays as it was.
            if result.get('status') == 'partial' and self.config is not None:
                root = C.library_root(self.config)
                if root.is_dir():
                    try:
                        record['result'] = C.refresh_collection(root, result)
                    except Exception:                       # a status read never fails on a bad entry
                        pass
        capability = self.store.get('game_capability', gid)
        if capability:
            record = record | {'capabilities': capability, 'backlog': self.store.get('capability_backlog', gid) or []}
        return record

    def track(self, game, entries=None):
        """Persist scoped capability gaps without inventing completion or inbox jobs."""
        from . import char_coverage as CC, game_capabilities as GC
        if not game.get('game_id'):
            return None
        if entries is None:
            entries = C.list_all(C.library_root(self.config))
        ex, roster = CC.extractor_for(game)
        evidence = self.store.get('game_capability_evidence', game['game_id']) or {}
        row = GC.describe(game, entries, extractor=ex, roster=roster, writer=CC.writer_for(game), evidence=evidence)
        row['captured_at'] = time.time()
        tasks = GC.backlog(row)
        with self.lock:
            self.store.put('game_capability', game['game_id'], row)
            self.store.put('capability_backlog', game['game_id'], tasks)
        return row

    def scan_favorites(self, submit=None, *, schedule=False, retry_failed=False):
        """Unfiltered local catalog scan; optional registered collection never launches."""
        from .favorite_capabilities import paginate_favorites
        def page(params):
            total, items = self.store.search(**params)
            return {'total': total, 'offset': params['offset'], 'items': items}
        games, catalog = paginate_favorites(page)
        entries = C.list_all(C.library_root(self.config))
        rows = [self.track(game, entries) for game in games]
        if schedule and catalog['pagination_complete']:
            if submit is None:
                raise ValueError('submit is required when scheduling registered collection')
            for game in games:
                self._schedule(game, None, None, submit, retry_failed=retry_failed)
        return {'catalog': catalog, 'games': rows,
                'backlog': [task for game in games for task in self.store.get('capability_backlog', game['game_id']) or []],
                'collection': {game['game_id']: self.status(game['game_id']) for game in games},
                'queue_scope': 'Registered roster subset only; full source, stages, reimport and unlocks require separate evidence.'}

    def _schedule(self, game, parent_request_id, session_id, submit, retry_failed=False):
        policy = self.policy()
        if not policy.get('enabled'):
            return
        gid = game.get('game_id')
        if not gid:
            return
        with self.lock:
            previous = self.status(gid)
            # A favorite action explicitly retries failed work; launches never repeat expensive failures.
            supported = any(test((game.get('title') or '').lower(), game.get('platform')) for _, test, _, _ in C.DEDICATED)
            if previous['state'] != 'not_started' and not (previous['state'] == 'unsupported' and supported) and not (retry_failed and previous['state'] == 'failed'):
                return
            if not supported:
                self.store.put('character_collection', gid, {'state': 'unsupported', 'updated': time.time(),
                               'message': 'No native model reader registered for this game.'})
                return
            created = submit({'tool': 'characters', 'input': {'op': 'collect', 'game_id': gid},
                              'require_os': 'linux', 'agent_use': True,
                              'parent_request_id': parent_request_id or policy.get('parent_request_id')})
            self.store.put('character_collection', gid, {'state': created['state'], 'job_id': created['id'],
                           'updated': time.time(), 'session_id': session_id})

    def after_launch(self, job, output, submit):
        # LaunchOut deliberately carries only game_id/title; platform comes from the validated launch input.
        game = (job.get('input', {}).get('game') or {}) | ((output.get('detail') or {}).get('_game') or {})
        self._schedule(game, job.get('parent_request_id'), output.get('session_id'), submit)

    def after_favorite(self, game, submit):
        """A favorite starts native roster collection without starting or interrupting the game."""
        self.track(game | {'favorite': True})
        self._schedule(game, None, None, submit, retry_failed=True)
