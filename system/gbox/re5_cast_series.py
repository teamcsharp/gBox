"""A deterministic series of RE5 Switch pool builds that covers every usable donor of the library once.

One build of the series is one MercMode overlay: a donor on every carrier of every reviewed enemy class
(`re5_enemy_cast`, the mix tables of `re5_enemy_writer.MIXES`) and a donor on each of the six player slots
(`re5_cast_writer.SLOTS`, with the corrected Chris costume labels). Inside a build no donor appears twice. Across the
series every usable donor of the shared survey (`re5_donor_pool.survey`) is dealt at least once before any donor is
dealt a second time, franchises taken in turn, from one seed: the same seed, survey, eligibility and refusals give
the same series.

    plan_series(seed, donors, ...)      -> the builds as {slot: slug} plans, nothing written
    build_series(...)                   -> writes the first N builds under <out>/build-NN/ and <out>/manifest.json

Refusals are part of the plan: a player slot that refuses its donor (its surface does not fit that slot's atlas)
has the series dealt again from that build on; an enemy class that refuses a donor (the fit collapses a triangle,
a fifth skin influence) gives that carrier to a deterministic substitute and the class is built again, the rest of
the build untouched. Both are recorded (`refusals`, `substitutions`), so the manifest and the archives on disk
always agree. Nothing here installs, launches or registers anything; every receipt says `live_verified: false`.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import re5_cast_writer as players
from . import re5_donor_pool as pool
from . import re5_enemy_cast as enemies
from . import re5_enemy_writer as writer

PLAYER_SLOTS = tuple(players.SLOTS)
#: What a MercMode queue does with the series until the hot-swap experiment (task guide package B) has an answer.
ROTATION = {
    'today': 'one build per N rounds: install build k as its own recovery-* overlay through switch_mods, queue N '
             'rounds over the six stages on it, then install build k+1; the title restarts between builds and each '
             'restart shows loading screens, so N is a trade between variety and restarts (the operator dislikes '
             'loading; N = 6, one round per stage, is the smallest cycle that shows every stage on a build)',
    'with_hotswap': 'one build per round: if the probe of package B shows that an in-place overwrite of an overlay '
                    'file is read at the next stage load, pad every archive of the series to one fixed size per '
                    'slot and overwrite the files at the results screen; the queue then advances one build per '
                    'round and a series of 17 builds is a 17-round cycle with 650 characters',
    'ordering': 'builds are played in index order; the manifest is the queue (build k -> its folder); a build that a '
                'live round refuses (a hang, a missing body) is skipped and recorded, not rebuilt in place',
    'players': 'the bot picks the roster slot by label; the six labels of a build map to six donors in the manifest, '
               'so a round can name its player character and the enemy classes it will meet',
}


class SeriesError(ValueError):
    """The series cannot be planned or built; the message names the build, the slot and the reason."""


@dataclass
class Build:
    """One planned overlay of the series."""
    index: int
    seed: str
    players: dict[str, str]                       # roster slot key -> slug
    enemies: dict[str, list[str]]                 # class -> slugs, one per carrier
    first_time: list[str] = field(default_factory=list)   # donors dealt for the first time in the series
    substitutions: list[dict] = field(default_factory=list)   # {class, refused, substitute, reason} while building

    @property
    def name(self) -> str:
        return f'build-{self.index:02d}'

    def slugs(self) -> list[str]:
        return list(self.players.values()) + [slug for slugs in self.enemies.values() for slug in slugs]


def substitute(build: Build, enemy: str, refused: str, *, candidates: set[str], seen: set[str],
               franchise_of: dict[str, str]) -> str:
    """The donor that takes a refused donor's carrier: deterministic from the build seed, never one already in the
    build, an unseen donor of the same franchise first, then any unseen donor, then a seen one of the franchise,
    then any. `candidates` are the enemy-eligible slugs not refused for the role."""
    taken = set(build.slugs())
    open_ = sorted(slug for slug in candidates if slug not in taken and slug != refused)
    if not open_:
        raise SeriesError(f'{build.name}: no donor is left to take the place of {refused} on {enemy}')
    rng = random.Random(f're5-series:{build.seed}:{enemy}:{refused}')
    rng.shuffle(open_)
    same = franchise_of.get(refused)
    for tier in ((lambda s: s not in seen and franchise_of.get(s) == same), (lambda s: s not in seen),
                 (lambda s: franchise_of.get(s) == same), (lambda s: True)):
        picks = [slug for slug in open_ if tier(slug)]
        if picks:
            return picks[0]
    raise SeriesError(f'{build.name}: no donor is left to take the place of {refused} on {enemy}')


def enemy_slots(classes: list[str] | None = None, tables: dict[str, str] | None = None, *,
                singles: bool = False) -> dict[str, int]:
    """{class: donors} for the reviewed classes (or `classes`): one per carrier of the class's mix table (another
    reviewed table per class on request), and with `singles` one donor for every reviewed class that has no mix
    table (the boss and special classes, written on every option group)."""
    sizes = {}
    for enemy in (classes or sorted(writer.MIXES) + (sorted(set(writer.ARCHIVES) - set(writer.MIXES)) if singles else [])):
        if enemy in writer.MIXES or (tables and enemy in tables):
            table = writer.MIX_TABLES[tables[enemy]] if tables and enemy in tables else writer.MIXES[enemy]
            sizes[enemy] = len(table.carriers)
        elif enemy in writer.ARCHIVES:
            sizes[enemy] = 1
        else:
            raise SeriesError(f'{enemy} is not a reviewed enemy class')
    return sizes


def load_pool(survey_path: Path) -> tuple[list[pool.Donor], dict[str, str]]:
    """(usable donors, {slug: winding}) of a shared survey report written by `re5_cast_writer survey`."""
    report = json.loads(Path(survey_path).read_text(encoding='utf-8'))
    donors = pool.donors_of(report)
    windings = {slug: row['rig'].get('winding', 'ccw') for slug, row in report['entries'].items() if row['usable']}
    return donors, windings


def plan_series(seed, donors: list[pool.Donor], *, enemy_pool: set[str], player_pool: set[str] | None = None,
                sizes: dict[str, int] | None = None, player_slots: tuple[str, ...] = PLAYER_SLOTS,
                refusals: dict[str, dict[str, str]] | None = None, fixed: list[Build] = (),
                limit: int = 60) -> list[Build]:
    """Deal the whole series: builds until every donor of either pool has been dealt once.

    `enemy_pool` and `player_pool` are the slugs eligible for each role (`player_pool` defaults to every donor);
    `refusals` is {slug: {role: reason}} from earlier builds, honoured as exclusions for that role; `fixed` are
    builds already written, kept as they are and counted as history. Each build deals the players first
    (`re5_donor_pool.plan`, every earlier build as history so unseen donors come first, franchises in turn), then
    the enemy carriers from the enemy pool without the build's players. A pure function of its arguments.
    """
    sizes = dict(sizes or enemy_slots())
    refusals = refusals or {}
    by_slug = {donor.slug: donor for donor in donors}
    eligible_players = {slug for slug in (player_pool if player_pool is not None else by_slug)
                        if slug in by_slug and 'player' not in refusals.get(slug, {})}
    eligible_enemies = {slug for slug in enemy_pool if slug in by_slug and 'enemy' not in refusals.get(slug, {})}
    everyone = eligible_players | eligible_enemies
    if len(eligible_players) < len(player_slots) or len(eligible_enemies) < sum(sizes.values()):
        raise SeriesError(f'{len(eligible_players)} player donors and {len(eligible_enemies)} enemy donors cannot '
                          f'fill {len(player_slots)} player slots and {sum(sizes.values())} carriers')
    builds = list(fixed)
    seen: set[str] = {slug for build in builds for slug in build.slugs()}
    history = [build.slugs() for build in builds]
    carrier_slots = [f'{enemy}:{number}' for enemy in sorted(sizes) for number in range(sizes[enemy])]
    while not everyone <= seen and len(builds) < limit:
        index = len(builds) + 1
        build_seed = f'{seed}-{index:02d}'
        player_donors = [by_slug[slug] for slug in sorted(eligible_players)]
        dealt_players = pool.plan(f'{build_seed}-players', list(player_slots), player_donors, history=history,
                                  avoid_last=max(1, len(history)))
        enemy_donors = [by_slug[slug] for slug in sorted(eligible_enemies)]
        dealt_carriers = pool.plan(f'{build_seed}-enemies', carrier_slots, enemy_donors, history=history,
                                   avoid_last=max(1, len(history)), exclude=frozenset(dealt_players.values()))
        enemy_plan = {enemy: [dealt_carriers[f'{enemy}:{number}'] for number in range(sizes[enemy])]
                      for enemy in sorted(sizes)}
        build = Build(index, build_seed, dict(dealt_players), enemy_plan)
        build.first_time = sorted(set(build.slugs()) - seen)
        builds.append(build)
        seen |= set(build.slugs())
        history.append(build.slugs())
    if not everyone <= seen:
        raise SeriesError(f'{len(everyone - seen)} donors were still unseen after {limit} builds')
    return builds


def _refused_slug(message: str, candidates: list[str]) -> str | None:
    """The donor a refusal names, or None when the message blames no donor of the build.

    Both writers prefix a refusal with the slot and its donors (`chris_bsaa <- slug: ...`, `uEm10 <- a+b+c: ...`)
    and the writer's own message then starts with the donor it refused (`slug cannot be fitted on em1000: ...`).
    """
    head, _, tail = message.partition(': ')
    arrow = re.search(r'<-\s*(\S+)$', head.strip())
    if arrow and '+' not in arrow.group(1) and arrow.group(1) in candidates:
        return arrow.group(1)
    for text in (tail, message):
        named = [slug for slug in candidates if re.match(rf'{re.escape(slug)}(\s|:|$)', text)]
        if len(named) == 1:
            return named[0]
    named = [slug for slug in candidates if re.search(rf'(^|\s){re.escape(slug)}(\s|:|$)', tail)]
    return named[0] if len(named) == 1 else None


def _kept_players(out: Path, build: Build) -> dict | None:
    """The player receipt already under `out` when it is this build's player deal and its files are intact (an
    enemy refusal re-deals only the enemies: the player deal of the build does not change), else None."""
    path = out / 'receipt-players.json'
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if receipt.get('assignment') != build.players:
        return None
    for row in receipt.get('slots', {}).values():
        file = out / row['output']['path']
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != row['output']['sha256']:
            return None
    return receipt


def _rename(folder: Path, old: str, new: str) -> None:
    source = folder / old
    if source.is_file():
        target = folder / new
        if target.exists():
            target.unlink()
        source.rename(target)


def build_one(build: Build, *, romfs: Path, archives_dir: Path, library: Path, out: Path,
              windings: dict[str, str], donors: dict[str, pool.Donor], enemy_pool: set[str] = frozenset(),
              seen: set[str] = frozenset(), refusals: dict[str, dict[str, str]] | None = None,
              tables: dict[str, str] | None = None, previews: bool = True, progress=None) -> dict:
    """Write one build under `out` (players and enemies into one `romfs/` tree) and return its receipt.

    The players are built first; a player slot that refuses its donor raises `SeriesError` with `role` 'player'
    and `slug`, and the caller deals the series again from this build. The enemy classes are then built one at a
    time; a class that refuses a donor records the refusal in `refusals` (role 'enemy') and the donor's carrier goes
    to a `substitute` from `enemy_pool` (minus refusals and the build), the class is built again and the build's
    plan and `substitutions` are updated in place. Nothing of a class is written before every carrier of it builds.
    """
    out = Path(out)
    refusals = refusals if refusals is not None else {}
    players_receipt = _kept_players(out, build)
    if players_receipt is None:
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        try:
            players_receipt = players.cast(Path(romfs), Path(library), build.players, out, plan={'series': build.seed})
        except players.CastWriterError as exc:
            slug = _refused_slug(str(exc), list(build.players.values()))
            error = SeriesError(f'{build.name}: player slot refused {slug}: {exc}')
            error.role, error.slug = 'player', slug
            raise error from exc
        _rename(out, 'receipt.json', 'receipt-players.json')
    else:                                     # the same player deal is kept; the enemy classes are built afresh
        for path in out.iterdir():
            if path.name.startswith('preview') or path.name.startswith('receipt-uEm') or path.name == 'receipt.json':
                path.unlink()
        for enemy in writer.ARCHIVES.values():
            (out / 'romfs' / enemy.path).unlink(missing_ok=True)
    franchise_of = {slug: donor.franchise for slug, donor in donors.items()}
    class_receipts = {}
    for enemy in list(build.enemies):
        path = Path(archives_dir) / Path(writer.ARCHIVES[enemy].path).name
        if not path.is_file():
            raise SeriesError(f'{build.name}: the original {path} is missing')
        archive = path.read_bytes()
        while True:
            slugs = build.enemies[enemy]
            resolved = [enemies.donor_from_pool(donors[slug], library, windings.get(slug, 'ccw')) for slug in slugs]
            assignment = enemies.Assignment(enemy, tuple(resolved), tuple([writer.NATIVE_HEIGHT] * len(resolved)),
                                            mix=enemy in writer.MIXES or bool((tables or {}).get(enemy)),
                                            table=(tables or {}).get(enemy))
            try:
                class_receipts[enemy] = enemies.build_cast(build.name, [assignment], {enemy: archive}, out,
                                                           previews=previews)
            except enemies.CastError as exc:
                refused = _refused_slug(str(exc), list(slugs))
                if refused is None:
                    raise SeriesError(f'{build.name}: {enemy} refused without naming a donor: {exc}') from exc
                refusals.setdefault(refused, {})['enemy'] = str(exc)
                candidates = {slug for slug in enemy_pool if 'enemy' not in refusals.get(slug, {})}
                taker = substitute(build, enemy, refused, candidates=candidates, seen=set(seen),
                                   franchise_of=franchise_of)
                build.enemies[enemy] = [taker if slug == refused else slug for slug in slugs]
                build.substitutions.append({'class': enemy, 'refused': refused, 'substitute': taker,
                                            'reason': str(exc)})
                if progress:
                    progress(f'set aside for the enemy role: {refused}; {taker} takes its carrier on {enemy} of '
                             f'{build.name}')
                continue
            break
        _rename(out, 'receipt.json', f'receipt-{enemy}.json')
        _rename(out, 'preview.png', f'preview-{enemy}.png')
        _rename(out, 'preview-posed.png', f'preview-{enemy}-posed.png')
    files = {}
    for key, row in players_receipt['slots'].items():
        files[row['output']['path']] = {'role': 'player', 'slot': key, 'label': players.SLOTS[key].label,
                                        'donor': row['donor'], 'sha256': row['output']['sha256'],
                                        'bytes': row['output']['bytes']}
    for enemy, receipt in class_receipts.items():
        row = receipt['archives'][enemy]
        files[row['archive']] = {'role': 'enemy', 'class': enemy, 'donors': [d['slug'] for d in row['donors']],
                                 'mix': row.get('mix'), 'sha256': row['output_sha256'], 'bytes': row['output_bytes']}
    for path, row in files.items():          # the files on disk are what the receipts say they are
        data = (out / path).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256'] or len(data) != row['bytes']:
            raise SeriesError(f'{build.name}: {path} on disk differs from its receipt')
    receipt = {
        'recipe': 're5_cast_series', 'build': build.name, 'index': build.index, 'seed': build.seed,
        'title_id': enemies.TITLE_ID, 'game_id': enemies.GAME_ID, 'overlay_root': 'romfs',
        'players': {key: {'label': players.SLOTS[key].label, 'archive': players.SLOTS[key].player_class, 'donor': slug,
                          'name': donors[slug].name, 'game': donors[slug].game}
                    for key, slug in build.players.items()},
        'enemies': {enemy: [{'slug': slug, 'name': donors[slug].name, 'game': donors[slug].game}
                            for slug in slugs] for enemy, slugs in build.enemies.items()},
        'first_time_in_series': build.first_time, 'substitutions': build.substitutions,
        'files': files, 'receipts': {'players': 'receipt-players.json',
                                     'enemies': {enemy: f'receipt-{enemy}.json' for enemy in class_receipts}},
        'previews': {'players': 'contact-sheet.png',
                     'enemies': {enemy: [f'preview-{enemy}.png', f'preview-{enemy}-posed.png'] for enemy in class_receipts}},
        'label_table': {'archives': players.LABEL_ARCHIVES, 'evidence': players.LABEL_EVIDENCE},
        'what_must_be_seen': [
            'Each roster entry of the six loads the donor the manifest names for its label (Chris (Safari) loads the '
            'uPl00ChrisCos2 donor); a stock costume on a slot means that label-to-archive row is wrong.',
            'Enemies of every class in the stage are several different whole characters at once; the shares per '
            'carrier are in receipt-enemies.json under each class.',
            'No enemy without a body, none showing two characters, no stock Majini part (the montage reading).',
            'Score and kills advance; the round ends by the kill goal or death, not by a hang.'],
        'failure_signs': [
            'A hang or black screen at the stage load: bisect by removing one class archive at a time; uEm12, uEm13, '
            'uEm14 and uEm21 have never been loaded with an edit.',
            'Enemies that can be hit but are not drawn: a spawn selected no carrier group (the table reading is wrong '
            'for that class).',
            'The uEm21 enemy (Public Assembly) as a stock Majini: the game drew the em2100 of uEm10.arc, not this one.',
            'A donor shown through the wrong texture (Majini cloth on a character): two archives carry that texture '
            'and the other copy won.'],
        'live_verified': False, 'gameplay_verified': False, 'writer_registered': False,
        'acceptance': 'experimental; offline structural checks only'}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=1), encoding='utf-8')
    return receipt


def build_series(seed, *, survey_path: Path, enemy_survey_path: Path | None, romfs: Path, archives_dir: Path,
                 library: Path, out: Path, count: int, tables: dict[str, str] | None = None,
                 exclude: set[str] | frozenset = frozenset(), previews: bool = True, progress=None,
                 singles: bool = False, rejects: dict[str, str] | None = None) -> dict:
    """Plan the series and write its first `count` builds; return the manifest (also written to <out>/manifest.json).

    `enemy_survey_path` is the enemy go/no-go (`re5_enemy_cast.survey`) over the shared survey's donors; without it
    every donor is tried as an enemy and refusals are found while building. `exclude` leaves donors out by slug.
    `rejects` ({slug: reason}, default: RE5's entries of gbox.donor_rejects) are left out of every role before the
    series is dealt: a donor out of proportion on the rig, or one the operator swapped out, is never dealt again.
    """
    from . import donor_rejects
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rejects = donor_rejects.rejected('re5') if rejects is None else dict(rejects)
    exclude = frozenset(exclude) | frozenset(rejects)
    donors, windings = load_pool(survey_path)
    donors = [donor for donor in donors if donor.slug not in exclude]
    by_slug = {donor.slug: donor for donor in donors}
    if enemy_survey_path is not None:
        rows = json.loads(Path(enemy_survey_path).read_text(encoding='utf-8'))
        enemy_pool = {row['slug'] for row in rows if row.get('usable') and row['slug'] in by_slug}
        enemy_reasons = {row['slug']: row['reason'] for row in rows if not row.get('usable') and row['slug'] in by_slug}
    else:
        enemy_pool, enemy_reasons = set(by_slug), {}
    sizes = enemy_slots(tables=tables, singles=singles)
    refusals: dict[str, dict[str, str]] = {slug: {'enemy': reason} for slug, reason in enemy_reasons.items()}
    manifest_path = out / 'manifest.json'
    fixed: list[Build] = []
    built: list[dict] = []
    builds = plan_series(seed, donors, enemy_pool=enemy_pool, sizes=sizes, refusals=refusals)
    while len(built) < min(count, len(builds)):
        build = builds[len(built)]
        if progress:
            progress(f'{build.name}: {len(build.slugs())} donors, {len(build.first_time)} for the first time')
        seen = {slug for earlier in fixed for slug in earlier.slugs()}
        try:
            receipt = build_one(build, romfs=romfs, archives_dir=archives_dir, library=library, out=out / build.name,
                                windings=windings, donors=by_slug, enemy_pool=enemy_pool, seen=seen,
                                refusals=refusals, tables=tables, previews=previews, progress=progress)
        except SeriesError as exc:
            if getattr(exc, 'slug', None) is None:
                raise
            refusals.setdefault(exc.slug, {})[exc.role] = str(exc)
            if progress:
                progress(f'set aside for the {exc.role} role: {exc.slug}; dealing again from {build.name}')
            builds = plan_series(seed, donors, enemy_pool=enemy_pool, sizes=sizes, refusals=refusals, fixed=fixed)
            manifest = _manifest(seed, survey_path, enemy_survey_path, donors, enemy_pool, sizes, refusals, builds,
                                 built, exclude)
            manifest_path.write_text(json.dumps(manifest, indent=1), encoding='utf-8')   # the refusal is on record
            continue
        build.first_time = sorted(set(build.slugs()) - seen)      # substitutions may have changed the deal
        fixed.append(build)
        built.append(receipt)
        builds = plan_series(seed, donors, enemy_pool=enemy_pool, sizes=sizes, refusals=refusals, fixed=fixed)
        manifest = _manifest(seed, survey_path, enemy_survey_path, donors, enemy_pool, sizes, refusals, builds, built,
                             exclude)
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    manifest = _manifest(seed, survey_path, enemy_survey_path, donors, enemy_pool, sizes, refusals, builds, built,
                         exclude)
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    return manifest


def _manifest(seed, survey_path, enemy_survey_path, donors, enemy_pool, sizes, refusals, builds, built, exclude) -> dict:
    receipts = {row['index']: row for row in built}
    rows = []
    for build in builds:
        row = {'index': build.index, 'name': build.name, 'seed': build.seed, 'built': build.index in receipts,
               'players': {key: {'label': players.SLOTS[key].label, 'archive': players.SLOTS[key].player_class,
                                 'donor': slug} for key, slug in build.players.items()},
               'enemies': build.enemies, 'donors': len(build.slugs()), 'first_time_in_series': build.first_time,
               'substitutions': build.substitutions}
        if build.index in receipts:
            row.update(folder=build.name, files=receipts[build.index]['files'])
        rows.append(row)
    franchises = {}
    for donor in donors:
        franchises[donor.franchise] = franchises.get(donor.franchise, 0) + 1
    covered = {slug for build in builds for slug in build.slugs()}
    return {
        'recipe': 're5_cast_series', 'seed': str(seed), 'title_id': enemies.TITLE_ID, 'game_id': enemies.GAME_ID,
        'survey': {'path': str(survey_path), 'sha256': hashlib.sha256(Path(survey_path).read_bytes()).hexdigest(),
                   'usable_donors': len(donors), 'excluded_by_name': sorted(exclude)},
        'enemy_survey': {'path': str(enemy_survey_path) if enemy_survey_path else None,
                         'sha256': hashlib.sha256(Path(enemy_survey_path).read_bytes()).hexdigest()
                         if enemy_survey_path else None, 'eligible': len(enemy_pool)},
        'franchises': dict(sorted(franchises.items(), key=lambda kv: (-kv[1], kv[0]))),
        'slots': {'players': {key: players.SLOTS[key].label for key in PLAYER_SLOTS},
                  'enemies': {enemy: {'carriers': count,
                                      'table': writer.MIXES[enemy].name if enemy in writer.MIXES else 'every option group',
                                      'stage_coverage_no_mercy': writer.STAGE_COVERAGE.get(enemy, {})}
                              for enemy, count in sizes.items()},
                  'classes_without_a_writer': writer.UNBUILDABLE_CLASSES,
                  'donors_per_build': len(PLAYER_SLOTS) + sum(sizes.values())},
        'builds': rows, 'build_count': len(builds), 'built': len(built),
        'coverage': {'donors_dealt': len(covered), 'donors_in_pool': len(donors),
                     'not_dealt': sorted(donor.slug for donor in donors if donor.slug not in covered)},
        'refusals': refusals,
        'label_table': {'archives': players.LABEL_ARCHIVES, 'evidence': players.LABEL_EVIDENCE},
        'rotation': ROTATION,
        'live_verified': False, 'gameplay_verified': False,
        'acceptance': 'experimental; offline structural checks only; no build of the series has been booted'}


def main(argv=None) -> int:
    """CLI: --romfs ROMFS --archives ORIGINALS --library LIB --survey library-survey.json [--enemy-survey FILE]
    --seed SEED --out DIR [--count 4] [--table CLASS=table] [--exclude a,b] [--no-preview] | --plan-only"""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='A deterministic series of RE5 Switch pool builds over every donor')
    parser.add_argument('--romfs', required=True, help='extracted RomFS root with the six player archives')
    parser.add_argument('--archives', required=True, help='folder holding the original class archives')
    parser.add_argument('--library', required=True)
    parser.add_argument('--survey', required=True, help='re5_cast_writer survey report (the 650 usable donors)')
    parser.add_argument('--enemy-survey', help='re5_enemy_cast survey over those donors (enemy go/no-go)')
    parser.add_argument('--seed', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--count', type=int, default=4, help='how many builds to write')
    parser.add_argument('--table', action='append', default=[], help='CLASS=table (another reviewed mix table)')
    parser.add_argument('--exclude', default='', help='comma-separated slugs to leave out')
    parser.add_argument('--no-preview', action='store_true')
    parser.add_argument('--with-bosses', action='store_true',
                        help='also deal one donor to every reviewed class without a mix table (the boss classes)')
    parser.add_argument('--plan-only', action='store_true', help='print the plan, write nothing')
    args = parser.parse_args(argv)
    tables = dict(text.split('=', 1) for text in args.table) or None
    from . import donor_rejects
    exclude = frozenset(slug for slug in args.exclude.split(',') if slug) | frozenset(donor_rejects.rejected('re5'))
    try:
        if args.plan_only:
            donors, _ = load_pool(Path(args.survey))
            donors = [donor for donor in donors if donor.slug not in exclude]
            enemy_pool = {donor.slug for donor in donors}
            refusals = {}
            if args.enemy_survey:
                rows = json.loads(Path(args.enemy_survey).read_text(encoding='utf-8'))
                enemy_pool = {row['slug'] for row in rows if row.get('usable')}
                refusals = {row['slug']: {'enemy': row['reason']} for row in rows if not row.get('usable')}
            builds = plan_series(args.seed, donors, enemy_pool=enemy_pool,
                                 sizes=enemy_slots(tables=tables, singles=args.with_bosses), refusals=refusals)
            print(json.dumps([{'name': b.name, 'players': b.players, 'enemies': b.enemies,
                               'first_time': len(b.first_time)} for b in builds], indent=1))
            return 0
        manifest = build_series(args.seed, survey_path=Path(args.survey),
                                enemy_survey_path=Path(args.enemy_survey) if args.enemy_survey else None,
                                romfs=Path(args.romfs), archives_dir=Path(args.archives), library=Path(args.library),
                                out=Path(args.out), count=args.count, tables=tables, exclude=exclude,
                                previews=not args.no_preview, progress=lambda text: print(text, flush=True),
                                singles=args.with_bosses)
    except (SeriesError, players.CastWriterError, enemies.CastError, writer.EnemyWriterError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'builds': manifest['build_count'], 'built': manifest['built'],
                      'coverage': manifest['coverage'], 'refusals': len(manifest['refusals'])}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
