"""Reusable, evidence-backed controls for an exact game revision and play mode.

Profiles are fetched from the authenticated control plane, never supplied by the
click. All fingerprints are checked again on the worker immediately before use.
"""
import hashlib
import json
import re
import threading

from pydantic import BaseModel, Field
from .models import Permission as P
from .registry import Unsupported, tool

PROFILE = 'game_live_controls'
TASK = 'game_live_controls_task'
CATEGORIES = {'items': 'Insert / spawn items', 'inventory': 'Add to inventory',
              'upgrades': 'Upgrade items', 'levels': 'Finish / skip level',
              'bosses': 'Set boss HP to zero', 'pedestrians': 'Rain pedestrians',
              'unlocks': 'Hidden characters, costumes, areas and extras'}
# Only native game operations belong here: never shell, launch, arbitrary calls,
# scripts, file edits, recursive tools, or a client-supplied tool/op.
NATIVE = {'pso_mods': {'give', 'item_set', 'floor_spawn', 'floor_rares', 'equip_any', 'stat'},
          're_inventory': {'give', 'set'}, 'gta_mods': {'ped_rain'},
          'sonic_adventure_2': {'finish_level', 'emblems'}, 'mgs_vr': {'complete', 'unlock_all'}}
_locks = {}
_guard = threading.Lock()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def integer(v, low, high, label):
    if type(v) is not int or not low <= v <= high:
        raise ValueError(f'{label}: expected an integer from {low} to {high}')
    return v


def guards(rows, revision=False):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 16:
        raise ValueError('Supply bounded revision fingerprints and mode guards')
    out = []
    for r in rows:
        address = integer(r.get('address'), 0, 0xFFFFFFFFFFFFFFFF, 'guard address')
        h = r.get('hex', '')
        if not isinstance(h, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}){1,128}', h):
            raise ValueError('Guard hex must contain 1–128 exact bytes')
        out.append({'address': address, 'hex': h.lower()})
    if revision and sum(len(r['hex']) // 2 for r in out) < 16:
        raise ValueError('Revision fingerprints need at least 16 bytes')
    return out


def parameters(rows):
    if not isinstance(rows, list) or len(rows) > 10:
        raise ValueError('At most ten parameters per action')
    out, seen = [], set()
    for r in rows:
        key = r.get('id', '')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key) or key in seen:
            raise ValueError('Parameter IDs must be unique identifiers')
        seen.add(key)
        row = {'id': key, 'label': text(r.get('label'), 'parameter label', 100), 'kind': r.get('kind')}
        if row['kind'] == 'integer':
            row['min'] = integer(r.get('min'), 0, 0xFFFFFFFF, 'minimum')
            row['max'] = integer(r.get('max'), row['min'], 0xFFFFFFFF, 'maximum')
            row['default'] = integer(r.get('default'), row['min'], row['max'], 'default')
        elif row['kind'] == 'choice':
            options = r.get('options')
            if not isinstance(options, list) or not 1 <= len(options) <= 2000:
                raise ValueError('Choice needs a bounded item/option database')
            row['options'] = [{'value': text(o.get('value'), 'option value', 100),
                               'label': text(o.get('label'), 'option label', 120)} for o in options]
            if len({o['value'] for o in row['options']}) != len(options):
                raise ValueError('Duplicate option values')
            row['default'] = r.get('default')
            if row['default'] not in {o['value'] for o in row['options']}:
                raise ValueError('Default must be a listed option')
        else:
            raise ValueError('Parameter kind must be integer or choice')
        out.append(row)
    return out


def text(v, label, limit=500):
    if not isinstance(v, str) or not v.strip() or len(v) > limit:
        raise ValueError(f'{label} must be nonempty text (up to {limit} characters)')
    return v.strip()


def validate(body, artifact_check):
    from .custom_build_unlocks import artifacts
    if not isinstance(body, dict) or not re.fullmatch('[0-9a-f]{64}', str(body.get('executable_sha256', ''))):
        raise ValueError('Pin the analyzed executable SHA256')
    out = {'executable_sha256': body['executable_sha256'],
           'revision_label': text(body.get('revision_label'), 'revision label'),
           'guards': guards(body.get('guards'), revision=True),
           'ghidra_artifacts': artifacts(artifact_check, body.get('ghidra_artifacts'), 'Ghidra analysis'),
           'runtime_artifacts': artifacts(artifact_check, body.get('runtime_artifacts'), 'Runtime verification'),
           'actions': []}
    actions = body.get('actions')
    if not isinstance(actions, list) or not 1 <= len(actions) <= 100:
        raise ValueError('Publish 1–100 tested actions')
    seen = set()
    for a in actions:
        key = a.get('id', '')
        if not re.fullmatch('[a-z][a-z0-9_]{0,59}', key) or key in seen:
            raise ValueError('Action IDs must be unique identifiers')
        seen.add(key)
        if a.get('category') not in CATEGORIES:
            raise ValueError('Unknown action category')
        row = {'id': key, 'category': a['category'], 'label': text(a.get('label'), 'action label', 120),
               'scope': text(a.get('scope'), 'exact mode / applicability'),
               'notes': text(a.get('notes'), 'effects / evidence / limitations', 2000),
               'guards': guards(a.get('guards')), 'parameters': parameters(a.get('parameters', []))}
        allowed = {p['id'] for p in row['parameters']}
        binding = a.get('binding') or {}
        if binding.get('kind') == 'memory':
            width = integer(binding.get('width'), 1, 4, 'write width')
            if width not in (1, 2, 4) or binding.get('byteorder') not in ('little', 'big'):
                raise ValueError('Use unsigned 8/16/32-bit fields and explicit byte order')
            address = integer(binding.get('address'), 0, 0xFFFFFFFFFFFFFFFF - width, 'write address')
            row['binding'] = {'kind': 'memory', 'address': address, 'width': width, 'byteorder': binding['byteorder']}
            if 'parameter' in binding:
                param = next((p for p in row['parameters'] if p['id'] == binding['parameter']), {})
                if param.get('kind') != 'integer' or param['max'] >= 1 << (8 * width):
                    raise ValueError('Memory value needs an integer parameter within the field width')
                row['binding']['parameter'] = param['id']
            else:
                row['binding']['value'] = integer(binding.get('value'), 0, (1 << (8 * width)) - 1, 'write value')
            # A write must never invalidate a version/mode guard itself.
            for g in out['guards'] + row['guards']:
                if address < g['address'] + len(bytes.fromhex(g['hex'])) and g['address'] < address + width:
                    raise ValueError('Write overlaps a fingerprint or mode guard')
        elif binding.get('kind') == 'native':
            name, inp = binding.get('tool'), binding.get('input')
            if name not in NATIVE or not isinstance(inp, dict) or inp.get('op') not in NATIVE[name]:
                raise ValueError('Use an approved native game tool and operation')
            if 'session_id' in inp or any(isinstance(v, (dict, list)) for v in inp.values()):
                raise ValueError('Native inputs are flat; session identity is injected by the worker')
            for v in inp.values():
                if isinstance(v, str) and v.startswith('$') and v[1:] not in allowed:
                    raise ValueError('Unknown native parameter')
            row['binding'] = {'kind': 'native', 'tool': name, 'input': inp}
        else:
            raise ValueError('Action needs a memory or native binding')
        out['actions'].append(row)
    return out


def check(ad, rows):
    for g in rows:
        expected = bytes.fromhex(g['hex'])
        if ad.read_memory(g['address'], len(expected)) != expected:
            return False
    return True


def values_for(action, values):
    if not isinstance(values, dict) or set(values) != {p['id'] for p in action['parameters']}:
        raise ValueError('Supply exactly the declared parameters')
    for p in action['parameters']:
        v = values[p['id']]
        if p['kind'] == 'integer':
            integer(v, p['min'], p['max'], p['label'])
        elif v not in [o['value'] for o in p['options']]:
            raise ValueError(f'{p["label"]}: choose a catalog entry')
    return values


def operate(ad, profile, game, inp, ctx):
    if game.get('game_id') != inp.game_id or profile.get('game_id') != inp.game_id:
        raise Unsupported('The selected session now belongs to another game')
    if profile.get('revision') != inp.revision:
        raise Unsupported('Research profile changed; refresh the controls')
    if not check(ad, profile['guards']):
        raise Unsupported('The running executable does not match the tested revision')
    if inp.op == 'inspect':
        return {'actions': [{'id': a['id'], 'available': check(ad, a['guards'])} for a in profile['actions']],
                'revision': profile['revision']}
    a = next((a for a in profile['actions'] if a['id'] == inp.action), None)
    if not a or not check(ad, a['guards']):
        raise Unsupported('Action is unavailable in this play mode or scene; refresh the controls')
    values = values_for(a, inp.values)
    b = a['binding']
    if b['kind'] == 'native':
        from .registry import REGISTRY
        native = REGISTRY[b['tool']]
        if reason := native.unavailable_reason(ctx.config):
            raise Unsupported(reason)
        args = {k: values[v[1:]] if isinstance(v, str) and v.startswith('$') else v for k, v in b['input'].items()}
        args['session_id'] = inp.session_id
        # Direct invocation avoids nested executor starvation and duplicate retries.
        result = native.Out.model_validate(native.fn(native.In.model_validate(args), ctx)).model_dump()
        detail = result.get('result', result)
        if isinstance(detail, dict) and (detail.get('error') or detail.get('verified') is False):
            raise Unsupported(str(detail.get('error') or 'Native action could not be verified'))
        return {'action': a['id'], 'result': result}
    before = ad.read_memory(b['address'], b['width'])
    if len(before) != b['width']:
        raise Unsupported('Cannot read the target field')
    value = values[b['parameter']] if 'parameter' in b else b['value']
    after = value.to_bytes(b['width'], b['byteorder'])
    ad.write_memory(b['address'], after)
    if ad.read_memory(b['address'], b['width']) != after:
        raise Unsupported('Game did not retain the requested value; no success recorded')
    return {'action': a['id'], 'verified': True, 'before': int.from_bytes(before, b['byteorder']), 'value': value}


class LiveIn(BaseModel):
    session_id: str
    game_id: str
    revision: str
    op: str = 'inspect'
    action: str = ''
    values: dict = Field(default_factory=dict)


class LiveOut(BaseModel):
    result: dict


@tool('game_live_controls', '1.0', LiveIn, LiveOut, capabilities=['runtime', 'memory'],
      permissions=[P.MEMORY_WRITE], timeout_s=120, retries=0)
def live_controls(inp, ctx):
    """Inspect or apply a published Ghidra-backed control for this exact session/revision/mode. No guessing addresses."""
    import httpx
    from .tools import SESSIONS
    if inp.op not in ('inspect', 'apply'):
        raise ValueError('Use inspect or apply')
    if not ctx.server:
        raise Unsupported('A control-plane profile is required')
    from urllib.parse import quote
    r = httpx.get(f'{ctx.server}/api/games/{quote(inp.game_id, safe="")}/live-controls', headers=ctx.headers, timeout=15)
    r.raise_for_status()
    profile = r.json().get('profile')
    if not profile:
        raise Unsupported('No tested live controls published for this game')
    with _guard:
        lock = _locks.setdefault(inp.session_id, threading.RLock())
    with lock:
        if inp.session_id not in SESSIONS:
            raise Unsupported('The selected game is no longer running here')
        ad, game = SESSIONS[inp.session_id]
        return {'result': operate(ad, profile, game, inp, ctx)}


class ResearchIn(BaseModel):
    game_id: str
    op: str = 'get'
    profile: dict = Field(default_factory=dict)


@tool('game_controls_research', '1.0', ResearchIn, LiveOut, permissions=[P.FILE_MUTATION], timeout_s=60, retries=0)
def research(inp, ctx):
    """Get discovered live controls (op=get), queue missing Ghidra research (discover), or publish tested findings
    (publish, profile object; docs/live-controls.md). Publishing requires executable SHA256, immutable revision
    guards, stored ghidra_artifacts/runtime_artifacts, and actions with category, scope, notes, mode guards,
    bounded parameters and memory/native binding. Never publish guessed or untested controls."""
    import httpx
    from urllib.parse import quote
    if not ctx.server or inp.op not in ('get', 'discover', 'publish'):
        raise Unsupported('Use get, discover or publish with a control-plane connection')
    url = f'{ctx.server}/api/games/{quote(inp.game_id, safe="")}/live-controls'
    if inp.op == 'get':
        response = httpx.get(url, headers=ctx.headers, timeout=30)
    else:
        response = httpx.post(url + ('/profile' if inp.op == 'publish' else '/discover'),
                             json=inp.profile if inp.op == 'publish' else {}, headers=ctx.headers, timeout=30)
    response.raise_for_status()
    return {'result': response.json()}
