"""Prepare an exact MercMode session without pausing its shader/loading work.

The launch worker returns immediately. A bounded observer waits for a stable,
native title/menu state before pausing; it sends no controller input or writes.
The session pump publishes the receipt independently of this observer.

A second, later step (gbox.tools autoplay op=prepare, RoundPrepare below) drives the
paused title's own menus to the start of a round in the background and pauses it
again right there, so the MercMode switch lands in gameplay (operator 2026-10-26:
"continue playing a round of mercenaries while the next session is loading and
preparing in the background so the swap is seamless"). Its receipt replaces this
observer's in the session detail: source "native_round", prepared true/false.
"""
from __future__ import annotations

import threading
import time

TIMEOUT_S, POLL_S, STABLE_S = 600., .5, 1.
RE4_IDS = frozenset({'78ab9efa2e310db4', 'e42c9b780c07c437'})
RE5_ID = 'e7ca89bbeb67360d'
ROUND_SOURCE = 'native_round'      # receipt source of a round preparation (the menu observer's is 'native_menu')


def _confirmed_pause(result) -> bool:
    return isinstance(result, dict) and (result.get('paused') is True or result.get('halted') is True
                                         or result.get('state') == 'PAUSED' and result.get('threads', 1) > 0)


def _confirmed_resume(result) -> bool:
    return isinstance(result, dict) and (result.get('paused') is False or result.get('halted') is False
                                         or result.get('state') in ('PLAYING', 'RUNNING'))


def native_probe(adapter, game):
    """Use measured readers only; guest mappings and process life are not ready."""
    from .. import mercs_bot
    memory = None

    def probe():
        nonlocal memory
        re4 = game.get('game_id') in RE4_IDS and game.get('platform') == 'gamecube'
        re5 = game.get('game_id') == RE5_ID and game.get('platform') == 'ps3'
        if not re4 and not re5:
            return {'ready': False, 'unsupported': True, 'screen': 'unknown',
                    'reason': 'No verified native warm-readiness reader for this exact game/platform.'}
        if memory is None:
            memory = mercs_bot._memory(adapter)
        if re4:
            from .. import re4_menus as menus
            # screen() also checks these signatures, but caches a success on
            # its memory view. Recheck while preparing so changed live code
            # cannot inherit an earlier match or a catalog region label.
            if any(memory.rd(address, len(code)) != code for address, code in menus.SIGNATURES.items()):
                return {'ready': False, 'screen': 'unknown', 'title': 'G4BE08'}
            state = menus.screen(memory)
            where = state.get('where')
            ready = where in {'title', 'press_start', 'main_menu', 'extra_menu', 'select_player', 'select_stage'}
            return {'ready': ready, 'screen': where, 'title': 'G4BE08',
                    'token': (where, state.get('title_routine'), state.get('title_step'))}
        if re5:
            from .titles import re5_ps3 as menus
            # These unchanged instruction bytes pin the UI reader to BLUS30491
            # 01.01. Avoid screen(), which also changes the global roster plan.
            if any(memory.rd(address, len(code)) != code for address, code in menus.CONTINUE_CODE):
                return {'ready': False, 'screen': 'unknown', 'title': 'BLUS30491'}
            units = menus.ui_units(memory, range(menus.N_LINES))
            if units.keys() & {'uIdNowLoading00', 'uIdSaving00'}:
                return {'ready': False, 'screen': 'loading', 'title': 'BLUS30491'}
            names = {'uIdStartUp00': 'main_menu', 'uIdStartUp01': 'play_game',
                     'uIdStartUp20': 'mercs_title', 'uIdStartUp29': 'reunion_title',
                     'uIdStartUp21': 'select_stage', 'uIdStartUp22': 'select_player'}
            for name, where in names.items():
                if name in units:
                    return {'ready': True, 'screen': where, 'title': 'BLUS30491', 'token': (name, units[name])}
            title = units.get('uIdTitle00')
            if title and 'uIdTopMenu00' not in units and menus.u32(memory, title + menus.TITLE_STEP) == menus.TITLE_PRESS_START:
                return {'ready': True, 'screen': 'title', 'title': 'BLUS30491', 'token': ('title', title)}
            alert = menus.alert_screen(memory, units)
            if alert and alert.get('where') in {'alert_signin', 'alert_ok'}:
                return {'ready': True, 'screen': alert['where'], 'title': 'BLUS30491',
                        'token': alert.get('confirmation_token')}
            return {'ready': False, 'screen': 'unknown', 'title': 'BLUS30491'}
    def close():
        nonlocal memory
        # _memory creates these views for this observer; never close the
        # adapter/debugger borrowed by its AdMem fallback.
        view, memory = memory, None
        stream = getattr(view, 'f', None)
        ram = getattr(view, 'ram', None)
        if stream is not None:
            stream.close()
        elif ram is not None:
            ram.close()
    probe.close = close
    return probe


class Preparation:
    def __init__(self, adapter, game, owned, *, probe=None, clock=time.monotonic,
                 timeout_s=TIMEOUT_S, stable_s=STABLE_S):
        self.adapter, self.owned, self.clock = adapter, owned, clock
        self.probe = probe or native_probe(adapter, game)
        self.started, self.timeout_s, self.stable_s = clock(), timeout_s, stable_s
        self.process = getattr(adapter, 'proc', None)
        self.generation = getattr(adapter, 'generation', None)
        self.lock, self.cancelled = threading.RLock(), threading.Event()
        self.pause_owned = False
        self.token, self.stable_since = None, None
        self.status = {'state': 'loading', 'ready': False, 'paused': False,
                       'reason': 'Waiting for a stable native title/menu state before pausing.'}

    def snapshot(self):
        with self.lock:
            return dict(self.status)

    def cancel(self, reason='Session control changed during background preparation.'):
        with self.lock:
            self.cancelled.set()
            self.pause_owned = False
            self.status = {**self.status, 'state': 'cancelled', 'ready': False, 'reason': reason}

    def autoplay_control(self, operation):
        """Claim input atomically with this observer's last possible pause.

        Start (and a MercMode round preparation, which drives the menus on from
        here) releases only a pause made by this exact preparation. A manually
        paused game, a replaced process, and Stop never acquire this exception.
        Return whether the claim took this background game over (Start: for
        normal priority; prepare keeps the background priority).
        """
        with self.lock:
            claims = operation in ('start', 'prepare')
            owned = claims and self._owned()
            loading = owned and self.status.get('state') == 'loading'
            resume = (claims and self.pause_owned
                      and self.status.get('paused') is True and getattr(self.adapter, 'gbox_warm', False)
                      and owned)
            self.cancel(f'Autoplay {operation} changed session control.')
            if not resume:
                return loading
            try:
                result = self.adapter.resume()
                confirmed = isinstance(result, dict) and (result.get('paused') is False
                    or result.get('halted') is False or result.get('state') in ('PLAYING', 'RUNNING'))
                if not confirmed:
                    raise RuntimeError('Emulator did not confirm resuming its prepared warm session.')
            except Exception as error:
                # A later explicit Start may retry this same failed resume.
                # Other control cancellation still revokes that exception.
                self.pause_owned = True
                self.status.update(state='failed', paused=True, reason=f'Warm resume failed: {error}'[:240])
                raise
            self.adapter.gbox_warm = False
            self.status.update(paused=False, resumed_by=f'autoplay_{operation}')
            return True

    def _owned(self):
        return (self.owned() and getattr(self.adapter, 'proc', None) is self.process
                and getattr(self.adapter, 'generation', None) == self.generation
                and (self.process is None or self.process.poll() is None))

    def tick(self):
        with self.lock:
            if self.cancelled.is_set() or self.status['state'] != 'loading':
                return False
            if not self._owned():
                self.cancel('The exact session or emulator process changed.')
                return False
            if self.clock() - self.started >= self.timeout_s:
                self.status = {**self.status, 'state': 'failed',
                               'reason': 'Native title/menu readiness timed out; the game was not paused.'}
                return False
        try:
            state = self.probe()
        except Exception as error:  # guest code/pages may still be loading
            state = {'ready': False, 'screen': 'unknown', 'reason': f'{type(error).__name__}: {error}'[:200]}
        with self.lock:
            # Cancellation can occur during a slow native read. Never pause a
            # session after Stop, Resume, player input or process replacement.
            if self.cancelled.is_set() or not self._owned():
                self.cancel('The exact session or emulator process changed.')
                return False
            if self.clock() - self.started >= self.timeout_s:
                self.status.update(state='failed', reason='Native title/menu readiness timed out; the game was not paused.')
                return False
            self.status.update(screen=state.get('screen', 'unknown'))
            if state.get('unsupported'):
                self.status.update(state='failed', reason=state['reason'])
                return False
            if state.get('ready') is not True:
                self.token, self.stable_since = None, None
                return True
            token = state.get('token', state.get('screen'))
            if token != self.token or self.stable_since is None:
                self.token, self.stable_since = token, self.clock()
                return True
            if self.clock() - self.stable_since < self.stable_s:
                return True
            try:
                result = self.adapter.pause()
                confirmed = isinstance(result, dict) and (result.get('paused') is True
                    or result.get('halted') is True
                    or result.get('state') == 'PAUSED' and result.get('threads', 1) > 0)
                if not confirmed:
                    raise RuntimeError('Emulator did not confirm it paused.')
            except Exception as error:
                self.status.update(state='failed', reason=f'{type(error).__name__}: {error}'[:240])
                return False
            self.adapter.gbox_warm = True
            self.pause_owned = True
            self.status = {'state': 'ready', 'ready': True, 'paused': True, 'screen': state['screen'],
                           'title': state.get('title'), 'source': 'native_menu',
                           'wait_s': round(self.clock() - self.started, 3)}
            return False

    def run(self):
        try:
            while self.tick():
                self.cancelled.wait(POLL_S)
        finally:
            close = getattr(self.probe, 'close', None)
            if callable(close):
                close()


class RoundPrepare:
    """The receipt and the pause of one round preparation (gbox.tools autoplay op=prepare) on a warm MercMode game.

    The title's own menu code (re4_merc_bot.play / mercs_bot.play with prepare=True) walks the paused game from
    wherever it waits (the boot's title, a results screen) to the first frame of a round and stops there with nothing
    pressed; finish() then pauses the game at that exact point (the parking pause: gbox_warm, background priority) and
    the receipt says prepared=true with the character and stage. A walk that ends anywhere else (a story game, menus
    RAM can't name, a timeout, an error) pauses the game back where it is - the old boot-paused state - and the
    receipt says prepared=false with the reason, so the switch falls back to resuming it at its menus. Stop, the
    player's pad, a manual pause and a closing session cancel it: the game is then left exactly as that control put it.
    """

    def __init__(self, adapter, title, job=None, clock=time.monotonic):
        self.adapter, self.title, self.clock = adapter, title, clock
        self.started = clock()
        self.lock = threading.RLock()
        self.driver = None                                  # the autoplay driver of the walk: cancel() stops it
        self.done, self.cancelled, self.pause_owned = False, False, False
        # every receipt names its prepare job: the scheduler matches it to the pool entry's prepare_job, so the receipt
        # of an earlier preparation of the same game (it played since, and waits parked again) never counts as ready
        self.stamp = {'job': job} if job else {}
        self.status = {'state': 'preparing', 'ready': False, 'paused': False, 'prepared': False,
                       'source': ROUND_SOURCE, 'title': title, **self.stamp,
                       'reason': 'Driving the native menus to the start of a round in the background.'}

    def snapshot(self):
        with self.lock:
            return dict(self.status)

    def note(self, **fields):
        """Live progress for the session detail (the menu screen the walk is on)."""
        with self.lock:
            if not self.done:
                self.status.update(fields)

    def cancel(self, reason='Session control changed during round preparation.'):
        """Stop the walk and leave the game as the new control put it; a finished preparation keeps its receipt."""
        with self.lock:
            if self.done:
                return
            self.done, self.cancelled, self.pause_owned = True, True, False
            self.status = {**self.status, 'state': 'cancelled', 'ready': False, 'prepared': False, 'reason': reason}
            if self.driver is not None:
                self.driver.stopped = True

    def finish(self, prepared, stats, error=None, *, owned=True):
        """The walk ended: pause the game where it is and write the receipt (once; a cancel wins)."""
        with self.lock:
            if self.done:
                return self.snapshot()
            self.done = True
            stats = stats or {}
            why = (f'{type(error).__name__}: {error}' if error is not None
                   else stats.get('wandered') or ('the walk stopped before a round started'
                                                   if not prepared else None))
            if not owned:
                self.cancelled = True
                self.status = {**self.status, 'state': 'cancelled', 'ready': False, 'prepared': False,
                               'reason': 'The session or its emulator process changed during round preparation.'}
                return self.snapshot()
            try:
                result = self.adapter.pause()
                if not _confirmed_pause(result):
                    raise RuntimeError('Emulator did not confirm it paused.')
            except Exception as exc:              # noqa: BLE001 - an unpaused background game: the scheduler closes it
                self.status = {'state': 'failed', 'ready': False, 'paused': False, 'prepared': bool(prepared),
                               'source': ROUND_SOURCE, 'title': self.title, 'screen': stats.get('screen'),
                               'reason': f'{type(exc).__name__}: {exc}'[:240], **self.stamp,
                               **({'prepare_failed': str(why)[:240]} if why else {})}
                return self.snapshot()
            self.adapter.gbox_warm = True
            self.pause_owned = True
            wait_s = round(self.clock() - self.started, 3)
            if prepared:
                self.status = {'state': 'ready', 'ready': True, 'paused': True, 'prepared': True,
                               'source': ROUND_SOURCE, 'title': self.title, 'screen': 'playing', 'wait_s': wait_s,
                               **self.stamp,
                               **{k: stats.get(k) for k in ('character', 'stage', 'stage_index', 'mercenaries_mode',
                                                           'room') if stats.get(k) is not None}}
            else:
                self.status = {'state': 'ready', 'ready': True, 'paused': True, 'prepared': False,
                               'source': 'native_menu', 'title': self.title, 'screen': stats.get('screen'),
                               'wait_s': wait_s, 'prepare_failed': str(why)[:240], **self.stamp}
            return self.snapshot()

    def autoplay_control(self, operation):
        """Start releases the pause this preparation made (the game is ours and paused at its round start); Stop
        and any other control only end a walk still running. Returns whether a resume happened."""
        with self.lock:
            if operation == 'prepare':
                return False                                 # the walk this receipt belongs to is starting (start_round)
            if not self.done:
                self.cancel(f'Autoplay {operation} changed session control.')
                return False
            if operation != 'start' or not self.pause_owned or self.status.get('paused') is not True \
                    or not getattr(self.adapter, 'gbox_warm', False):
                return False
            result = self.adapter.resume()
            if not _confirmed_resume(result):
                raise RuntimeError('Emulator did not confirm resuming its prepared round.')
            self.adapter.gbox_warm = False
            self.pause_owned = False
            self.status = {**self.status, 'paused': False, 'resumed_by': 'autoplay_start'}
            return True


def start(adapter, game, owned):
    cancel(adapter, 'A newer warm preparation replaced this observer.')
    preparation = Preparation(adapter, game, owned)
    adapter.gbox_warm_preparation = preparation
    adapter.gbox_round_prepare = None                      # a new boot: no round receipt of an earlier one
    threading.Thread(target=preparation.run, daemon=True, name='mercmode-warm-ready').start()
    return preparation.snapshot()


def start_round(adapter, title, job=None):
    """Register a round preparation's receipt before its walk begins (the session pump posts it from here on)."""
    previous = getattr(adapter, 'gbox_round_prepare', None)
    if previous is not None:
        previous.cancel('A newer round preparation replaced this one.')
    round_prepare = RoundPrepare(adapter, title, job)
    adapter.gbox_round_prepare = round_prepare
    return round_prepare


def cancel(adapter, reason='Session control changed during background preparation.'):
    preparation = getattr(adapter, 'gbox_warm_preparation', None)
    if preparation is not None:
        preparation.cancel(reason)
    round_prepare = getattr(adapter, 'gbox_round_prepare', None)
    if round_prepare is not None:
        round_prepare.cancel(reason)


def autoplay_control(adapter, operation):
    resumed = False
    preparation = getattr(adapter, 'gbox_warm_preparation', None)
    if preparation is not None:
        resumed = preparation.autoplay_control(operation)
    round_prepare = getattr(adapter, 'gbox_round_prepare', None)
    if round_prepare is not None:
        resumed = round_prepare.autoplay_control(operation) or resumed
    return resumed


def status(adapter):
    """The receipt the session pump posts: the round preparation's once one began, else the boot observer's."""
    round_prepare = getattr(adapter, 'gbox_round_prepare', None)
    if round_prepare is not None:
        return round_prepare.snapshot()
    preparation = getattr(adapter, 'gbox_warm_preparation', None)
    return preparation.snapshot() if preparation is not None else None


def receipt(session, job):
    """Prefer the worker's live state over its original launch receipt."""
    live = ((session or {}).get('detail') or {}).get('warm')
    return live if isinstance(live, dict) else (((job or {}).get('output') or {}).get('detail') or {}).get('warm') or {}


def loading(session, job):
    return receipt(session, job).get('state') == 'loading'


def prepared(session, job, title):
    """Paused at a verified native point of this exact title: its boot menu, or (a round preparation) its round."""
    value = receipt(session, job)
    return (value.get('state') == 'ready' and value.get('ready') is True and value.get('paused') is True
            and value.get('source') in ('native_menu', ROUND_SOURCE) and value.get('title') == title)


def round_receipt(session, job, prepare_job=None):
    """The live round-preparation receipt (source native_round, or the fallback with prepare_failed), {} while only the
    boot observer has reported. With prepare_job, a receipt stamped by another preparation (an earlier one of the same
    game, which played since) is {} too."""
    value = receipt(session, job)
    if not (value.get('source') == ROUND_SOURCE or value.get('prepare_failed')):
        return {}
    if prepare_job is not None and value.get('job') and value['job'] != prepare_job:
        return {}
    return value


def preparing(session, job):
    return round_receipt(session, job).get('state') == 'preparing'


def round_ready(session, job, title):
    """Paused at the first frame of a round of this exact title: the switch lands in gameplay."""
    value = receipt(session, job)
    return prepared(session, job, title) and value.get('source') == ROUND_SOURCE and value.get('prepared') is True
