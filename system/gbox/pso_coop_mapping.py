"""Keep proven pad-to-player mappings on one live Dolphin adapter, never disk.

An attestation is evidence for an explicitly started bot, not permission to start
one. Native actor pointers may be refreshed by the already-mapped live bot;
a later bot must reobserve those exact actors and every process/config binding.
"""
from __future__ import annotations

import configparser
from dataclasses import dataclass
import hashlib
import json
import math
import marshal
import os
from pathlib import Path
from types import FunctionType

from .registry import Unsupported

_SEAL = object()
ATTRIBUTE = '_pso_controller_attestation'


@dataclass
class Attestation:
    seal: object
    adapter: object
    process: object
    environment: dict
    players: tuple
    probe: tuple


def _diagnostic(ad, status, reason=''):
    ad._pso_mapping_diagnostic = {'controller_receipt_status': status,
        'controller_receipt_reason': str(reason)[:240]}


def diagnostics(ad):
    """Evidence status only; never a source of active controller permission."""
    return {**getattr(ad, '_pso_mapping_diagnostic', {'controller_receipt_status': 'absent'}),
            'controller_receipt_retained': _receipt(ad) is not None,
            'controller_mapping_epoch': getattr(ad, '_pso_mapping_epoch', 0)}


def invalidate(ad, reason='reset_or_state_restore'):
    """Reset/restore invalidates evidence before its first native input."""
    setattr(ad, ATTRIBUTE, None)
    ad._pso_verified_player_slots = set()
    ad._pso_mapping_epoch = getattr(ad, '_pso_mapping_epoch', 0) + 1
    _diagnostic(ad, 'invalidated', reason)


def _path(value):
    return os.path.normcase(str(Path(value).resolve(strict=True)))


def _process(ad):
    import psutil
    from .tools import _native_process_created
    proc = getattr(ad, 'proc', None)
    pid = getattr(proc, 'pid', None)
    born = _native_process_created(ad, pid)
    if born is None:
        raise ValueError('The original live process birth cannot be verified')
    live = psutil.Process(pid)
    args, executable = live.cmdline(), live.exe()
    if _native_process_created(ad, pid) != born:
        raise ValueError('The native process changed during verification')
    return pid, born, executable, args


def _routing(ad):
    from . import pso_coop_setup
    from .desktop_input_lease import InputLease
    digest = hashlib.sha256(json.dumps({'pad2': pso_coop_setup.PAD2, 'pad2_windows': pso_coop_setup.PAD2_WIN,
        'p1_aliases': pso_coop_setup.P1_ALIASES, 'adapter_keys': getattr(ad, 'keys', {})}, sort_keys=True).encode())
    functions = [pso_coop_setup.input_rows]
    lease = getattr(ad, '_desktop_input_lease', None)
    scoped = None
    if lease is not None:
        scoped = ad.send_input_player
        if (type(lease) is not InputLease or ad.send_input is not lease
                or lease.send is not lease.__wrapped__ or not isinstance(scoped, FunctionType)):
            raise ValueError('The desktop input lease routing changed')
        closure = dict(zip(scoped.__code__.co_freevars, (cell.cell_contents for cell in scoped.__closure__ or ())))
        if closure.get('lease') is not lease or closure.get('scoped') is not getattr(scoped, '__wrapped__', None):
            raise ValueError('The scoped controller wrapper is not the attached desktop input lease')
        # Retain both the exact lease identity and its underlying input code.
        # Never generically unwrap an unknown callable and silently ignore it.
        digest.update(str(id(lease)).encode())
        functions += [InputLease.__call__, InputLease.identity, InputLease._effective,
                      lease.normalize, lease.axis, lease.__wrapped__, scoped, scoped.__wrapped__]
    else:
        functions += [ad.send_input, ad.send_input_player]
    for fn in functions:
        if getattr(fn, '__wrapped__', None) is not None and fn is not scoped:
            raise ValueError('Unsupported input wrapper in controller routing')
        owner = getattr(fn, '__self__', None)
        if owner is not None:
            digest.update(str(id(owner)).encode())
        fn = getattr(fn, '__func__', fn)
        if not isinstance(fn, FunctionType):
            raise ValueError('Unsupported input callable in controller routing')
        digest.update(str(id(fn)).encode())
        digest.update(marshal.dumps(fn.__code__))
    return digest.hexdigest()


def _environment(ad, sid, game):
    from .pso_coop_progress import card_binding
    from .pso_campaign import GAME_IDS
    auth = getattr(ad, '_pso_coop_new_card', {}) or {}
    if (not sid or auth.get('session_id') != sid or auth.get('isolated') is not True
            or getattr(ad, 'name', None) != 'dolphin' or getattr(ad, 'coop_players', None) != 2
            or game.get('game_id') not in GAME_IDS):
        raise ValueError('Mapping requires the exact private two-player PSO session')
    card = card_binding(auth, getattr(ad, 'memory_card_context', {}) or {})
    if not card:
        raise ValueError('The private card identity is unavailable')
    card = _path(card)
    info = Path(card).stat()
    if not info.st_ino:
        raise ValueError('The card file identity is unavailable')
    user = _path(getattr(ad, 'gameplay_demo_user', ''))
    if user != _path(Path(auth['path']) / 'User'):
        raise ValueError('The private Dolphin user directory changed')
    pid, born, executable, args = _process(ad)
    options, users, roms = {}, [], []
    for index, arg in enumerate(args[:-1]):
        value = args[index + 1]
        if arg in ('-u', '--user'):
            users.append(_path(value))
        elif arg in ('-e', '--exec'):
            roms.append(_path(value))
        elif arg in ('-C', '--config') and '=' in value:
            key, value = value.split('=', 1)
            if key in options and options[key] != value:
                raise ValueError('Conflicting Dolphin configuration overrides')
            options[key] = value
    if (users != [user] or len(roms) != 1 or options.get('Dolphin.Core.SIDevice0') != '6'
            or options.get('Dolphin.Core.SIDevice1') != '6' or options.get('Dolphin.Core.SlotA') != '1'
            or _path(options.get('Dolphin.Core.MemcardAPath', '')) != card):
        raise ValueError('The running process does not confirm the private card and both standard controllers')
    raw = (Path(user) / 'Config' / 'GCPadNew.ini').read_bytes()
    config = configparser.ConfigParser(interpolation=None, strict=True)
    config.read_string(raw.decode('utf-8-sig'))
    for section in ('GCPad1', 'GCPad2'):
        for key in ('Device', 'Buttons/A', 'Main Stick/Up', 'Main Stick/Down', 'Main Stick/Left', 'Main Stick/Right'):
            if not config.get(section, key, fallback='').strip():
                raise ValueError('A required private controller binding is unavailable')
    if ('XInput/' in config['GCPad1']['Device']
            and not config.getboolean('GCPad1', 'Options/Always Connected', fallback=False)):
        raise ValueError('Player one lacks the verified connected keyboard fallback')
    if ad.read_memory(0x80000000, 8) != b'GPOE8P\0\x02':
        raise ValueError('The current disc revision changed')
    return {'session_id': sid, 'game_id': game['game_id'], 'pid': pid, 'born': born,
            'executable': executable, 'rom': roms[0], 'user': user, 'card': card,
            'card_file': (info.st_dev, info.st_ino), 'pad_sha256': hashlib.sha256(raw).hexdigest(),
            'input_routing_sha256': _routing(ad),
            'epoch': getattr(ad, '_pso_mapping_epoch', 0)}


def _players(state):
    if (state.get('verified') is not True or state.get('cooperative') is not True
            or state.get('phase') != 14 or state.get('travelling') or set(state.get('players', {})) != {1, 2}):
        raise ValueError('Two current native offline players are required')
    rows = []
    for slot in (1, 2):
        row = state['players'][slot]
        pointer = row.get('ptr')
        if (not isinstance(pointer, str) or len(pointer) != 8
                or not 0x80000000 <= int(pointer, 16) <= 0x817FEE00 or int(pointer, 16) % 4
                or row.get('class') != 'TObjPlayer' or row.get('entity_id') != slot - 1
                or row.get('controller') != slot):
            raise ValueError('The native controller and player identities disagree')
        rows.append((slot, pointer.upper(), slot - 1))
    if rows[0][1] == rows[1][1]:
        raise ValueError('Both controllers identify the same native player')
    return tuple(rows)


def _receipt(ad):
    value = getattr(ad, ATTRIBUTE, None)
    return value if (isinstance(value, Attestation) and value.seal is _SEAL
                     and value.adapter is ad and value.process is getattr(ad, 'proc', None)) else None


def prove(ad, reader, inputs, state, sid, game, stopped, probe):
    """Only an actual successful two-pad movement probe can create evidence."""
    setattr(ad, ATTRIBUTE, None)
    _diagnostic(ad, 'checking')
    try:
        before = _environment(ad, sid, game)
    except Exception as exc:
        before = None  # Normal safe-town mapping can still work without a reusable attestation.
        _diagnostic(ad, 'unavailable', f'{type(exc).__name__}: {exc}')
    if stopped():
        _diagnostic(ad, 'stopped', 'Stopped before the two-pad probe')
        raise InterruptedError('PSO stopped before mapping')
    try:
        rows = probe(reader, inputs, state)
    except Exception as exc:
        if before is not None:
            _diagnostic(ad, 'probe_failed', f'{type(exc).__name__}: {exc}')
        raise
    if stopped() or before is None:
        return rows
    try:
        fresh = reader.snapshot()
        players = _players(fresh)
        if (fresh.get('floor') != 0 or len(rows) != 2 or _environment(ad, sid, game) != before):
            raise ValueError('Mapping environment changed during the two-pad probe')
        for slot, row in enumerate(rows, 1):
            moved, other = row.get('moved'), row.get('other_moved')
            if (row.get('controller') != slot or row.get('native_slot') != slot - 1
                    or row.get('pointer') != fresh['players'][slot]['ptr']
                    or type(moved) not in (int, float) or not math.isfinite(moved) or moved < 2
                    or type(other) not in (int, float) or not math.isfinite(other) or not 0 <= other <= 1.5):
                raise ValueError('The probe did not attest both current native players')
        if not stopped():
            setattr(ad, ATTRIBUTE, Attestation(_SEAL, ad, ad.proc, before, players, tuple(dict(r) for r in rows)))
            _diagnostic(ad, 'retained', 'Both controllers physically verified on this live adapter')
    except Exception as exc:
        invalidate(ad, f'probe_verification: {type(exc).__name__}: {exc}')
        raise Unsupported('PSO mapping proof changed during verification; inputs remain released') from exc
    return rows


def restore(ad, reader, sid, game, stopped):
    """Revalidate without sending input; None leaves the existing safe-town probe mandatory."""
    proof = _receipt(ad)
    if proof is None or stopped():
        if getattr(ad, ATTRIBUTE, None) is not None and proof is None:
            _diagnostic(ad, 'rejected', 'The attestation no longer belongs to this adapter and process')
        return None
    try:
        current = _environment(ad, sid, game)
        if current != proof.environment:
            changed = ', '.join(sorted(key for key in current if current[key] != proof.environment.get(key)))
            raise ValueError('PSO mapping bindings changed: ' + changed)
        fresh = reader.snapshot()
        if (_players(fresh) != proof.players or _environment(ad, sid, game) != proof.environment
                or _receipt(ad) is not proof):
            raise ValueError('PSO actors changed outside the mapped live controller')
        if stopped():
            return None
        _diagnostic(ad, 'revalidated', 'Same live adapter, native players and controller bindings')
        return {'state': fresh, 'probe': [dict(row) for row in proof.probe]}
    except Exception as exc:
        setattr(ad, ATTRIBUTE, None)
        _diagnostic(ad, 'rejected', f'{type(exc).__name__}: {exc}')
        return None


def observe(ad, state, sid, game, stopped):
    """The already-mapped bot can follow native actor recreation across a normal area load."""
    proof = _receipt(ad)
    if proof is None or stopped() or not state.get('verified') or state.get('travelling'):
        return
    players = _players(state)
    if players == proof.players:
        return
    try:
        if _environment(ad, sid, game) != proof.environment:
            raise ValueError('Mapping bindings changed while the native actors were recreated')
    except Exception as exc:
        invalidate(ad, f'actor_refresh: {type(exc).__name__}: {exc}')
        raise Unsupported('PSO mapping continuity changed; verify the controllers again in Pioneer 2') from exc
    if not stopped():
        proof.players = players
