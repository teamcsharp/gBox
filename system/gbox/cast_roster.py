"""Read-only visual cast inventory; roster rows are not invented writer slots."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote

from . import cast_swap as CS, characters as C, char_coverage as CC


def _same_source(meta, gid):
    return (meta.get('source') or {}).get('game_id') == gid


def _assets(meta, root):
    """Only expose URLs the existing character-file routes can actually serve."""
    result = {'preview_url': None, 'model_url': None, 'model': None, 'format': None}
    slug = meta.get('slug')
    if not re.fullmatch(r'[a-f0-9]{16}', str((meta.get('source') or {}).get('game_id') or '')) \
            or not isinstance(slug, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,180}', slug):
        return result
    try:
        base = (root / slug).resolve()
        if base.parent != root.resolve():
            return result
        preview = base / 'preview.png'
        if preview.is_file() and preview.stat().st_size and preview.resolve().is_relative_to(base):
            result['preview_url'] = f'/api/characters/{quote(slug, safe="")}/preview'
        name = str(meta.get('model') or '').replace('\\', '/')
        relative = PurePosixPath(name)
        if not name or relative.is_absolute() or '..' in relative.parts or ':' in name:
            return result
        model = (base / name).resolve()
        if model.is_relative_to(base) and model.is_file() and model.stat().st_size:
            result.update(model=name, format=model.suffix.lower().lstrip('.'),
                model_url=f'/api/characters/{quote(slug, safe="")}/file/' + '/'.join(quote(p, safe='') for p in relative.parts))
    except (OSError, ValueError):
        pass
    return result


def _registered(config, game, chars):
    """Use the title's real reader roster without triggering collection or jobs."""
    for name, test, roster, _run in C.DEDICATED:
        try:
            matches = test((game.get('title') or '').lower(), game.get('platform'))
        except Exception:
            continue
        if not matches:
            continue
        try:
            entries = C.dedicated_entries(config, game, name, roster)
        except Exception as error:
            return [], [f'Registered {name} roster could not be read: {type(error).__name__}']
        by_slug = {m.get('slug'): m for m in chars}
        out = []
        for raw in entries:
            entry = dict(raw)
            slug = entry.get('slug')
            # Legacy _same_game permits equal display titles. This read-only
            # inventory never attaches another edition/platform's collection.
            if slug in by_slug and not _same_source(by_slug[slug], game['game_id']):
                entry['slug'] = f"{slug}_{game['game_id']}"
            out.append(entry)
        return out, []
    return [], []


def _roster_entries(config, game, chars):
    registered, issues = _registered(config, game, chars)
    actual = {m['slug']: m for m in chars if m.get('slug') and _same_source(m, game['game_id'])
              and m.get('kind') != 'environment'}
    rows, seen = [], set()
    for entry in registered:
        slug = entry.get('slug')
        if slug in seen or entry.get('kind') == 'environment':
            continue
        seen.add(slug)
        rows.append((entry, actual.get(slug)))
    rows.extend((meta, meta) for slug, meta in actual.items() if slug not in seen)
    return rows, issues


def _row(entry, meta, root, gid):
    slug = (meta or entry).get('slug')
    identity = slug or hashlib.sha256(json.dumps(entry, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return {'id': 'roster:' + identity, 'slot': None, 'name': entry.get('name') or slug or 'Registered character',
            'slug': slug, 'kind': entry.get('kind') or 'character', 'source_game_id': gid,
            'groups': list(entry.get('groups') or []),
            **(_assets(meta, root) if meta else {'preview_url': None, 'model_url': None, 'model': None, 'format': None}),
            'buildable': False}


def _roster_scope(rows, scope):
    if scope.lower().strip() in ('', 'all', 'everyone', '*'):
        return rows
    tokens = [part.strip().lower() for part in scope.split(',') if part.strip()]
    return [row for row in rows if any(
        (token == 'main' and row['kind'] in CS.MAIN_KINDS)
        or row['kind'] == CS.KIND_WORDS.get(token, token)
        or token in {str(group).lower() for group in row.get('groups') or []}
        or token in (row['id'].lower(), str(row.get('slug') or '').lower()) for token in tokens)]


def roster(game, chars, root, config, source='', source_game=None, slots='all'):
    """Union native slots and exact-title roster; never call plan/build/refresh."""
    root = Path(root)
    gid = game['game_id']
    writer = CC.writer_for(game)
    writer_name = (writer or {}).get('writer')
    routed = bool(writer and writer.get('routed'))
    combined = routed and CS.strategy(writer_name)[0] != 'single'
    all_native = CS.slot_rows(game)
    try:
        native = CS.filter_slots(all_native, slots)
    except ValueError:
        native = []
    entries, issues = _roster_entries(config, game, chars)
    exact = {meta['slug']: meta for _entry, meta in entries if meta}
    targets, consumed = [], set()
    for slot in native:
        # Only a declared collection identity can enrich a native slot. A
        # generic player slot does not stand for the title's entire cast.
        slug = slot.get('slug') or slot.get('collection_slug')
        meta = exact.get(slug)
        if meta:
            consumed.add(slug)
        targets.append({'id': slot['slot'], 'slot': slot['slot'], 'name': slot.get('name') or slot['slot'],
            'slug': meta.get('slug') if meta else None, 'kind': slot.get('kind') or 'slot', 'source_game_id': gid,
            **(_assets(meta, root) if meta else {'preview_url': None, 'model_url': None, 'model': None, 'format': None}),
            'buildable': routed and slot.get('status') != 'not_working',
            **({'reason': slot['reason']} if slot.get('reason') else {})})
    visual = [_row(entry, meta, root, gid) for entry, meta in entries if (meta or entry).get('slug') not in consumed]
    targets.extend(_roster_scope(visual, slots))
    key = source.strip()
    label, source_rows = key, []
    target_kind = 'sprites' if writer_name == 'gbox.clayfighter_swap' else 'character'
    candidate_slugs = {m['slug'] for m in CS._candidates(chars, target_kind)}
    if key in CS.GROUPS:
        label = CS.GROUPS[key]['label']
        pool = [m for m in CS._candidates(chars, target_kind) if CS.in_group(m, key)]
        # Retain the existing planner's costume and preferred-pack selection.
        pool, _dropped = CS.dedupe(pool)
        if CS.GROUPS[key].get('best_per_character'):
            proven = [meta for meta in pool if re.fullmatch(r'[a-f0-9]{16}', str((meta.get('source') or {}).get('game_id') or ''))]
            eligible, _refused, _refreshed = CS.gate(proven, root, target_kind)
            best, _superseded = CS.best_per_character(eligible)
            accepted = {m['slug'] for m in eligible}
            pool = best + [meta for meta in pool if meta['slug'] not in accepted]
        source_rows = [(meta, meta) for meta in pool]
    elif key:
        if not source_game or source_game.get('game_id') != key:
            raise ValueError('Select a named source group or an exact catalog source game_id')
        label = source_game['title']
        source_rows, source_issues = _roster_entries(config, source_game, chars)
        issues.extend(source_issues)
    donors = []
    for entry, meta in source_rows:
        donor = _row(entry, meta, root, (meta.get('source') or {}).get('game_id') if meta else source_game['game_id'])
        donor.update(id=donor['slug'], ready=False, reason='Registered character has not been extracted for this exact title')
        donor.pop('slot', None)
        donor.pop('buildable', None)
        if meta:
            if not re.fullmatch(r'[a-f0-9]{16}', str(donor.get('source_game_id') or '')):
                donor['reason'] = 'Exact source game_id is not recorded for this collection entry'
            elif meta.get('slug') not in candidate_slugs:
                donor['reason'] = f"This {meta.get('kind') or 'character'} entry is not an eligible {target_kind} donor in the existing cast planner"
            else:
                try:
                    accepted, refused, _refreshed = CS.gate([meta], root, target_kind)
                    donor['reason'] = (refused[0].get('reason') if refused else None) or ''
                    donor['ready'] = bool(accepted)
                except Exception as error:
                    donor['reason'] = f'Donor readiness check unavailable: {type(error).__name__}'
                if not donor['model_url'] or not donor['preview_url'] or not (root / meta['slug'] / 'meta.json').is_file():
                    donor['ready'], donor['reason'] = False, 'Collection model or preview files are missing; extract this exact-title entry first'
        donors.append(donor)
    blocking = list(issues)
    if not routed:
        blocking.append('No routed native character writer is registered for this title')
    elif not combined:
        blocking.append('The registered writer supports individual replacements, not one combined whole-cast build')
    if any(row['slot'] is None for row in targets):
        blocking.append('Roster-only rows are visual inventory; their native writable slots are not registered')
    if not native:
        blocking.append('No native writable cast slots match the requested scope' if all_native else 'No native writable cast slots are registered')
    if not targets and slots.lower().strip() not in ('', 'all', 'everyone', '*'):
        blocking.append('No extracted or registered roster rows match the requested scope; matching coverage remains pending')
    if any(not row['buildable'] for row in targets if row['slot'] is not None):
        blocking.append('Some native slots are marked not working by their writer')
    if not key:
        blocking.append('Choose a donor group or exact source title')
    elif not any(row['ready'] for row in donors):
        blocking.append('No extracted donor passes the existing readiness gate for this source')
    return {'game': {k: game.get(k) for k in ('game_id', 'title', 'platform')}, 'requested_scope': slots,
            'source': {'key': key, 'label': label}, 'targets': targets, 'donors': donors,
            'capability': {'status': 'ready' if combined and not blocking else 'partial' if routed and all_native else 'unsupported',
                'writer': writer_name, 'combined_writer': combined, 'native_slots_count': len(native),
                'blocking_reasons': blocking}}
