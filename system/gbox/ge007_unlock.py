"""GoldenEye 007 (PC port + bots) on-load unlock profile (request #2874, game_id 6e4d417eef84e49b).

Mechanism: the port's own ``Game.AllUnlocked`` ini setting (jkdansereau/goldeneye-pc-port, commit pinned in
SOURCE_EVIDENCE). It is a query-time RAM override: every solo level at every difficulty reads COMPLETED
(file2.c), cheats read unlocked (file2.c fileGetIsCheatUnlocked), and the 007 / all-levels debug flags are seeded
(port/src/main.c portAllUnlockedApply). The save (data/ge007.eep) is never read or written, so there is nothing
to corrupt; rollback restores the ini key. Original ROM is untouched.

Status is deliberately ``candidate_pending_verification``: static source evidence only, no runtime selection of
every item yet (see NEXT_STEP). Nothing here runs REA/Ghidra; that stays in the background task.
"""
from __future__ import annotations
import json
import re
import shutil
from pathlib import Path

GAME_ID = '6e4d417eef84e49b'
PORT_ID = 'ge007'
ROM_SHA1 = 'abe01e4aeb033b6c0836819f549c791b26cfde83'   # 007 - GoldenEye (USA), the only ROM the port builds for
SECTION, KEY, VALUE = 'Game', 'AllUnlocked', '1'
SOURCE_EVIDENCE = {
    'repo': 'https://github.com/jkdansereau/goldeneye-pc-port',
    'commit': 'fda76b69837e6c5aae436e0d3e798989e49b06d2',
    'files': {
        'port/src/video.c': 'configRegisterInt("Game.AllUnlocked", &portAllUnlocked, 0, 1)',
        'src/game/file2.c': 'fileGetIsCheatUnlocked and stage-status queries return unlocked/COMPLETED when portAllUnlocked',
        'port/src/main.c': 'portAllUnlockedApply seeds debug_enable_all_levels_flag + debug_007_unlock_flag (LEFTOVERDEBUG builds only)',
        'src/game/front.c': 'unlock_stage_select/unlock_chars/unlock_game_length/unlock_weapon_select/unlock_handicap/'
                            'unlock_control_style/unlock_aim_sight default TRUE; 007 mode gated by fileIs007ModeUnlocked || debug flag',
    },
}
CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages', 'costumes', 'items', 'extras')
# Entry statuses: unlocked_by_override (static evidence), not_present, unknown (needs runtime proof).
INVENTORY = {
    'characters': [{'name': 'multiplayer roster', 'status': 'unknown', 'note': 'MP char select gated by unlock_chars (TRUE); roster size unverified at runtime'}],
    'hidden_characters': [{'name': 'CHEAT_EXTRA_MP_CHARS', 'status': 'unlocked_by_override', 'evidence': 'cheat id 1 via fileGetIsCheatUnlocked'}],
    'modes': [{'name': '007 mode', 'status': 'unlocked_by_override', 'evidence': 'debug_007_unlock_flag seeded; front.c:3155'},
              {'name': 'cheat menu', 'status': 'unlocked_by_override', 'evidence': 'file2.c D442 override'}],
    'levels': [{'name': 'all solo levels (SP_LEVEL_DAM..SP_LEVEL_MAX)', 'status': 'unlocked_by_override',
                'evidence': 'stage status COMPLETED at every difficulty (file2.c)'}],
    'stages': [{'name': 'multiplayer arenas', 'status': 'unlocked_by_override', 'evidence': 'unlock_stage_select TRUE (front.c:756)'}],
    'costumes': [{'name': 'costumes/heads', 'status': 'unknown', 'note': 'no lock check found yet; model-swap mods are a separate feature'}],
    'items': [{'name': 'Magnum, Laser, Golden Gun, Silver/Gold PP7 cheat weapons', 'status': 'unlocked_by_override',
               'evidence': 'cheat unlock checks compare against COMPLETED; cheat ids CHEAT_MAGNUM..CHEAT_GOLD_PP7'}],
    'extras': [{'name': 'cheats (CHEAT_UNLOCK_* set)', 'status': 'unlocked_by_override', 'evidence': 'fileGetIsCheatUnlocked'}],
}
NEXT_STEP = ('Boot the port on i9-NUC/Spark (idle, 2% audio, isolated data dir) with Game.AllUnlocked=1, select every '
             'solo level, 007 mode, every cheat and MP arena/character; record results; test 2nd launch + rollback; '
             'resolve the unknown entries (MP roster, costumes) via REA/Ghidra on the owned build.')


def profile() -> dict:
    return {'status': 'pending_verification', 'profile': 'ge007-port-allunlocked-ini-v1', 'verified': False,
            'game_id': GAME_ID, 'scope': list(CATEGORIES), 'mechanism': f'{SECTION}.{KEY}={VALUE} in data/ge007.ini',
            'rom_sha1': ROM_SHA1, 'evidence': SOURCE_EVIDENCE, 'inventory': INVENTORY,
            'save_effect': 'none: query-time override, ge007.eep never read or written',
            'reason': 'Static source evidence only; not runtime-verified for every category.', 'next': NEXT_STEP}


def ini_path(config) -> Path:
    return Path(config.runtime) / 'ports' / PORT_ID / 'src' / 'data' / 'ge007.ini'


def _current(path: Path):
    if not path.is_file():
        return None
    sec = None
    for line in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'\s*\[([^\]]+)\]\s*$', line)
        if m:
            sec = m.group(1)
            continue
        kv = re.match(r'\s*([^=;#]+?)\s*=\s*(.*?)\s*$', line)
        if kv and sec == SECTION and kv.group(1) == KEY:
            return kv.group(2)
    return None


def apply(path: Path) -> dict:
    """Set Game.AllUnlocked=1, keeping a one-time backup of the ini beside it. Idempotent; settings preserved."""
    from . import native_ports
    path = Path(path)
    if not path.is_file():
        return {'applied': False, 'state': 'pending_build', 'reason': f'port ini not present: {path}'}
    backup = path.with_name(path.name + '.gbox-unlock.bak')
    if not backup.exists():
        shutil.copy2(path, backup)
    changed = native_ports.pin_ini(path, {SECTION: {KEY: VALUE}})
    return {'applied': _current(path) == VALUE, 'state': 'applied_unverified', 'changed': changed, 'backup': str(backup)}


def rollback(path: Path) -> dict:
    path = Path(path)
    backup = path.with_name(path.name + '.gbox-unlock.bak')
    if not backup.is_file():
        return {'restored': False, 'reason': 'no backup'}
    shutil.copy2(backup, path)
    backup.unlink()
    return {'restored': True, 'AllUnlocked': _current(path)}


def pre_launch(ctx) -> dict:
    try:
        res = apply(ini_path(ctx.config))
    except Exception as exc:
        return {'state': 'failed', 'applied': False, 'reason': str(exc)[:500]}
    return {**res, 'profile': 'ge007-port-allunlocked-ini-v1', 'scope': list(CATEGORIES), 'verified': False}
