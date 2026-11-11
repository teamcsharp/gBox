"""MercMode donor rotation: each title block plays a different verified donor build, drawn at random.

Operator 2026-11-10: "for RE4 / 5 / 6, I want to continue seeing new and randomized characters from the database being
used in games and swapped frequently ... I want to see all the characters extracted throughout the game changing on
rounds if hot swapping is possible."

How a round's build is chosen (mercmode.default_mod; the DJ queue's own `mod` still wins, as before):

* **pool** - the title's verified donor builds: the audited builds of the title (`gbox.donor_rejects` audited_builds,
  written by `python -m gbox.donor_fit_audit --write`), or the host's explicit `donor_pool[title]` list, that pass the
  fit gate (`fit_gate`: indexed, at least one library donor, no donor on the reject list, no slot the audit refused)
  and exist on the PC that plays. Each block draws one of them at random from a shuffle bag: every build of the pool
  plays once before any plays again, and never the same build twice in a row.
* **fresh** - the pool, plus a new build written from the character library when a title's bag has run out (at most
  one job at a time per PC, FRESH_MIN_INTERVAL_S apart, FRESH_MAX per title): RE5 redraws FRESH_SLOTS player slots of
  a pool build through the donor swap's own job (switch_mods op=donor_variant, gbox.donor_swap.build_variant: every
  redrawn donor passes the fit audit or the slot plays native). The new build joins the pool when the job lands
  (`accept_fresh`) and is the next block's first choice. RE4 and RE6 have no in-service redraw yet
  (gbox.donor_swap.NATIVE_WHY): their pools grow through the offline writers.
* **off** - default_mods, as before.

A LayeredFS build is read when the title boots (gbox.switch_mods: Eden packs the layered RomFS once per boot), so a
new build is a relaunch of the title. Inside one build every round's random character pick already wears a different
donor (a cast build dresses every roster slot). `donor_rounds` (opt-in, gbox.screensaver.round_boundary) relaunches
the same title with the next draw every N rounds inside a block; the block's round count carries over, so a block is
still rounds_per_title matches. Each such relaunch costs a cold boot (~50 s of loading on lilspark, and Eden hung
black at boot on 4 of 9 restarts on 2026-11-09).
"""
from __future__ import annotations

import re
import time
import uuid

from . import donor_rejects

STATE = 'mercmode_donor_rotation'   # host -> {host, titles: {title: {current, history, cycle, left, pool, at,
                                    #                                fresh: {...}, fresh_builds: [...]}}}
MODES = ('off', 'pool', 'fresh')
HISTORY_MAX = 24
BLUEPRINT = '-blueprint'
#: experiments, never rotation material in the automatic pool (an explicit donor_pool list decides for itself)
EXPERIMENT = re.compile(r'(?:^|[-_])(test|probe|harness|greybox|grey|bisect|hotswap|noop|stock|nudge|control|sandbox)'
                        r'(?=$|[-_])', re.I)
ROT = re.compile(r'^(?P<base>.+?)-rot(?P<n>\d+)$')
FRESH_TITLES = frozenset({'re5'})   # titles with an in-service redraw (gbox.donor_swap.REDRAW_TITLES)
FRESH_SLOTS = 3                     # player slots one fresh build redraws (the job's time budget covers about three)
FRESH_MIN_POOL = 3                  # below this many verified builds a fresh one is asked for even mid-cycle
FRESH_MIN_INTERVAL_S = 1800.0       # one fresh build per title at most this often ...
FRESH_MAX = 12                      # ... and at most this many per title and PC (each RE5 build + companion ~1.3 GB)
FRESH_JOB_TTL_S = 3600.0            # a fresh job still unanswered after this is given up (the next one may go)
PURPOSE = 'rotation'
SWAP_PREFIX = 'rot'                 # a fresh build's swap id (gbox.donor_swap's own ids are hex)


def _plain(name: str | None) -> str:
    name = str(name or '')
    return name[:-len(BLUEPRINT)] if name.endswith(BLUEPRINT) and len(name) > len(BLUEPRINT) else name


def library_donors(entry: dict | None) -> set[str]:
    """The library characters of an audited build (players and enemies). A native costume another slot wears
    (RE6's roster shuffle, `chris/Omake00`) is not a library donor."""
    entry = entry or {}
    out = {r.get('donor') for r in (entry.get('players') or {}).values() if isinstance(r, dict)}
    out |= {d for r in (entry.get('enemies') or {}).values() if isinstance(r, dict) for d in r.get('donors') or []}
    return {d for d in out if isinstance(d, str) and d and '/' not in d}


def fit_gate(title: str, build: str, doc: dict | None = None, game_id: str | None = None) -> tuple[bool, str]:
    """(passes, why not) for one build of `title`: the operator's donor fit rule (2026-11-10: "models that I don't
    even want to see in the rotation"). Unknown to the audit = not verified = refused."""
    doc = donor_rejects.load() if doc is None else doc
    entry = donor_rejects.build_index(build, doc=doc)
    if not entry:
        return False, 'not in the donor fit audit (python -m gbox.donor_fit_audit --write indexes it)'
    owner = entry.get('title') or donor_rejects.title_of(entry.get('game_id') or '')
    if owner and owner != title:
        return False, f'audited as a {owner} build'
    if game_id and entry.get('game_id') and entry['game_id'] != game_id:
        return False, f"audited for game {entry['game_id']}"
    if not library_donors(entry):
        return False, 'no library donor in it (native models only)'
    players = donor_rejects.rejected(title, 'player', doc=doc)
    enemies = donor_rejects.rejected(title, 'enemy', doc=doc)
    bad = sorted({r.get('donor') for r in (entry.get('players') or {}).values() if r.get('donor') in players}
                 | {d for r in (entry.get('enemies') or {}).values() for d in r.get('donors') or [] if d in enemies})
    if bad:
        return False, 'donors on the reject list: ' + ', '.join(bad)
    refused = sorted(slot for slot, r in (entry.get('players') or {}).items() if r.get('verdict') == 'reject')
    if refused:
        return False, 'the audit refused slot(s) ' + ', '.join(refused)
    return True, ''


def _states(store, host) -> dict:
    doc = store.get(STATE, host) or {}
    return {'host': host, 'titles': dict(doc.get('titles') or {})}


def title_state(store, host, title) -> dict:
    return dict(_states(store, host)['titles'].get(title) or {})


def _put_title(store, host, title, row) -> None:
    doc = _states(store, host)
    doc['titles'][title] = row
    store.put(STATE, host, doc)


def _known(builds, game_id) -> set[str] | None:
    """The build names this PC's build index lists for the game, None when it cannot be read."""
    if builds is None:
        return None
    try:
        return {str(b.get('name') or '') for b in builds(game_id) or []}
    except Exception:                                   # noqa: BLE001 - an unreadable index proves nothing
        return None


def pool(store, host, cfg, title, game_id, *, builds=None, doc=None, refused: dict | None = None) -> list[str]:
    """The verified donor builds of `title` this PC can play now (plain names, a donor swap's variant in place of the
    build it superseded). `refused` collects {build: why} for the ones left out."""
    from . import donor_swap
    refused = {} if refused is None else refused
    if title not in donor_rejects.TITLES:
        return []
    doc = donor_rejects.load() if doc is None else doc
    audited = doc.get('audited_builds') or {}
    row = title_state(store, host, title)
    fresh = list(row.get('fresh_builds') or [])
    explicit = [str(b) for b in ((cfg or {}).get('donor_pool') or {}).get(title) or [] if b]
    if explicit:
        names = [_plain(b) for b in explicit]
    else:
        names = sorted(b for b, e in audited.items() if isinstance(e, dict)
                       and (e.get('title') or donor_rejects.title_of(e.get('game_id') or '')) == title
                       and not b.endswith(BLUEPRINT) and not EXPERIMENT.search(b) and not ROT.match(b))
    names += [b for b in fresh if b not in names]
    have = _known(builds, game_id)
    sets: dict[str, set] = {}
    for name in names:
        resolved = donor_swap.resolve(store, game_id, name) or name
        if resolved in sets:
            continue
        ok, why = fit_gate(title, resolved, doc, game_id)
        if not ok:
            refused[name] = why
            continue
        if resolved not in fresh and (have is None or resolved not in have):
            refused[name] = 'not on this PC' if have is not None else "this PC's build index is not readable"
            continue
        sets[resolved] = library_donors(donor_rejects.build_index(resolved, doc=doc))
    if explicit:
        return list(sets)
    keep = []
    for name, donors in sets.items():
        # a bisect / subset build (its donors all in another build of the pool) adds nothing new to see
        bigger = next((other for other, theirs in sets.items() if other != name and donors <= theirs
                       and (donors != theirs or other < name)), None)
        if bigger:
            refused[name] = f'its donors are all in {bigger}'
            continue
        keep.append(name)
    return keep


def draw(store, host, cfg, title, game_id, rng, *, builds=None, doc=None, now=None, avoid=(),
         strict=False) -> str | None:
    """The next block's build of `title` (plain name), recorded as drawn; None when the title has no verified pool
    (default_mods then plays, as before). A shuffle bag over the pool: every build once per cycle, never the build
    drawn last (nor any in `avoid`, e.g. the one running) while another exists; a fresh build no round has played
    yet comes first. `strict`: None (nothing recorded) when every build of the pool is in `avoid`."""
    now = time.time() if now is None else now
    names = pool(store, host, cfg, title, game_id, builds=builds, doc=doc)
    avoid = {_plain(b) for b in avoid if b}
    if not names or strict and not [b for b in names if b not in avoid]:
        return None
    row = title_state(store, host, title)
    history = list(row.get('history') or [])
    last = history[-1] if history else None
    drawn = [b for b in row.get('cycle') or [] if b in names]
    bag = [b for b in names if b not in drawn]
    if not bag:
        drawn, bag = [], list(names)
    avoid |= {last} if last else set()
    choices = [b for b in bag if b not in avoid] or [b for b in names if b not in avoid] or list(names)
    fresh = set(row.get('fresh_builds') or [])
    unseen = [b for b in choices if b in fresh and b not in history]
    pick = rng.choice(sorted(unseen or choices))
    if pick not in drawn:
        drawn.append(pick)
    _put_title(store, host, title, row | {'current': pick, 'history': (history + [pick])[-HISTORY_MAX:],
                                          'cycle': drawn, 'left': [b for b in names if b not in drawn],
                                          'pool': list(names), 'at': now})
    return pick


def drawer(store, worker, cfg, rng, builds=None):
    """title, game_id -> the draw (mercmode.choose hands it to default_mod), or None when rotation is off."""
    if (cfg or {}).get('donor_rotation', 'off') == 'off':
        return None
    host = worker['name']
    return lambda title, game_id: draw(store, host, cfg, title, game_id, rng, builds=builds)


# --- fresh builds -----------------------------------------------------------------------------------------------

def _rot_root(build: str) -> str:
    name = _plain(build)
    while (m := ROT.match(name)):
        name = m['base']
    return name


def next_name(build: str, existing=()) -> str:
    """`<root>-rotN`, the next free N for the build's root (a fresh build of a fresh build continues the count)."""
    root = _rot_root(build)
    used = {int(m['n']) for name in existing if (m := ROT.match(_plain(str(name)))) and _rot_root(m['base']) == root}
    return f'{root}-rot{max(used, default=0) + 1}'


def fresh_due(store, host, cfg, title, *, now=None, settle=True) -> str | None:
    """Why no fresh build of `title` is asked for now (None = one may be). With `settle`, a fresh job that failed or
    went unanswered is recorded as failed (status reads without writing)."""
    now = time.time() if now is None else now
    if (cfg or {}).get('donor_rotation') != 'fresh':
        return 'donor_rotation is not fresh'
    if title not in FRESH_TITLES:
        return f'{title} has no in-service redraw yet (gbox.donor_swap.NATIVE_WHY): its pool grows offline'
    row = title_state(store, host, title)
    fresh = dict(row.get('fresh') or {})
    if fresh.get('state') == 'queued':
        job = store.get('job', fresh.get('job')) or {}
        if job.get('state') in ('failed', 'invalid', 'cancelled', 'canceled', 'rejected'):
            if settle:
                _put_title(store, host, title, row | {'fresh': fresh | {
                    'state': 'failed', 'error': str(job.get('error') or job.get('state'))[:300], 'settled_at': now}})
        elif now - float(fresh.get('at') or 0) < FRESH_JOB_TTL_S:
            return f"a fresh build is on its way ({fresh.get('variant')})"
        elif settle:
            _put_title(store, host, title, row | {'fresh': fresh | {'state': 'failed', 'settled_at': now,
                                                                    'error': 'no answer within the job TTL'}})
    if now - float(fresh.get('at') or 0) < FRESH_MIN_INTERVAL_S:
        return 'the last fresh build was asked for less than %d min ago' % (FRESH_MIN_INTERVAL_S // 60)
    if len(row.get('fresh_builds') or []) >= FRESH_MAX:
        return f'{FRESH_MAX} fresh builds of {title} exist on this PC (the cap): prune some to make more'
    if row.get('left') and len(row.get('pool') or []) >= FRESH_MIN_POOL:
        return 'the pool still has builds this cycle has not played'
    return None


def fresh_request(store, host, cfg, title, game_id, *, rng, builds=None, doc=None, now=None) -> dict | None:
    """The switch_mods job input for a fresh build of `title` (or None): FRESH_SLOTS random player slots of a pool
    build redrawn from library characters the rotation has not shown yet, never a rejected one."""
    if fresh_due(store, host, cfg, title, now=now):
        return None
    doc = donor_rejects.load() if doc is None else doc
    names = pool(store, host, cfg, title, game_id, builds=builds, doc=doc)
    sources = []
    for name in names:
        entry = donor_rejects.build_index(name, doc=doc) or {}
        slots = sorted(s for s, r in (entry.get('players') or {}).items() if r.get('donor') and r.get('files'))
        if slots:
            sources.append((name, entry, slots))
    if not sources:
        return None
    source, entry, slots = rng.choice(sources)
    chosen = sorted(rng.sample(slots, min(FRESH_SLOTS, len(slots))))
    players = [{'slot': s, **{k: entry['players'][s].get(k) for k in ('donor', 'label', 'files')}} for s in chosen]
    shown = set()
    for name in names:
        shown |= library_donors(donor_rejects.build_index(name, doc=doc))
    exclude = sorted(set(donor_rejects.rejected(title, doc=doc)) | shown)
    existing = set(names) | set(title_state(store, host, title).get('fresh_builds') or []) \
        | (_known(builds, game_id) or set())
    name = next_name(source, existing)
    swap_id = SWAP_PREFIX + uuid.uuid4().hex[:12]
    return {'op': 'donor_variant', 'game_id': game_id, 'build': source, 'new_name': name,
            'changes': {'title': title, 'players': players, 'enemies': [], 'exclude': exclude,
                        'taken': sorted(library_donors(entry)), 'running': source, 'swap_id': swap_id,
                        'purpose': PURPOSE},
            'note': f"MercMode donor rotation {swap_id}: {source} with {', '.join(chosen)} redrawn from the library"}


def fresh_submitted(store, host, title, inp: dict, job_id, *, now=None) -> None:
    now = time.time() if now is None else now
    row = title_state(store, host, title)
    _put_title(store, host, title, row | {'fresh': {
        'state': 'queued', 'job': job_id, 'swap_id': (inp.get('changes') or {}).get('swap_id'), 'of': inp.get('build'),
        'variant': inp.get('new_name'), 'slots': [p['slot'] for p in (inp.get('changes') or {}).get('players') or []],
        'at': now}})


def accept_fresh(store, result: dict, *, now=None, rejects_path=None) -> dict | None:
    """switch_mods op=donor_variant came back for a rotation request: index the build for the fit gate and add it to
    that title's pool (the source build stays in the pool; nothing is superseded or queued). None when the result
    is not one of the rotation's."""
    from . import donor_swap
    now = time.time() if now is None else now
    swap_id = result.get('swap_id')
    if not isinstance(swap_id, str) or not swap_id.startswith(SWAP_PREFIX):
        return None                    # an operator donor swap's id is hex: never one of these
    for doc in store.all(STATE):
        for title, row in (doc.get('titles') or {}).items():
            fresh = row.get('fresh') or {}
            if fresh.get('swap_id') != swap_id:
                continue
            host = doc.get('host')
            variant = result.get('variant')
            if not variant:
                _put_title(store, host, title, row | {'fresh': fresh | {
                    'state': 'failed', 'error': str(result.get('reason') or 'the job wrote no build')[:300],
                    'settled_at': now}})
                return title_state(store, host, title)
            slots = result.get('slots') or []
            donor_swap._index_variant(result.get('of') or fresh.get('of'), variant, slots, rejects_path=rejects_path)
            gid = result.get('game_id') or donor_rejects.TITLE_GAMES.get(title)
            made = dict(store.get(donor_swap.VARIANTS, gid) or {})
            made[variant] = {'of': result.get('of') or fresh.get('of'), 'blueprint': result.get('blueprint'), 'at': now,
                             'swap': swap_id, 'purpose': PURPOSE}
            store.put(donor_swap.VARIANTS, gid, made)
            builds = list(row.get('fresh_builds') or [])
            if variant not in builds:
                builds.append(variant)
            _put_title(store, host, title, row | {'fresh_builds': builds[-FRESH_MAX:], 'fresh': fresh | {
                'state': 'ready', 'variant': variant, 'blueprint': result.get('blueprint'), 'ready_at': now,
                'slots': [{k: s.get(k) for k in ('slot', 'old', 'new', 'how')} for s in slots]}})
            if hasattr(store, 'audit'):
                store.audit('autoplay-screensaver', 'mercmode.donor_rotation_fresh', host,
                            {'title': title, 'build': variant, 'of': result.get('of'), 'slots': slots})
            return title_state(store, host, title)
    return None


# --- status -----------------------------------------------------------------------------------------------------

def status(store, host, cfg, builds=None) -> dict | None:
    """GET /api/mercmode hosts[].donor_rotation: the mode and, per title, the verified pool, what plays, what is left
    this cycle, what was refused and why, and the fresh build in flight."""
    from . import mercmode
    mode = (cfg or {}).get('donor_rotation', 'off')
    if mode == 'off':
        return None
    doc = donor_rejects.load()
    titles = {}
    for title in (cfg or {}).get('titles') or []:
        if title not in donor_rejects.TITLES:
            continue
        spec = mercmode.title_spec(title, cfg)
        game_id = (spec.get('game_ids') or [None])[0]
        refused: dict = {}
        names = pool(store, host, cfg, title, game_id, builds=builds, doc=doc, refused=refused)
        row = title_state(store, host, title)
        titles[title] = {'pool': names, 'current': row.get('current'), 'recent': (row.get('history') or [])[-6:],
                         'left_this_cycle': [b for b in row.get('left') or names if b in names],
                         'refused': dict(sorted(refused.items())[:12]),
                         'fallback': None if names else (cfg.get('default_mods') or {}).get(title),
                         'fresh': row.get('fresh'), 'fresh_builds': row.get('fresh_builds') or [],
                         'fresh_blocked': fresh_due(store, host, cfg, title, settle=False) if mode == 'fresh' else None}
    return {'mode': mode, 'donor_rounds': (cfg or {}).get('donor_rounds') or 0, 'titles': titles}
