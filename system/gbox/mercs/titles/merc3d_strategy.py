"""Merc3D level research binding. No speculative marker, barrel or rank RAM fields."""
from __future__ import annotations
import hashlib
from ...level_strategy import Runtime, Store
from ...level_strategy_web import MANUAL, GUIDE

GAME_ID = '0ed22ae742e1b56b'
TITLE = 'Resident Evil: The Mercenaries 3D'
# Original short summaries checked against Berserker's mission walkthrough.
# Native (level << 8)|tab is zero-based; a human mission label is not a RAM ID.
OBJECTIVES = {0x0000: 'Visit the active movement markers in sequence.',
              0x0001: 'Destroy every red explosive barrel.',
              0x0002: 'Defeat the Majini.',
              0x0100: 'Defeat 15 Town Majini.', 0x0101: 'Defeat 20 Town Majini.',
              0x0102: 'Defeat 25 Town Majini.',
              0x0200: 'Defeat 15 Town Majini, including parasite transformations.',
              0x0201: 'Defeat 10 Town Majini.', 0x0202: 'Defeat 20 Majini.',
              0x0203: 'Defeat 100 Majini.', 0x0204: 'Defeat Popokarimu.'}


def build_id():
    from .merc3d_3ds import CODE_SIGNATURE
    return 'merc3d-eur-code-prefix64:' + hashlib.sha256(CODE_SIGNATURE).hexdigest()


def context(snap, base=None):
    mid = snap.get('mission_id')
    if type(mid) is not int or not 0 <= mid <= 0xFFFF:
        return None
    level, tab = mid >> 8, mid & 255
    targets = {str(e.get('class')): {'enemy_class': e['class']} for e in snap.get('enemies', ())
               if e.get('class') and (e.get('hp') or 0) > 0}
    return {'game_id': GAME_ID, 'build': build_id(), 'mod': '', **(base or {}),
            'title': TITLE, 'platform': 'Nintendo 3DS', 'level': f'{level+1}-{tab+1}',
            'objective': OBJECTIVES.get(mid, 'Read this exact mission objective from a cited guide and verify it in play.'),
            'required_action': {0: 'follow_markers', 1: 'destroy_barrels'}.get(mid),
            'actions': ['defeat_enemies', 'defeat_boss', 'verify_result'], 'targets': targets,
            'source_urls': [MANUAL, GUIDE, 'https://tasvideos.org/Forum/Topics/23732'],
            'limitations': ['No verified movement-marker or explosive-barrel reader.',
                'No native result-rank encoding; objective end alone is not B-rank clear or unlock.',
                'No native laser or wall mesh; current combat uses guarded close-range input.',
                'Route landmark labels require native grounding before navigation.']}


def runtime(m, clock):
    from .merc3d_3ds import CODE_SIGNATURE
    try:
        if m.rd(0x100000, len(CODE_SIGNATURE)) != CODE_SIGNATURE:
            return None
    except (OSError, ValueError, RuntimeError):
        return None
    ad = getattr(m, 'adapter', None)
    root = getattr(ad, '_level_strategy_root', None)
    config = getattr(ad, 'config', None)
    if root is None and config is not None:
        root = config.data_dir / 'level-strategy'
    binding = {'session_id': None}
    def observed(snap):
        # A persisted enable belongs to a game, but the plan also belongs to its
        # modification. Resolve this adapter's live registration each time;
        # never assume an unlabelled mod is the base game after a restart.
        from ...tools import SESSIONS
        matches = [(sid, game) for sid, (adapter, game) in SESSIONS.items() if adapter is ad]
        if len(matches) != 1:
            return None
        sid, game = matches[0]
        if game.get('game_id') != GAME_ID:
            return None
        binding['session_id'] = sid
        return context(snap, {'game_id': game['game_id'], 'mod': str(game.get('mod') or '')})
    network = lambda: 'network' in getattr(config, 'granted_permissions', ())
    def research(ctx, _, previous):
        from ...level_strategy_service import transport
        if config is None or not config.public_url or not binding['session_id']:
            raise ValueError('No authenticated strategy authority is available')
        remote = transport(config.public_url, {'Authorization': 'Bearer ' + config.token(),
                           'X-GBox-Actor': 'level-strategy'}, binding['session_id'], network)
        return remote(ctx, {}, previous)
    return Runtime(observed,
                   store=Store(root) if root else Store(), clock=clock, research=research,
                   network_allowed=network)


def native_context(ad, game):
    from . import merc3d_3ds as M
    class Memory:
        def rd(self, address, length):
            return ad.read_memory(address, length)
    m = Memory()
    if m.rd(0x100000, len(M.CODE_SIGNATURE)) != M.CODE_SIGNATURE:
        raise ValueError('Merc3D executable signature does not match the verified reader')
    snap = M.snapshot(m)
    ctx = context(snap, {'game_id': game['game_id'], 'mod': str(game.get('mod') or '')})
    if not ctx:
        raise ValueError('Native Merc3D mission is unavailable')
    return ctx, snap
