"""Read-only proof that this deployment's external drain holds scheduled intake.

Hermes gateway.drain_control owns the marker protocol. This reader never begins,
renews or clears it and never treats an empty active_agents counter as idle.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
import time

MARKER_MAX_AGE = 3600  # installed gateway/drain_control.py protocol
ACK_MAX_AGE = 5
TICK_MAX_AGE = 90


def _read(path, limit):
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Drain evidence exceeds its read bound')
    return data


def _stamp(value):
    stamp = dt.datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('Ambiguous drain timestamp')
    return stamp.timestamp()


def _process(proc, pid):
    fields = _read(proc / str(pid) / 'stat', 4096).decode().rsplit(')', 1)[1].split()
    if fields[0] == 'Z':
        raise ValueError('Gateway is a zombie')
    return int(fields[19])


def acknowledgment(home: Path, owner: str, *, now=None, proc=Path('/proc')) -> dict:
    """Only an exact owner with a fresh, live gateway/ticker acknowledgment qualifies.

    This proves scheduled intake is held, not that existing work is finished.
    Manual invocations/new worker jobs still require the canonical active ledger
    checks, including the last check immediately before activation.
    """
    now = time.time() if now is None else now
    result = {'acknowledged': False, 'reason': 'External drain is not acknowledged for this owner.'}
    if not isinstance(owner, str) or not owner or type(now) not in (int, float) or not math.isfinite(now):
        return result
    try:
        home, proc = Path(home), Path(proc)
        marker_raw = _read(home / '.drain_request.json', 8192)
        marker = json.loads(marker_raw)
        state = json.loads(_read(home / 'gateway_state.json', 65536))
        identity_raw = _read(home / 'gateway.pid', 8192)
        identity = json.loads(identity_raw)
        if not all(isinstance(item, dict) for item in (marker, state, identity)):
            return result
        epoch = _read(proc / 'sys/kernel/random/boot_id', 256).decode().strip() + ':' + str(_process(proc, 1))
        requested = _stamp(marker.get('requested_at'))
        if (marker.get('action') != 'drain' or marker.get('principal') != owner or marker.get('epoch') != epoch
                or not 0 <= now - requested < MARKER_MAX_AGE - 60):
            return result
        pid, started = identity.get('pid'), identity.get('start_time')
        if (type(pid) is not int or pid <= 1 or type(started) is not int or started <= 0
                or identity.get('kind') != 'hermes-gateway' or state.get('kind') != 'hermes-gateway'
                or state.get('pid') != pid or state.get('start_time') != started
                or Path(identity.get('hermes_home', '')).resolve() != home.resolve()
                or _process(proc, pid) != started):
            return result
        updated = _stamp(state.get('updated_at'))
        if (state.get('gateway_state') != 'draining' or state.get('restart_requested') is not False
                or state.get('exit_reason') is not None or state.get('served_profiles') != []
                or updated < requested or not 0 <= now - updated <= ACK_MAX_AGE):
            return result
        # The built-in ticker writes its own PID heartbeat, including while its
        # can_dispatch gate is closed. A configured model/provider is no proof.
        heartbeat = _read(home / 'cron/ticker_heartbeat', 128).decode().split()
        if len(heartbeat) != 2 or int(heartbeat[1]) != pid or not 0 <= now - float(heartbeat[0]) <= TICK_MAX_AGE:
            return result
        if (_read(home / '.drain_request.json', 8192) != marker_raw or
                _read(home / 'gateway.pid', 8192) != identity_raw):
            return result
        return {'acknowledged': True, 'reason': '', 'owner': owner, 'gateway_pid': pid,
                'gateway_start_time': started, 'requested_at': requested, 'acknowledged_at': updated,
                'expires_at': requested + MARKER_MAX_AGE,
                'boundary': 'Scheduled intake held; active work still requires the canonical idle checks.'}
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError):
        return result
