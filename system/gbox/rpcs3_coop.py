"""Opt-in local controller2 routing, independent of the operator's controller1.

Preparation configures only the next launch. No live handler reload is assumed.
Configuration verification is not native second-player gameplay verification.
"""
import hashlib
import json
import re
from pathlib import Path

import yaml

from .registry import Unsupported

KEYPAD = dict(zip(
    ('cross','circle','square','triangle','l1','r1','l2','r2','l3','r3','start','select',
     'dup','ddown','dleft','dright','lup','ldown','lleft','lright','rup','rdown','rleft','rright'),
    (*('F'+str(i) for i in range(13,25)), *'0123456789', '[', ']')))
VK = {**{'F'+str(i):0x70+i-1 for i in range(13,25)}, '[':0xDB, ']':0xDD}
XKEYS = {'[':'bracketleft',']':'bracketright'}
CONFIG_NAME = 'gbox-local-partner'


def marker(adapter):
    home=getattr(adapter,'home',None)
    if home is None:raise Unsupported('An existing RPCS3 runtime profile is required to save controller2 preparation')
    return Path(home)/'gbox-controller2-preparation.json'


def preparation(adapter):
    try:
        path=marker(adapter)
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('version')==1 and data.get('player')==2 and type(data.get('enabled')) is bool \
                and data.get('home')==str(Path(adapter.home).resolve()):return data
    except (OSError,ValueError,TypeError,Unsupported):pass
    return None


def without_owned_p2(text,names):
    data=yaml.safe_load(text)
    if not isinstance(data,dict):raise Unsupported('Existing controller configuration is invalid')
    expected={'Handler':'Keyboard','Device':'Keyboard',
        'Config':{**{name:KEYPAD[key] for name,key in names},'PS Button':''}}
    if data.get('Player 2 Input')==expected:data.pop('Player 2 Input')
    return yaml.safe_dump(data,sort_keys=False)


def configuration(text, names):
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or not isinstance(data.get('Player 1 Input'), dict):
        raise Unsupported('Player1 controller configuration is unavailable; it was not changed')
    for name, player in data.items():
        if name == 'Player 2 Input' or not isinstance(player, dict) or player.get('Handler') != 'Keyboard':
            continue
        bindings = player.get('Config') or {}
        if not isinstance(bindings, dict):
            raise Unsupported('Existing keyboard bindings could not be verified')
        tokens={part.strip().casefold() for value in bindings.values()
                for part in re.split(r'[+,]',str(value))}
        if tokens & {key.casefold() for key in KEYPAD.values()}:
            raise Unsupported('Controller2 keyboard bindings conflict with another player; controller1 was not changed')
    data['Player 2 Input'] = {'Handler':'Keyboard','Device':'Keyboard',
        'Config':{**{name:KEYPAD[key] for name,key in names},'PS Button':''}}
    return yaml.safe_dump(data, sort_keys=False)


def prepare(adapter, player=2, enabled=True):
    if type(player) is not int or player != 2:
        raise Unsupported('Teammate control is restricted to controller2')
    if type(enabled) is not bool:raise Unsupported('Controller2 preparation requires a boolean enabled value')
    path=marker(adapter);path.parent.mkdir(parents=True,exist_ok=True)
    data={'version':1,'player':2,'enabled':enabled,'home':str(Path(adapter.home).resolve())}
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data),encoding='utf-8');temporary.replace(path)
    adapter.teammate_player = 2 if enabled else None
    if not enabled:
        return {'prepared':False,'verified':False,'requires_relaunch':True,'player':2,'enabled':False,
                'reason':'Controller2 preparation disabled for future launches; current controller1 is unchanged'}
    status = readiness(adapter)
    if status['prepared']:
        return status
    return {'prepared':False,'verified':False,'requires_relaunch':True,'player':2,'enabled':True,
            'reason':'Controller2 preparation saved for the next launch; current controller1 is unchanged'}


def install(adapter, path, text, names):
    """Called before native launch; preserve the full selected P1 configuration."""
    adapter._teammate_pad_launch = None
    adapter._teammate_pad_config = None
    saved=preparation(adapter)
    if getattr(adapter,'teammate_player',None) != 2 and not (saved and saved['enabled']):
        return None
    path = Path(path)
    output = configuration(text,names)
    path.write_text(output,encoding='utf-8')
    raw = path.read_bytes()
    if yaml.safe_load(raw) != yaml.safe_load(output):
        raise Unsupported('Controller2 configuration readback differed')
    adapter._teammate_pad_config = {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
    return path


def launched(adapter):
    config = getattr(adapter,'_teammate_pad_config',None)
    if config and adapter.proc and adapter.proc.poll() is None:
        adapter._teammate_pad_launch = dict(config,pid=adapter.proc.pid)


def readiness(adapter):
    result = {'prepared':False,'verified':False,'requires_relaunch':True,'player':2,
              'reason':'This launch has no verified independent controller2 configuration'}
    record = getattr(adapter,'_teammate_pad_launch',None)
    proc = getattr(adapter,'proc',None)
    try:
        if record and proc and proc.poll() is None and proc.pid == record['pid'] \
                and hashlib.sha256(Path(record['path']).read_bytes()).hexdigest() == record['sha256']:
            result.update(prepared=True,verified=True,requires_relaunch=False,
                reason='Controller2 launch configuration verified; native second-player readiness is checked separately')
    except (OSError,KeyError,TypeError):
        pass
    return result


def events(adapter, rows, player, aliases):
    """Validate the entire batch before any key is posted; never fall back to P1."""
    if type(player) is not int or player != 2 or not readiness(adapter)['verified']:
        raise Unsupported('A verified independent controller2 launch is required; no input was sent')
    if not isinstance(rows,list) or len(rows)>128:
        raise Unsupported('Controller2 input batch exceeds its bound; no input was sent')
    result = []
    for row in rows:
        if not isinstance(row,dict) or row.get('player',2) != 2 or type(row.get('player',2)) is not int:
            raise Unsupported('Teammate input may only address controller2; no input was sent')
        key = aliases.get(row.get('key'),row.get('key'))
        if key not in KEYPAD:
            raise Unsupported('Unknown controller2 button; no input was sent')
        if type(row.get('down',True)) is not bool:
            raise Unsupported('Invalid controller2 button state; no input was sent')
        result.append((KEYPAD[key],row.get('down',True)))
    return result
