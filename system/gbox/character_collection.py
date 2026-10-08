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

    def after_launch(self, job, output, submit):
        policy = self.policy()
        if not policy.get('enabled'):
            return
        # LaunchOut deliberately carries only game_id/title; platform comes from the validated launch input.
        game = (job.get('input', {}).get('game') or {}) | ((output.get('detail') or {}).get('_game') or {})
        gid = game.get('game_id')
        if not gid:
            return
        with self.lock:
            previous = self.status(gid)
            # Failed/partial jobs remain visible and require explicit retry, rather than repeating expensive work.
            supported = any(test((game.get('title') or '').lower(), game.get('platform')) for _, test, _, _ in C.DEDICATED)
            if previous['state'] != 'not_started' and not (previous['state'] == 'unsupported' and supported):
                return
            if not supported:
                self.store.put('character_collection', gid, {'state': 'unsupported', 'updated': time.time(),
                               'message': 'No native model reader registered for this game.'})
                return
            created = submit({'tool': 'characters', 'input': {'op': 'collect', 'game_id': gid},
                              'require_os': 'linux',
                              'parent_request_id': job.get('parent_request_id') or policy.get('parent_request_id')})
            self.store.put('character_collection', gid, {'state': created['state'], 'job_id': created['id'],
                           'updated': time.time(), 'session_id': output.get('session_id')})
