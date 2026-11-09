"""Enemy casts for RE5 Switch Mercenaries: library donors on the Majini classes, one overlay tree per cast.

Three ways to put more than one character into a round, all composed here from `re5_enemy_writer`:

* **one donor per class** - donor A on `uEm10` (the men), donor B on `uEm11` (the women). Every option group of the
  class carries the donor; this is the shape the game has loaded and drawn (SM64 DS Mario on `uEm10`, 2026-11-09).
* **a mix** - several donors on ONE class, one per montage carrier (`uEm10`: the ten pants textures, `uEm11`: the two
  shirts). A spawn then shows the donor of the pants its montage selects. This rests on an inferred reading of the
  montage table and has not been booted; its receipt says what a live frame must show.
* **a pool** - `plan(seed, ...)` deals donors from a surveyed library over the carriers of every class without a
  repeat inside one overlay, alternating franchises, so different seeds give different rounds.

    <out>/<name>/romfs/nativeNXx64/ImgNX/Archive/uEm10.arc     complete replacement archives, one per class
    <out>/<name>/receipt.json                                  donors, hashes, groups, role maps, fits, counts
    <out>/<name>/preview.png, preview-posed.png                every donor: rest pose, and one native clip on the CPU

Nothing here installs, launches or registers anything, and every receipt says `live_verified: False`. A structurally
valid archive is not a visible replacement: only a watched round shows which character the game draws.

Donor seam: this module asks a library entry for nothing but `re5_enemy_writer.Donor` (slug, name, model path,
sha256, the fifteen role joints, provenance) through `find_donor`, and for a go/no-go through `survey`. A shared
donor survey / role-profile module can replace those two functions without touching the writer.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from . import characters, mtf_materials
from . import re5_enemy_writer as writer

TITLE_ID, GAME_ID = '010018100CD46000', '52d15709be0fda1a'
BACKDROP = (54, 60, 72)

#: The reviewed one-donor-per-class casts: (class, library slug, fit). Any other library donor with complete role
#: metadata builds through `--assign` without a change here.
CASTS = {
    'enemy-cast-a-v1': (('uEm10', 'sm64ds_mario', 'native_height'), ('uEm11', 'sm64ds_luigi', 'native_height')),
    'enemy-cast-b-v1': (('uEm10', 'sa2_shadow', 'native_height'), ('uEm11', 'sa2_amy_rose', 'native_height')),
    'enemy-cast-c-v1': (('uEm10', 'sonic', 'native_height'), ('uEm11', 'sa2_tails', 'native_height')),
}
#: Model revisions that were reviewed; a reviewed slug must be this file. Other donors are recorded by hash.
DONORS = {
    'sm64ds_mario': 'ea509bdf870190e72c3fe9046b916a3b83d3a8058af422ad6186b11332bf12bb',
}

#: What the first boot of an overlay can show, per class. `uEm10` with every group carrying one donor has been loaded
#: and drawn by the game (the Mario candidate, 2026-11-09); everything else here has not.
FIRST_BOOT_RISKS = {
    'uEm10': [
        'The table shape (native records blanked, one donor record per option group, three LOD models) is the one the '
        'game loaded and drew with SM64 DS Mario. A donor with more vertices grows each model further than that test.',
        'The fit is new: per-role scales and a lowered head have not been drawn. A part that is too small or detached '
        'shows as a gap at the shoulders, hips or neck; it is not a format fault.',
        'Rigid donors crease at elbows, knees and shoulders; skinned donors keep at most four influences per vertex.',
    ],
    'uEm11': [
        'uEm11.arc has never been loaded with any edit by this writer: a load hang or black screen here is new '
        'information. Remove this one file from the overlay to return to the uEm10-only state.',
        'Only em1100 is replaced. Every Mercenaries layout spawns uEm11 with model type 0; that em1100 is model type 0 '
        'is inferred from uEm10 (em1000 replaced alone drew the donor), not observed. Stock women with a donor atlas '
        'on their clothes mean the archive loaded and the game draws em1101.',
        'The atlas sits on a cloth material, not the sandal material that has drawn a donor: its flag field differs '
        'and it has never drawn this vertex format. Wrong surface (too dark, glossy, see-through) points here.',
        'em1100 has an origin bone above its body root that em1000 does not have; the donor is bound to the same role '
        'bones, but a donor standing in the floor or floating would point at that bone.',
    ],
}
MIX_RISKS = [
    'Donor records exist only in the carrier groups. If the game selects groups in another way than the montage table '
    'reads, a spawn can come out with no body at all (hits and shadows without a figure) or with two overlapping '
    'figures.',
    'Each donor uses its own native material (the pants or shirt material of its carrier). Those materials have drawn '
    'the donor vertex format natively, but never a donor; a wrong surface on one character only points at its material.',
    'The mesh table is still grown and every native record blanked, as in the proven shape; only the number and the '
    'groups of the donor records differ (one per carrier group instead of one per option group).',
]


def mix_expectation(row: dict) -> dict:
    """What a live round must show for the montage reading to be right, and what it shows when it is wrong."""
    donors = [f'{d["name"]} ({d["share_if_montages_are_uniform"]} outfits)' for d in row['donors']]
    return {
        'right': [
            f'Enemies of class {row["class"]} appear as several different characters in the same round: '
            + ', '.join(donors) + '.',
            'Each enemy is one whole character: no Majini part, no second figure inside it, nothing missing.',
            'An enemy keeps its character while it walks from far to near (the three LOD models carry the same deal).',
            'Counting them over a round gives the montage picture: if the game picks the montages uniformly the '
            'shares are the ones listed; another stable ratio means a stage-specific montage list, which is still '
            'the idea working.',
        ],
        'wrong': [
            f'Every {row["class"]} enemy is the same single character: the game does not vary the carrier category '
            'the way the table reads (or always picks one montage).',
            'Some enemies have no body (they can be hit, cast a shadow or bleed, but nothing is drawn): a spawn '
            'selected no carrier group, so groups are not chosen from this table as read.',
            'An enemy shows two characters at once: a spawn selected two carrier groups.',
            'Stock Majini parts on a donor: a native record was drawn, which the offline decoder says cannot happen.',
        ],
        'evidence_to_keep': 'build and session ids, the class census from RAM, frames with at least two different '
                            'donors in view, kills and score advancing, and a count of donors seen over the round',
    }


class CastError(ValueError):
    """The cast cannot be built; the message names the class, the donor and the reason."""


@dataclass(frozen=True)
class Assignment:
    """What one class archive carries: one donor on every option group, or several donors as a mix."""
    enemy: str                              # 'uEm10'
    donors: tuple[writer.Donor, ...]
    fits: tuple[writer.Fit, ...]
    mix: bool = False                       # one donor may also be built as a mix (carried by the carrier groups only)
    models: tuple[str, ...] | None = None   # narrow the class to some model names (a bisect build)


# --- library ------------------------------------------------------------------------------------------------------

def find_donor(slug: str, libraries: list[Path]) -> writer.Donor:
    """The library entry `slug` in the first library that has it; a reviewed slug must be its pinned revision."""
    if not slug or Path(slug).name != slug:
        raise CastError(f'{slug!r} is not a library slug')
    for library in libraries:
        entry = Path(library) / slug
        if (entry / 'meta.json').is_file():
            return writer.load_donor(entry, sha256=DONORS.get(slug))
    raise CastError(f'no library entry {slug!r} under {", ".join(str(p) for p in libraries) or "(no library given)"}')


def franchise(donor: writer.Donor) -> str:
    """The donor's source game, the key franchises are alternated by."""
    return str(donor.provenance.get('game') or 'unknown')


def survey(libraries: list[Path], slugs: list[str] | None = None, *, atlas_size=(512, 256),
           trial: tuple[bytes, str] | None = None) -> list[dict]:
    """Go/no-go for library entries as enemy donors, with the reason for every refusal.

    A donor is usable when its metadata names the fifteen roles, its model loads through the atlas importer at the
    enemy atlas size, `check_rig` accepts its joints, and the default fit on the measured `em1000` joints gives a
    whole figure: no height between the ankles and the head joint is left without geometry (a chest floating above
    its hips, a head above its neck). `trial` = (original archive bytes, class) also builds every such donor on the
    first model of that class and keeps only the ones the writer accepts (a fit can still collapse a triangle or
    need a fifth skin influence); the trial archive is thrown away. Without it nothing is built.
    """
    names = slugs if slugs is not None else sorted({p.parent.name for lib in libraries
                                                    for p in Path(lib).glob('*/meta.json')})
    rows = []
    for slug in names:
        row = {'slug': slug, 'usable': False}
        try:
            donor = find_donor(slug, libraries)
            row.update(name=donor.name, franchise=franchise(donor), sha256=donor.sha256)
            vertices, triangles, _, report = mtf_materials.source_mesh(donor.model, atlas_size=atlas_size)
            gltf, _, _, world = characters._load(donor.model)
            nodes, joints = writer._donor_joints(gltf, world, donor.roles, slug)
            orphans: set = set()
            owners = writer._role_owners(vertices, gltf, nodes, orphans)
            rig = writer.check_rig(vertices, owners, joints, slug)
            floor = min(v['position'][1] for v in vertices)
            if any(joints[f'{side}_foot'][1] - floor <= 1e-6 for side in 'lr'):
                raise writer.EnemyWriterError(f'{slug} has an incomplete rig: its ankles are not above its floor')
            bind = writer.REFERENCE_BIND
            limbs, scales, offsets, fitted = writer.fit_scales(writer.NATIVE_HEIGHT, vertices, owners, joints, bind,
                                                               writer.REFERENCE_TOP)
            row.update(scales={key: round(fitted[key], 3) for key in ('limbs', 'torso', 'head', 'hands')})
            placed = writer.fitted_points(vertices, gltf, world, nodes, bind, limbs, scales, offsets,
                                          orphans=bool(orphans))
            holes = writer.vertical_holes(placed, triangles, bind['l_foot'][1], bind['head'][1])
            problems = [f'nothing of it is drawn between {a:.0f} and {b:.0f} cm' for a, b in holes]
            if problems:
                raise writer.EnemyWriterError(f'{slug} does not fit the Majini skeleton well: ' + '; '.join(problems))
            if trial is not None:
                enemy = writer.ARCHIVES[trial[1]]
                target = enemy.targets()[0]
                first = target.models[0][0].rsplit('\\', 1)[-1]
                writer.build_donor(trial[0], donor, enemy, models=(first,))
                row['trial'] = f'built on {first}'
            row.update(usable=True, vertices=len(vertices), triangles=len(triangles),
                       texture_scale=report.get('texture_scale'),
                       roles_without_vertices=rig['roles_without_vertices'])
        except (CastError, writer.EnemyWriterError) as exc:
            row['reason'] = str(exc)
        except (ValueError, OSError, KeyError) as exc:      # the importer's own refusals (materials, samplers, sizes)
            row['reason'] = f'{slug} cannot be imported: {exc}'
        rows.append(row)
    return rows


# --- seeded pools -------------------------------------------------------------------------------------------------

def plan(seed: int, slots: dict[str, int], donors: dict[str, str]) -> dict[str, list[str]]:
    """Deal donors over the classes of one overlay: {class: [slug, ...]} with no donor used twice.

    `slots` is {class: how many different donors it shows} and `donors` is {slug: franchise}. The deal is a pure
    function of its arguments. Each pick draws a franchise first and then a donor of it, so a franchise with fifty
    entries does not crowd out one with a single character, and no franchise gets more than a quarter of an overlay
    while another can still serve. Different seeds therefore give different mixes, not the same faces reordered.
    """
    if any(count < 1 for count in slots.values()) or not slots:
        raise CastError('every class needs at least one donor')
    wanted = sum(slots.values())
    if wanted > len(donors):
        raise CastError(f'{wanted} different donors were asked for and the pool holds {len(donors)}')
    rng = random.Random(int(seed))
    pools: dict[str, list[str]] = {}
    for slug in sorted(donors):
        pools.setdefault(donors[slug], []).append(slug)
    cap = max(1, -(-wanted // 4))
    taken = {name: 0 for name in pools}
    dealt = []
    for _ in range(wanted):
        open_ = sorted(name for name in pools if pools[name])
        under = [name for name in open_ if taken[name] < cap]
        name = rng.choice(under or open_)
        dealt.append(pools[name].pop(rng.randrange(len(pools[name]))))
        taken[name] += 1
    out, cursor = {}, 0
    for enemy in sorted(slots):
        out[enemy] = dealt[cursor:cursor + slots[enemy]]
        cursor += slots[enemy]
    return out


# --- overlays -----------------------------------------------------------------------------------------------------

def parse_assignment(text: str, libraries: list[Path], models: dict[str, tuple[str, ...]] | None = None) -> Assignment:
    """`uEm10=sm64ds_mario`, `uEm10=sm64ds_mario@proportional`, or a mix `uEm10=sonic+sa2_shadow+sm64ds_luigi`."""
    enemy, _, rest = text.partition('=')
    if enemy not in writer.ARCHIVES or not rest:
        raise CastError(f'{text!r} is not CLASS=slug[@fit][+slug...] with a class of {sorted(writer.ARCHIVES)}')
    donors, fits = [], []
    for part in rest.split('+'):
        slug, _, fit = part.partition('@')
        if fit and fit not in writer.FITS:
            raise CastError(f'{fit!r} is not a fit; choose from {sorted(writer.FITS)}')
        donors.append(find_donor(slug, libraries))
        fits.append(writer.FITS[fit or 'native_height'])
    return Assignment(enemy, tuple(donors), tuple(fits), mix=len(donors) > 1, models=(models or {}).get(enemy))


def _stack(rows: list[Path], out: Path) -> None:
    """One picture from one row per donor, left aligned."""
    from PIL import Image
    images = [Image.open(row).convert('RGB') for row in rows]
    sheet = Image.new('RGB', (max(i.width for i in images), sum(i.height for i in images)), BACKDROP)
    top = 0
    for image in images:
        sheet.paste(image, (0, top))
        top += image.height
    sheet.save(out)


def _fit_row(fit: dict) -> dict:
    return {'name': fit['name'], 'scales': fit['scales'], 'rules': fit['rules'], 'role_offsets': fit['role_offsets'],
            'height_cm': fit['height'], 'native_height_cm': fit['native_height'], 'bounds': fit['bounds'],
            'shape': fit['shape']}


def build_cast(name: str, assignments: list[Assignment], archives: dict[str, bytes], out: Path, *,
               previews: bool = True, secondary: str = 'neutral') -> dict:
    """Build every assigned class, write the overlay tree under `out`, and return its receipt.

    `archives` holds the measured original bytes per class. Each written archive is complete (every entry of the
    original, the reviewed ones replaced), so the overlay is the files themselves; no other file of the title is
    written. Everything is built and verified before the first byte is written.
    """
    if not name or Path(name).name != name:
        raise CastError('a cast needs a plain folder name')
    classes = [a.enemy for a in assignments]
    if not assignments or len(set(classes)) != len(classes):
        raise CastError('a cast assigns donors to each class once, and to at least one class')
    missing = [enemy for enemy in classes if enemy not in archives]
    if missing:
        raise CastError(f'the original archives of {", ".join(missing)} were not given')
    used = [donor.sha256 for a in assignments for donor in a.donors]
    if len(set(used)) != len(used):
        raise CastError('a donor may appear once in an overlay')
    out = Path(out)
    built = {}
    for a in assignments:
        enemy = writer.ARCHIVES[a.enemy]
        try:
            if a.mix:
                built[a.enemy] = writer.build_mix(archives[a.enemy], list(a.donors), enemy, fits=list(a.fits),
                                                  models=a.models, secondary=secondary)
            else:
                built[a.enemy] = writer.build_donor(archives[a.enemy], a.donors[0], enemy, models=a.models,
                                                    fit=a.fits[0], secondary=secondary)
        except writer.EnemyWriterError as exc:
            raise CastError(f'{a.enemy} <- {"+".join(d.slug for d in a.donors)}: {exc}') from exc
    rest, posed, rows = [], [], {}
    for a in assignments:
        enemy = writer.ARCHIVES[a.enemy]
        output, receipt = built[a.enemy]
        path = out / 'romfs' / enemy.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(output)
        target = writer.SETS[writer.MIXES[a.enemy].target] if a.mix else enemy.targets()[0]
        if a.models is not None:
            target = writer.only_models(target, a.models)
        row = {'archive': 'romfs/' + enemy.path, 'class': enemy.name, 'source_sha256': enemy.sha256,
               'output_sha256': receipt['written_sha256'], 'output_bytes': len(output),
               'models': receipt['target']['models'], 'not_replaced': receipt['target']['not_replaced'],
               'unbuilt': receipt['target']['unbuilt'],
               'option_group_slots': {slot: list(ids) for slot, ids in target.groups},
               'role_map': receipt['role_map'], 'counts': receipt['counts'],
               'entries_replaced': receipt['entries_replaced'], 'live_verified': False}
        carriers = list(writer.MIXES[a.enemy].carriers) if a.mix else [None]
        shown = {}                                           # one picture row per different donor
        for number, carrier in enumerate(carriers):
            key = receipt['carriers'][number]['donor']['slug'] if a.mix else a.donors[0].slug
            if key not in shown:
                shown[key] = carrier
        pictures = {}
        if previews:
            entry, clip, frames = enemy.pose
            sampled = None                                   # one clip sample serves every donor of the archive
            for slug, carrier in shown.items():
                still = out / f'preview-{enemy.name}-{slug}.png'
                moving = out / f'preview-{enemy.name}-{slug}-posed.png'
                moved = writer.posed_preview(archives[a.enemy], output, moving, motion_entry=entry, clip=clip,
                                             frames=frames, target=target, backdrop=BACKDROP, carrier=carrier,
                                             sampled=sampled)
                sampled = moved.pop('sampled', None)
                pictures[slug] = {
                    'rest': writer.preview(output, still, target=target, backdrop=BACKDROP, carrier=carrier)
                    | {'preview': still.name},
                    'posed': moved | {'preview': moving.name}}
                rest.append(still)
                posed.append(moving)
        if a.mix:
            row.update(
                kind='mix', mix=receipt['mix'], slot=receipt['slot'], donors=receipt['donors'],
                option_groups_handled=sorted(int(group) for group in receipt['option_groups']['groups']),
                carrier_groups=sorted(group for c in receipt['carriers'] for group in c['groups']),
                carriers=[{'carrier': c['carrier'], 'groups': c['groups'], 'albedo': c['albedo'],
                           'atlas_size': c['atlas_size'], 'donor': c['donor']['slug'], 'fit': _fit_row(c['fit']),
                           'montages': c['montages'],
                           'share_if_montages_are_uniform': c['share_if_montages_are_uniform'],
                           'texture_scale': c['atlas_source'].get('texture_scale')} for c in receipt['carriers']],
                montage_table=receipt['montage_table'], first_boot_risks=MIX_RISKS + FIRST_BOOT_RISKS[enemy.name][-3:]
                if enemy.name == 'uEm11' else MIX_RISKS)
            row['live_test'] = mix_expectation(row)
        else:
            fit = receipt['fit']
            row.update(
                kind='one donor on every option group', donor=receipt['source'],
                option_groups_handled=sorted(int(group) for group in receipt['option_groups']['groups']),
                fit=_fit_row(fit),
                atlas={'texture': receipt['appearance']['atlas_texture'], 'size': receipt['appearance']['atlas_size'],
                       'material': receipt['appearance']['material'],
                       'texture_scale': receipt['appearance']['atlas_source'].get('texture_scale')},
                first_boot_risks=FIRST_BOOT_RISKS.get(enemy.name, []))
        row.update(previews=pictures, receipt=receipt)
        rows[enemy.name] = row
    if previews:
        _stack(rest, out / 'preview.png')
        _stack(posed, out / 'preview-posed.png')
    donors = {}
    for enemy, row in rows.items():
        if row['kind'] == 'mix':
            donors[enemy] = [{'slug': d['slug'], 'name': d['name'], 'sha256': d['sha256'], 'fit': d['fit'],
                              'groups': d['groups'], 'share_if_montages_are_uniform':
                                  d['share_if_montages_are_uniform']} for d in row['donors']]
        else:
            donors[enemy] = [{'slug': row['donor']['slug'], 'name': row['donor']['name'],
                              'sha256': row['donor']['sha256'], 'fit': row['fit']['name'],
                              'height_cm': round(row['fit']['height_cm'], 1), 'groups': 'every option group'}]
    receipt = {
        'recipe': 're5_enemy_cast', 'name': name, 'title_id': TITLE_ID, 'game_id': GAME_ID,
        'donors': donors, 'archives': rows,
        'overlay_files': [row['archive'] for row in rows.values()],
        'previews': {'rest': 'preview.png', 'posed': 'preview-posed.png'} if previews else {},
        'classes_left_native': 'every enemy class without an archive in this overlay (executioners, dogs, bosses, '
                               'the other Majini classes) is drawn as shipped',
        'install': 'a separate recovery-* LayeredFS build through switch_mods; never the live acceptance build',
        'live_verified': False, 'gameplay_verified': False, 'writer_registered': False,
        'acceptance': 'experimental; offline structural checks only'}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def main(argv=None) -> int:
    """CLI: --archives DIR --library DIR [--library DIR] --out DIR
    (--cast NAME | --name NAME --assign CLASS=slug[@fit][+slug...] | --name NAME --pool SEED [--pool-from FILE])
    [--only-models CLASS=model[,model]] [--no-preview] | --survey [--slugs a,b]"""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Build an offline RE5 Switch enemy-cast overlay tree')
    parser.add_argument('--archives', help='folder holding the original uEm10.arc / uEm11.arc')
    parser.add_argument('--library', action='append', required=True, help='a character library folder (repeatable)')
    parser.add_argument('--out', help='parent folder; the tree is written to <out>/<name>')
    parser.add_argument('--cast', choices=sorted(CASTS), help='one of the reviewed casts')
    parser.add_argument('--name', help='folder name for --assign and --pool builds')
    parser.add_argument('--assign', action='append', default=[],
                        help='CLASS=slug[@fit] or a mix CLASS=slug+slug+..., e.g. uEm10=sm64ds_mario')
    parser.add_argument('--pool', type=int, help='seed: deal surveyed donors over the mix carriers of every class')
    parser.add_argument('--pool-from', help='a survey JSON written by --survey (default: survey the libraries now)')
    parser.add_argument('--pool-size', default='uEm10=10,uEm11=2', help='CLASS=count,... different donors per class')
    parser.add_argument('--pool-max-vertices', type=int, default=4500, help='leave out heavier donors')
    parser.add_argument('--pool-exclude', default='', help='comma-separated text; a slug or franchise holding it is out')
    parser.add_argument('--only-models', action='append', default=[], help='CLASS=model[,model] (a bisect build)')
    parser.add_argument('--no-preview', action='store_true')
    parser.add_argument('--survey', action='store_true',
                        help='print the go/no-go of the library entries and exit; with --archives each usable donor '
                             'is also trial-built on em1000')
    parser.add_argument('--slugs', help='limit --survey to these comma-separated slugs')
    args = parser.parse_args(argv)
    libraries = [Path(p) for p in args.library]
    try:
        if args.survey:
            trial = None
            if args.archives:                                 # with the originals at hand, also try each donor
                path = Path(args.archives) / Path(writer.ARCHIVES['uEm10'].path).name
                if not path.is_file():
                    raise CastError(f'{path} is missing')
                trial = (path.read_bytes(), 'uEm10')
            print(json.dumps(survey(libraries, args.slugs.split(',') if args.slugs else None, trial=trial), indent=1))
            return 0
        chosen = [bool(args.cast), bool(args.assign), args.pool is not None]
        if sum(chosen) != 1 or not args.archives or not args.out:
            raise CastError('give --archives, --out and exactly one of --cast, --assign, --pool')
        name = args.cast or args.name
        if not name:
            raise CastError('--assign and --pool builds need a --name')
        only = {}
        for text in args.only_models:
            enemy, _, models = text.partition('=')
            only[enemy] = tuple(model for model in models.split(',') if model)
        if args.pool is not None:
            rows = (json.loads(Path(args.pool_from).read_text(encoding='utf-8')) if args.pool_from
                    else survey(libraries))
            out_words = [word for word in args.pool_exclude.split(',') if word]
            usable = {row['slug']: row['franchise'] for row in rows
                      if row.get('usable') and row.get('vertices', 0) <= args.pool_max_vertices
                      and not any(word in row['slug'] or word in row['franchise'] for word in out_words)}
            sizes = {enemy: int(count) for enemy, _, count in (p.partition('=') for p in args.pool_size.split(','))}
            dealt = plan(args.pool, sizes, usable)
            texts = [f'{enemy}=' + '+'.join(slugs) for enemy, slugs in dealt.items()]
        elif args.cast:
            texts = [f'{enemy}={slug}@{fit}' for enemy, slug, fit in CASTS[args.cast]]
        else:
            texts = args.assign
        assignments = [parse_assignment(text, libraries, only) for text in texts]
        if args.pool is not None:                            # a pool is always a mix, also with one donor in a class
            assignments = [Assignment(a.enemy, a.donors, a.fits, True, a.models) for a in assignments]
        archives = {}
        for a in assignments:
            path = Path(args.archives) / Path(writer.ARCHIVES[a.enemy].path).name
            if not path.is_file():
                raise CastError(f'{path} is missing')
            archives[a.enemy] = path.read_bytes()
        receipt = build_cast(name, assignments, archives, Path(args.out) / name, previews=not args.no_preview)
        if args.pool is not None:
            receipt['pool'] = {'seed': args.pool, 'sizes': sizes, 'pool_donors': len(usable),
                               'franchises': sorted(set(usable.values())), 'max_vertices': args.pool_max_vertices,
                               'excluded': out_words, 'dealt': dealt}
            (Path(args.out) / name / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    except (CastError, writer.EnemyWriterError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'cast': name, 'folder': str(Path(args.out) / name), 'donors': receipt['donors'],
                      'archives': {enemy: {'sha256': row['output_sha256'], 'bytes': row['output_bytes']}
                                   for enemy, row in receipt['archives'].items()}}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
