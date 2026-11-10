"""Platforms a worker never runs: excluded_platforms in gbox.toml.

Operator 2026-11-10, of the Spark (lilspark): "i only want builds related to the switch version of RE on the spark. No
more xbox or ps3 work on the spark."

The key is per node, in the style of the other per-node keys: an entry is keyed by an OS ("linux" / "windows") or by a
host / worker name ("lilspark", matched without case), and a node excludes the union of every entry that names it:

    excluded_platforms = { lilspark = ["ps3", "xbox", "xbox360"] }

The worker reports its own list in its registration (WorkerInfo.excluded_platforms: GET /api/workers, the background
status, the MercMode panel's reasons), and everything that picks a worker reads it from there:
  - submit (server.submit): a job pinned to such a worker, or one that no online worker but such workers could take,
    is rejected with a PlatformExcluded error; a launch never picks such a worker as its candidate;
  - claim (server._claim): such a worker never claims the job; it waits for another PC, and one that only excluded
    workers could take fails with the same error;
  - the worker itself refuses one that arrives anyway (worker._run_job, adapters.for_game);
  - the schedulers skip the platform for that worker instead of failing: MercMode's titles (mercmode.inventory), the
    screensaver / roulette (screensaver.Screensaver._start), favorite unlock research (custom_build_unlocks), Hermes
    queue dispatch (hermes_work_queue.candidates) and the Spark helper's chores (spark_grunt).

A job's platform is its game's catalog platform: input.game, input.game_id / target_game / game_ids, else the game of
input.session_id, else input.platform, else the game of its parent request. Wind-down operations (stop a game, save
its state, delete or quarantine a build: WIND_DOWN) are never refused, so a game that predates the setting can still
be closed and its builds cleaned up.
"""
from __future__ import annotations

import platform as _platform

from .config import HOST_OS
from .registry import ToolUnavailable

CODE = 'platform_excluded'
ERROR = 'PlatformExcluded'
ALIASES = {'x360': 'xbox360', 'xbox 360': 'xbox360', 'xbox_360': 'xbox360', 'xbox-360': 'xbox360',
           'playstation 3': 'ps3', 'playstation3': 'ps3', 'playstation_3': 'ps3'}
LABELS = {'ps3': 'PS3', 'xbox': 'Xbox', 'xbox360': 'Xbox 360', 'ps2': 'PS2', 'ps4': 'PS4', 'psx': 'PS1',
          'switch': 'Switch', 'gamecube': 'GameCube', 'wii': 'Wii', '3ds': '3DS'}
# (tool, op) pairs that only wind a game or build down: never refused, so a PS3 game left running when the setting
# arrived can still be saved and closed, and its builds deleted
WIND_DOWN = frozenset({('session_op', 'stop_game'), ('session_op', 'save_state'), ('session_op', 'query_runtime'),
                       ('file_mod', 'delete_build'), ('file_mod', 'quarantine_build')})


class PlatformExcluded(ToolUnavailable):
    """This worker's excluded_platforms lists the game's platform: it never runs that work."""


def normalize(value) -> str:
    """A catalog platform id as the exclusion list compares it: lower case, a few spelled-out aliases folded."""
    text = str(value or '').strip().casefold()
    return ALIASES.get(text, text)


def normalize_all(values) -> frozenset:
    if isinstance(values, str):
        values = [values]
    return frozenset(p for p in (normalize(v) for v in (values or ())) if p)


def label(plat: str) -> str:
    return LABELS.get(plat, plat.upper() if len(plat) <= 4 else plat)


def node_keys(name: str | None = None, *, os_name: str = HOST_OS, host: str | None = None) -> set[str]:
    """The keys an excluded_platforms entry may use for this node: its OS, its host name and its worker name (each
    also without a domain suffix), case-folded."""
    keys = {str(os_name or '').casefold()}
    for value in (_platform.node() if host is None else host, name):
        text = str(value or '').strip().casefold()
        if text:
            keys |= {text, text.split('.')[0]}
    keys.discard('')
    return keys


def for_node(table, name: str | None = None, *, os_name: str = HOST_OS, host: str | None = None) -> list[str]:
    """The platforms an excluded_platforms table excludes on this node, sorted (empty: none). A bare list (or one
    platform) instead of a table applies to every node that reads it (meant for a host's own gbox.local-<host>.toml)."""
    if isinstance(table, (list, tuple, str)):
        return sorted(normalize_all(table))
    keys = node_keys(name, os_name=os_name, host=host)
    out: set[str] = set()
    for key, platforms in (table or {}).items():
        if str(key).strip().casefold() in keys:
            out |= normalize_all(platforms)
    return sorted(out)


def of_worker(worker) -> frozenset:
    """A worker registration's own excluded platforms (an older worker reports none)."""
    return normalize_all((worker or {}).get('excluded_platforms') or ())


def game_platform(game) -> str:
    """The platform a catalog entry runs on. An older catalog row may call an original Xbox game windows_native
    (gbox.xbox.is_xbox_game recognizes it): it counts as xbox."""
    if not isinstance(game, dict):
        return ''
    plat = normalize(game.get('platform'))
    if plat == 'windows_native':
        try:
            from .xbox import is_xbox_game
            if is_xbox_game(game):
                return 'xbox'
        except Exception:                                    # noqa: BLE001 - an odd row keeps its own platform
            pass
    return plat


def _entry(store, gid):
    get = getattr(store, 'catalog_get', None)
    if get is None or not isinstance(gid, str) or not gid:
        return None
    try:
        return get(gid)
    except Exception:                                        # noqa: BLE001 - an unreadable row names no platform
        return None


def exempt(job) -> bool:
    inp = job.get('input') if isinstance(job.get('input'), dict) else {}
    return (job.get('tool'), inp.get('op')) in WIND_DOWN


def job_platforms(store, job) -> frozenset:
    """The platforms of the games a job works on (see the module docstring for where they are read from)."""
    inp = job.get('input') if isinstance(job.get('input'), dict) else {}
    found: set[str] = set()
    ids: list[str] = []
    game = inp.get('game')
    if isinstance(game, dict):
        if game.get('platform'):
            found.add(game_platform(game))
        elif isinstance(game.get('game_id'), str):
            ids.append(game['game_id'])
    elif isinstance(game, str) and game:
        ids.append(game)
    for key in ('game_id', 'target_game'):
        if isinstance(inp.get(key), str) and inp[key]:
            ids.append(inp[key])
    if isinstance(inp.get('game_ids'), (list, tuple)):
        ids.extend(g for g in inp['game_ids'] if isinstance(g, str) and g)
    sid = inp.get('session_id')
    if not found and not ids and isinstance(sid, str) and sid:
        session = (store.get('session', sid) if store is not None else None) or {}
        if isinstance(session.get('game_id'), str) and session['game_id']:
            ids.append(session['game_id'])
    for gid in dict.fromkeys(ids):
        found.add(game_platform(_entry(store, gid)))
    if not found and not ids and isinstance(inp.get('platform'), str):
        found.add(normalize(inp['platform']))
    rid = job.get('parent_request_id')
    if not found and not ids and isinstance(rid, str) and rid and store is not None:
        context = ((store.get('request', rid) or {}).get('context') or {})
        found.add(game_platform(_entry(store, context.get('game_id'))))
    found.discard('')
    return frozenset(found)


def message(name, platforms, excluded=None) -> str:
    """Why `name` does not run work on these platforms (no error-name prefix: reason() adds it)."""
    what = ' / '.join(label(p) for p in sorted(platforms))
    listed = f": {', '.join(sorted(excluded))}" if excluded else ''
    return (f"{name or 'This PC'} does not run {what} work (excluded_platforms{listed} in its gbox.toml); "
            f"choose a PC that runs {what} games")


def reason(name, platforms, excluded=None) -> str:
    return f'{ERROR}: {message(name, platforms, excluded)}'


def worker_reason(worker, plat) -> str | None:
    """Why this registered worker does not run games on `plat` (None: it does). For per-title readiness rows."""
    excluded = of_worker(worker)
    plat = normalize(plat)
    if plat and plat in excluded:
        return message((worker or {}).get('name'), {plat}, excluded)
    return None


def blocked_workers(store, job, workers) -> tuple[frozenset, frozenset]:
    """(ids of the registered workers whose exclusions cover this job's platforms, those platforms). Cheap when no
    worker excludes anything: the job's platforms are only looked up then."""
    excluding = [w for w in workers or () if of_worker(w)]
    if not excluding or exempt(job):
        return frozenset(), frozenset()
    plats = job_platforms(store, job)
    if not plats:
        return frozenset(), plats
    return frozenset(w.get('id') for w in excluding if of_worker(w) & plats), plats


def _matches(job, worker) -> bool:
    return (job.get('tool') in (worker.get('tools') or ())
            and job.get('require_os') in (None, worker.get('os'))
            and job.get('require_worker') in (None, worker.get('id'), worker.get('name')))


def placement_reason(job, blocked, plats, workers) -> str | None:
    """Why this job can run nowhere (None: some worker may take it, or none is online yet to judge): it is pinned to a
    worker that excludes its platform, or every online worker that could take it does."""
    if not blocked:
        return None
    rows = list(workers or ())
    pinned = job.get('require_worker')
    if pinned:
        w = next((w for w in rows if w.get('id') == pinned), None) or next(
            (w for w in sorted(rows, key=lambda r: not r.get('online')) if w.get('name') == pinned), None)
        if w is not None and w.get('id') in blocked:
            return reason(w.get('name'), of_worker(w) & plats, of_worker(w))
        return None
    candidates = [w for w in rows if w.get('online') and _matches(job, w)]
    if candidates and all(w.get('id') in blocked for w in candidates):
        names = ', '.join(sorted({str(w.get('name')) for w in candidates}))
        what = ' / '.join(label(p) for p in sorted(plats))
        return (f'{ERROR}: no online PC that could take this job runs {what} work: {names} '
                f'exclude it (excluded_platforms in gbox.toml); choose a PC that runs {what} games')
    return None


def claim_reason(store, worker, job) -> str | None:
    """Why this worker must not claim this job (None: it may). Looks the job's platforms up only on a worker that
    excludes something."""
    excluded = of_worker(worker)
    if not excluded or exempt(job):
        return None
    hit = job_platforms(store, job) & excluded
    return reason(worker.get('name'), hit, excluded) if hit else None


def host_exclusions(workers, host: str | None = None) -> frozenset:
    """The exclusions of this machine's own worker: the registration named like the host, else (none named so) every
    Linux worker's (the Spark, where Hermes and the Spark helper run)."""
    rows = [w for w in workers or () if isinstance(w, dict)]
    keys = node_keys(None, os_name='', host=host)
    named = [w for w in rows if str(w.get('name') or '').casefold() in keys]
    pool = named or [w for w in rows if w.get('os') == 'linux']
    out: set[str] = set()
    for w in pool:
        out |= of_worker(w)
    return frozenset(out)


def local_reason(excluded, job, sessions=None, name: str = '') -> str | None:
    """The worker's own refusal (defense in depth: the control plane should never have handed it this job). Reads
    the platforms the control plane stamped at claim (game_platforms), the job's own game entry and platform, and the
    game of a session this worker runs."""
    excluded = normalize_all(excluded)
    if not excluded or exempt(job):
        return None
    inp = job.get('input') if isinstance(job.get('input'), dict) else {}
    plats = set(normalize_all(job.get('game_platforms') or ()))
    if isinstance(inp.get('game'), dict):
        plats.add(game_platform(inp['game']))
    if isinstance(inp.get('platform'), str):
        plats.add(normalize(inp['platform']))
    sid = inp.get('session_id')
    entry = (sessions or {}).get(sid) if isinstance(sid, str) else None
    if isinstance(entry, (tuple, list)) and len(entry) > 1:
        plats.add(game_platform(entry[1]))
    hit = frozenset(plats) & excluded
    return reason(name or _platform.node(), hit, excluded) if hit else None


def refuse_game(config, game, name: str | None = None) -> None:
    """adapters.for_game: raise PlatformExcluded for a game whose platform this node excludes."""
    table = getattr(config, 'excluded_platforms', None)
    if not table:
        return
    excluded = for_node(table, name)
    plat = game_platform(game)
    if plat and plat in excluded:
        raise PlatformExcluded(message(name or _platform.node(), {plat}, excluded))
