"""Read-only probe of the XIII (USA) GameCube unlock surface (gamecode GX3E41).

Everything here is grounded in the owned GameCube revision of XIII (USA) and was
verified against the extracted disc and its executable:

  * main.dol is 3,689,120 bytes, sha256
    6ecfde6dad73b52049c39292555a09c6b430fb5c57ad2047f9e40b953df6d041.
  * The playable roster is config driven, not save driven: System/MSL.ini lists
    the ten selectable skins (SkinReadableName/SkinName/SkinCode/CodeMesh) and
    System/custom.txt lists the solo and multiplayer map rosters.
  * The persistent surface is the Unreal Engine 2 profile save: main.dol
    contains the format string "Save%i.usa" plus the profile keys
    "profilestats", "SavePath", "SaveExt" and "SaveBind".
  * The shipped Gecko code list for GX3E41 holds four gameplay cheats
    (Infinite Health, Infinite Ammo, Can Breath Underwater, Super Speed).
    None of them is a content unlock, so no cheat-held unlock profile is
    published for this title.

This module never writes a save, a ROM, a config file or a progress flag. It
exists so an unlock routine can be revision-guarded: it names the exact roster
inventory, the exact config digests, the exact save-naming surface and the
evidence that is still missing before any writer may run.
"""
from __future__ import annotations

import base64
import hashlib
import re

GAME_ID = '4f32cfd9649d71cf'
PLATFORM = 'gamecube'
GAME_CODE = 'GX3E41'
DOL_SHA256 = '6ecfde6dad73b52049c39292555a09c6b430fb5c57ad2047f9e40b953df6d041'
DOL_SIZE = 3689120
CATEGORIES = ('characters', 'skins', 'levels', 'modes', 'extras')

# Byte-exact copies of the two owned config files, stored so the probe stays
# reviewable without the disc. The digests below are the revision guard.
CONFIG_BASE64 = {
    'System/MSL.ini': 'W0VuZ2luZS5NZXNoU2tpbkxpc3RdDQpNZXNoU2tpbkxpc3RJbmZvPShTa2luUmVhZGFibGVOYW1lPSJYSUlJIixTa2luTmFtZT0iWElJSVBlcnNvcy5YSUlJTWlsaXRNIixTa2luQ29kZT0iUzEzTSIsU0tpblJlZD0iWElJSVBlcnNvcy5NdWxfWElJSU1pbGl0X1JvdWdlVGV4IixTa2luQmx1ZT0iWElJSVBlcnNvcy5NdWxfWElJSU1pbGl0X0JsZXVUZXgiLENvZGVNZXNoPTkpDQpNZXNoU2tpbkxpc3RJbmZvPShTa2luUmVhZGFibGVOYW1lPSJTaGlueWFrdSIsU2tpbk5hbWU9IlhJSUlQZXJzb3MuRGFuaHN1TSIsU2tpbkNvZGU9IkRBTkgiLFNLaW5SZWQ9IlhJSUlQZXJzb3MuTXVsX2RhbmhzdV9yb3VnZVRFWCIsU2tpbkJsdWU9IlhJSUlQZXJzb3MuTXVsX2RhbmhzdV9ibGV1VEVYIixDb2RlTWVzaD0xNCkNCk1lc2hTa2luTGlzdEluZm89KFNraW5SZWFkYWJsZU5hbWU9IlRyeXN0YW4iLFNraW5OYW1lPSJYSUlJUGVyc29zLlNjYW5kaU0iLFNraW5Db2RlPSJTQ0FOIixTS2luUmVkPSJYSUlJUGVyc29zLk11bF9zY2FuZGlfcm91Z2VURVgiLFNraW5CbHVlPSJYSUlJUGVyc29zLk11bF9zY2FuZGlfYmxldVRFWCIsQ29kZU1lc2g9MjkpDQpNZXNoU2tpbkxpc3RJbmZvPShTa2luUmVhZGFibGVOYW1lPSJDYXJyaW5ndG9uIixTa2luTmFtZT0iWElJSVBlcnNvcy5DYXJyaW5ndG9uTSIsU2tpbkNvZGU9IkNBUlIiLFNLaW5SZWQ9IlhJSUlQZXJzb3MuTXVsX0NhcnJpbmd0b25fcm91Z2VURVgiLFNraW5CbHVlPSJYSUlJUGVyc29zLk11bF9DYXJyaW5ndG9uX2JsZXVURVgiLENvZGVNZXNoPTE2KQ0KTWVzaFNraW5MaXN0SW5mbz0oU2tpblJlYWRhYmxlTmFtZT0iSm9obiIsU2tpbk5hbWU9IlhJSUlQZXJzb3MuR2FtaW5NIixTa2luQ29kZT0iR0FNSSIsU0tpblJlZD0iWElJSVBlcnNvcy5NdWxfZ2FtaW5fcm91Z2VURVgiLFNraW5CbHVlPSJYSUlJUGVyc29zLk11bF9nYW1pbl9ibGV1VEVYIixDb2RlTWVzaD0xMykNCk1lc2hTa2luTGlzdEluZm89KFNraW5SZWFkYWJsZU5hbWU9IkRlbnNldHN1IixTa2luTmFtZT0iWElJSVBlcnNvcy5OaWhlaU0iLFNraW5Db2RlPSJOSUhFIixTS2luUmVkPSJYSUlJUGVyc29zLk11bF9uaWhlaV9yb3VnZVRFWCIsU2tpbkJsdWU9IlhJSUlQZXJzb3MuTXVsX25paGVpX2JsZXVURVgiLENvZGVNZXNoPTYpDQpNZXNoU2tpbkxpc3RJbmZvPShTa2luUmVhZGFibGVOYW1lPSJSb2dlciIsU2tpbk5hbWU9IlhJSUlQZXJzb3MuRnJlbmNoeU0iLFNraW5Db2RlPSJGUjFNIixTS2luUmVkPSJYSUlJUGVyc29zLk11bF9GcmVuY2h5X3JvdWdlVEVYIixTa2luQmx1ZT0iWElJSVBlcnNvcy5NdWxfRnJlbmNoeV9ibGV1VEVYIixDb2RlTWVzaD0zNCkNCk1lc2hTa2luTGlzdEluZm89KFNraW5SZWFkYWJsZU5hbWU9IlJvYmVydCIsU2tpbk5hbWU9IlhJSUlQZXJzb3MuRnJlbmNoeTJNIixTa2luQ29kZT0iRlIyTSIsU0tpblJlZD0iWElJSVBlcnNvcy5NdWxfRnJlbmNoeTJfcm91Z2VURVgiLFNraW5CbHVlPSJYSUlJUGVyc29zLk11bF9GcmVuY2h5Ml9ibGV1VEVYIixDb2RlTWVzaD0yOCkNCk1lc2hTa2luTGlzdEluZm89KFNraW5SZWFkYWJsZU5hbWU9IkFybWFlbCIsU2tpbk5hbWU9IlhJSUlQZXJzb3MuUmFzdGFNIixTa2luQ29kZT0iUkFTVCIsU0tpblJlZD0iWElJSVBlcnNvcy5NdWxfcmFzdGFfcm91Z2VURVgiLFNraW5CbHVlPSJYSUlJUGVyc29zLk11bF9yYXN0YV9ibGV1VEVYIixDb2RlTWVzaD04KQ0KTWVzaFNraW5MaXN0SW5mbz0oU2tpblJlYWRhYmxlTmFtZT0iTW9uZ29vc2UiLFNraW5OYW1lPSJYSUlJUGVyc29zLk1hbmdvdXN0ZU0iLFNraW5Db2RlPSJNT05HIixTS2luUmVkPSJYSUlJUGVyc29zLk11bF9NYW5nb3VzdGVfcm91Z2VURVgiLFNraW5CbHVlPSJYSUlJUGVyc29zLk11bF9NYW5nb3VzdGVfYmxldVRFWCIsQ29kZU1lc2g9MjcpDQo=',
    'System/custom.txt': 'TUFQU19TT0xPDQptYXBtZW51CQkoNTEyLDMwKQ0KYW1vczAxCQkoNDA5NiwxMDAwKQ0KYmFucXVlMDEJKDEwMjQsMTAwMCkNCmJhc2UwMQkJKDE1MDAsMTIwMCkNCmJhdGVhdTAxCSgxMDI0LDUwMCkNCmh1YWwwMWEJCSgxMDI0LDkwMCkNCmh1YWwwMWIJCSgxMDI0LDkwMCkNCmh1YWwwMgkJKDEwMjQsMjAwMCkNCmh1YWwwNGEJCSgxMDI0LDgwMCkNCmh1YWwwNGMJCSgxMDI0LDgwMCkNCmtlbGxvMDFhCSgxMDI0LDEwMDApDQprZWxsbzAxYgkoMjA0OCw4MDApDQpwYWxhY2UwMQkoMTAyNCwxMDAwKQ0KcGxhZ2UwMAkJKDEwMjQsNTAwKQ0KcGxhZ2UwMQkJKDIwNDgsOTAwKQ0KcHJvY2swMWEJKDUxMiwxMDAwKQ0KcHJvY2swMwkJKDEwMjQsMTEwMCkNCnByb2NrMDRhCSgxMDI0LDgwMCkNCnByb2NrMDRiCSg1MTIsODAwKQ0Kc2FuYzAxCQkoMTAyNCw5MDApDQpzYW5jMDJhCQkoMTAyNCw4MDApDQpzYW5jMDJiCQkoMTAyNCwxMDAwKQ0Kc2FuYzAzCQkoMjA0OCw2MDApDQpzbWFyaW4wMQkoMTAyNCwxNzAwKQ0Kc21hcmluMDIJKDIwNDgsMjQwMCkNCnNwYWRzMDEJCSgxMDI0LDcwMCkNCnNwYWRzMDJhCSgxMDI0LDEzMDApDQpzcGFkczAyYgkoMTAyNCwxMTAwKQ0Kc3NoMTAxYQkJKDEwMjQsMTEwMCkNCnNzaDEwMWIJCSgxMDI0LDkwMCkNCnNzaDEwMWMJCSgxMDI0LDgwMCkNCnNzaDEwMmIJCSgxMDI0LDgwMCkNCnRvaXRzMDEJCSgxMDI0LDk1MCkNCnVzYTAxCQkoMTAyNCw5MDApDQp1c2EwMgkJKDEwMjQsMTAwMCkNCg0KTUFQU19NVUxUSQ0KY3RmX2Jhc2UJKDEwMjQpDQpjdGZfaHVhbAkoMTAyNCkNCmN0Zl9zYW5jCSgxMDI0KQ0KY3RmX3Nub3cJKDEwMjQpDQpjdGZfdGVtcGxlCSgxMDI0KQ0KY3RmX3RlbXBsZXBybwkoMTAyNCkNCmN0Zl90ZXN0Ym90CSgxMDI0KQ0KY3RmX3RvaXRzCSgxMDI0KQ0KZG1fYW1vcwkJKDQwOTYpDQpkbV9iYW5xdWUJKDQwOTYpDQpkbV9iYXNlCQkoNDA5NikNCmRtX2Jhc2UyCSg0MDk2KQ0KZG1faHVhbDA0YQkoMTAyNCkNCmRtX2h1YWwxCSg0MDk2KQ0KZG1fbG9zdHRlbXBsZQkoMTAyNCkNCmRtX3BhbAkJKDIwNDgpDQpkbV9wcm9jawkoMjA0OCkNCmRtX3Byb2NrMDFhCSgxMDI0KQ0KZG1fc20wMQkJKDEwMjQpDQpkbV9zcGFkcwkoMTAyNCkNCmRtX3VzYTAxCSgxMDI0KQ0KZG1fdXNhMl9kZW1vCSgxMDI0KQ0KZG1fd2FyZWhvdXNlCSgxMDI0KQ0K',
}
CONFIG_SHA256 = {
    'System/MSL.ini': '90cedfff8d68dc887d6be70e122d654d49e0023a330999688cdc7cfad09f9a05',
    'System/custom.txt': '904f6ea0aee29bf31c9b247ab7b949d9fe2f8d3026bb2fb41ba8a90d9e2f2199',
}

# File offsets of the relevant strings inside the 3,689,120-byte main.dol.
DOL_STRING_OFFSETS = {
    'Save%i.usa': (0x33c5cf, 0x33c907),
    'custom.txt': (0x343954,),
    'profilestats': (0x33f62c,),
    'SavePath': (0x344530,),
    'SaveExt': (0x3828e0,),
    'SaveBind': (0x342028,),
}


def config_bytes(name: str) -> bytes:
    """Byte-exact content of an owned config file of this revision."""
    try:
        return base64.b64decode(CONFIG_BASE64[name])
    except KeyError:
        raise KeyError('unknown XIII config file: ' + name) from None


def config_digest(name: str) -> str:
    """sha256 of an owned config file of this revision."""
    return hashlib.sha256(config_bytes(name)).hexdigest()


def config_ok(name: str) -> bool:
    """True when the stored config copy still matches its pinned digest."""
    return name in CONFIG_SHA256 and config_digest(name) == CONFIG_SHA256[name]


def character_inventory() -> list:
    """The ten selectable skins this revision exposes (System/MSL.ini)."""
    out = []
    for line in config_bytes('System/MSL.ini').decode('latin-1').splitlines():
        if not line.startswith('MeshSkinListInfo='):
            continue
        kv = dict(re.findall(r'([A-Za-z]+)="([^"]*)"', line))
        mesh = re.search(r'CodeMesh=(\d+)', line)
        out.append({
            'name': kv.get('SkinReadableName', ''),
            'skin': kv.get('SkinName', ''),
            'code': kv.get('SkinCode', ''),
            'code_mesh': int(mesh.group(1)) if mesh else None,
        })
    return out


def map_inventory() -> dict:
    """Solo and multiplayer map rosters (System/custom.txt)."""
    out = {'solo': [], 'multi': []}
    section = None
    for line in config_bytes('System/custom.txt').decode('latin-1').splitlines():
        text = line.strip()
        if not text:
            continue
        if text == 'MAPS_SOLO':
            section = 'solo'
            continue
        if text == 'MAPS_MULTI':
            section = 'multi'
            continue
        if section is None:
            continue
        match = re.match(r'^(\S+)\s*\(([^)]*)\)$', text)
        if match:
            out[section].append({'name': match.group(1), 'budget': match.group(2)})
    return out


def category_inventory() -> dict:
    """Category counts that a runtime unlock routine would have to cover."""
    chars = character_inventory()
    maps = map_inventory()
    return {
        'characters': len(chars),
        'skins': len(chars),
        'levels': len(maps['solo']) + len(maps['multi']),
        'modes': len(maps['multi']),
        'extras': 0,
    }


def save_name_pattern() -> str:
    """The UE2 profile save name template this revision formats."""
    return 'Save%i.usa'


def profile_gate() -> dict:
    """Honest, unverified gate for the XIII (USA) unlock scope."""
    return {
        'verified': False,
        'reason': ('XIII (USA) GX3E41: the roster and map inventory and the UE2 '
                   'profile save surface are mapped and digest-pinned, but no '
                   'unlock writer exists and no category entry has been '
                   'runtime-verified.'),
        'categories': list(CATEGORIES),
        'evidence': {
            'executable': 'main.dol sha256 ' + DOL_SHA256,
            'executable_size': DOL_SIZE,
            'game_code': GAME_CODE,
            'roster': 'System/MSL.ini sha256 ' + CONFIG_SHA256['System/MSL.ini'],
            'maps': 'System/custom.txt sha256 ' + CONFIG_SHA256['System/custom.txt'],
            'save_surface': 'UE2 profile save template Save%i.usa plus profile '
                            'keys profilestats/SavePath/SaveExt/SaveBind',
            'dol_string_offsets': ', '.join(
                name + '@' + hex(offsets[0]) for name, offsets in DOL_STRING_OFFSETS.items()),
            'cheat_codes': 'four gameplay cheats only (GX3E41 gecko list); no '
                           'content-unlock code exists for this title',
            'inventory': category_inventory(),
        },
        'blockers': [
            'The per-entry meaning of the profile save is not mapped: the byte '
            'layout of the UE2 profilestats blob inside Save%i.usa is still '
            'unknown, so no unlock flag can be named or written.',
            'No runtime acceptance has been performed: no boot, no character or '
            'map selection, no second-launch persistence check, no rollback.',
            'Whether the profile save is written to the memory card or to an '
            'internal file is not confirmed on the owned revision.',
        ],
        'next': ('Boot XIII (USA) on an idle agent worker (i9-NUC or the Spark, '
                 '2 percent audio), capture the Save%i.usa profile blob before '
                 'and after selecting each roster entry, map the byte that flips '
                 'per entry, then implement a revision-guarded writer and verify '
                 'it with a second launch plus a rollback to the original save.'),
    }
