"""RE6 recovery episodes: flash during a QTE, native grant, escape and mines.

The native job never owns the pad. Its result can request the existing mine lane;
movement continues through the bot's escape planner while the controller runs.
"""
import threading
import time
import uuid


class Recovery:
    def __init__(self, ad, submit=None, fire=None, clock=time.monotonic):
        self.ad = ad
        self.submit = submit or (lambda fn: threading.Thread(target=fn, daemon=True, name='re6-qte-cover').start())
        self.fire = fire or self._fire
        self.clock = clock
        self.observed_at = -1e20
        self.key = self.episode = None
        self.valid = False
        self.held = False
        self.now = 0
        self.last_flash = -1e20

    def _fire(self, expected, allowed):
        from .interventions import native_controller
        ctl = native_controller(self.ad)
        with ctl.lock:
            if not allowed() or ctl.ready() != expected:
                return {'state': 'unavailable', 'reason': 'QTE recovery life changed or request expired'}
            return ctl.grenade_ring('flash', count=8, radius_cm=600, inner_cm=400, expand=False, ripple_ms=0)

    def observe(self, snap, stats, now, grants=0, *, playing=True):
        from .titles import re6_switch as R
        p = snap.get('player') or {}
        key = (stats.get('round_evidence_id'), p.get('ptr'), p.get('generation'))
        if key != self.key:
            self.key, self.episode = key, None
            stats['qte_escape_active'] = False
            stats.pop('qte_escape_mines_due', None)
            stats.pop('qte_escape_flash_at', None)
        self.now = now
        self.observed_at = self.clock()
        self.held = p.get('state') in R.HELD_STATES
        self.valid = bool(playing and p.get('ptr') and p.get('generation') is not None and
                          (p.get('hp') or 0) > 0 and not stats.get('operator_control'))
        if not self.valid:
            self.episode = None
            stats['qte_escape_active'] = False
            stats.pop('qte_escape_mines_due', None)
            return
        if self.held:
            stats.pop('qte_escape_mines_due', None)
            if self.episode is None or self.episode.get('released_at') is not None:
                self.episode = {'id': uuid.uuid4().hex, 'grant': False, 'released_at': None}
            self.episode['grant'] |= grants > 0
            self.episode['released_at'] = None
            stats['qte_escape_active'] = False
            self._dispatch(stats, now, key, self.episode)
            return
        episode = self.episode
        if episode and episode.get('released_at') is not None and now - episode['released_at'] >= 3:
            stats['qte_escape_active'] = False
            stats.pop('qte_escape_mines_due', None)
            self.episode = None
            return
        if grants > 0 and episode is None:
            episode = self.episode = {'id': uuid.uuid4().hex, 'grant': True, 'released_at': None}
            self._dispatch(stats, now, key, episode)
        if episode and not episode['grant']:
            self.episode = None
            return
        if not episode or not episode['grant'] or episode.get('released'):
            return
        stats['qte_escape_active'] = True
        if episode['released_at'] is None:
            episode['released_at'] = now
            return
        if now - episode['released_at'] < .1:
            return
        episode['released'] = True
        stats['qte_escapes_observed'] = stats.get('qte_escapes_observed', 0) + 1
        stats['qte_escape_episode'] = episode['id']
        if episode.get('flash_confirmed') is not None and now - episode['flash_confirmed'] <= 5:
            stats['qte_escape_mines_due'] = episode['id']
        self._dispatch(stats, now, key, episode)

    def _dispatch(self, stats, now, key, episode):
        if episode.get('dispatched'):
            return
        episode['dispatched'] = True  # reserve once per QTE, including while held
        self.last_flash = now
        started = self.clock()
        stats['qte_escape_flash'] = {'state': 'requested', 'episode': episode['id']}

        def allowed():
            return (self.key == key and self.episode is episode and self.valid
                    and self.clock() - started < 5 and self.clock() - self.observed_at <= .75)

        def run():
            try:
                result = self.fire((key[1], key[2]), allowed) if allowed() else {'state': 'expired'}
            except Exception as exc:
                result = {'state': 'uncertain', 'reason': str(exc)[:200]}
            if not allowed():
                return
            stats['qte_escape_flash'] = {**result, 'episode': episode['id']}
            if result.get('state') == 'confirmed' and result.get('verified') is True:
                episode['flash_confirmed'] = self.now
                stats['qte_escape_flash_at'] = self.now
                if episode.get('released') and not self.held:
                    stats['qte_escape_mines_due'] = episode['id']
                stats['native_flash_confirmed_at'] = time.time()
        self.submit(run)
