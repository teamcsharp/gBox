"""Plan native weighted seam models without deleting or rigidizing triangles.

Each logical vertex has one canonical unordered joint pair and one quantized
parameter. A model is drawn in its owner-A frame; several A/B descriptors may
update disjoint subsets of that same model. Native SUP draws it once per
descriptor, so repeated models are permitted only for explicitly opaque input.
This module plans data; it does not claim those repeated draws are GPU-tested.
"""
from __future__ import annotations
import collections
import functools
import itertools
import numpy as np

MAX_SEAMS = 14


def _influence(joints, weights):
    if len(joints) != len(weights) or not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError('skin weights require matching finite nonnegative arrays')
    merged = collections.defaultdict(float)
    for joint, weight in zip(joints, weights):
        if weight > 0:
            if int(joint) != joint or not 0 <= joint < 44:
                raise ValueError('native skin references an unsupported joint')
            merged[int(joint)] += float(weight)
    total = sum(merged.values())
    if total <= 0:
        raise ValueError('skin vertex has no positive influence')
    items = tuple((j, w / total) for j, w in sorted(merged.items()))
    if len(items) > 2:
        raise ValueError('native SUP supports at most two influences per vertex; explicit reduction is required')
    if len(items) == 1:
        j = items[0][0]
        return {'pair': (j, j), 'sample': 0, 'native': (j,), 'weight_b': 0., 'error': 0.}, items
    a, b = items[0][0], items[1][0]
    weight_b = items[1][1]
    sample = min(16, int(np.floor(weight_b * 16 + .5)))
    native = (a,) if sample == 0 else (b,) if sample == 16 else (a, b)
    return {'pair': (a, b), 'sample': sample, 'native': native,
            'weight_b': weight_b, 'error': abs(sample / 16 - weight_b)}, items


def canonical_vertices(primitives):
    """Validate shared bind positions/weights and quantize each logical ID once."""
    logical = {}
    for pi, primitive in enumerate(primitives):
        pos = np.asarray(primitive['pos'], float)
        joints, weights = np.asarray(primitive['J']), np.asarray(primitive['W'], float)
        ids = np.asarray(primitive['logical_vertex_id'])
        if (pos.ndim != 2 or pos.shape[1:] != (3,) or joints.ndim != 2 or joints.shape != weights.shape
                or len(pos) != len(joints) or ids.shape != (len(pos),)
                or not np.issubdtype(ids.dtype, np.integer) or not np.isfinite(pos).all()):
            raise ValueError('native seam planning requires complete finite per-vertex geometry and logical IDs')
        for vertex, key in enumerate(ids):
            row, items = _influence(joints[vertex], weights[vertex])
            key = int(key)
            if key in logical:
                previous = logical[key]
                if (len(previous['influences']) != len(items)
                        or any(a != b or abs(x-y) > 1e-8 for (a, x), (b, y) in zip(previous['influences'], items))
                        or not np.allclose(previous['position'], pos[vertex], rtol=0, atol=1e-8)):
                    raise ValueError(f'logical vertex{key} has inconsistent shared positions or weights')
            else:
                logical[key] = {**row, 'influences': items, 'position': pos[vertex].copy(),
                                'first_occurrence': (pi, vertex)}
    return logical


def _opaque(primitive):
    if 'opaque' in primitive:
        return bool(primitive['opaque'])
    if primitive.get('alpha_mode') == 'BLEND' or tuple(primitive.get('color', (255,255,255,255)))[3] < 255:
        return False
    texture = primitive.get('tex')
    if texture is not None:
        pixels = np.asarray(texture.convert('RGBA') if hasattr(texture,'convert') else texture)
        if pixels.ndim != 3 or pixels.shape[2] not in (3,4):
            raise ValueError('material opacity requires a complete RGB/RGBA texture')
        return pixels.shape[2] == 3 or bool(np.all(pixels[:,:,3] == 255))
    # No texture plus alpha255 is a fully opaque constant-color material.
    return True


def _triangle_choices(rows, opaque):
    sets = [set(row['native']) for row in rows]
    union = set().union(*sets)
    if len(union) == 1:
        return None, next(iter(union))
    blended = [item for item in sets if len(item) == 2]
    owners = set.intersection(*blended) if blended else union
    choices = []
    for owner in sorted(owners):
        edges = frozenset((owner, other) for other in union - {owner})
        if opaque or len(edges) == 1:
            choices.append((owner, edges))
    if not choices:
        reason = 'transparent repeated drawing' if owners else 'no common owner for native two-joint curves'
        raise ValueError(f'weighted triangle requires unsupported {reason}')
    return tuple(choices), None


def _chunks(primitives, triangle_rows, logical):
    chunks = []
    by_primitive = collections.defaultdict(list)
    for pi, ti in triangle_rows:
        by_primitive[pi].append(ti)
    for pi, selected in sorted(by_primitive.items()):
        source = primitives[pi]
        tris = np.asarray(source['tris'], int)[selected]
        vertices = np.unique(tris)
        lookup = np.full(len(source['pos']), -1, int)
        lookup[vertices] = np.arange(len(vertices))
        chunk = {**source, 'tris': lookup[tris], 'source_primitive': pi,
                 'source_triangles': np.asarray(selected, int), 'source_vertices': vertices}
        for key in ('pos', 'nrm', 'uv', 'J', 'W', 'logical_vertex_id'):
            chunk[key] = np.asarray(source[key])[vertices].copy()
        chunk['canonical_pair'] = np.asarray([logical[int(i)]['pair'] for i in chunk['logical_vertex_id']], int)
        chunk['canonical_sample'] = np.asarray([logical[int(i)]['sample'] for i in chunk['logical_vertex_id']], np.uint8)
        chunks.append(chunk)
    return chunks


def plan_seams(primitives, *, maximum_seams=MAX_SEAMS, allowed=None, single=None):
    """Return rigid models and common-owner seam models preserving topology.

    Optional ``opaque`` per primitive overrides conservative alpha inspection.
    Ownership is deterministic: forced choices seed a directed edge cover,
    followed by the choice introducing the fewest additional native records.
    A local improvement pass removes avoidable edges. The report explicitly
    identifies this as a feasible cover rather than asserting global optimality.
    Transparent triangles are separated by exact pair and are drawn only once;
    a single-pair model holds opaque and transparent triangles of that pair
    together, as the native seam models mix list-0 and list-2 meshes.
    Donor skins that cannot satisfy these rules go through ``fit_native_skin``,
    whose report carries the ``allowed``/``single`` edge constraints it chose.
    """
    return _plan(primitives, maximum_seams, enforce=True, allowed=allowed, single=single)


def _edge_set(edges):
    return None if edges is None else frozenset((int(a), int(b)) for a, b in edges)


def _within(edges, allowed=None, single=None):
    """A choice inside ``allowed`` directed edges that uses ``single`` edges only as its one pair."""
    return ((allowed is None or edges <= allowed)
            and (single is None or len(edges) == 1 or not edges & single))


def _plan(primitives, maximum_seams=MAX_SEAMS, *, enforce=True, allowed=None, single=None):
    """``allowed`` (directed edges) and ``single`` (edges kept out of repeated models) restrict each triangle to
    the choices that satisfy them whenever it has one."""
    primitives = list(primitives)
    allowed, single = _edge_set(allowed), _edge_set(single)
    logical = canonical_vertices(primitives)
    rigid = collections.defaultdict(list)
    pending = []
    for pi, primitive in enumerate(primitives):
        tris = np.asarray(primitive['tris'])
        ids = np.asarray(primitive['logical_vertex_id'])
        if (tris.ndim != 2 or tris.shape[1:] != (3,) or not np.issubdtype(tris.dtype,np.integer)
                or np.any(tris < 0) or np.any(tris >= len(ids))):
            raise ValueError('native seam triangle indices are invalid')
        opaque = _opaque(primitive)
        for ti, tri in enumerate(tris):
            choices, owner = _triangle_choices([logical[int(i)] for i in ids[tri]], opaque)
            if choices is None:
                rigid[owner].append((pi,ti))
            else:
                choices = tuple(c for c in choices if _within(c[1], allowed, single)) or choices
                pending.append({'triangle':(pi,ti), 'choices': choices, 'opaque': opaque})
    pending.sort(key=lambda row:(len(row['choices']),row['triangle']))
    used = set()
    for row in pending:
        owner, edges = min(row['choices'], key=lambda item:(len(item[1]-used),len(item[1]),item[0]))
        row['selected'] = (owner,edges)
        used.update(edges)
    # Removing currently selected edges before rescoring avoids a sticky greedy
    # choice when later forced constraints already cover another orientation.
    for _ in range(8):
        changed = False
        counts = collections.Counter(edge for row in pending for edge in row['selected'][1])
        for row in pending:
            current = row['selected']
            for edge in current[1]:
                counts[edge] -= 1
            rest = {edge for edge,count in counts.items() if count}
            best = min(row['choices'], key=lambda item:(len(item[1]-rest),len(item[1]),item[0]))
            # Tie changes are deterministic and cannot increase total records.
            row['selected'] = best
            for edge in best[1]:
                counts[edge] += 1
            changed |= best != current
        if not changed:
            break
    by_model = collections.defaultdict(list)
    multi_edges = collections.defaultdict(set)
    for row in pending:
        if len(row['selected'][1]) > 1:
            multi_edges[row['selected'][0]].update(row['selected'][1])
    for row in pending:
        a, edges = row['selected']
        # Triangles spanning several pairs share their owner's repeated opaque
        # model, as do opaque single-pair triangles whose pair it already draws.
        # Every other triangle sits in a model of its exact pair, drawn once,
        # opaque and transparent material together like the native seam models.
        alone = len(edges) == 1 and not (row['opaque'] and edges <= multi_edges[a])
        key = (a, next(iter(edges))[1]) if alone else (a, None)
        by_model[key].append(row)
    models = []
    for (a,only_b), rows in sorted(by_model.items(),key=lambda item:(item[0][0], -1 if item[0][1] is None else item[0][1])):
        edges = sorted(set().union(*(row['selected'][1] for row in rows)))
        if len(edges) > 1 and not all(row['opaque'] for row in rows):
            raise AssertionError('transparent triangles would be drawn more than once')
        model = {'bone_a':a, 'bone_bs':[b for _,b in edges], 'opaque':all(row['opaque'] for row in rows),
                 'chunks':_chunks(primitives,[row['triangle'] for row in rows],logical),
                 'triangles':[row['triangle'] for row in rows], 'draw_count':len(edges)}
        for chunk in model['chunks']:
            b = np.full(len(chunk['pos']), -1, int)
            sample = np.zeros(len(b), np.uint8)
            for vi,key in enumerate(chunk['logical_vertex_id']):
                vertex = logical[int(key)]
                native = vertex['native']
                if len(native) == 1:
                    if native[0] != a:
                        b[vi], sample[vi] = native[0], 16
                else:
                    c,d = vertex['pair']
                    if a not in (c,d):
                        raise AssertionError('owner omitted a canonical blended joint')
                    b[vi] = d if a == c else c
                    sample[vi] = vertex['sample'] if a == c else 16-vertex['sample']
            chunk['sup_bone_b'], chunk['sup_sample'] = b,sample
            chunk['owner'] = np.full(len(b),a,int)
        models.append(model)
    count = sum(model['draw_count'] for model in models)
    if enforce and count > min(MAX_SEAMS,int(maximum_seams)):
        raise ValueError(f'weighted topology requires{count} native SUP descriptors, exceeding{min(MAX_SEAMS,int(maximum_seams))}')
    total = sum(len(p['tris']) for p in primitives)
    rigid_count = sum(len(rows) for rows in rigid.values())
    seam_count = sum(len(model['triangles']) for model in models)
    if total != rigid_count + seam_count:
        raise AssertionError('native seam planning changed the triangle count')
    report = {'triangles':total, 'rigid_triangles':rigid_count, 'seam_triangles':seam_count,
              'logical_vertices':len(logical), 'native_descriptors':count, 'native_limit':MAX_SEAMS,
              'seam_models':len(models),
              'max_quantized_weight_error':max((v['error'] for v in logical.values()),default=0.),
              'endpoint_snapped_logical_vertices':sum(len(v['influences'])==2 and len(v['native'])==1 for v in logical.values()),
              'repeated_opaque_models':sum(model['draw_count']>1 for model in models),
              'duplicate_draw_triangles':sum((model['draw_count']-1)*len(model['triangles']) for model in models),
              'transparent_repeated_models':0, 'geometry_deleted':0, 'triangle_subdivision':0,
              'ownership_method':'deterministic directed edge cover with local improvement; global optimum not asserted',
              'runtime_duplicate_draw_verified':False,
              'models':[{'bone_a':m['bone_a'],'bone_bs':m['bone_bs'],'opaque':m['opaque'],
                         'triangles':len(m['triangles']),'draw_count':m['draw_count']} for m in models]}
    return {'logical':logical, 'rigid':{a:_chunks(primitives,rows,logical) for a,rows in sorted(rigid.items())},
            'models':models, 'report':report}


# ---------------------------------------------------------------- donor skin fitting
#
# The owned disc's fighters (every CHR/SUP pair on DOA2 LE) draw each SUP seam model exactly once with one (A, B)
# pair, use only the opaque (PVR list 0) and translucent (list 2) lists - never punch-through, so there is no
# alpha-test pass to move blended faces into - and hold at most 14 seams. A translucent seam model is therefore always
# a single pair: a transparent triangle whose corners span three joints would need the same blended surface drawn once
# per pair. Donor skins (SA2 quills, hair, glass) do that, and some (Chaos 0, Rouge, Dr. Eggman) need more descriptors
# than the native limit. Before planning, the fewest and lightest corner influences are folded onto a joint the
# triangle already uses; each change rewrites one logical vertex everywhere it occurs, so the mesh stays watertight.

@functools.lru_cache(maxsize=65536)
def _choices_of(natives, opaque):
    """(choices, drawable) for a triangle given its corners' native joint sets; choices None when rigid."""
    try:
        return _triangle_choices([{'native': native} for native in natives], opaque)[0], True
    except ValueError:
        return None, False


@functools.lru_cache(maxsize=None)
def _rigid(joint):
    return _influence(np.asarray([joint]), np.asarray([1.]))[0]


def _fits(rows, opaque, allowed=None, single=None):
    choices, drawable = _choices_of(tuple(row['native'] for row in rows), bool(opaque))
    return drawable and (choices is None or any(_within(edges, allowed, single) for _a, edges in choices))


class _Skin:
    """Per-logical-vertex influences over fixed primitives; a change rewrites a vertex in every primitive."""

    def __init__(self, primitives):
        # Opacity is resolved once (texture alpha scans) and carried on to the planner.
        self.primitives = primitives = [{**p, 'opaque': _opaque(p)} for p in primitives]
        logical = canonical_vertices(primitives)
        self.original = {key: v['influences'] for key, v in logical.items()}
        self.state = dict(self.original)
        self.rows = {key: {k: v[k] for k in ('pair', 'sample', 'native', 'weight_b', 'error')}
                     for key, v in logical.items()}
        self.opaque = [p['opaque'] for p in primitives]
        self.triangles = [(pi, [int(k) for k in np.asarray(p['logical_vertex_id'])[tri]])
                          for pi, p in enumerate(primitives) for tri in np.asarray(p['tris'], int)]
        self.by_key = collections.defaultdict(list)
        for t, (_pi, keys) in enumerate(self.triangles):
            for key in set(keys):
                self.by_key[key].append(t)
        self.reasons = {}

    def copy(self):
        other = object.__new__(_Skin)
        other.__dict__.update(self.__dict__)
        other.state, other.rows, other.reasons = dict(self.state), dict(self.rows), dict(self.reasons)
        return other

    def set(self, key, influences, reason):
        joints = np.asarray([j for j, _w in influences])
        weights = np.asarray([w for _j, w in influences], float)
        self.rows[key], self.state[key] = _influence(joints, weights)
        self.reasons.setdefault(key, reason)

    def fits(self, pi, keys, allowed=None, single=None):
        return _fits([self.rows[k] for k in keys], self.opaque[pi], allowed, single)

    def cheapest(self, pi, keys, allowed=None, single=None, reassign=False):
        """Lightest corner changes making one triangle native: (cost, {key: joint}) or None.

        A blended corner may snap to either of its joints (cost: the weight it drops). Only with ``reassign`` may a
        corner follow a joint of the triangle it has no weight on (cost 1 + 1), the last resort for a transparent
        triangle whose corners are rigid on three different joints."""
        unique = list(dict.fromkeys(keys))
        union = sorted({j for k in unique for j in self.rows[k]['native']})
        options = []
        for key in unique:
            native, items = self.rows[key]['native'], dict(self.state[key])
            option = [(0., None)]
            if len(native) == 2:
                option += sorted((1. - items.get(j, 0.), j) for j in native)
            if reassign:
                option += [(2. - items.get(j, 0.), j) for j in union if j not in native]
            options.append(option)
        best = None
        for combo in itertools.product(*options):
            cost = sum(c for c, _j in combo)
            if best is not None and cost >= best[0] - 1e-12:
                continue
            local = {key: self.rows[key] if j is None else _rigid(j) for key, (_c, j) in zip(unique, combo)}
            if _fits([local[k] for k in keys], self.opaque[pi], allowed, single):
                best = (cost, {key: j for key, (_c, j) in zip(unique, combo) if j is not None})
        return best

    def constrain(self, allowed, single, reason, edge=None):
        """Change corners until every triangle has a choice within the constraints: the cost, or None.

        Snaps come first; a corner follows another joint of its triangle only when no snap can satisfy it. A changed
        corner rechecks every triangle it belongs to. ``edge`` names the only edge whose constraint changed, so only
        the triangles spanning both of its joints start the work list."""
        if edge is None:
            work = set(range(len(self.triangles)))
        else:
            a, b = edge
            work = {t for key, row in self.rows.items() if b in row['native'] for t in self.by_key[key]
                    if any(a in self.rows[k]['native'] for k in self.triangles[t][1])}
        total = 0.
        for _ in range(16):
            if not work:
                return total
            following = set()
            for t in sorted(work):
                pi, keys = self.triangles[t]
                if self.fits(pi, keys, allowed, single):
                    continue
                fix = (self.cheapest(pi, keys, allowed, single)
                       or self.cheapest(pi, keys, allowed, single, reassign=True))
                if fix is None:
                    return None
                total += fix[0]
                why = reason or ('common_owner' if self.opaque[pi] else 'transparent_single_pair')
                for key, joint in fix[1].items():
                    self.set(key, ((joint, 1.),), why)
                    following.update(self.by_key[key])
            work = following
        return None

    def drawable(self):
        """Every triangle drawable natively: transparent ones on one pair, blended corners sharing an owner."""
        if self.constrain(None, None, None) is None:
            raise ValueError('native skin fitting did not converge on drawable triangles')
        return self

    def skinned(self):
        changed = {key for key in self.reasons if self.state[key] != self.original[key]}
        return _with_skin(self.primitives, self.state, changed), changed

    def plan(self, allowed=None, single=None):
        return _plan(self.skinned()[0], enforce=False, allowed=allowed, single=single)


def fit_native_skin(primitives, *, maximum_seams=MAX_SEAMS):
    """Return (primitives, report) whose skins ``plan_seams`` accepts, moving as little weight as possible.

    1. A transparent triangle spanning more than one joint pair keeps a single pair: the cheapest corner influences
       outside it fold onto it (a corner rigid on a third joint follows the pair only as a last resort). An opaque
       triangle whose blended corners share no joint is fixed the same way.
    2. While the plan needs more SUP descriptors than the native limit, the cheapest step that lowers the count is
       taken: drop one directed edge, or keep one edge out of repeated (multi-pair) models so it shares a single-pair
       model. A triangle that no snap can satisfy has one rigid corner follow another joint of the triangle.
    Changes are per logical vertex, so the mesh stays watertight. The report lists every change per primitive
    (material) with the triangles it touches; pass its ``allowed``/``single`` constraints on to ``plan_seams``."""
    primitives = list(primitives)
    limit = min(MAX_SEAMS, int(maximum_seams))
    skin = _Skin(primitives).drawable()
    allowed = single = None
    plan = skin.plan()
    count = before = plan['report']['native_descriptors']
    steps = []
    for _ in range(64):
        if count <= limit:
            break
        used = frozenset((m['bone_a'], b) for m in plan['models'] for b in m['bone_bs'])
        multi = sorted({(m['bone_a'], b) for m in plan['models'] if m['draw_count'] > 1 for b in m['bone_bs']})
        candidates = []
        for kind, edges in (('drop_edge', sorted(used)), ('single_edge', multi)):
            for edge in edges:
                trial = skin.copy()
                rule = ((used - {edge}, single) if kind == 'drop_edge'
                        else (used, (single or frozenset()) | {edge}))
                cost = trial.constrain(*rule, 'descriptor_limit', edge)
                if cost is not None:
                    candidates.append((cost, kind, edge, trial, rule))
        # Cheapest first; the first step whose plan really needs fewer descriptors is kept.
        for cost, kind, edge, trial, rule in sorted(candidates, key=lambda c: c[:3]):
            trial_plan = trial.plan(*rule)
            if trial_plan['report']['native_descriptors'] < count:
                skin, (allowed, single), plan = trial, rule, trial_plan
                count = plan['report']['native_descriptors']
                steps.append({'step': kind, 'edge': list(edge), 'weight': round(cost, 4), 'descriptors': count})
                break
        else:
            raise ValueError(f'weighted topology requires{count} native SUP descriptors, exceeding{limit}')
    else:
        raise ValueError('native skin fitting did not converge within the descriptor limit')

    fitted, changed = skin.skinned()
    per = []
    for pi, p in enumerate(primitives):
        ids = np.asarray(p['logical_vertex_id'])
        hit = np.isin(ids, sorted(changed)) if changed else np.zeros(len(ids), bool)
        tris = np.asarray(p['tris'], int)
        touched = int(hit[tris].any(axis=1).sum()) if len(tris) else 0
        if touched:
            keys = {int(k) for k in ids[hit]}
            per.append({'primitive': pi, 'name': p.get('name'), 'opaque': skin.opaque[pi], 'vertices': len(keys),
                        'triangles': touched,
                        'reasons': dict(collections.Counter(skin.reasons[k] for k in keys))})

    def moved(key):
        a, b = dict(skin.original[key]), dict(skin.state[key])
        return .5 * sum(abs(a.get(j, 0.) - b.get(j, 0.)) for j in set(a) | set(b))
    report = {'vertices_changed': len(changed),
              'triangles_changed': sum(row['triangles'] for row in per),
              'by_reason': dict(collections.Counter(skin.reasons[k] for k in changed)),
              'rigid_reassigned': sum(bool({j for j, _w in skin.state[k]} - {j for j, _w in skin.original[k]})
                                      for k in changed),
              'max_weight_moved': round(max((moved(k) for k in changed), default=0.), 4),
              'total_weight_moved': round(sum(moved(k) for k in changed), 4),
              'descriptors_before': before, 'descriptors': count, 'steps': steps, 'primitives': per,
              'allowed': None if allowed is None else sorted(allowed),
              'single': None if single is None else sorted(single),
              'policy': 'corner influences folded onto a joint the triangle keeps; logical vertices stay shared'}
    return fitted, report


def _with_skin(primitives, state, changed):
    """Copies of the primitives whose changed logical vertices carry their fitted influences."""
    if not changed:
        return primitives
    out = []
    for p in primitives:
        ids = np.asarray(p['logical_vertex_id'])
        hit = [v for v, key in enumerate(ids) if int(key) in changed]
        if not hit:
            out.append(p)
            continue
        joints, weights = np.array(p['J'], copy=True), np.array(p['W'], float, copy=True)
        owner = np.array(p['owner'], copy=True) if 'owner' in p else None
        for v in hit:
            items = state[int(ids[v])]
            if len(items) > joints.shape[1]:
                raise AssertionError('fitted skin has more influences than the primitive holds')
            heaviest = max(items, key=lambda item: (item[1], -item[0]))[0]
            joints[v], weights[v] = heaviest, 0.
            for column, (j, w) in enumerate(items):
                joints[v, column], weights[v, column] = j, w
            if owner is not None:
                owner[v] = heaviest
        out.append({**p, 'J': joints, 'W': weights, **({'owner': owner} if owner is not None else {})})
    return out
