"""Unfiltered favorite capability scans and safe, explicit job plans.

A complete catalog scan is not a complete source-game extraction. Unsupported
operations stay in the backlog; only existing registered collection tools can
be optionally scheduled. This tool never launches an emulator or changes saves.
"""
from __future__ import annotations

from collections import Counter
import json
import time
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

from . import game_capabilities as GC, game_unlocks
from .models import Permission as P
from .registry import tool

FILTERS = {'q': '', 'platform': '', 'system': '', 'library': '', 'local': '',
           'letter': '', 'exclude_platforms': '', 'favorites': True,
           'recent': False, 'sort': 'name'}


def paginate_favorites(fetch_page, *, page_size=500, max_pages=10000):
    """Return every favorite or an explicit incomplete scan; never silently cap."""
    if not isinstance(page_size, int) or not 1 <= page_size <= 500:
        raise ValueError('page_size must be between 1 and the catalog API maximum of 500')
    if not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError('max_pages must be positive')
    games, pages, errors, seen = [], [], [], set()
    offset, total, complete = 0, None, False
    for _ in range(max_pages):
        try:
            response = fetch_page(FILTERS | {'limit': page_size, 'offset': offset})
        except Exception as error:
            errors.append(f'Page at offset {offset} could not be read: {error}')
            break
        if not isinstance(response, dict) or not isinstance(response.get('items'), list):
            errors.append(f'Page at offset {offset} has no catalog items/total envelope')
            break
        n = response.get('total')
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            errors.append(f'Page at offset {offset} has an invalid total')
            break
        if total is None:
            total = n
        elif n != total:
            errors.append('Favorite count changed during pagination; repeat the scan for a consistent snapshot')
        if response.get('offset', offset) != offset:
            errors.append(f'Page returned the wrong offset, expected {offset}')
        items = response['items']
        before = len(games)
        for game in items:
            gid = game.get('game_id') if isinstance(game, dict) else None
            if not gid or game.get('favorite') is not True:
                errors.append(f'Invalid/non-favorite catalog entry at offset {offset}')
                continue
            if gid in seen:
                errors.append(f'Repeated game {gid} during pagination')
                continue
            seen.add(gid)
            games.append(game)
        pages.append({'offset': offset, 'returned': len(items), 'new_games': len(games) - before, 'total': n})
        if offset + len(items) >= n:
            complete = not errors and len(games) == n
            break
        if not items or len(games) == before:
            errors.append('Pagination made no progress before reaching the reported total')
            break
        # Advancing by returned rows also handles a server-side page size cap.
        offset += len(items)
    else:
        errors.append('Maximum page count reached before the catalog scan completed')
    return games, {'filters': dict(FILTERS), 'reported_total': total, 'count': len(games),
                   'pages': pages, 'pagination_complete': complete, 'errors': errors}


def read_favorites(ctx, api, **kwargs):
    games, catalog = paginate_favorites(lambda params: api(ctx, 'GET', '/api/catalog', params=params), **kwargs)
    raw_url = getattr(ctx, 'server', None) or getattr(getattr(ctx, 'config', None), 'public_url', None) or ''
    parsed = urlsplit(raw_url)
    # Reports identify the server without embedding credentials, query or fragment.
    catalog['control_url'] = urlunsplit((parsed.scheme, parsed.hostname + (f':{parsed.port}' if parsed.port else '')
                                       if parsed.hostname else '', parsed.path, '', ''))
    catalog['scope'] = 'All favorites in this control catalog, with no platform/library/local/hidden-platform filters.'
    catalog['limitation'] = 'This does not establish favorites from another control instance or full asset extraction.'
    catalog['platform_counts'] = dict(Counter(g.get('platform') or 'unknown' for g in games))
    catalog['library_counts'] = dict(Counter(g.get('library') or 'unknown' for g in games))
    return games, catalog


def scan(ctx, api, *, schedule_collection=False, retry_failed=False, page_size=500):
    from . import char_coverage as CC
    games, catalog = read_favorites(ctx, api, page_size=page_size)
    entries = api(ctx, 'GET', '/api/characters')
    rows, tasks, jobs = [], [], []
    policy = api(ctx, 'GET', '/api/character-collection/policy') if schedule_collection else {}
    for game in games:
        ex, roster = CC.extractor_for(game)
        row = GC.describe(game, entries, extractor=ex, roster=roster, writer=CC.writer_for(game))
        rows.append(row)
        tasks.extend(GC.backlog(row))
        if schedule_collection and catalog['pagination_complete'] and policy.get('enabled') and ex:
            status = api(ctx, 'GET', f'/api/games/{game["game_id"]}/roster').get('collection') or {}
            state = status.get('state', 'not_started')
            if state in ('not_started', 'unsupported') or retry_failed and state == 'failed':
                # The control plane's existing collector deduplicates concurrently.
                # Re-favoriting an existing favorite uses that atomic path and never launches.
                result = api(ctx, 'POST', f'/api/catalog/{game["game_id"]}/favorite', params={'on': True})
                collection = result.get('collection') or {}
                if collection.get('job_id'):
                    jobs.append({'game_id': game['game_id'], 'job_id': collection['job_id'],
                                 'state': collection.get('state'), 'scope': 'registered_roster_subset'})
    return {'captured_at': time.time(), 'catalog': catalog, 'games': rows, 'backlog': tasks,
            'collection_jobs': jobs, 'schedule_requested': schedule_collection,
            'summary': {'favorites': len(rows), 'registered_readers': sum(bool(r['operations']['characters']['extractor']) for r in rows),
                        'routed_writers': sum(r['operations']['native_reimport']['supported'] for r in rows),
                        'verified_fighter_costume_sources': sum(bool(r['verified_fighter_costume_source']) for r in rows),
                        'runtime_verified_native_reimports': sum(r['operations']['native_reimport'].get('runtime_verified', False) for r in rows),
                        'complete_sources_verified': sum(r['complete_source_verified'] for r in rows),
                        'backlog_items': len(tasks)},
            'queue_scope': 'Only registered roster collection is optionally queued; unsupported RE/stage/writer/unlock work remains explicit backlog.'}


def markdown(report):
    catalog = report['catalog']
    out = ['# Favorite capability report', '', catalog['scope'], '',
           f'Catalog: {catalog["control_url"] or "local"}. Scanned {catalog["count"]} of {catalog["reported_total"]} favorites; '
           f'pagination complete: {catalog["pagination_complete"]}.', '', catalog['limitation'], '',
           '| Game | Platform | Characters | Costumes | Stages | Native reimport | Unlock profile |',
           '|---|---|---|---|---|---|---|']
    for row in report['games']:
        ops = row['operations']
        characters = ops['characters']
        character_status = f'{characters["status"]} ({len(characters["in_collection"])}/{characters["registered_roster"]} registered entries collected)'
        cells = [str(row['title']), str(row['platform']), character_status] + [ops[k]['status'] for k in ('costumes', 'stages', 'native_reimport', 'unlocks')]
        out.append('| ' + ' | '.join(c.replace('|', '\\|').replace('\n', ' ') for c in cells) + ' |')
    for row in report['games']:
        source = row.get('verified_fighter_costume_source')
        if source:
            out += ['', f'{row["title"]}: {source["verified"]}/{source["expected"]} available native fighter/costume exports verified '
                    f'({source["scope"]}); {source.get("native_declared", source["expected"])} declared native entries. '
                    'Stage/effect extraction and per-donor gameplay remain separate.',
                    f'Unavailable source entries: {json.dumps(source.get("unavailable_native_sources", []))}.']
        runtime = row['operations']['native_reimport'].get('evidence')
        if runtime and runtime.get('runtime_verified'):
            out += ['', f'{row["title"]} native gameplay verified scope: {runtime["scope"]}. Additional donor/slot cases remain in the backlog.']
    out += ['', '## Backlog', '']
    for task in report['backlog']:
        out.append(f'- `{task["id"]}`: {task["title"]} ({task["capability_status"]}).')
    if catalog['errors']:
        out += ['', '## Scan errors', ''] + [f'- {error}' for error in catalog['errors']]
    return '\n'.join(out)


class FavoritesIn(BaseModel):
    op: Literal['scan', 'unlock_profile', 'launch_plan'] = 'scan'
    schedule_collection: bool = False
    retry_failed: bool = False
    game_id: str = ''
    worker_id: str = ''
    mod: str = ''
    enable_unlock: bool = False
    allow_save_upgrade: bool = False
    session_id: str = ''
    page_size: int = Field(default=500, ge=1, le=500)


class FavoritesOut(BaseModel):
    result: dict


@tool('favorite_capabilities', '1.0', FavoritesIn, FavoritesOut,
      capabilities=['catalog', 'analysis', 'asset'], permissions=[P.READ, P.NETWORK, P.EXECUTE], timeout_s=600,
      side_effects=['Optional deduplicated registered roster collection via the existing favorite workflow'],
      artifacts=['favorite-capabilities.json', 'favorite-capabilities.md'])
def favorite_capabilities(inp: FavoritesIn, ctx):
    """Scan every favorite without UI filters, expose scoped RE gaps, optionally collect supported rosters, or plan verified opt-in unlock launches on JAYBUILTFINALE. Plans never dispatch emulator/save jobs."""
    from . import characters as C
    if inp.op == 'scan':
        result = scan(ctx, C._api, schedule_collection=inp.schedule_collection,
                      retry_failed=inp.retry_failed, page_size=inp.page_size)
        ctx.artifact('favorite-capabilities.json', json.dumps(result, indent=2).encode(), 'application/json')
        ctx.artifact('favorite-capabilities.md', markdown(result).encode(), 'text/markdown')
        return {'result': result}
    if not inp.game_id:
        raise ValueError('game_id is required for an exact-build profile or launch plan')
    game = C._api(ctx, 'GET', f'/api/catalog/{inp.game_id}')
    if inp.op == 'unlock_profile':
        return {'result': game_unlocks.profile_for(game)}
    workers = C._api(ctx, 'GET', '/api/workers')
    worker = next((w for w in workers if w['id'] == inp.worker_id), None)
    if not worker:
        raise ValueError('Select an existing testing worker_id')
    if inp.session_id:
        sessions = C._api(ctx, 'GET', '/api/sessions')
        session = next((s for s in sessions if s.get('session_id') == inp.session_id), None)
        if not session or session.get('state') != 'running' or not inp.session_id.startswith(worker['id'] + '-') or session.get('game_id') != inp.game_id:
            raise ValueError('The supplied live session must match both the game and designated testing worker')
    return {'result': game_unlocks.launch_plan(game, worker, mod=inp.mod, enable_unlock=inp.enable_unlock,
                      allow_save_upgrade=inp.allow_save_upgrade, session_id=inp.session_id,
                      parent_request_id=getattr(ctx, 'parent_request_id', None))}
