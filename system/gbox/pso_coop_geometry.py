"""Read-only, bounded collision provider for exact 3OE2 town and Forest collision layouts.

Every observation hashes the current loaded REL bytes and manager table. Cached
rasters are used only while that identity remains unchanged. Unknown layouts
produce no grid. Dynamic doors, enemies and switches are not static geometry.
"""
from __future__ import annotations

from collections import deque
import hashlib
import heapq
import json
import math
import struct
from types import SimpleNamespace

from .psomap import _height, _inside, TRIGGER_FLAG
from .registry import Unsupported

KNOWN = {
    (1, 0, "03d26c27a128ecc58de161843c86b55878f6e512a0badbdfcb06bdd2de13da26"): "Scene/map_city00_00c.rel",
    (1, 1, "2f1c7a9652eebdf1fc62add0416c4a0f56adc9e4607194a9f48106367ec289a1"): "Scene/map_forest01c.rel",
    (1, 2, "862138578893d90fd00027679028864cafc89462fe3145d1c287d7f9c38253d9"): "Scene/map_forest02c.rel",
    (1, 2, "6b114f3ba0f099c6e869ada62a942732450799dca95665f9b823e5005039f2d5"): "Scene/map_aforest02c.rel",
}
# 80207038 obtains the native floor's record through 802077CC, selects its
# map-index/variant via 80207E88, then passes that exact name to 80206F20.
# Both index2/variant0 tables resolve to the two owned-disc Forest2 files.
# The third floor-record word describes other layout data, not this collision;
# it is retained in the before/after binding rather than assigned a meaning.
FLOOR_CODE = (
    (0x802077CC, bytes.fromhex('2c0300114081000c386000004e8000201cc3000c3ca080513860000138a539207c05302e7ca5321490040000800500049004000480050008900400084e800020')),
    (0x80207E88, bytes.fromhex('9421fff07c0802a69001001493e1000c7c7f1b782c1f00234081000c3860000048000034481027fd2c030000418200183c60804d57e01838386392707c63002e480000143c60804d57e0183838638fc07c63002e8001001483e1000c7c0803a6382100104e800020')),
)
ROOTS = (0x805D4E68, 0x805D6000, 0x805D6014, 0x805D5650)
MAX_BYTES = 262144
MAX_MESHES = 256
MAX_FACES = 16384
MAX_CELLS = 120000
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _read(ad, address, length):
    if type(address) is not int or address & 3 or not 0 < length <= MAX_BYTES or not 0x80000000 <= address <= 0x81800000 - length:
        raise ValueError("Collision memory range")
    data = b"".join(ad.read_memory(address + offset, min(65536, length - offset)) for offset in range(0, length, 65536))
    if len(data) != length:
        raise ValueError("Short collision read")
    return data


def _roots(ad):
    return tuple(struct.unpack(">I", _read(ad, address, 4))[0] for address in ROOTS)


def _binding(ad):
    return tuple(struct.unpack(">I", _read(ad, address, 4))[0] for address in (0x804FE120, 0x805D6060, 0x805D5FC0, 0x805D49B8)) + struct.unpack(">2I", _read(ad, 0x8050EA10, 8))


def _forest2_binding(ad, episode, floor):
    if (episode, floor) != (1, 2):
        return None
    for address, expected in FLOOR_CODE:
        if _read(ad, address, len(expected)) != expected:
            raise ValueError("Forest2 native floor accessor changed")
    record = _read(ad, 0x80513920 + 12 * floor, 12)
    selected = _read(ad, 0x805D5FC4, 8)
    if struct.unpack('>3I', record)[:2] != (2, 0) or struct.unpack('>2I', selected) != (2, 0):
        raise ValueError("Forest2 native map-index/variant binding differs")
    return record + selected


def _table(ad, manager):
    raw = _read(ad, manager + 0x1C, (MAX_MESHES + 1) * 4)
    pointers = struct.unpack('>' + str(MAX_MESHES + 1) + 'I', raw)
    if 0 not in pointers or pointers.index(0) == 0:
        raise ValueError('Collision mesh terminator')
    return raw[:(pointers.index(0) + 1) * 4]


def parse_loaded(base, blob, table):
    """All relocated pointers must remain inside the captured allocation."""
    def get(pointer, length):
        offset = pointer - base
        if pointer & 3 or offset < 0 or length < 0 or offset + length > len(blob):
            raise ValueError("Collision relocation outside allocation")
        return blob[offset:offset + length]

    pointers = struct.unpack(">" + str(len(table) // 4) + "I", table)
    if 0 not in pointers or not 0 < pointers.index(0) <= MAX_MESHES:
        raise ValueError("Collision mesh terminator")
    pointers = pointers[:pointers.index(0)]
    if len(set(pointers)) != len(pointers):
        raise ValueError("Duplicate collision entry")
    triangles = []
    digest = hashlib.sha256()
    vertices_total = 0
    for entry in pointers:
        mesh, *sphere, _flags = struct.unpack(">I4fI", get(entry, 24))
        if not all(math.isfinite(v) and abs(v) < 100000 for v in sphere):
            raise ValueError("Invalid collision bounds")
        nv, vp, nf, fp = struct.unpack(">4I", get(mesh, 16))
        vertices_total += nv
        if not 0 < nv <= 16384 or not 0 < nf <= MAX_FACES or vertices_total > 65536 or len(triangles) + nf > MAX_FACES:
            raise ValueError("Collision element budget")
        vb, fb = get(vp, nv * 12), get(fp, nf * 36)
        vertices = list(struct.iter_unpack(">3f", vb))
        if any(not math.isfinite(v) or abs(v) >= 100000 for row in vertices for v in row):
            raise ValueError("Invalid collision vertex")
        for offset in range(0, len(fb), 36):
            a, b, c, flags = struct.unpack_from(">4H", fb, offset)
            normal = struct.unpack_from(">3f", fb, offset + 8)
            if max(a, b, c) >= nv or any(not math.isfinite(v) or abs(v) > 1.01 for v in normal):
                raise ValueError("Invalid collision face")
            row = (vertices[a], vertices[b], vertices[c], flags, normal)
            triangles.append(row)
            digest.update(struct.pack(">12fH", *vertices[a], *vertices[b], *vertices[c], *normal, flags))
    return triangles, digest.hexdigest()


def _clip(triangle, x0, z0, size):
    """Clip XYZ polygon to an XZ cell, preserving wall height at that cell."""
    poly = list(triangle)
    for axis, bound, sign in ((0, x0, 1), (0, x0 + size, -1), (2, z0, 1), (2, z0 + size, -1)):
        result = []
        if not poly:
            break
        previous = poly[-1]
        for current in poly:
            p, q = sign * (previous[axis] - bound), sign * (current[axis] - bound)
            if (p >= 0) != (q >= 0):
                t = p / (p - q)
                result.append(tuple(previous[k] + t * (current[k] - previous[k]) for k in range(3)))
            if q >= 0:
                result.append(current)
            previous = current
        poly = result
    return poly


class Atlas:
    """Keep every sampled floor height; project only one connected surface per player.

    When a connected bridge loops over itself, a projection conservatively keeps
    one canonically seeded height at each cell. It never connects the two levels.
    A new projection is built if the player's measured height leaves that view.
    """
    def __init__(self, triangles, size=5.0):
        triangles = self.triangles = tuple(triangles)
        self.size, self.heights, self.views = size, {}, []
        self.work_revision = 0
        self.failed_projections = {}
        work = 0
        walls = []
        for a, b, c, flags, normal in triangles:
            if flags & TRIGGER_FLAG:
                continue
            if normal[1] <= .6:
                if abs(normal[1]) <= .6:
                    walls.append((a, b, c))
                continue
            for cell in self._bounds((a, b, c)):
                work += 1
                if work > 1000000:
                    raise ValueError("Collision raster work budget")
                x, z = self.center(cell)
                if _inside(x, z, a, b, c):
                    height = _height(x, z, a, b, c)
                    values = self.heights.setdefault(cell, [])
                    if all(abs(height - value) > .25 for value in values):
                        values.append(height)
                    if len(values) > 4 or len(self.heights) > MAX_CELLS:
                        raise ValueError("Collision layer/cell budget")
        # A wall below a bridge cannot block the bridge. Intersect each clipped
        # wall's local vertical span with each floor's body interval separately.
        for triangle in walls:
            for cell in self._bounds(triangle):
                work += 1
                if work > 2000000:
                    raise ValueError("Collision wall work budget")
                if cell not in self.heights:
                    continue
                poly = _clip(triangle, cell[0] * size, cell[1] * size, size)
                if not poly:
                    continue
                low, high = min(v[1] for v in poly), max(v[1] for v in poly)
                self.heights[cell] = [h for h in self.heights[cell] if not (high > h + 2 and low < h + 12)]
        self.heights = {cell: sorted(values) for cell, values in self.heights.items() if values}

    def _bounds(self, triangle):
        lo = [math.floor(min(v[k] for v in triangle) / self.size) for k in (0, 2)]
        hi = [math.floor(max(v[k] for v in triangle) / self.size) for k in (0, 2)]
        if (hi[0] - lo[0] + 1) * (hi[1] - lo[1] + 1) > MAX_CELLS:
            raise ValueError("Collision triangle raster budget")
        return ((x, z) for x in range(lo[0], hi[0] + 1) for z in range(lo[1], hi[1] + 1))

    def cell(self, player):
        return math.floor(player['x'] / self.size), math.floor(player['z'] / self.size)

    def center(self, cell):
        return (cell[0] + .5) * self.size, (cell[1] + .5) * self.size

    def compatible(self, a, ah, b, bh):
        return abs(ah - bh) <= .75 + .75 * self.size * math.dist(a, b)

    def _connected(self, start, height):
        selected = {start: height}
        todo = deque([start])
        while todo:
            cell = todo.popleft()
            h = selected[cell]
            for dx, dz in DIRECTIONS:
                nxt = cell[0] + dx, cell[1] + dz
                if nxt in selected:
                    continue
                candidates = [v for v in self.heights.get(nxt, []) if self.compatible(cell, h, nxt, v)]
                if not candidates:
                    continue
                nh = min(candidates, key=lambda v: abs(v - h))
                if dx and dz:
                    sides = ((cell[0] + dx, cell[1]), (cell[0], cell[1] + dz))
                    if not all(any(self.compatible(cell, h, side, sh) and self.compatible(side, sh, nxt, nh)
                                   for sh in self.heights.get(side, [])) for side in sides):
                        continue
                selected[nxt] = nh
                todo.append(nxt)
        return selected

    def _failed_projection(self, key):
        # The Atlas belongs to one exact loaded collision fingerprint. Failed
        # canonical/layer projections stay unknown, but must not cause another
        # whole-map traversal and fresh-observation loop on every native tick.
        self.failed_projections[key] = None
        if len(self.failed_projections) > 128:
            self.failed_projections.pop(next(iter(self.failed_projections)))
        return None

    def project(self, player):
        if any(type(player.get(k)) not in (int, float) or not math.isfinite(player[k]) for k in ('x', 'y', 'z')):
            raise ValueError('Invalid player geometry position')
        start = self.cell(player)
        values = self.heights.get(start, [])
        if not values:
            return None
        height = min(values, key=lambda h: abs(h - player['y']))
        # Allow the measured foot position versus cell-centre terrain slope,
        # but never guess a remote floor when a player is falling or teleporting.
        if abs(height - player['y']) > 1 + self.size * .75:
            return None
        for view in self.views:
            if start in view['_heights'] and abs(view['_heights'][start] - height) <= .25:
                return view
        key = (start, height)
        if key in self.failed_projections:
            return None
        # Reject an unsafe seed before a whole-map traversal; a buddy standing
        # against a wall must not trigger an expensive failed raster every tick.
        if not all(any(self.compatible(start, height, (start[0]+dx,start[1]+dz), h)
                       for h in self.heights.get((start[0]+dx,start[1]+dz), [])) for dx,dz in DIRECTIONS):
            return None
        self.work_revision += 1
        selected = self._connected(start, height)
        anchor = min(selected)
        selected = self._connected(anchor, selected[anchor])
        # A connected overpass may loop onto another height at the same XZ.
        # A single 2-D view cannot represent both; retain only the canonical
        # surface and fail closed for an incompatible measured player layer.
        if start not in selected or abs(selected[start] - height) > .25:
            return self._failed_projection(key)
        # Remove cells beside missing floor at this layer (one-cell clearance).
        safe = {cell: h for cell, h in selected.items() if all(
            (cell[0] + dx, cell[1] + dz) in selected and
            self.compatible(cell, h, (cell[0] + dx, cell[1] + dz), selected[(cell[0] + dx, cell[1] + dz)])
            for dx, dz in DIRECTIONS)}
        if start not in safe:
            return self._failed_projection(key)
        rows = [[*cell, round(h, 4)] for cell, h in sorted(safe.items())]
        layer = _hash(json.dumps(rows, separators=(',', ':')).encode())
        view = {'geometry_layer': layer, '_heights': safe,
                'collision_grid': {'size': self.size, 'floor': [row[:2] for row in rows], 'walls': [],
                                   'heights': rows, 'max_step': .75, 'max_slope': .75}}
        self.views.append(view)
        self.views = self.views[-4:]
        return view


NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))
AROUND = tuple((x, z) for x in (-1, 0, 1) for z in (-1, 0, 1) if x or z)


class MarginViews:
    """Cache canonical raw surfaces only within one exact loaded Atlas.

    A bridge's different elevations are never flattened. Ambiguous cells are
    excluded from recovery paths, including the exact start and endpoint.
    """
    def __init__(self, atlas):
        self.atlas = atlas
        self.views = []
        self.failed = {}
        self.revision = 0

    def _fail(self, key):
        self.failed[key] = None
        if len(self.failed) > 128:
            self.failed.pop(next(iter(self.failed)))
        return None

    def _view(self, player):
        a = self.atlas
        if any(type(player.get(k)) not in (int, float) or not math.isfinite(player[k]) for k in ('x', 'y', 'z')):
            return None
        start = a.cell(player)
        values = a.heights.get(start, [])
        # Do not choose between overlapping floors during reduced clearance.
        if len(values) != 1 or abs(values[0] - player['y']) > 1 + a.size * .75:
            return None
        height = values[0]
        for view in self.views:
            if start in view['base'] and abs(view['base'][start] - height) <= .25:
                return view
        key = (start, height)
        if key in self.failed:
            return None
        self.revision += 1
        selected = a._connected(start, height)
        anchor = min(selected)
        selected = a._connected(anchor, selected[anchor])
        if start not in selected or abs(selected[start] - height) > .25:
            return self._fail(key)
        safe = {cell: h for cell, h in selected.items() if all(
            (cell[0] + dx, cell[1] + dz) in selected and
            a.compatible(cell, h, (cell[0] + dx, cell[1] + dz), selected[(cell[0] + dx, cell[1] + dz)])
            for dx, dz in AROUND)}
        if not safe:
            return self._fail(key)
        # Match Atlas.project's canonical layer name, while retaining its
        # additional raw edge cells solely as reduced-clearance evidence.
        rows = [[*cell, round(h, 4)] for cell, h in sorted(safe.items())]
        layer = hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
        base = {c: h for c, h in selected.items() if len(a.heights.get(c, [])) == 1}
        view = {'base': base, 'safe': safe, 'geometry_layer': layer}
        self.views.append(view)
        self.views = self.views[-4:]
        return view

    def clear(self, start, end, base):
        """Check every crossed cell, including both sides of boundary points."""
        a = self.atlas
        if (len(start) != 2 or len(end) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in (*start, *end)) or
                math.dist(start, end) > 12):
            return False
        crossings = {0., 1.}
        for dimension in (0, 1):
            delta = end[dimension] - start[dimension]
            if delta:
                low, high = sorted((start[dimension], end[dimension]))
                for boundary in range(math.ceil(low / a.size), math.floor(high / a.size) + 1):
                    crossings.add((boundary * a.size - start[dimension]) / delta)
        ordered = sorted(crossings)
        samples = sorted(ordered + [(x + y) / 2 for x, y in zip(ordered, ordered[1:])])
        previous = set()
        for fraction in samples:
            x, z = (start[d] + (end[d] - start[d]) * fraction for d in (0, 1))
            cells = {(math.floor((x + dx) / a.size), math.floor((z + dz) / a.size))
                     for dx in (-1e-7, 1e-7) for dz in (-1e-7, 1e-7)}
            if any(c not in base for c in cells):
                return False
            adjacent = cells | previous
            if any(not a.compatible(c, base[c], d, base[d]) for c in adjacent for d in adjacent if c != d):
                return False
            previous = cells
        return True

    def recover(self, player, geometry_identity):
        view = self._view(player)
        if view is None:
            return None
        a, base, safe = self.atlas, view['base'], view['safe']
        first = a.cell(player)
        start = (player['x'], player['z'])
        if first not in base or first in safe or not self.clear(start, a.center(first), base):
            return None
        initial = math.dist(start, a.center(first))
        queue = [(initial, first)]
        costs, previous = {first: initial}, {first: None}
        while queue and len(previous) <= 128:
            distance, cell = heapq.heappop(queue)
            if distance != costs[cell] or distance > 12:
                continue
            if cell in safe:
                chain = []
                while cell is not None:
                    chain.append(cell)
                    cell = previous[cell]
                chain.reverse()
                path = [start, *(a.center(c) for c in chain)]
                heights = [player['y'], *(base[c] for c in chain)]
                index = 1
                for n, point in enumerate(path[1:], 1):
                    if 1e-6 < math.dist(start, point) <= 6 and self.clear(start, point, base):
                        index = n
                path, heights = [start, *path[index:]], [heights[0], *heights[index:]]
                waypoint = path[1]
                distance = sum(math.dist(p, q) for p, q in zip(path, path[1:]))
                return {'geometry_identity': geometry_identity,
                        'geometry_layer': view['geometry_layer'], 'player_ptr': player.get('ptr'),
                        'start': {k: player[k] for k in ('x', 'y', 'z')},
                        'path': [list(p) for p in path], 'path_heights': heights,
                        'waypoint': {'x': waypoint[0], 'z': waypoint[1]}, 'path_length': distance,
                        'source': 'verified_native_collision_base', 'clearance_verified': False,
                        'dynamic_passability_verified': False}
            for dx, dz in NEIGHBORS:
                nxt = cell[0] + dx, cell[1] + dz
                score = distance + a.size
                if (score > 12 or nxt not in base or score >= costs.get(nxt, math.inf) or
                        not self.clear(a.center(cell), a.center(nxt), base)):
                    continue
                costs[nxt], previous[nxt] = score, cell
                heapq.heappush(queue, (score, nxt))
        return None


def _segment_triangle_interval(start, end, triangle):
    """Exact convex XZ coverage interval for a nondegenerate triangle."""
    a, b, c = [(p[0], p[2]) for p in triangle]
    cross = lambda p, q: p[0] * q[1] - p[1] * q[0]
    area = cross((b[0]-a[0], b[1]-a[1]), (c[0]-a[0], c[1]-a[1]))
    if abs(area) < 1e-9:
        return None
    sign = 1 if area > 0 else -1
    low, high = 0., 1.
    for p, q in ((a,b), (b,c), (c,a)):
        edge = q[0]-p[0], q[1]-p[1]
        base = sign*cross(edge, (start[0]-p[0], start[1]-p[1]))
        slope = sign*cross(edge, (end[0]-start[0], end[1]-start[1]))
        if abs(slope) < 1e-12:
            if base < -1e-8:
                return None
        elif slope > 0:
            low = max(low, -base/slope)
        else:
            high = min(high, -base/slope)
        if low > high + 1e-9:
            return None
    return max(0.,low), min(1.,high)


def _segments_touch(a, b, c, d):
    cross = lambda p, q, r: (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    if any(max(min(a[k],b[k]), min(c[k],d[k])) > min(max(a[k],b[k]), max(c[k],d[k]))+1e-8 for k in (0,1)):
        return False
    x, y, u, v = cross(a,b,c), cross(a,b,d), cross(c,d,a), cross(c,d,b)
    return ((x <= 1e-8 and y >= -1e-8) or (y <= 1e-8 and x >= -1e-8)) and ((u <= 1e-8 and v >= -1e-8) or (v <= 1e-8 and u >= -1e-8))


class LocalConnectors:
    """Small exact-surface connectors into the unchanged canonical safe grid.

    A half-unit local raster selects candidates; continuous triangle coverage
    and wall intersection checks prove each segment. No coarse cell is promoted.
    """
    SIZE = .5
    SURFACE_WORK_LIMIT = 400000

    def __init__(self, atlas):
        self.atlas, self.views, self.failed = atlas, [], {}
        self.single_cache = {}
        self.revision = 0

    def _charge(self, count=1):
        work = getattr(self, '_surface_work', None)
        if work is not None:
            work[0] += count
            if work[0] > self.SURFACE_WORK_LIMIT:
                raise Unsupported('Local surface work limit')

    def _native_surface(self, player, identity):
        """Connect only the locally shared-XYZ sheet matching measured feet.

        Overlapping disconnected floors never join this surface. The endpoint
        must leave the overlap and pass the unchanged normal-grid projection.
        """
        start = player['x'], player['z']
        key = start, player['y']
        def bound(proof):
            if proof is None:
                return None
            return dict(proof, geometry_identity=identity, player_ptr=player.get('ptr'),
                        start={k: player[k] for k in ('x', 'y', 'z')})
        # Exact feet, not a rounded cell, select the seed on this immutable
        # Atlas. Provider revalidates its loaded identity and actors each read.
        if key in self.single_cache:
            return bound(self.single_cache[key])
        self.revision += 1
        def finish(proof=None):
            self.single_cache[key] = proof
            if len(self.single_cache) > 128:
                self.single_cache.pop(next(iter(self.single_cache)))
            return bound(proof)
        floors, walls, hits = {}, [], []
        work = [0]
        x0,z0 = start[0]-12.5,start[1]-12.5
        for index, row in enumerate(self.atlas.triangles):
            work[0] += 1
            a,b,c,flags,normal = row
            if flags & TRIGGER_FLAG or not _clip((a,b,c),x0,z0,25):
                continue
            if normal[1] > .6:
                floors[index] = row
                if _inside(*start,a,b,c):
                    h = _height(*start,a,b,c)
                    if abs(h-player['y']) <= .05:
                        hits.append((index,h))
            elif abs(normal[1]) <= .6:
                walls.append(row)
            if len(floors) > 128 or len(walls) > 128:
                return finish()
        # The chosen face must match measured feet within .01. A second face
        # within .05 remains ambiguous; farther overlapping sheets do not
        # acquire foot authority merely by sharing the actor's XZ coordinates.
        if len(hits) != 1 or abs(hits[0][1]-player['y']) > .01:
            return finish()
        edges = {}
        for index,row in floors.items():
            a,b,c = row[:3]
            for p,q in ((a,b),(b,c),(c,a)):
                work[0] += 1
                if not _clip((p,q,q),x0,z0,25):
                    continue
                edge = tuple(sorted((tuple(p),tuple(q))))
                edges.setdefault(edge,[]).append(index)
                if len(edges[edge]) > 2:
                    return finish()
        component = {hits[0][0]}
        queue = [hits[0][0]]
        for index in queue:
            a,b,c = floors[index][:3]
            for p,q in ((a,b),(b,c),(c,a)):
                work[0] += 1
                for neighbor in edges.get(tuple(sorted((tuple(p),tuple(q)))),[]):
                    if neighbor not in component:
                        component.add(neighbor);queue.append(neighbor)
        # Reuse the original bounded local raster/path and segment/wall checker.
        # Only exact shared 3-D edges supply floor membership; normal projection
        # remains the original full Atlas and is never replaced by this sheet.
        sheet = SimpleNamespace(triangles=[floors[i] for i in sorted(component)]+walls,
                                cell=self.atlas.cell,project=self.atlas.project)
        local = LocalConnectors(sheet)
        local._native_child = True
        local._surface_work = work
        def endpoint_ok(point, height):
            for row in floors.values():
                local._charge()
                if _inside(*point,*row[:3]) and abs(_height(*point,*row[:3])-height) > .05:
                    return False
            return True
        local.endpoint_ok = endpoint_ok
        try:
            proof = local.recover(player,identity)
        except Unsupported:
            return finish()
        if proof:
            proof.update(connector_basis='exact_connected_native_foot_surface',
                         seed_triangle=hits[0][0],surface_triangles=sorted(component),
                         surface_work=work[0])
        return finish(proof)

    def _point_height(self, point):
        values = []
        for a,b,c,flags,normal in self.atlas.triangles:
            self._charge()
            if not flags & TRIGGER_FLAG and normal[1] > .6 and _inside(point[0],point[1],a,b,c):
                h = _height(point[0],point[1],a,b,c)
                if all(abs(h-v) > .25 for v in values):
                    values.append(h)
                    if len(values) > 1:
                        return None
        return values[0] if values else None

    def _fail(self, key):
        self.failed[key] = None
        if len(self.failed) > 128:
            self.failed.pop(next(iter(self.failed)))
        return None

    def _local(self, start, height):
        cell = tuple(math.floor(v/self.SIZE) for v in start)
        for view in self.views:
            if cell in view['base'] and abs(view['base'][cell]-height) <= .75:
                return view
        key = cell, round(height,3)
        if key in self.failed:
            return None
        self.revision += 1
        low = tuple(v-25 for v in cell); high = tuple(v+25 for v in cell)
        values, floors, walls = {}, [], []
        work = 0
        for a,b,c,flags,normal in self.atlas.triangles:
            self._charge()
            if flags & TRIGGER_FLAG:
                continue
            xmin = max(low[0], math.floor(min(p[0] for p in (a,b,c))/self.SIZE))
            xmax = min(high[0], math.floor(max(p[0] for p in (a,b,c))/self.SIZE))
            zmin = max(low[1], math.floor(min(p[2] for p in (a,b,c))/self.SIZE))
            zmax = min(high[1], math.floor(max(p[2] for p in (a,b,c))/self.SIZE))
            if xmin>xmax or zmin>zmax:
                continue
            if normal[1] > .6:
                floors.append((a,b,c))
                for x in range(xmin,xmax+1):
                    for z in range(zmin,zmax+1):
                        self._charge()
                        work += 1
                        if work > 200000:
                            return self._fail(key)
                        px,pz = self.center((x,z))
                        if _inside(px,pz,a,b,c):
                            h = _height(px,pz,a,b,c)
                            row = values.setdefault((x,z),[])
                            if all(abs(h-v)>.25 for v in row):
                                row.append(h)
                            if len(row)>4:
                                return self._fail(key)
            elif abs(normal[1]) <= .6:
                walls.append((a,b,c))
        base = {c:v[0] for c,v in values.items() if len(v)==1}
        for triangle in walls:
            for c,h in list(base.items()):
                self._charge()
                work += 1
                if work > 200000:
                    return self._fail(key)
                poly = _clip(triangle,c[0]*self.SIZE,c[1]*self.SIZE,self.SIZE)
                if poly and max(p[1] for p in poly)>h+2 and min(p[1] for p in poly)<h+12:
                    base.pop(c)
        if cell not in base or abs(base[cell]-height) > .75:
            return self._fail(key)
        view = {'base':base,'floors':floors,'walls':walls,'goals':{}}
        self.views.append(view); self.views=self.views[-4:]
        return view

    @classmethod
    def center(cls, cell):
        return (cell[0]+.5)*cls.SIZE, (cell[1]+.5)*cls.SIZE

    def clear(self, start, end, h0, h1, view):
        if math.dist(start,end)>12 or abs(h1-h0)>.75+.75*math.dist(start,end):
            return False
        intervals=[]
        for triangle in view['floors']:
            self._charge(3)  # Coverage plus its two endpoint-height samples.
            interval=_segment_triangle_interval(start,end,triangle)
            if interval is None:
                continue
            matched=True
            for t in interval:
                x,z=start[0]+t*(end[0]-start[0]),start[1]+t*(end[1]-start[1])
                if abs(_height(x,z,*triangle)-(h0+t*(h1-h0)))>.25:
                    matched=False;break
            if matched:
                intervals.append(interval)
        covered=0.
        for lo,hi in sorted(intervals):
            if lo>covered+1e-8:
                return False
            covered=max(covered,hi)
        if covered<1-1e-8:
            return False
        for triangle in view['walls']:
            self._charge(4)  # Triangle coverage plus three projected edges.
            # Conservatively reject a projected wall crossing whenever its
            # vertical span could overlap this segment's body interval.
            if max(p[1] for p in triangle)<=min(h0,h1)+2 or min(p[1] for p in triangle)>=max(h0,h1)+12:
                continue
            if _segment_triangle_interval(start,end,triangle) is not None:
                return False
            points=[(p[0],p[2]) for p in triangle]
            if any(_segments_touch(start,end,p,q) for p,q in zip(points,points[1:]+points[:1])):
                return False
        return True

    def recover(self, player, identity):
        if any(type(player.get(k)) not in (int,float) or not math.isfinite(player[k]) for k in ('x','y','z')):
            return None
        start=player['x'],player['z'];height=self._point_height(start)
        if height is None:
            return None if getattr(self,'_native_child',False) else self._native_surface(player, identity)
        if abs(height-player['y'])>.35:
            return None
        view=self._local(start,height)
        if view is None:
            return None
        base=view['base'];first=tuple(math.floor(v/self.SIZE) for v in start)
        if not self.clear(start,self.center(first),height,base[first],view):
            return None
        distance=math.dist(start,self.center(first))
        queue=[(distance,first)];costs={first:distance};previous={first:None};tested=0
        while queue and len(previous)<=2601:
            self._charge()
            distance,cell=heapq.heappop(queue)
            if distance!=costs[cell] or distance>12:
                continue
            point=self.center(cell);coarse=self.atlas.cell({'x':point[0],'z':point[1]})
            # Ineligible overlap points cannot be endpoints. Do not spend a
            # normal-projection slot or cache their coarse cell as a failure:
            # a later point in that same cell may leave the overlap.
            eligible=not getattr(self,'endpoint_ok',None) or self.endpoint_ok(point,base[cell])
            goal=view['goals'].get(coarse,False) if eligible else None
            if eligible and goal is False:
                # A normal target still passes the original Atlas projection.
                if tested>=12:
                    goal=None
                else:
                    tested+=1
                    goal=self.atlas.project({'x':point[0],'y':base[cell],'z':point[1]})
                    view['goals'][coarse]=goal
            if goal and coarse in goal['_heights'] and abs(goal['_heights'][coarse]-base[cell])<=.75:
                chain=[];cursor=cell
                while cursor is not None:
                    chain.append(cursor);cursor=previous[cursor]
                chain.reverse();path=[start,*[self.center(c) for c in chain]];heights=[height,*[base[c] for c in chain]]
                # Compact only continuously verified segments; keep the core's
                # exact path[1]==waypoint and <=16-node contract.
                compact=[path[0]];compact_h=[heights[0]];at=0
                while at<len(path)-1:
                    self._charge(len(path)-at-1)
                    choices=[n for n in range(at+1,len(path)) if math.dist(path[at],path[n])<=6 and self.clear(path[at],path[n],heights[at],heights[n],view)]
                    if not choices:
                        return None
                    at=max(choices);compact.append(path[at]);compact_h.append(heights[at])
                length=sum(math.dist(a,b) for a,b in zip(compact,compact[1:]))
                if not 2<=len(compact)<=16 or not 0<length<=12 or not 0<math.dist(*compact[:2])<=6:
                    return None
                return {'geometry_identity':identity,'geometry_layer':goal['geometry_layer'],
                        'player_ptr':player.get('ptr'),'start':{k:player[k] for k in ('x','y','z')},
                        'path':[list(p) for p in compact],'path_heights':compact_h,
                        'waypoint':{'x':compact[1][0],'z':compact[1][1]},'path_length':length,
                        'source':'verified_native_collision_base','connector_basis':'exact_local_triangles',
                        'sampling_size':self.SIZE,'continuous_surface_verified':True,
                        'clearance_verified':False,'dynamic_passability_verified':False}
            for dx,dz in NEIGHBORS:
                nxt=cell[0]+dx,cell[1]+dz;score=distance+self.SIZE
                if (nxt not in base or score>12 or score>=costs.get(nxt,math.inf) or
                        not self.clear(point,self.center(nxt),base[cell],base[nxt],view)):
                    continue
                costs[nxt]=score;previous[nxt]=cell;heapq.heappush(queue,(score,nxt))
        return None


class Provider:
    def __init__(self, ad):
        self.ad, self.identity, self.atlas, self.source = ad, None, None, None
        self.layout_identity = None
        self.margin = None
        self.local = None

    def snapshot(self, state):
        try:
            return self._snapshot(state)
        except (ValueError, OSError, KeyError, TypeError, struct.error, Unsupported) as exc:
            self.identity, self.atlas, self.source = None, None, None
            self.layout_identity = None
            self.margin = None
            self.local = None
            return {'geometry_verified': False, 'geometry_diagnostic': str(exc)}

    def _snapshot(self, state):
        players = state.get('players') or {}
        if state.get('verified') is not True or state.get('phase') != 14 or state.get('travelling') or set(players) != {1, 2}:
            raise ValueError("Geometry needs fresh two-player gameplay")
        episode, floor = state['episode'], state['floor']
        if (episode, floor) not in {(a, b) for a, b, _ in KNOWN}:
            raise ValueError("No verified geometry for this area")
        expected = (14, episode - 1, floor, 0, *(int(players[p]['ptr'], 16) for p in (1, 2)))
        floor_binding = _forest2_binding(self.ad, episode, floor)
        if _binding(self.ad) != expected:
            raise ValueError("Geometry player/area observation changed")
        if _read(self.ad, 0x8007A728, 8) != bytes.fromhex('806db0504e800020'):
            raise ValueError("Collision manager getter code changed")
        roots = _roots(self.ad)
        root, base, size, manager = roots
        if not 0 < size <= MAX_BYTES:
            raise ValueError("Collision allocation budget")
        table = _table(self.ad, manager)
        blob = _read(self.ad, base, size)
        if not base <= root <= base + size - 4:
            raise ValueError("Collision root outside allocation")
        if (_roots(self.ad) != roots or _table(self.ad, manager) != table or _binding(self.ad) != expected or
                _forest2_binding(self.ad, episode, floor) != floor_binding):
            raise ValueError("Collision changed during observation")
        identity = _hash(struct.pack('>6I', episode, floor, *roots) + table + blob)
        refreshed = identity != self.identity
        if identity != self.identity:
            triangles, digest = parse_loaded(base, blob, table)
            source = KNOWN.get((episode, floor, digest))
            if not source:
                raise ValueError("Loaded collision layout has no exact disc proof")
            self.atlas = Atlas(triangles)
            self.margin = MarginViews(self.atlas)
            self.local = LocalConnectors(self.atlas)
            self.identity, self.source = identity, {'path': source, 'triangles_sha256': digest, 'triangle_count': len(triangles)}
            # Native allocations are cache authority, not persistent map names.
            self.layout_identity = _hash(f'3OE2|{episode}|{floor}|{digest}'.encode())
        views, recoveries = {}, {}
        revision = self.atlas.work_revision
        margin_revision = self.margin.revision
        local_revision = self.local.revision
        for slot, player in players.items():
            view = self.atlas.project(player)
            if view:
                views[slot] = {k: v for k, v in view.items() if not k.startswith('_')}
                views[slot]['geometry_identity'] = self.layout_identity
            elif floor > 0:
                recovery = self.margin.recover(player, self.layout_identity)
                if recovery is None and not self.atlas.heights.get(self.atlas.cell(player)):
                    recovery = self.local.recover(player, self.layout_identity)
                elif recovery is None and len(self.atlas.heights.get(self.atlas.cell(player), [])) > 1:
                    recovery = self.local._native_surface(player, self.layout_identity)
                if recovery:
                    recoveries[slot] = recovery
        if (_roots(self.ad) != roots or _binding(self.ad) != expected or
                _forest2_binding(self.ad, episode, floor) != floor_binding):
            raise ValueError("Collision area changed during raster")
        refreshed = refreshed or self.atlas.work_revision != revision or self.margin.revision != margin_revision or self.local.revision != local_revision
        return {'geometry_verified': True, 'geometry_identity': self.layout_identity,
                'geometry_loaded_fingerprint': self.identity,
                'geometry_players': views, 'geometry_recovery_players': recoveries, 'geometry_source': self.source,
                'geometry_dynamic_gates_verified': False, 'geometry_refreshed': refreshed}
