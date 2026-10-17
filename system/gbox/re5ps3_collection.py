"""Exact-build, two-target RE5 PS3 collection adapter; no game asset writer.

Only PARAM.SFO, EBOOT.BIN and the normal Chris/Sheva packs are read. Archived
sources are unpacked once to a bounded four-file cache, never a full game tree.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from .re5ps3_arc import Arc, sha
from .re5ps3_models import GAME_ID, TITLE_ID, export_archive
from .re5ps3_roles import CHRIS_MODEL, SHEVA_MODEL, NATIVE_ROLES, ROLE_VERSION

READER_VERSION = 2
_LOCK = threading.Lock()
SFO = 'PS3_GAME/PARAM.SFO'
EBOOT = 'PS3_GAME/USRDIR/EBOOT.BIN'
PACK_ROOT = 'PS3_GAME/USRDIR/nativePS3/Image/Archive/'
CHRIS = PACK_ROOT + 'uPl00ChrisNormal.arc'
SHEVA = PACK_ROOT + 'uPl01ShebaNormal.arc'
# Byte identities measured from the owned BLUS30491 disc, not filename guesses.
FILES = {
    SFO: (1040, 'c736989af229f1696e676af2f1aafc3716e0f254e3b544decb23cfec4b3b30aa'),
    EBOOT: (25067328, 'a0c06e58f8c590ee27ab0fee90d97de5973623a8e38f5f67f626719a590bbb2c'),
    CHRIS: (8852180, '51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867'),
    SHEVA: (8357231, '27ce670e29438738d024e5ec5a7b729ea5da19eab98a668ada42da9630d92d6f'),
}


def roster():
    return [dict(key=key, slug=slug, name=name, aliases=aliases, kind='character')
            for key, slug, name, aliases in (
                (CHRIS, 're5ps3_chris_normal', 'Chris Redfield (RE5 PS3 normal)', ['Chris', 'RE5 Chris']),
                (SHEVA, 're5ps3_sheva_normal', 'Sheva Alomar (RE5 PS3 normal)', ['Sheva', 'RE5 Sheva']))]


def collection_scope():
    return {'scope': 'two_normal_player_models', 'known_targets': 2, 'full_cast': False,
            'native_formats': ['PS3 ARC v8', 'MOD 156 revision 1', 'TEX 102'],
            'lod_mask': 1, 'textures': 'diffuse only', 'semantic_roles': '18 exact-source offline body anchors',
            'native_model_writer': False, 'gameplay_verified': False,
            'native_asset_writer': 'transactional fixed-layout MOD/TEX edits only',
            'pending': ['other costumes, NPCs, enemies and cutscenes', 'native animations and motion compatibility',
                        'arbitrary donor topology and Sonic/Mario fitting', 'unlock and live inventory/equip validation']}


def needs_refresh(meta):
    """An old/unproven model must not bypass exact-source extraction on reuse."""
    source = meta.get('source') or {}
    evidence = meta.get('native_evidence') or {}
    rig = meta.get('rig') or {}
    if not all(isinstance(v, dict) for v in (source, evidence, rig)):
        return True
    member = evidence.get('archive_member')
    target = next((r['key'] for r in roster() if meta.get('slug') in
                   (r['slug'], r['slug'] + '_' + GAME_ID)), None)
    model = r'pawn\pl\pl00\model\pl0000' if member == CHRIS else r'pawn\pl\pl01\model\pl0100'
    model_hash = CHRIS_MODEL if member == CHRIS else SHEVA_MODEL
    roles = evidence.get('role_evidence') or {}
    if not isinstance(roles, dict):
        return True
    return not (meta.get('re5ps3_reader') == READER_VERSION and
                source.get('game_id') == GAME_ID and source.get('platform') == 'ps3' and
                meta.get('role_mapping_policy') == 'explicit_only' and
                not rig.get('roles_guessed') and target is not None and target == member and
                meta.get('native_coverage') == collection_scope() and member in (CHRIS, SHEVA) and
                evidence.get('game_id') == GAME_ID and evidence.get('title_id') == TITLE_ID and
                evidence.get('disc_version') == '02.00' and evidence.get('app_version') == '01.00' and
                evidence.get('model_member') == model and
                evidence.get('source_sha256') == model_hash and
                roles.get('version') == ROLE_VERSION and roles.get('source_model_sha256') == model_hash and
                roles.get('native_joint_ids') == NATIVE_ROLES[model_hash] and
                roles.get('roles') == {r: f'j{j:03d}' for r, j in NATIVE_ROLES[model_hash].items()} and
                evidence.get('archive_sha256') == FILES[member][1] and
                evidence.get('source_files_sha256') == {m: FILES[m][1] for m in (SFO, EBOOT, member)})


def _identity(src):
    st = src.stat()
    return {'path': str(src.resolve()), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}


def _read(path, member):
    expected_size, digest = FILES[member]
    if not path.is_file() or path.stat().st_size != expected_size:
        raise ValueError(f'{member}: missing or wrong size for exact {TITLE_ID} build')
    with path.open('rb') as stream:
        data = stream.read(expected_size + 1)
    if len(data) != expected_size or sha(data) != digest:
        raise ValueError(f'{member}: SHA256 differs from exact {TITLE_ID} owned build')
    return data


def _folder(src, member):
    # Catalogs may point at the game folder, PS3_GAME, or its boot executable.
    if src.name == 'EBOOT.BIN' and src.parent.name == 'USRDIR':
        src = src.parent.parent
    root = src if src.name == 'PS3_GAME' else src / 'PS3_GAME'
    root = root.resolve()
    path = root / member.removeprefix('PS3_GAME/')
    if not path.resolve().is_relative_to(root):
        raise ValueError(f'{member}: source member escapes PS3_GAME')
    return path


def _archive_cache(src, cache, progress):
    """Select exact members under one PS3_GAME root; 7z e flattens four files.

    Missing/bad character packs remain per-target failures. Identity files must
    both be present, and are rehashed before every model export, even on cache hits.
    """
    from .rom_archives import members, seven_zip
    identity = _identity(src)
    key = sha(json.dumps(identity, sort_keys=True).encode())[:24]
    base = Path(cache) / 're5ps3-native'
    out = base / key
    marker = out / 'source.json'
    with _LOCK:
        if marker.is_file():
            record = json.loads(marker.read_text(encoding='utf8'))
            if record.get('source') != identity:
                raise ValueError('RE5 native cache source identity mismatch')
            return out, record
        entries = members(src)
        if len(entries) > 20000:
            raise ValueError('RE5 archive member count exceeds limit')
        roots = [e['name'][:-len(SFO)] for e in entries if
                 e['name'] == SFO or e['name'].endswith('/' + SFO)]
        if len(roots) != 1:
            raise ValueError('expected one exact PS3_GAME/PARAM.SFO archive member')
        prefix = roots[0]
        selected = {}
        errors = {}
        for member, (size, _digest) in FILES.items():
            hits = [e for e in entries if e['name'] == prefix + member]
            if len(hits) != 1 or hits[0]['size'] != size:
                errors[member] = 'missing, ambiguous or wrong-size exact member'
            else:
                selected[member] = hits[0]['name']
        if any(name.startswith('@') for name in selected.values()):
            raise ValueError('RE5 archive member cannot be a 7-Zip listfile argument')
        if SFO in errors or EBOOT in errors:
            raise ValueError('RE5 exact build identity files unavailable: ' + str(errors))
        base.mkdir(parents=True, exist_ok=True)
        progress(25, 'Reading four native RE5 source members (solid 7z may take several minutes)')
        with tempfile.TemporaryDirectory(prefix='partial-', dir=base) as temp:
            work = Path(temp)
            # No wildcards, recursive extraction or output member paths. Archive
            # listing rejects links and traversal; e writes only these flat names.
            args = [seven_zip(), 'e', '-y', '-spd', '-ssc', '-bb0', '-bso0', '-bsp0', f'-o{work}', '--',
                    str(src.resolve()), *selected.values()]
            try:
                result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=1800,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('RE5 native member extraction timed out; no complete cache published') from exc
            if result.returncode:
                raise ValueError(f'RE5 exact member extraction failed (7z exit {result.returncode})')
            for member in selected:
                path = work / Path(member).name
                if path.is_symlink() or not path.is_file() or path.stat().st_size != FILES[member][0]:
                    raise ValueError(f'{member}: incomplete native member extraction')
            if _identity(src) != identity:
                raise ValueError('RE5 source changed during extraction')
            record = {'source': identity, 'members': selected, 'errors': errors}
            (work / 'source.json').write_text(json.dumps(record), encoding='utf8')
            try:
                os.rename(work, out)
            except OSError:
                # Another process completed this immutable source key first.
                if not marker.is_file():
                    raise
                existing = json.loads(marker.read_text(encoding='utf8'))
                if existing != record:
                    raise ValueError('RE5 concurrent cache identity mismatch')
        return out, record


def extract_run(ctx, game, entry, work):
    from .characters import _rom
    if game.get('game_id') != GAME_ID or game.get('platform') != 'ps3':
        raise ValueError('RE5 collection requires exact PS3 game e7ca89bbeb67360d / BLUS30491')
    row = next((r for r in roster() if r['key'] == entry.get('key')), None)
    if row is None:
        raise ValueError('unknown RE5 PS3 native target')
    src = _rom(ctx, game)
    if src.suffix.lower() == '.7z':
        cache, record = _archive_cache(src, ctx.config.cache, ctx.progress)
        member = row['key']
        if member in record['errors']:
            raise ValueError(f'{member}: {record["errors"][member]}')
        paths = {m: cache / Path(m).name for m in (SFO, EBOOT, member)}
        source = record['source'] | {'kind': '7z exact members',
                                     'members': {m: record['members'][m] for m in paths}}
    elif src.is_dir() or src.name == 'EBOOT.BIN':
        paths = {m: _folder(src, m) for m in (SFO, EBOOT, row['key'])}
        source = {'path': str(src.resolve()), 'kind': 'folder game',
                  'members': {m: str(p) for m, p in paths.items()}}
    else:
        raise ValueError('RE5 collection needs the owned folder game, EBOOT.BIN or its .7z archive')
    # Do not substitute sibling titles, ports, costumes or modified inputs.
    hashes = {}
    pack = None
    for member, path in paths.items():
        data = _read(path, member)
        hashes[member] = sha(data)
        if member == row['key']:
            pack = data
    model = r'pawn\pl\pl00\model\pl0000' if row['key'] == CHRIS else r'pawn\pl\pl01\model\pl0100'
    output = Path(work) / (row['slug'] + '.glb')
    result = export_archive(Arc(pack), model, output, lod=1)
    result.update(game_id=GAME_ID, title_id=TITLE_ID, disc_version='02.00', app_version='01.00',
                  source=source, source_files_sha256=hashes, archive_member=row['key'])
    roles = result.get('role_evidence')
    if not roles:
        raise ValueError('exact native model is missing verified offline body roles')
    return {'files': [output], 'roles': roles['roles'], 'tool': 'gbox.re5ps3_collection',
            'source_files': [f'{m} SHA256 {h}' for m, h in hashes.items()] + [model],
            'notes': 'Native PS3 normal player model, LOD mask 1, diffuse textures and original weighted numeric joints. '
                     'Only Chris/Sheva normal models are covered. Eighteen exact-source body anchors were verified '
                     'by controlled offline poses. Native animation compatibility remains unverified; '
                     'bounded MOD/TEX edits do not establish a full cast swap, unlock/inventory or gameplay acceptance.',
            'extra': {'re5ps3_reader': READER_VERSION, 'native_evidence': result,
                      'native_coverage': collection_scope(), 'role_mapping_policy': 'explicit_only'}}
