"""Plan native weighted seam models without deleting or rigidizing triangles.

Each logical vertex has one canonical unordered joint pair and one quantized
parameter. A model is drawn in its owner-A frame; several A/B descriptors may
update disjoint subsets of that same model. Native SUP draws it once per
descriptor, so repeated models are permitted only for explicitly opaque input.
This module plans data; it does not claim those repeated draws are GPU-tested.
"""
from __future__ import annotations
import collections
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


def plan_seams(primitives, *, maximum_seams=MAX_SEAMS):
    """Return rigid models and common-owner seam models preserving topology.

    Optional ``opaque`` per primitive overrides conservative alpha inspection.
    Ownership is deterministic: forced choices seed a directed edge cover,
    followed by the choice introducing the fewest additional native records.
    A local improvement pass removes avoidable edges. The report explicitly
    identifies this as a feasible cover rather than asserting global optimality.
    Transparent triangles are separated by exact pair and are drawn only once.
    """
    primitives = list(primitives)
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
    for row in pending:
        a, edges = row['selected']
        # Separate each transparent pair. It can share updates with other
        # primitives in this single-pair model, but must never repeat drawing.
        key = (a, None) if row['opaque'] else (a, next(iter(edges))[1])
        by_model[key].append(row)
    models = []
    for (a,only_b), rows in sorted(by_model.items(),key=lambda item:(item[0][0], -1 if item[0][1] is None else item[0][1])):
        edges = sorted(set().union(*(row['selected'][1] for row in rows)))
        model = {'bone_a':a, 'bone_bs':[b for _,b in edges], 'opaque':only_b is None,
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
    if count > min(MAX_SEAMS,int(maximum_seams)):
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
