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
        return record

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
                              'require_os': 'linux',
                              'parent_request_id': parent_request_id or policy.get('parent_request_id')})
            self.store.put('character_collection', gid, {'state': created['state'], 'job_id': created['id'],
                           'updated': time.time(), 'session_id': session_id})

    def after_launch(self, job, output, submit):
        # LaunchOut deliberately carries only game_id/title; platform comes from the validated launch input.
        game = (job.get('input', {}).get('game') or {}) | ((output.get('detail') or {}).get('_game') or {})
        self._schedule(game, job.get('parent_request_id'), output.get('session_id'), submit)

    def after_favorite(self, game, submit):
        """A favorite starts native roster collection without starting or interrupting the game."""
        self._schedule(game, None, None, submit, retry_failed=True)
