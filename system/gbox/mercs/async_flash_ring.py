"""One cancellable RE5 flash ring; native waits never own the combat thread.

Only flash rings are admitted here. Explosive movement/clearance needs a separate
contract. Receipts return to the originating round on its combat thread.
"""
from __future__ import annotations

import copy
from pathlib import Path
import threading
import time
import uuid

from .follow_report_delivery import _write


COUNTERS = ('rings_attempted', 'rings_deployed', 'ring_defends', 'ring_launcher_fallback')
OUTPUTS = frozenset(COUNTERS + ('ring_last_at', 'ring_error', 'ring_first_failure', 'ring_defend_shell_refused',
    'ring_defend_kind', 'ring_kind_fired', 'ring_launcher_fallback_note', 'ring_last_detonated',
    'ring_last_failure', 'ring_pending', 'native_flash_confirmed_at', 'flash_stamp_at', 'flash_reason_last',
    'flash_reasons', 'flash_paths'))
ROOT = Path(__file__).resolve().parents[2] / 'gbox-data' / 'mercs' / 'native-ring-receipts'


def identity(snap, stats):
    p = snap.get('player') or {}
    return stats.get('round_evidence_id'), p.get('ptr'), p.get('generation')


class Flight:
    def __init__(self):
        self.job = None
        self.closed = False

    def cancel(self):
        if self.job is not None:
            self.job['cancel'].set()

    def close(self):
        self.closed = True
        self.cancel()

    def observe(self, snap, stats, playing=True):
        job = self.job
        if job is not None and (not playing or stats.get('operator_control')
                                or identity(snap, stats) != job['identity']):
            self.cancel()

    def poll(self, snap, stats):
        self.observe(snap, stats)
        job = self.job
        if job is None:
            return None
        stats['ring_async_pending'] = not job['done'].is_set()
        if not job['done'].is_set():
            return {'fire': False, 'pending': True, 'reason': 'native flash ring executing; combat continues'}
        self.job = None
        result = job['result']
        if identity(snap, stats) != job['identity'] or job['cancel'].is_set():
            # Keep the original identity with the receipt; no new-round counters
            # or cooldowns may inherit a late acknowledgment.
            stats['ring_async_retired'] = {'identity': list(job['identity']), 'receipt': result,
                                          'cancelled': job['cancel'].is_set()}
            return {'fire': False, 'reason': 'flash receipt retired with its originating round'}
        before, after = job['before'], job['stats']
        for key, value in after.items():
            if key not in OUTPUTS:
                continue
            if key in COUNTERS:
                stats[key] = int(stats.get(key, 0)) + int(value) - int(before.get(key, 0))
            elif key in ('flash_reasons', 'flash_paths'):
                dst = stats.setdefault(key, {})
                for name, count in value.items():
                    delta = count - (before.get(key) or {}).get(name, 0)
                    dst[name] = dst.get(name, 0) + delta
            elif key in ('native_flash_confirmed_at', 'flash_stamp_at', 'ring_last_at'):
                stats[key] = max(stats.get(key) or 0, value)
            elif key not in before or value != before[key]:
                stats[key] = value
        if 'ring_error' in before and 'ring_error' not in after and stats.get('ring_error') == before['ring_error']:
            stats.pop('ring_error', None)
        stats['ring_async_receipt'] = result
        return {**job['decision'], 'attempted': True, 'fired': result.get('state') == 'confirmed',
                'receipt': result, 'background': True}

    def submit(self, snap, stats, decision, now, run):
        owner = identity(snap, stats)
        if self.closed or self.job is not None or not owner[0] or any(type(v) is not int for v in owner[1:]):
            return {'fire': False, 'reason': 'flash ring needs an idle worker and a verified round/player identity'}
        # Copy only the evidence fire() consumes or changes, never the whole bot.
        before = {k: copy.deepcopy(v) for k, v in stats.items() if k in OUTPUTS or k == 'kills'}
        job = {'identity': owner, 'decision': dict(decision), 'before': before, 'stats': copy.deepcopy(before),
               'cancel': threading.Event(), 'done': threading.Event()}
        job['record'] = {'schema': 'gbox.mercs.native-ring/1', 'id': uuid.uuid4().hex,
                         'identity': list(owner), 'session': stats.get('source_session_id'),
                         'requested_at': now, 'decision': dict(decision), 'state': 'requested'}
        self.job = job
        deadline = time.monotonic() + 8.0

        def allowed():
            return not job['cancel'].is_set() and time.monotonic() < deadline

        def work():
            path = ROOT / (job['record']['id'] + '.json')
            try:
                # Persist original identity before native publication. The final
                # receipt survives even when game over prevents another tick.
                _write(path, job['record'])
                job['result'] = run(job['decision'], job['stats'], now,
                                    {'expected': owner[1:], 'allowed': allowed, 'wait_for_lock': False})
            except Exception as exc:
                job['result'] = {'state': 'failed', 'reason': f'{type(exc).__name__}: {exc}'[:240]}
            finally:
                job['record'].update(state='finished', receipt=job['result'], finished_at=time.time(),
                                     cancelled=job['cancel'].is_set())
                try:
                    _write(path, job['record'])
                except Exception as exc:
                    job['result']['receipt_archive_error'] = f'{type(exc).__name__}: {exc}'[:200]
                job['done'].set()

        stats['ring_async_pending'] = True
        stats['ring_async_requested_at'] = now
        stats['ring_last_at'] = now
        stats['ring_last_reason'] = decision['reason'][:200]
        try:
            threading.Thread(target=work, name='mercs-re5-flash-ring', daemon=True).start()
        except Exception:
            self.job = None
            stats['ring_async_pending'] = False
            raise
        return {'fire': False, 'pending': True, 'reason': 'native flash ring submitted; combat continues'}
