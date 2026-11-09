"""Which library characters can stand on a native RE5 skeleton, and why the others cannot.

Shared by the RE5 writers (`re5_cast_writer` for the player slots, `re5_enemy_writer` for the enemies): both fit a donor
through the same fifteen anatomical roles, so the donor side lives here and neither writer owns it.

* `rig_check` holds a role profile against the donor's own joints, skin and surface and refuses an incomplete rig with
  the reason;
* `resolve` turns one library folder into a `Donor`: it tries the folder's own role metadata, then the joint-tree
  measurement `characters.tree_roles`, each with the hip raised to a skinned parent joint when that is what is missing,
  and accepts the first profile `rig_check` passes. Nothing is guessed past that: a folder no profile fits is refused;
* `survey` does that for a whole library and counts usable donors per source game and refusals per reason;
* `plan` deals donors to slots from a seed: never the same donor twice in one overlay, donors of the last overlays
  last, franchises taken in turn so one large roster does not crowd out the rest.

Read-only: nothing here writes into the library, installs or launches anything.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import characters, mtf_materials

ROLES = ('hip', 'chest', 'head', 'l_upper', 'l_fore', 'l_hand', 'r_upper', 'r_fore', 'r_hand',
         'l_thigh', 'l_shin', 'l_foot', 'r_thigh', 'r_shin', 'r_foot')
#: The role that must be an ancestor of each role in the donor's own joint tree: only along a limb. Rigs differ in how
#: the hip, the spine and the shoulders hang together (SoulCalibur's chest is a sibling of its hip), and the fit does not
#: need that order: it needs every skinned joint to be a role or to hang below one, which `rig_check` measures.
ROLE_PARENTS = {'l_fore': 'l_upper', 'l_hand': 'l_fore', 'r_fore': 'r_upper', 'r_hand': 'r_fore',
                'l_shin': 'l_thigh', 'l_foot': 'l_shin', 'r_shin': 'r_thigh', 'r_foot': 'r_shin'}
MAX_VERTICES = 0xFFFF           # one native mesh record addresses its vertices with 16-bit indices
SURVEY_ATLAS = (1024, 1024)     # the largest atlas a reviewed slot offers
#: Refusal categories, in the order `resolve` can meet them.
REASONS = {'no_metadata': 'the folder has neither metadata nor a model',
           'no_model': 'no 3D model (a 2D sprite sheet or another kind of entry)',
           'model_unreadable': 'the model file is missing or cannot be read',
           'no_rig': 'the model has no skin: nothing binds its surface to joints',
           'no_textures': 'the model carries no texture image',
           'unsupported_surface': 'the surface cannot be packed into one atlas by the bounded importer',
           'too_large': 'more vertices than one native mesh record can address',
           'no_roles': 'no role profile: the metadata names no complete set and the joint tree gives none',
           'rig_refused': 'a role profile exists but the measured rig refuses it',
           'duplicate': 'the same model bytes as another entry'}
_FRANCHISES = (('Sonic', ('sonic',)), ('Mario', ('mario',)), ('Smash Bros.', ('smash bros',)),
               ('Metal Gear', ('metal gear',)), ('Dead or Alive', ('dead or alive',)),
               ('SoulCalibur', ('soul calibur', 'soulcalibur')),
               ('Phantasy Star Online', ('phantasy star', 'return to ragol')), ('Resident Evil', ('resident evil',)),
               ('Wrestling', ('wcw', 'wwf')), ('Def Jam', ('def jam',)), ('007', ('007',)),
               ('Final Fantasy', ('final fantasy',)), ('Zelda', ('zelda',)), ('Grand Theft Auto', ('grand theft auto',)),
               ('Jet Set Radio', ('jet set radio', 'jet grind radio')), ('Stranglehold', ('stranglehold',)),
               ('Marvel vs. Capcom', ('marvel vs',)), ('Metal Arms', ('metal arms',)), ('Crazy Taxi', ('crazy taxi',)),
               ('Parasite Eve', ('parasite eve',)), ('Shenmue', ('shenmue',)), ('Tetris', ('tetris',)),
               ('Clay Fighter', ('clay fighter',)))
#: An explicit size in the metadata (`size`, top level or under `rig`) and the height factor it stands for. No library
#: entry sets one today, so every donor is brought to the slot's native height; the hook is here for the day one does.
SIZE_FACTORS = {'large': 1.15, 'small': .85}


class DonorError(ValueError):
    """The folder is not a usable donor; `category` is one of `REASONS` and the message says why."""

    def __init__(self, category: str, reason: str):
        super().__init__(reason)
        self.category = category


@dataclass(frozen=True)
class Donor:
    """One usable library model: pinned bytes, provenance from its own metadata and its fifteen role joints."""
    slug: str
    name: str
    game: str                       # source game title without region or disc
    franchise: str
    platform: str
    model: str                      # file name inside the library folder
    sha256: str
    roles: tuple[tuple[str, str], ...]
    roles_from: str                 # which profile `rig_check` accepted
    provenance: str
    size: str = 'native'            # 'native', or what the metadata says ('large', 'small', a factor)
    height_factor: float = 1.

    def role_names(self) -> dict[str, str]:
        return dict(self.roles)


def rig_check(gltf: dict, world, vertices: list[dict], triangles: list[tuple], roles: dict[str, str]) -> dict:
    """Check a role profile against the donor's own joints, skin and surface; an incomplete rig raises `ValueError`.

    Returns what was measured: the joints, how much of the skin follows each role, the facing, and whether the triangles
    are wound against their normals (a model exported with clockwise fronts).
    """
    def refuse(reason: str):
        raise ValueError(f'incomplete rig: {reason}')

    missing, unknown = sorted(set(ROLES) - set(roles)), sorted(set(roles) - set(ROLES))
    if missing or unknown:
        refuse('the role profile ' + '; '.join(part for part in (
            f'lacks {", ".join(missing)}' if missing else '', f'names unknown roles {", ".join(unknown)}' if unknown else '')
            if part))
    nodes = gltf.get('nodes') or []
    joint = {}
    for role in ROLES:
        named = [i for i, node in enumerate(nodes) if node.get('name') == roles[role]]
        if len(named) != 1:
            refuse(f'{role} names joint {roles[role]!r}, which the model has {len(named)} times')
        joint[role] = named[0]
    if len(set(joint.values())) != len(ROLES):
        refuse('two roles name the same joint')
    parents = {child: i for i, node in enumerate(nodes) for child in node.get('children', [])}

    def ancestors(node: int) -> list[int]:
        chain, seen = [], set()
        while node in parents and node not in seen:
            seen.add(node)
            node = parents[node]
            chain.append(node)
        return chain

    for role, parent in ROLE_PARENTS.items():
        if joint[parent] not in ancestors(joint[role]):
            refuse(f'{role} ({roles[role]}) does not hang below {parent} ({roles[parent]}) in the joint tree')
    point = {role: np.asarray(world[node], float)[:3, 3] for role, node in joint.items()}
    for part in ('upper', 'fore', 'hand', 'thigh', 'shin', 'foot'):
        if not point[f'l_{part}'][0] > point[f'r_{part}'][0]:
            refuse(f'l_{part} is not on the +X side of r_{part}; the sides are swapped or the model faces -Z')
    for s in 'lr':
        if not point[f'{s}_thigh'][1] > point[f'{s}_shin'][1] > point[f'{s}_foot'][1]:
            refuse(f'the {s} leg does not descend thigh, shin, foot')
    if not point['head'][1] > point['chest'][1] > point['l_thigh'][1]:
        refuse('the head, chest and legs are not stacked upward')
    heights = [float(vertex['position'][1]) for vertex in vertices] or [0.]
    tall = max(heights) - min(heights)
    spine = {'hip_to_chest': float(point['chest'][1] - point['hip'][1]),
             'chest_to_head': float(point['head'][1] - point['chest'][1])}
    if spine['chest_to_head'] < .02 * tall:
        refuse(f'the head joint sits on the chest joint ({spine["chest_to_head"]:.3g} in a model {tall:.3g} tall): '
               'the torso has no length to span a native spine')
    # Many rigs keep the whole torso on one joint whose origin is at the waist, beside the hip joint. That joint's
    # counterpart on a native skeleton is the lower spine joint, not the chest: a writer maps it there.
    torso = 'spine' if spine['hip_to_chest'] >= .02 * tall else 'waist'
    by_node = {node: role for role, node in joint.items()}
    follows = {role: 0. for role in ROLES}
    owner = {}
    foot_points = {'l_foot': [], 'r_foot': []}
    most, blended = 0, 0
    if not vertices or not triangles:
        refuse('the model has no skinned surface')
    for vertex in vertices:
        merged = {}
        for node, weight in zip(vertex.get('source_joints', ()), vertex.get('source_weights', ())):
            if not weight:
                continue
            if node not in owner:
                found = next((by_node[n] for n in [node] + ancestors(node) if n in by_node), None)
                if found is None:
                    name = nodes[node].get('name', f'#{node}') if 0 <= node < len(nodes) else f'#{node}'
                    refuse(f'joint {name!r} carries skin but neither it nor an ancestor is one of the fifteen roles')
                owner[node] = found
            merged[owner[node]] = merged.get(owner[node], 0.) + float(weight)
        if not merged:
            refuse('a vertex has no skin weight')
        if len(merged) > 4:
            refuse('a vertex follows more than four roles; the native skin holds four')
        most, blended = max(most, len(merged)), blended + (len(merged) > 1)
        for role, weight in merged.items():
            follows[role] += weight
            if role in foot_points and weight > .5:
                foot_points[role].append(vertex['position'])
    empty = sorted(role for role, weight in follows.items() if weight <= 0)
    if empty:
        refuse(f'no vertex follows {", ".join(empty)}')
    toes = [float(np.mean(np.asarray(rows, float)[:, 2]) - point[role][2]) for role, rows in foot_points.items() if rows]
    if len(toes) != 2 or min(toes) <= 0:
        refuse('the feet do not extend to +Z from the ankles; the model does not face +Z')
    positions = np.asarray([v['position'] for v in vertices], float)
    normals = np.asarray([v['normal'] for v in vertices], float)
    faces = np.asarray(triangles, int)
    geometric = np.cross(positions[faces[:, 1]] - positions[faces[:, 0]], positions[faces[:, 2]] - positions[faces[:, 0]])
    against = float((np.einsum('fcj,fj->fc', normals[faces], geometric) < 0).mean())
    if .1 < against < .9:
        refuse(f'{against:.0%} of the triangle corners are wound against their normals; the winding is inconsistent')
    floor = float(positions[:, 1].min())
    return {'joints': len(nodes), 'role_joints': {role: roles[role] for role in ROLES},
            'role_position': {role: [round(float(v), 5) for v in point[role]] for role in ROLES},
            'skin_weight_by_role': {role: round(weight, 3) for role, weight in follows.items()},
            'skinned_joints': len(owner), 'max_roles_per_vertex': most, 'spine': spine, 'torso': torso,
            'blended_vertex_share': round(blended / len(vertices), 4),
            'winding': 'cw' if against >= .9 else 'ccw', 'corners_wound_against_normals': round(against, 4),
            'facing': '+Z', 'floor_y': floor, 'height': float(positions[:, 1].max()) - floor,
            'vertices': len(vertices), 'triangles': len(triangles)}


def game_of(meta: dict) -> str:
    """The source game's title without region, disc or edition brackets, so two dumps of one game count once."""
    source = meta.get('source') if isinstance(meta.get('source'), dict) else {}
    title = str(source.get('game_title') or meta.get('game_title') or '').strip()
    title = re.sub(r'\s*\([^)]*\)', '', title).replace(' - ', ': ').strip()
    return {'Soulcalibur II': 'Soul Calibur II', 'Jet Set Radio': 'Jet Grind Radio',
            'Marvel vs. Capcom 2: New Age of Heroes': 'Marvel vs. Capcom 2',
            'Return To Ragol V1.0.3': 'Phantasy Star Online Episode I & II Plus'}.get(title, title) or 'unknown'


def franchise_of(game: str) -> str:
    low = game.lower()
    return next((name for name, keys in _FRANCHISES if any(key in low for key in keys)), game)


def size_of(meta: dict) -> tuple[str, float]:
    """(`native` or the metadata's word, height factor). Only an explicit `size` field counts; prose is not parsed."""
    rig = meta.get('rig') if isinstance(meta.get('rig'), dict) else {}
    value = meta.get('size', rig.get('size'))
    if isinstance(value, str) and value.lower() in SIZE_FACTORS:
        return value.lower(), SIZE_FACTORS[value.lower()]
    if isinstance(value, (int, float)) and not isinstance(value, bool) and .5 <= float(value) <= 1.5:
        return f'factor {float(value):g}', float(value)
    return 'native', 1.


def _model_file(folder: Path, meta: dict) -> Path:
    name = str(meta.get('model') or '')
    if meta.get('kind') not in (None, 'character'):
        raise DonorError('no_model', f'the entry is a {meta.get("kind")}, not a character model')
    if name.rsplit('.', 1)[-1].lower() in ('glb', 'gltf'):
        return folder / name
    if name:
        raise DonorError('no_model', f'the entry\'s model is {name!r}, not a glTF model')
    found = sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.glb', '.gltf')) if folder.is_dir() else []
    if len(found) != 1:
        raise DonorError('no_metadata' if not meta else 'no_model', 'the folder names no single glTF model')
    return found[0]


def _repaired(gltf: dict, vertices: list[dict], roles: dict[str, str]) -> tuple[dict[str, str], str] | None:
    """The profile moved onto the joints that carry the skin, or None when it already sits on them.

    Two measured repairs, nothing else. A hand or foot role that no vertex follows names a tip joint: it is raised to
    the highest skinned joint between it and the limb joint above it. A skinned joint above the hip or the chest has no
    role to follow: that role is raised to the topmost such joint. `rig_check` still judges the result.
    """
    nodes = gltf.get('nodes') or []
    names = [node.get('name') for node in nodes]
    joint = {}
    for role in ROLES:
        if names.count(roles.get(role)) != 1:
            return None
        joint[role] = names.index(roles[role])
    parents = {child: i for i, node in enumerate(nodes) for child in node.get('children', [])}
    skinned = {node for vertex in vertices for node, weight in zip(vertex['source_joints'], vertex['source_weights'])
               if weight}

    def above(node: int) -> list[int]:
        chain, seen = [], set()
        while node in parents and node not in seen:
            seen.add(node)
            node = parents[node]
            chain.append(node)
        return chain

    notes = []
    for role in ('l_hand', 'r_hand', 'l_foot', 'r_foot'):
        own = joint[role]
        if any(own == node or own in above(node) for node in skinned):
            continue
        chain = above(own)
        limb = joint[ROLE_PARENTS[role]]
        if limb not in chain:
            continue
        between = [node for node in chain[:chain.index(limb)] if node in skinned]
        if between and names.count(names[between[-1]]) == 1:
            joint[role] = between[-1]
            notes.append(f'{role} raised from the tip {roles[role]} to {names[between[-1]]}')
    for role in ('hip', 'chest'):
        owned = set(joint.values())
        loose = [node for node in skinned if node not in owned and not owned & set(above(node))]
        tops = [node for node in loose if node in above(joint[role])]
        if tops:
            top = min(tops, key=lambda node: len(above(node)))
            if names.count(names[top]) == 1:
                joint[role] = top
                notes.append(f'{role} raised from {roles[role]} to the skinned joint {names[top]} above it')
    if not notes or len(set(joint.values())) != len(ROLES):
        return None
    return {role: names[node] for role, node in joint.items()}, '; '.join(notes)


def resolve(folder: Path) -> tuple[Donor, dict]:
    """(Donor, measured rig) for one library folder, or `DonorError` with the category and the reason."""
    folder = Path(folder)
    try:
        meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    path = _model_file(folder, meta)
    try:
        data = path.read_bytes()
        gltf, _, _, world = characters._load(path)
    except Exception as exc:                      # an unreadable model is a refusal, whatever the loader raised
        raise DonorError('model_unreadable', f'{path.name}: {exc}') from exc
    if not any(skin.get('joints') for skin in gltf.get('skins') or []):
        raise DonorError('no_rig', REASONS['no_rig'])
    if not gltf.get('images'):
        raise DonorError('no_textures', REASONS['no_textures'])
    try:
        vertices, triangles, _, _ = mtf_materials.source_mesh(path, atlas_size=SURVEY_ATLAS, strict_samplers='in_range')
    except Exception as exc:
        raise DonorError('unsupported_surface', str(exc)) from exc
    if len(vertices) > MAX_VERTICES:
        raise DonorError('too_large', f'{len(vertices)} vertices; one native mesh record addresses {MAX_VERTICES}')
    rig = meta.get('rig') if isinstance(meta.get('rig'), dict) else {}
    listed = rig.get('roles') if isinstance(rig.get('roles'), dict) else {}

    def from_metadata():
        return {role: str(listed[role]) for role in ROLES} if set(ROLES) <= set(listed) else None

    def from_tree():                               # only measured when the metadata does not settle it
        try:
            tree = characters.tree_roles(path)
        except Exception:
            return None
        return {role: str(tree[role]) for role in ROLES} if set(ROLES) <= set(tree) else None

    refusals, profiles = [], 0
    for label, profile in (('library metadata', from_metadata), ('joint-tree measurement', from_tree)):
        roles = profile()
        if roles is None:
            continue
        profiles += 1
        repaired = _repaired(gltf, vertices, roles)
        for how, candidate in ((label, roles), (f'{label}; {repaired[1]}', repaired[0]) if repaired else (label, None)):
            if candidate is None:
                continue
            try:
                measured = rig_check(gltf, world, vertices, triangles, candidate)
            except ValueError as exc:
                refusals.append(f'{how}: {exc}')
                continue
            source = meta.get('source') if isinstance(meta.get('source'), dict) else {}
            game = game_of(meta)
            size, factor = size_of(meta)
            title = str(source.get('game_title') or game)
            tool = str(meta.get('extraction_tool') or 'unrecorded tool')
            donor = Donor(slug=str(meta.get('slug') or folder.name), name=str(meta.get('name') or folder.name),
                          game=game, franchise=franchise_of(game), platform=str(source.get('platform') or 'unknown'),
                          model=path.name, sha256=hashlib.sha256(data).hexdigest(), roles=tuple(candidate.items()),
                          roles_from=how, provenance=f'{title}; {tool}', size=size, height_factor=factor)
            return donor, measured
    if not profiles:
        raise DonorError('no_roles', REASONS['no_roles'] if not listed else
                         f'the metadata names {len(set(ROLES) & set(listed))} of the fifteen roles and the joint tree '
                         'gives no complete set')
    raise DonorError('rig_refused', refusals[-1] if len(refusals) > 1 else refusals[0])


def survey(library: Path, *, progress=None, known: dict | None = None) -> dict:
    """Every folder of a character library resolved once: the usable donors and why each other folder is refused.

    Two folders with the same model bytes are one donor; the later one is counted as a duplicate. `known` holds rows
    of an interrupted survey of the same library (`entries` of its report); those folders are not resolved again.
    """
    library = Path(library)
    rows, seen = {}, {}
    folders = sorted(p for p in library.iterdir() if p.is_dir())
    for number, folder in enumerate(folders):
        if known and folder.name in known:
            rows[folder.name] = known[folder.name]
            if rows[folder.name]['usable']:
                seen[rows[folder.name]['donor']['sha256']] = folder.name
            if progress:
                progress(number + 1, len(folders), folder.name, rows[folder.name])
            continue
        try:
            donor, rig = resolve(folder)
            if donor.sha256 in seen:
                raise DonorError('duplicate', f'the same model bytes as {seen[donor.sha256]}')
            seen[donor.sha256] = folder.name
            rows[folder.name] = {'usable': True, 'donor': donor.__dict__ | {'roles': dict(donor.roles)},
                                 'rig': {key: rig[key] for key in ('vertices', 'triangles', 'blended_vertex_share',
                                                                   'winding', 'height', 'skinned_joints')}}
        except DonorError as exc:
            try:
                meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                meta = {}
            game = game_of(meta if isinstance(meta, dict) else {})
            rows[folder.name] = {'usable': False, 'category': exc.category, 'reason': str(exc), 'game': game,
                                 'franchise': franchise_of(game)}
        if progress:
            progress(number + 1, len(folders), folder.name, rows[folder.name])
    return {'library_entries': len(folders), 'entries': rows, 'summary': summarise(rows)}


def summarise(rows: dict) -> dict:
    """Usable donors per franchise and game, and refusals per reason, from survey rows."""
    franchises, reasons = {}, {}
    for row in rows.values():
        game = row['donor']['game'] if row['usable'] else row['game']
        franchise = row['donor']['franchise'] if row['usable'] else row['franchise']
        entry = franchises.setdefault(franchise, {'usable': 0, 'refused': 0, 'games': {}, 'refusals': {}})
        per_game = entry['games'].setdefault(game, {'usable': 0, 'refused': 0})
        if row['usable']:
            entry['usable'] += 1
            per_game['usable'] += 1
        else:
            entry['refused'] += 1
            per_game['refused'] += 1
            entry['refusals'][row['category']] = entry['refusals'].get(row['category'], 0) + 1
            reasons[row['category']] = reasons.get(row['category'], 0) + 1
    return {'usable': sum(row['usable'] for row in rows.values()),
            'refused': sum(not row['usable'] for row in rows.values()),
            'by_franchise': dict(sorted(franchises.items(), key=lambda kv: (-kv[1]['usable'], kv[0]))),
            'refusals_by_reason': dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            'reason_text': REASONS}


def donors_of(report: dict) -> list[Donor]:
    """The usable donors of a survey report (also after it went through JSON)."""
    out = []
    for row in report['entries'].values():
        if row['usable']:
            fields = dict(row['donor'])
            fields['roles'] = tuple(fields['roles'].items()) if isinstance(fields['roles'], dict) else tuple(
                map(tuple, fields['roles']))
            out.append(Donor(**fields))
    return out


def plan(seed, slots: list[str], donors: list[Donor], *, history: list | tuple = (), avoid_last: int = 3,
         games: list[str] | None = None, exclude: set[str] | frozenset = frozenset()) -> dict[str, str]:
    """{slot: donor slug} dealt from a seed: a donor at most once, recently used donors last, franchises in turn.

    `history` lists earlier overlays, oldest first, each a {slot: slug} mapping or a list of slugs; donors of the last
    `avoid_last` of them are only dealt when nothing else is left. `games` keeps donors whose game title or franchise
    is one of the given names (case-insensitive). `exclude` removes slugs outright (a donor a slot refused). The same
    seed, slots, donors and history always give the same plan.
    """
    slots = list(slots)
    if len(set(slots)) != len(slots) or not slots:
        raise ValueError('a plan needs distinct slots')
    wanted = {name.strip().lower() for name in games} if games else None
    pool = {}
    for donor in sorted(donors, key=lambda d: d.slug):
        if donor.slug in exclude or (wanted is not None and donor.game.lower() not in wanted
                                     and donor.franchise.lower() not in wanted):
            continue
        pool.setdefault(donor.slug, donor)
    if len(pool) < len(slots):
        raise ValueError(f'{len(pool)} donors cannot fill {len(slots)} slots without repeating one')
    recent = set()
    for overlay in list(history)[-avoid_last:] if avoid_last > 0 else []:
        recent.update(overlay.values() if isinstance(overlay, dict) else overlay)
    rng = random.Random(f're5-cast:{seed}')
    chosen: dict[str, str] = {}
    for tier in (False, True):                                   # donors not seen lately first, then the rest
        groups = {}
        for slug, donor in pool.items():
            if (slug in recent) == tier and slug not in chosen.values():
                groups.setdefault(donor.franchise, []).append(slug)
        order = sorted(groups)
        rng.shuffle(order)
        for group in groups.values():
            rng.shuffle(group)
        while len(chosen) < len(slots) and any(groups.values()):
            for franchise in order:
                if groups[franchise] and len(chosen) < len(slots):
                    chosen[slots[len(chosen)]] = groups[franchise].pop()
    return chosen
