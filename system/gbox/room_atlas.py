"""Cumulative room atlas: every observed room/stage iteration, its landmarks and exits.

Observations are merged across visits so each pass adds confidence. Landmarks
(checkpoint, switch, button, door, exit, ...) are stored per (game, level, room
variant). Routes are planned over observed links only: a link that has failed more
than it succeeded is avoided, unobserved targets are reported as unknown, never guessed.
Pure data: no coordinates or addresses are executed; adapters bind actions themselves.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'gbox-data' / 'room-atlas'
KINDS = {'checkpoint', 'switch', 'button', 'door', 'exit', 'entrance', 'item', 'save', 'boss', 'hazard', 'other'}
_LOCK = threading.RLock()


def _slug(text):
    text = str(text or '').strip()
    if not text:
        raise ValueError('empty identifier')
    return text[:120]


def layout_hash(landmarks):
    """Stable id of a room iteration from its landmark set (order independent)."""
    rows = sorted((str(r.get('kind')), str(r.get('name')), tuple(round(float(c), 1) for c in (r.get('pos') or ())))
                  for r in landmarks)
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:12]


class Atlas:
    def __init__(self, game_id, root=None):
        self.game_id = _slug(game_id)
        self.root = Path(root) if root else ROOT
        self.path = self.root / (hashlib.sha256(self.game_id.encode()).hexdigest()[:16] + '.json')
        self.data = {'game_id': self.game_id, 'rooms': {}, 'links': {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())

    # -- recording -------------------------------------------------------------
    def observe_room(self, level, room, landmarks=(), variant=None, build=''):
        """Merge one visit. Landmarks seen again gain `seen`; new ones are added."""
        level, room = _slug(level), _slug(room)
        landmarks = list(landmarks)
        for row in landmarks:
            if row.get('kind') not in KINDS or not row.get('name'):
                raise ValueError('landmark needs a known kind and a name: %r' % (row,))
        variant = variant or layout_hash(landmarks) if landmarks else (variant or 'default')
        rid = '%s/%s#%s' % (level, room, variant)
        with _LOCK:
            rec = self.data['rooms'].setdefault(rid, {
                'level': level, 'room': room, 'variant': variant, 'visits': 0,
                'landmarks': {}, 'builds': [], 'first_seen': time.time()})
            rec['visits'] += 1
            rec['last_seen'] = time.time()
            if build and build not in rec['builds']:
                rec['builds'].append(build)
            for row in landmarks:
                lk = '%s:%s' % (row['kind'], row['name'])
                ent = rec['landmarks'].setdefault(lk, {'kind': row['kind'], 'name': str(row['name']),
                                                       'pos': row.get('pos'), 'seen': 0, 'state': None})
                ent['seen'] += 1
                if row.get('pos') is not None:
                    ent['pos'] = list(row['pos'])
                if 'state' in row:
                    ent['state'] = row['state']
        return rid

    def observe_link(self, src, dst, via=None, ok=True):
        """Record a traversal src -> dst (room ids), via a named landmark (door/exit)."""
        key = '%s>%s' % (src, dst)
        with _LOCK:
            link = self.data['links'].setdefault(key, {'src': src, 'dst': dst, 'via': via, 'ok': 0, 'fail': 0})
            link['ok' if ok else 'fail'] += 1
            if via:
                link['via'] = via
        return key

    # -- queries ---------------------------------------------------------------
    def confidence(self, rid):
        rec = self.data['rooms'].get(rid)
        if not rec:
            return 0.0
        return round(1 - 1 / (1 + rec['visits']), 3)

    def find(self, kind, name=None, level=None):
        out = []
        for rid, rec in self.data['rooms'].items():
            if level and rec['level'] != level:
                continue
            for ent in rec['landmarks'].values():
                if ent['kind'] == kind and (name is None or ent['name'] == name):
                    out.append({'room': rid, **ent})
        return sorted(out, key=lambda r: (r['room'], r['name']))

    def route(self, src, dst):
        """Cheapest observed route; failure-prone links cost more, mostly-failing links are skipped."""
        graph = {}
        for link in self.data['links'].values():
            if link['fail'] > link['ok']:
                continue
            cost = 1 + link['fail'] / max(1, link['ok'])
            graph.setdefault(link['src'], []).append((link['dst'], cost, link))
        dist, prev, heap = {src: 0.0}, {}, [(0.0, src)]
        while heap:
            d, node = heapq.heappop(heap)
            if node == dst:
                break
            if d > dist.get(node, 1e18):
                continue
            for nxt, cost, link in graph.get(node, ()):
                nd = d + cost
                if nd < dist.get(nxt, 1e18):
                    dist[nxt], prev[nxt] = nd, (node, link)
                    heapq.heappush(heap, (nd, nxt))
        if dst not in dist:
            return {'status': 'unknown', 'reason': 'no observed route', 'src': src, 'dst': dst}
        steps, node = [], dst
        while node != src:
            node, link = prev[node]
            steps.append({'from': link['src'], 'to': link['dst'], 'via': link['via']})
        steps.reverse()
        return {'status': 'ok', 'cost': round(dist[dst], 3), 'steps': steps}

    def route_to_landmark(self, src, kind, name=None):
        """Route to the nearest observed room holding the landmark; unknown if never seen."""
        best = None
        for hit in self.find(kind, name):
            plan = {'status': 'ok', 'cost': 0.0, 'steps': []} if hit['room'] == src else self.route(src, hit['room'])
            if plan['status'] == 'ok' and (best is None or plan['cost'] < best['cost']):
                best = {**plan, 'landmark': hit}
        return best or {'status': 'unknown', 'reason': 'landmark not observed or unreachable',
                        'kind': kind, 'name': name}

    def coverage(self):
        """What is understood so far and what is a dangling frontier (link target never visited)."""
        rooms = self.data['rooms']
        frontier = sorted({l['dst'] for l in self.data['links'].values() if l['dst'] not in rooms})
        counts = {}
        for rec in rooms.values():
            for ent in rec['landmarks'].values():
                counts[ent['kind']] = counts.get(ent['kind'], 0) + 1
        return {'rooms': len(rooms), 'links': len(self.data['links']), 'landmarks': counts,
                'unvisited_frontier': frontier}

    def save(self):
        with _LOCK:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
            os.replace(tmp, self.path)
