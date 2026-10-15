"""Reusable, evidence-backed controls for an exact game revision and play mode.

Profiles are fetched from the authenticated control plane, never supplied by the
click. All fingerprints are checked again on the worker immediately before use.
"""
import hashlib
import json
import math
import re
import threading
import time

from pydantic import BaseModel, Field
from .models import Permission as P
from .registry import Unsupported, tool

PROFILE = 'game_live_controls'
TASK = 'game_live_controls_task'
COMMAND = 'game_live_controls_command'
CATEGORIES = {'items': 'Insert / spawn items', 'inventory': 'Add to inventory',
              'upgrades': 'Upgrade items', 'levels': 'Finish / skip level',
              'bosses': 'Set boss HP to zero', 'pedestrians': 'Rain pedestrians',
              'movement': 'Walk through walls and obstacles', 'checkpoints': 'Warp to next checkpoint',
              'ammunition': 'Unlimited ammunition', 'projectiles': 'Weapon projectile overrides',
              'unlocks': 'Hidden characters, costumes, areas and extras'}
REQUESTED_CONTROLS = ('noclip', 'give_item', 'finish_level', 'next_checkpoint',
                      'infinite_ammo', 'rocket_pistol')
DISCOVERY_SCHEMA = 2
# Only native game operations belong here: never shell, launch, arbitrary calls,
# scripts, file edits, recursive tools, or a client-supplied tool/op.
NATIVE = {'pso_mods': {'give', 'item_set', 'floor_spawn', 'floor_rares', 'equip_any', 'stat'},
          're_inventory': {'give', 'set'}, 'gta_mods': {'ped_rain'},
          'auf_live': {'noclip', 'give_item', 'finish_level', 'next_checkpoint', 'infinite_ammo', 'rocket_pistol'},
          'sonic_adventure_2': {'finish_level', 'emblems'}, 'mgs_vr': {'complete', 'unlock_all'}}
# Read-only inspectors have separately reviewed contracts, not a profile-supplied
# operation. Only these adapters may back true stateful switches.
NATIVE_INSPECT = {'auf_live': 'inspect'}
NATIVE_SWITCHES = {'auf_live': {'noclip', 'infinite_ammo', 'rocket_pistol'}}
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
        elif row['kind'] == 'boolean':
            if type(r.get('default')) is not bool:
                raise ValueError('Boolean parameters need an explicit true/false default')
            row['default'] = r['default']
        else:
            raise ValueError('Parameter kind must be integer, choice or boolean')
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
            if {'session_id', 'command_id', 'expires'} & set(inp) or any(isinstance(v, (dict, list)) for v in inp.values()):
                raise ValueError('Native inputs are flat; session identity is injected by the worker')
            for v in inp.values():
                if isinstance(v, str) and v.startswith('$') and v[1:] not in allowed:
                    raise ValueError('Unknown native parameter')
            row['binding'] = {'kind': 'native', 'tool': name, 'input': inp}
            if 'state_key' in binding:
                key = binding['state_key']
                if key not in NATIVE_SWITCHES.get(name, set()) or key != inp['op']:
                    raise ValueError('State key must name this operation in an approved native inspector')
                row['binding']['state_key'] = key
        else:
            raise ValueError('Action needs a memory or native binding')
        control = a.get('control', 'button')
        if control not in ('button', 'toggle'):
            raise ValueError('Control must be a button or toggle')
        if control == 'toggle':
            parameter = a.get('toggle_parameter')
            param = next((p for p in row['parameters'] if p['id'] == parameter), {})
            if param.get('kind') != 'boolean' or row['binding']['kind'] != 'native':
                raise ValueError('A toggle needs a boolean parameter and a tested native adapter')
            if not any(v == '$' + parameter for v in row['binding']['input'].values()):
                raise ValueError('Toggle parameter must control the native operation')
            if 'state_key' not in row['binding']:
                raise ValueError('A toggle needs an inspected native state key')
            row.update(control='toggle', toggle_parameter=parameter)
        elif 'toggle_parameter' in a:
            raise ValueError('Only toggles may declare a toggle parameter')
        elif 'state_key' in row['binding']:
            raise ValueError('Only toggles may declare a native state key')
        out['actions'].append(row)
    if 'assessments' in body:
        assessments = body['assessments']
        if not isinstance(assessments, dict) or len(assessments) > len(CATEGORIES):
            raise ValueError('Use bounded category applicability assessments')
        out['assessments'] = {}
        for category, assessment in assessments.items():
            if category not in CATEGORIES or not isinstance(assessment, dict):
                raise ValueError('Unknown assessment category')
            status = assessment.get('status')
            if status not in ('unsupported', 'not_relevant', 'research_pending'):
                raise ValueError('Assessment status must describe an unresolved or inapplicable capability')
            if any(a['category'] == category for a in out['actions']) and status != 'research_pending':
                raise ValueError('An unavailable category cannot also contain a published action')
            out['assessments'][category] = {'status': status,
                'scope': text(assessment.get('scope'), 'assessment scope'),
                'reason': text(assessment.get('reason'), 'assessment reason', 2000)}
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
        elif p['kind'] == 'boolean':
            if type(v) is not bool:
                raise ValueError(f'{p["label"]}: expected true or false')
        elif v not in [o['value'] for o in p['options']]:
            raise ValueError(f'{p["label"]}: choose a catalog entry')
    return values


def current_command(inp):
    """Late UI commands must not mutate a different moment of a running game."""
    now = time.time()
    if (not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', inp.command_id)
            or not math.isfinite(inp.expires) or not now < inp.expires <= now + 30):
        raise Unsupported('This control command expired; refresh and activate it again')


def inspect_actions(ad, profile, inp, ctx):
    from .registry import REGISTRY
    inspected, actions = {}, []
    for action in profile['actions']:
        row = {'id': action['id'], 'available': check(ad, action['guards'])}
        binding = action['binding']
        name = binding.get('tool') if binding['kind'] == 'native' else None
        if row['available'] and name in NATIVE_INSPECT:
            if name not in inspected:
                try:
                    native = REGISTRY[name]
                    if reason := native.unavailable_reason(ctx.config):
                        raise Unsupported(reason)
                    result = native.Out.model_validate(native.fn(native.In.model_validate(
                        {'op': NATIVE_INSPECT[name], 'session_id': inp.session_id}), ctx)).model_dump()
                    detail = result.get('result', result)
                    if detail.get('error') or detail.get('verified') is False:
                        raise Unsupported(str(detail.get('error') or 'Native revision is unavailable'))
                    inspected[name] = (detail, '')
                except Exception as exc:
                    # A read-only probe failing makes actions unavailable; it must
                    # never fall back to defaults or silently execute another op.
                    inspected[name] = ({}, str(exc))
            detail, reason = inspected[name]
            row['available'] = detail.get('available', {}).get(binding['input']['op']) is True
            operation_reason = (detail.get('unavailable_reasons') or {}).get(binding['input']['op'])
            if not row['available'] and isinstance(operation_reason, str):
                row['reason'] = operation_reason[:2000]
            if reason:
                row['reason'] = reason
            if name == 'auf_live' and binding['input']['op'] == 'give_item':
                item = binding['input'].get('item')
                parameter = next((p for p in action['parameters']
                                  if p['kind'] == 'choice' and item == '$' + p['id']), None)
                catalog = detail.get('items')
                if parameter and isinstance(catalog, list):
                    loaded = {r.get('id') for r in catalog[:2000] if isinstance(r, dict) and isinstance(r.get('id'), str)}
                    row['item_choices'] = {'parameter': parameter['id'],
                                           'values': [o['value'] for o in parameter['options'] if o['value'] in loaded]}
                    if not row['item_choices']['values']:
                        row['available'] = False
                        row['reason'] = row.get('reason') or 'No reviewed item choices are loaded in this mission'
                else:
                    row['available'] = False
                    row['reason'] = row.get('reason') or 'The loaded mission item catalog is unavailable'
            if action.get('control') == 'toggle':
                value = detail.get('switches', {}).get(binding['state_key'])
                if type(value) is bool:
                    row['value'] = value
                else:
                    row['available'] = False
                    row['reason'] = reason or 'The current switch state could not be verified'
        actions.append(row)
    return actions


def operate(ad, profile, game, inp, ctx):
    if game.get('game_id') != inp.game_id or profile.get('game_id') != inp.game_id:
        raise Unsupported('The selected session now belongs to another game')
    if profile.get('revision') != inp.revision:
        raise Unsupported('Research profile changed; refresh the controls')
    if not check(ad, profile['guards']):
        raise Unsupported('The running executable does not match the tested revision')
    if inp.op == 'inspect':
        return {'actions': inspect_actions(ad, profile, inp, ctx),
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
        # Existing adapters retain their schemas. New latency-sensitive adapters
        # repeat these checks after acquiring their own pause/transaction locks.
        for field in ('command_id', 'expires'):
            if field in native.In.model_fields:
                args[field] = getattr(inp, field)
        # Direct invocation avoids nested executor starvation and duplicate retries.
        current_command(inp)
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
    current_command(inp)
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
    command_id: str = ''
    expires: float = 0


class LiveOut(BaseModel):
    result: dict


@tool('game_live_controls', '1.0', LiveIn, LiveOut, capabilities=['runtime', 'memory'],
      permissions=[P.MEMORY_WRITE], timeout_s=120, retries=0)
def live_controls(inp, ctx):
    """Inspect/apply published exact-revision controls. Apply needs unique command_id and expires (Unix time, <=30s ahead); prefer the live-controls/run API which supplies these. No guessed addresses or stale queued mutations."""
    import httpx
    from .tools import SESSIONS
    if inp.op not in ('inspect', 'apply'):
        raise ValueError('Use inspect or apply')
    if inp.op == 'apply':
        current_command(inp)
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


@tool('game_controls_research', '1.0', ResearchIn, LiveOut, permissions=[P.READ, P.STAGE], timeout_s=60, retries=0,
      side_effects=['Publishes evidence-backed control-plane profiles or queues saved research requests'])
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
