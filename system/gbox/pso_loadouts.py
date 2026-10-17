"""Source-backed PSO item references and loadouts, resolved against the owned disc.

No web list supplies RAM addresses or unvalidated item codes. Research is separate
from mutation: a resolved list uses the existing session-pinned, verified drop RPC.
"""
import hashlib
import re
import time
import uuid
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, Field

from .models import Permission
from .registry import Unsupported, tool

WIKI = 'https://wiki.pioneer2.net'
GUIDE = 'https://www.pso-world.com/sections.php?artid=2350&op=viewarticle'
EQUIPMENT = 'https://www.pso-world.com/sections.php?artid=2307&op=viewarticle'
ES_SOURCE = 'https://wiki.pioneer2.net/w/ES_weapons'
SPECIALS = ('No special', 'Jellen', 'Zalure', 'HP Revival', 'TP Revival', 'Burning', 'Tempest',
            'Blizzard', 'Arrest', 'Chaos', 'Hell', 'Spirit', 'Berserk', "Demon's", 'Gush', 'Geist', "King's")
# Verified original V3 code semantics; not Ephinea's cosmetic skin variants.
ES_CLASSES = set(range(0x70, 0x89)) | set(range(0xA5, 0xAA))
# Article titles whose spelling differs from the on-disc text. Remaining titles
# use title case; absent reference images are visibly omitted, never substituted.
TITLES = {'TSUMIKIRI J-SWORD': 'Tsumikiri_J-Sword', 'HEAVEN PUNISHER': 'Heaven_Punisher',
          'SANGE & YASHA': 'Sange_&_Yasha', 'L&K14 COMBAT': 'L&K14_Combat',
          'M&A60 VISE': 'M&A60_Vise', 'YASMINKOV 9000M': 'Yasminkov_9000M',
          'OROTIAGITO': 'Orotiagito', 'NEI\'S CLAW': "Nei's_Claw", 'J-CUTTER': 'ES_J-Cutter'}
PRESETS = {
    'community': {'label': 'Community powerful-weapon shortlist', 'sources': [GUIDE, EQUIPMENT],
        'names': ['Tsumikiri J-Sword', 'Black King Bar', 'Sange & Yasha', 'Double Cannon',
                  'Spread Needle', 'Guld Milla', 'Frozen Shooter', 'Heaven Punisher', 'Vjaya', 'Psycho Wand'],
        'note': 'A mixed-role community shortlist, not a universal damage ranking. Specials, targets and class matter.'},
    'hunter': {'label': 'Hunter damage and utility kit', 'sources': [GUIDE, EQUIPMENT],
        'names': ['Tsumikiri J-Sword', 'Black King Bar', 'Sange & Yasha', 'Double Cannon', 'Demolition Comet',
                  'Chain Sawd', 'Rainbow Baton', 'Red Sword', 'Vjaya', 'Red Handgun', 'God Hand', 'Yamigarasu'],
        'note': 'Melee damage, crowd attacks, recovery and ranged coverage; only this disc and class are included.'},
    'ranger': {'label': 'Ranger damage and utility kit', 'sources': [GUIDE, EQUIPMENT],
        'names': ['Spread Needle', 'Frozen Shooter', 'Guld Milla', 'Heaven Punisher', 'Yasminkov 9000M',
                  'Snow Queen', 'Baranz Launcher', "Bringer's Rifle", 'Red Mechgun', 'Red Handgun', 'Panzer Faust'],
        'note': 'Ranged damage and control. Frozen Shooter/Snow Queen are utility choices, not the highest ATP.'},
    'force': {'label': 'Force technique and support kit', 'sources': [GUIDE, EQUIPMENT],
        'names': ['Psycho Wand', 'Summit Moon', 'Magical Piece', 'Striker of Chao', 'Caduceus',
                  'Club of Laconium', 'Mace of Adaman', 'Club of Zumiuran', 'Fire Scepter: Agni',
                  'Ice Staff: Dagon', 'Storm Wand: Indra', 'Demonic Fork'],
        'note': 'Technique/support tools; raw weapon ATP does not measure technique effectiveness.'},
    'atp': {'label': 'Top distinct weapons by maximum-grind ATP', 'sources': [], 'names': [],
        'note': 'Computed from this disc: ATP max + 2 × maximum grind. This is not DPS or special-attack ranking.'},
}


def normalized(name):
    return re.sub(r'[^a-z0-9]', '', str(name).lower().replace('s-rank', 'es').replace('s rank', 'es'))


def enrich(row, version):
    """Preserve the native name/code while adding explicit family/special labels."""
    row = dict(row)
    name = row['name']
    code = bytes.fromhex(row['code'])
    es = code[0] == 0 and code[1] in ES_CLASSES
    family = ('S-Rank ' + name.title()) if es else name
    variant = SPECIALS[code[2]] if es and code[2] < len(SPECIALS) else f'Variant {code[2]:02X}'
    row.update(version=version, family_name=family, family_key=f'{row["cat"]}:{normalized(family)}',
               variant_name=variant if es else f'Item {row["code"]}',
               display_name=f'{family} — {variant}' if es else name, s_rank=es)
    if row.get('cat') == 'Weapons':
        row['max_grind_atp'] = row.get('atp_max', 0) + 2 * row.get('max_grind', 0)
        title = ('ES_' + name.title().replace(' ', '_')) if es else TITLES.get(name.upper(), name.title().replace(' ', '_'))
        filename = title + '.png'
        digest = hashlib.md5(filename.encode()).hexdigest()  # MediaWiki filename layout, not a security hash.
        row['reference_url'] = WIKI + '/w/' + quote(title, safe='_\'-')
        row['thumbnail_url'] = f'{WIKI}/images/{digest[0]}/{digest[:2]}/' + quote(filename, safe='_\'-')
        row['reference_note'] = 'Wiki image reference. Stats and availability below come from your disc; Ephinea balance can differ.'
    return row


def presets():
    return [{'id': key, **value} for key, value in PRESETS.items()]


def source_urls(values):
    result = []
    for value in values:
        parts = urlsplit(value)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or len(value) > 1000:
            raise ValueError('Research sources must be public HTTPS article URLs')
        # Sources are provenance only. Never fetch or execute a submitted URL.
        if value not in result:
            result.append(value)
    return result


def plan(rows, version, preset='community', character_class='', count=10, names=None, sources=None):
    from .psoitems import CLASSES
    if version not in ('gc', 'dcv2'):
        raise ValueError('Choose GameCube or Dreamcast Ver. 2')
    if not 1 <= count <= 20:
        raise ValueError('Choose between 1 and 20 items')
    if character_class and character_class not in list(CLASSES)[:9 if version == 'dcv2' else 12]:
        raise ValueError('Choose a class present in this PSO version')
    if names is None and preset not in PRESETS:
        raise ValueError('Choose a researched preset or supply exact researched item names')
    meta = PRESETS.get(preset, PRESETS['community']) if names is None else {
        'label': 'Imported researched list', 'note': 'Only unambiguous, disc-present names are included.', 'sources': []}
    requested = names if names is not None else meta['names']
    if len(requested) > 20:
        raise ValueError('A researched list can contain up to 20 names per drop')
    if any(not isinstance(name, str) or not name.strip() or len(name) > 160 for name in requested):
        raise ValueError('Each researched item needs a nonempty name or code, up to 160 characters')
    candidates = [r for r in rows if not character_class or character_class in r.get('classes', [])]
    selected, missing, incompatible, ambiguous = [], [], [], []
    seen = set()
    if preset == 'atp' and names is None:
        ordered = sorted((r for r in candidates if r['cat'] == 'Weapons'),
                         key=lambda r: (-r.get('max_grind_atp', r.get('atp_max', 0) + 2*r.get('max_grind', 0)),
                                        -r.get('ata', 0), r['code']))
        for row in ordered:
            family = row.get('family_key', normalized(row['name']))
            if family not in seen:
                seen.add(family)
                selected.append(row)
            if len(selected) >= count:
                break
    else:
        for value in requested:
            key = normalized(value)
            exact = [r for r in rows if key in {normalized(r['code']), normalized(r.get('display_name', '')),
                     normalized(r.get('family_name', r['name'])), normalized(r['name'])}]
            if not exact:
                missing.append(value)
                continue
            compatible = [r for r in exact if r in candidates]
            if not compatible:
                incompatible.append(value)
                continue
            # A family name selects its no-special/base variant; a special's full
            # display name selects that exact code. Unrelated same-name items need a code.
            families = {r.get('family_key', r['code'][:4]) for r in compatible}
            if len(families) > 1:
                ambiguous.append(value)
                continue
            row = sorted(compatible, key=lambda r: r['code'])[0]
            if row['code'] not in seen and len(selected) < count:
                selected.append(row)
                seen.add(row['code'])
    warnings = []
    if not character_class:
        warnings.append('No class filter selected; this list can include equipment your character cannot normally use.')
    if missing:
        warnings.append('Not present on this disc: ' + ', '.join(missing))
    if incompatible:
        warnings.append('Excluded for this class: ' + ', '.join(incompatible))
    if ambiguous:
        warnings.append('Ambiguous names; choose an exact item code: ' + ', '.join(ambiguous))
    if len(selected) < count:
        warnings.append(f'{len(selected)} distinct compatible items resolved; no unavailable items or duplicates were invented to reach {count}.')
    return {'version': version, 'label': meta['label'], 'character_class': character_class or None,
            'items': selected, 'codes': [r['code'] for r in selected], 'requested_count': count,
            'sources': source_urls(list(meta['sources']) + list(sources or [])),
            'note': meta['note'], 'warnings': warnings, 'missing': missing, 'incompatible': incompatible,
            'ambiguous': ambiguous, 'researched_on': '2026-10-15'}


class LoadoutIn(BaseModel):
    session_id: str = ''
    op: str = Field(default='plan', pattern='^(plan|drop)$')
    version: str = Field(default='gc', pattern='^(gc|dcv2)$')
    preset: str = 'community'
    character_class: str = ''
    count: int = Field(default=10, ge=1, le=20)
    names: list[str] | None = Field(default=None, max_length=20)
    source_urls: list[str] = Field(default_factory=list, max_length=10)
    radius: float = Field(default=18, ge=5, le=100, allow_inf_nan=False)
    max_grind: bool = True


class LoadoutOut(BaseModel):
    result: dict


@tool('pso_loadout', '1.0', LoadoutIn, LoadoutOut, capabilities=['runtime', 'memory'],
      permissions=[Permission.READ], timeout_s=25, retries=0)
def pso_loadout(inp, ctx):
    """PSO researched tier lists/build drops. plan returns an exact disc/class-matched list.

    For 'best/strongest weapons', research PSO-World for the running GameCube or
    Dreamcast version with web_search, then provide names and source_urls. Built-in
    presets: community, hunter, ranger, force; atp is a measured ATP-only ranking.
    drop sends one of each planned item through the verified live PSO channel,
    requires session_id and memory_write; online play/unknown revisions are refused.
    A timed-out mutation is never retried. Never claim a universal DPS ranking or
    copy Blue Burst-only items/skins/balance onto GC/DC.
    """
    import httpx
    if not ctx or not ctx.server:
        raise Unsupported('Connect to Spark to resolve the owned-disc item database')
    version = inp.version
    with httpx.Client(headers=ctx.headers, timeout=12) as client:
        if inp.session_id:
            sessions = client.get(ctx.server + '/api/sessions');sessions.raise_for_status()
            session = next((s for s in sessions.json() if (s.get('session_id') or s.get('id')) == inp.session_id), None)
            if not session or session.get('state') != 'running':
                raise ValueError('Choose a running PSO session')
            game = client.get(ctx.server + '/api/catalog/' + session['game_id']);game.raise_for_status()
            from .pso_controls import is_pso
            entry = game.json()
            if not is_pso(entry) or entry.get('platform') not in ('gamecube', 'dreamcast'):
                raise ValueError('Choose a running GameCube or Dreamcast PSO session')
            version = 'gc' if entry['platform'] == 'gamecube' else 'dcv2'
        response = client.get(ctx.server + '/api/pso/items', params={'version': version});response.raise_for_status()
        result = plan(response.json(), version, inp.preset, inp.character_class, inp.count, inp.names, inp.source_urls)
        if inp.op == 'drop':
            if not inp.session_id:
                raise ValueError('A running PSO session_id is required to drop items')
            if Permission.MEMORY_WRITE not in ctx.config.granted_permissions:
                raise PermissionError('memory_write permission is required to drop items')
            if not result['codes']:
                raise ValueError('No compatible owned-disc items resolved; nothing was dropped')
            body = {'op': 'pso_controls', 'args': {'command_id': str(uuid.uuid4()), 'expires': time.time() + 8,
                'input': {'session_id': inp.session_id, 'op': 'floor_spawn', 'codes': result['codes'],
                          'radius': inp.radius, 'max_grind': inp.max_grind, 'count': len(result['codes'])}}}
            try:
                reply = client.post(ctx.server + '/api/sessions/' + quote(inp.session_id, safe='') + '/rpc', json=body)
                reply.raise_for_status()
            except httpx.TimeoutException as error:
                raise TimeoutError('Drop outcome is unknown. Check the game; this command was not retried.') from error
            result['drop'] = reply.json()
            result['verified'] = result['drop'].get('verified') is True
    return {'result': result}
