"""Background delivery of coaching reports; no HTTP waits in a combat tick.

Local records contain immutable evidence and delivery state, never credentials.
An unacknowledged POST is retained as uncertain and is not automatically replayed.
The detailed damage outbox and round flight recorder remain the source evidence.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import queue
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2] / 'gbox-data' / 'mercs' / 'follow-reports'
_QUEUE = queue.Queue(maxsize=64)
_LOCK = threading.Lock()
_THREAD = None


def _write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(record, stream, allow_nan=False, separators=(',', ':'))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _run():
    while True:
        callback = _QUEUE.get()
        try:
            callback()
        except Exception:
            # Delivery records failures itself; keep unrelated queued reports
            # moving if a caller's callback unexpectedly fails.
            pass
        finally:
            _QUEUE.task_done()


def _dispatch(callback):
    global _THREAD
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_run, name='mercs-follow-reports', daemon=True)
            _THREAD.start()
        _QUEUE.put_nowait(callback)


def submit(post, config, payload, stats, kind, receipt):
    """Persist and queue one immutable request; return queued, not delivered.

    Capture credentials only in the closure. Reconfiguring the next title cannot
    retarget an old report or rewrite its provenance while HTTP is in flight.
    """
    cfg, body = dict(config), deepcopy(payload)
    event_id = uuid.uuid4().hex
    body.setdefault('context', {})['follow_report_event_id'] = event_id
    path = ROOT / (event_id + '.json')
    record = {'schema':'gbox.mercs.follow-report/1', 'event_id':event_id,
              'kind':kind, 'queued_at':time.time(), 'state':'queued', 'payload':body}
    result = dict(receipt, event_id=event_id, state='queued', request=None)
    try:
        _write(path, record)
    except Exception as exc:
        stats[kind + '_report_error'] = f'evidence write: {type(exc).__name__}: {exc}'[:200]
        stats[kind + '_report_failures'] = int(stats.get(kind + '_report_failures', 0)) + 1
        return None

    def deliver():
        try:
            # Persist the attempted state before contacting the server. A crash
            # cannot leave a possibly submitted request labelled safe to retry.
            record.update(state='attempted', attempted_at=time.time())
            _write(path, record)
            reply = post(cfg['url'], cfg['token'], body)
            if not isinstance(reply, dict) or not reply.get('id'):
                raise ValueError('server did not acknowledge a request id')
            result.update(state='delivered', request=reply['id'], at=round(time.time(), 1))
            record.update(state='delivered', delivered_at=time.time(), request=reply['id'])
            stats[kind + '_reports'] = int(stats.get(kind + '_reports', 0)) + 1
            stats[kind + '_report_last'] = dict(result)
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
            if cfg.get('token'):
                error = error.replace(cfg['token'], '[redacted]')
            error = error[:200]
            result.update(state='uncertain', error=error)
            record.update(state='uncertain', error=error)
            stats[kind + '_report_error'] = error
            stats[kind + '_report_failures'] = int(stats.get(kind + '_report_failures', 0)) + 1
        finally:
            try:
                _write(path, record)
            except Exception as exc:
                stats[kind + '_report_archive_error'] = f'{type(exc).__name__}: {exc}'[:200]
            stats[kind + '_reports_pending'] = max(0, int(stats.get(kind + '_reports_pending', 0)) - 1)

    stats[kind + '_reports_pending'] = int(stats.get(kind + '_reports_pending', 0)) + 1
    try:
        _dispatch(deliver)
    except queue.Full:
        stats[kind + '_reports_pending'] -= 1
        stats[kind + '_report_error'] = 'delivery queue full; evidence retained locally, not submitted'
        record.update(state='not_submitted', error='delivery queue full')
        try:
            _write(path, record)
        except OSError:
            pass
        return None
    stats[kind + '_reports_queued'] = int(stats.get(kind + '_reports_queued', 0)) + 1
    return result if result['state'] != 'uncertain' else None
