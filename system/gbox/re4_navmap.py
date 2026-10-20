"""Resident Evil 4 (GameCube G4BE08) level data for autoplay: a top-down navigation map of a room built from the game's
own files (collision, events, pickups, spawns) and a path planner. First target: the Mercenaries Village, room r400.

    from gbox import re4_navmap as N
    st = N.stage("r400")                     # cached JSON (profiles/gamedata/re4_r400_navmap.json), no disc needed
    st["events"]                             # [{kind: time_bonus|combo_bonus|ladder|area|item, pos: [x, y, z], ...}]
    N.path(st, (x, z), (gx, gz))             # [Waypoint(x, y, z, action)]; action "vault" = press A at the fence /
                                             # window (JUMP OVER), "ladder" = climb, None = run
    N.tour(st, (x, y, z))                    # visiting order of the hourglasses (indices into st["hourglasses"])
    st["grid"].state_at(x, z, y)             # "free" | "near" | "vault" | "wall" | "void"
    N.sight(st, a, b)                        # does a bullet ray from a to b clear the walls?

Regenerate (reads the disc read-only; a GCZ is read in place):
    python -m gbox.re4_navmap --iso "<RE4 (USA) (Disc 1).gcz|.iso>" --room r400 \
        --out profiles/gamedata/re4_r400_navmap.json --png docs/evidence/re4-navmap/r400.png

Where the data lives (G4BE08 disc 1; formats decoded by gBox from main.dol, 2026-10-20). World units are mm, y up,
the same floats Leon has at player+0x94 (heading = atan2(dx, dz)).
  St4/r4xx.das   UDAS (re4gc_inventory.udas_entries). Entry type 0 is the room DAT, packed: ASCII "<packed hex>\\t<size
                 hex>\\n", data at the next 32-byte boundary. Codec (main.dol 0x801701d4 header, 0x80170260 set-up,
                 0x8018f5cc loop): an LZP dictionary - per previous byte value a 512-slot ring of (position, length) of
                 the chunks that followed it - coded with an adaptive range coder: a 0x500-symbol model (0x000-0x1ff =
                 ring slot + explicit length, 0x200-0x3ff = ring slot with its remembered length, 0x400-0x4ff = literal)
                 and a 0x100-symbol model for length bytes; total frequency 2^15, rescaled by halving. das_unpack().
  room DAT       r400: 46 entries CAM SAT LIT LIT SMD SMX SHD EFF TEX ITM ETM ETS EAR SAR EAT AEV RTP MDT CNS STB FSE
                 ESE OSD BLK EVS DRA BIN TPL BIN TPL ITA DSE EMI BIN TPL FCV x11.
  SAT / EAT      player / enemy collision (header read at 0x800b7a9c): u32 0x8001FF79, u32 body offset (8); body: u16,
                 u16 #verts, u16 #normals, u16 #edges, u16, u16 #tris, 4 x u16 (tree); f32 xyz vertices, f32 normals,
                 f32 edge vectors (3 per triangle: v1-v0, v2-v1, v0-v2), 20-byte triangles (u16 v0 v1 v2 normal e0 e1
                 e2 pad, u32 attribute), then a bounding-volume tree. Attribute = hi << 16 | lo (0x800b53c8); in the
                 triangle filter (0x800b4b54 / 0x800b4fcc): bits 29-31 skip one edge's test; 0x400 collides only in
                 query mode 0x8000 (most rays use mode 0 and pass it: an invisible blocker); 0x00800000 is skipped in
                 that mode; 0x40 is skipped in mode 0x4000 and by the hand-grenade ray (0x8003b5fc); 0x20 is skipped
                 by several rays. In r400 every 0x20 / 0x40 wall is a 1000-high two-sided fence or window sill with a
                 0x400 wall on top: the JUMP OVER / window spots. That reading (VAULT_BITS) is inferred from geometry
                 plus those rules, not from the prompt code - check one in game before trusting it blindly.
  AEV / ITA      'AEV\\0' / 'ITA\\0', u16 version (0x104 / 0x105), u16 count, 0x9c-byte entries: +0x08 zone floor y,
                 +0x0c zone height, +0x14 four (x, z) corners, +0x35 type, +0x36 index, +0x38 trigger (1 = entering,
                 2 = action button), type data from +0x5c. AEV handlers per type at 0x8020CAD4 (1 = door 0x8014CA4C,
                 4 = area, 0x10 = climb 0x8014edc4: +0x5c stand x y z, +0x68 facing, +0x6c signed rung count -> player
                 routine 0x10). ITA (+0x35 = 3): +0x5c x y z, +0x78 u16 item id, +0x7a flag, +0x7c u16 amount (the
                 item-get routine 0x8001a510 is called with exactly those two); position 0 = inside a breakable.
  Hourglasses    item 0x73 Time Bonus: item-get stores the amount in pG+0x4F7E and the clock adds amount x 30 frames;
                 item 0x75 Combo Bonus: MERC+0x50 += amount x 30 frames, and while it runs every kill scores at least
                 the bonus value (add-kill 0x8001eea8). Both draw the hourglass model of the room's ITM pack.
  etc/*.esl      enemy set lists: omake01 = Mercenaries r400 / r402, omake02 = r403 / r404, omake00 = Assignment Ada;
                 32-byte entries: +0x00 flags, +0x01 em id (0x16 = village Ganado, em16.drs), +0x02 type, +0x08 u16
                 hp, +0x0c s16 x y z / 10, +0x12 s16 angles (0x8000 = pi), +0x18 u16 room.
  RTP            the enemies' route graph ('2RTP', u32 #nodes, u32, u32 node table, u32 links, u32 next-hop matrix;
                 nodes f32 x y z + u16 first link + u16 count, links u16 node + u16 distance / 10) -> st["routes"].

The map: SAT floors (normal y >= 0.7) sampled 3 x 3 per cell and clustered into storeys; a storey with another floor
less than CLEAR above it has no headroom (r400 has a catch-all y=0 plane under the whole map, hills included); steep
triangles and ceilings block the storeys whose head room they cut, except VAULT_BITS walls (vault) and the 0x400
blockers above them; 0x00800000 walls are kept solid (conservative). reach: 2 = a central spawn can walk there and
back (the playable area), 1 = one way only. Every hourglass gets a "stand" point: inside its action zone when it has
one, else floor within 900 units of the item.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import heapq
import json
import math
import os
import re
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import NamedTuple

import numpy as np

GAME_ID, DISC_ID = "78ab9efa2e310db4", "G4BE08"
FORMAT = "gbox.re4_navmap/1"
DATA_DIR = Path(__file__).resolve().parent.parent / "profiles" / "gamedata"

CELL = 200.0          # grid cell (world units = mm)
STEP = 350.0          # highest step between neighbouring cells (stairs, kerbs)
CLEAR = 1700.0        # a wall or ceiling between floor + STEP and floor + CLEAR blocks the cell (Leon is ~1.8 m)
VAULT_TOP = 1200.0    # a VAULT_BITS wall whose top is at most this far above the floor can be jumped over
DROP_MAX = 4600.0     # deepest drop through a vault (out of a window)
LAYER_GAP = 600.0     # floor samples of one cell further apart than this are separate storeys
VAULT_BITS, BLOCKER_BIT = 0x60, 0x400
FREE, NEAR, VAULT, WALL = 1, 2, 3, 4
STATE_NAMES = {0: "void", FREE: "free", NEAR: "near", VAULT: "vault", WALL: "wall"}
NEAR_COST, VAULT_COST, LADDER_COST = 2.5, 2500.0, 6000.0
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
E_WALK, E_VAULT, E_DROP, E_LADDER = 0, 1, 2, 3
ITEM_TIME, ITEM_COMBO = 0x73, 0x75
ITEM_NAMES = {ITEM_TIME: "Time Bonus (hourglass)", ITEM_COMBO: "Combo Bonus (hourglass)"}
EM_NAMES = {0x16: "Ganado (village)"}


# ================================================================ room archive codec (main.dol 0x8018f5cc)

_HDR = re.compile(rb"([0-9a-fA-F]{1,8})\t([0-9a-fA-F]{1,8})\n")


class _Model:
    """One adaptive frequency model of the room codec (0x80170260 init, 0x8018f798 decode/update)."""
    __slots__ = ("n", "cf", "cs", "freq", "count", "shift", "threshold", "dirty", "lookup")

    def __init__(self, n: int):
        self.n = n
        freq = [0x8000 // n + (1 if i < 0x8000 % n else 0) for i in range(n)]
        self.cf, self.cs, run = list(freq), [0] * n, 0
        for i, f in enumerate(freq):
            self.cs[i], run = run, run + f
        self.freq, self.count, shift = [1] * n, n, 0
        while True:
            shift += 1
            if shift > 14 or self.count < (1 << shift):
                break
        self.shift, self.threshold, self.dirty, self.lookup = shift, 1 << shift, True, [0] * 0x8000

    def rebuild(self):
        lk, j = self.lookup, 0
        for s in range(self.n):
            end = self.cs[s] + self.cf[s]
            if j < end:
                lk[j:end] = [s] * (end - j)
                j = end
        self.dirty = False

    def update(self, s: int):
        self.freq[s] += 1
        self.count += 1
        if self.shift <= 14:
            if self.count == self.threshold:               # scale counts to a 2^15 total, keep counting
                k, run = 15 - self.shift, 0
                for i, f in enumerate(self.freq):
                    self.cf[i], self.cs[i] = f << k, run
                    run += f << k
                self.shift += 1
                self.threshold, self.dirty = 1 << self.shift, True
        elif self.count > 0x7FFF:                          # 2^15 seen: these become the table, counts halve
            run, total, fr = 0, 0, self.freq
            for i in range(self.n):
                f = fr[i]
                self.cf[i], self.cs[i] = f, run
                run += f
                if f > 1:
                    f >>= 1
                    fr[i] = f
                total += f
            self.count, self.dirty = total, True


def das_unpack(data: bytes) -> bytes:
    """A packed RE4 GC room DAT ("<packed>\\t<size>\\n" header) -> the plain DAT."""
    m = _HDR.match(bytes(data[:32]))
    if not m:
        raise ValueError("not a packed RE4 room DAT (no '<packed hex>\\t<size hex>\\n' header)")
    packed, size = int(m.group(1), 16), int(m.group(2), 16)
    p = (m.end() - 1 + 0x20) & ~0x1F
    if p + packed > len(data) + 4 or size > 64 << 20:
        raise ValueError(f"packed room DAT header ({packed:#x} -> {size:#x}) does not fit the "
                         f"{len(data):#x}-byte entry")
    src = bytes(data) + bytes(8)
    rng, code = 0x80, src[p]
    p += 1
    A, B = _Model(0x500), _Model(0x100)

    def sym(md: _Model) -> int:
        nonlocal rng, code, p
        if rng <= 0x800000:
            if rng > 0x8000:
                code, rng, p = ((code << 8) | src[p]) & 0xFFFFFFFF, (rng << 8) & 0xFFFFFFFF, p + 1
            elif rng > 0x80:
                code = ((code << 16) | (src[p] << 8) | src[p + 1]) & 0xFFFFFFFF
                rng, p = (rng << 16) & 0xFFFFFFFF, p + 2
            else:
                code = ((code << 24) | (src[p] << 16) | (src[p + 1] << 8) | src[p + 2]) & 0xFFFFFFFF
                rng, p = (rng << 24) & 0xFFFFFFFF, p + 3
        r = rng >> 14
        if md.dirty:
            md.rebuild()
        v = code // r
        if v >= 0x8000:
            raise ValueError("room DAT stream is corrupt (symbol outside the model)")
        s = md.lookup[v]
        code = (code - r * md.cs[s]) & 0xFFFFFFFF
        rng = ((r * md.cf[s]) & 0xFFFFFFFF) >> 1
        md.update(s)
        return s

    out = bytearray(size)
    ring_i = [0] * 256
    ring_p = [[0] * 512 for _ in range(256)]
    ring_n = [[0] * 512 for _ in range(256)]
    o = last = 0
    while o < size:
        s = sym(A)
        if s > 0x3FF:                                       # literal
            out[o] = s & 0xFF
            o += 1
            n = 1
        else:                                               # copy a chunk that once followed this byte value
            c = out[last]
            slot = (s + ring_i[c]) & 0x1FF
            if s <= 0x1FF:
                n = sym(B)
                if n <= 2:                                  # escape: 2 / 1 / 0 -> a 2 / 3 / 4-byte length follows
                    nb, n = 4 - n, 0
                    for _ in range(nb):
                        n = (n << 8) | sym(B)
                n -= 1
            else:
                n = ring_n[c][slot]
            ptr = ring_p[c][slot]
            if n <= 0 or o + n > size or ptr >= o:
                raise ValueError(f"room DAT stream is corrupt (copy of {n} at {o:#x})")
            for i in range(n):
                out[o + i] = out[ptr + i]
            o += n
        if last < o - 1:
            c = out[last]
            k = ring_i[c]
            ring_p[c][k], ring_n[c][k], ring_i[c] = last + 1, n, (k + 1) & 0x1FF
            last = o - 1
    return bytes(out)


def room_files(das: bytes) -> list[tuple[str, bytes]]:
    """St4/rXXX.das -> [(ext, bytes)] of its room DAT (unpacked when packed)."""
    from .re4gc_inventory import dat_entries, udas_entries
    ent = next((e for e in udas_entries(das) if e["type"] == 0), None)
    if ent is None:
        raise ValueError("room archive has no DAT entry (UDAS type 0)")
    dat = das[ent["offset"]:ent["offset"] + ent["size"]]
    if _HDR.match(dat[:32]):
        dat = das_unpack(dat)
    return [(ext, dat[off:off + n]) for ext, off, n in dat_entries(dat)]


# ================================================================ room file readers

def sat_read(b: bytes) -> dict:
    """SAT / EAT collision -> {verts (n,3), tris (m,3), normals (m,3), attr (m,) u32}."""
    if len(b) < 0x1C:
        raise ValueError("collision file too short")
    magic, body = struct.unpack_from(">II", b, 0)
    if magic != 0x8001FF79 or body + 0x14 > len(b):
        raise ValueError(f"not a SAT/EAT collision file (magic {magic:#x})")
    nv, nn, ne, _u, nt = struct.unpack_from(">HHHHH", b, body + 2)
    o = body + 0x14
    if o + 12 * (nv + nn + ne) + 20 * nt > len(b):
        raise ValueError("collision tables run past the end of the file")
    verts = np.frombuffer(b, ">f4", 3 * nv, o).reshape(nv, 3).astype(np.float64)
    o += 12 * nv
    normals = np.frombuffer(b, ">f4", 3 * nn, o).reshape(nn, 3).astype(np.float64)
    o += 12 * (nn + ne)
    t = np.frombuffer(b, ">u2", 10 * nt, o).reshape(nt, 10).astype(np.int64)
    if nt and (t[:, :3].max() >= nv or t[:, 3].max() >= nn):
        raise ValueError("collision triangle indexes a vertex / normal that is not there")
    return {"verts": verts, "tris": t[:, :3].copy(), "normals": normals[t[:, 3]] if nt else normals[:0],
            "attr": ((t[:, 8] << 16) | t[:, 9]).astype(np.uint32)}


def events_read(b: bytes, magic: bytes) -> list[dict]:
    """AEV (magic b'AEV\\0') or ITA (b'ITA\\0') -> entries with zone, type and the raw 0x9c bytes."""
    if b[:4] != magic or len(b) < 0x10:
        raise ValueError(f"not an {magic[:3].decode()} table")
    ver, n = struct.unpack_from(">HH", b, 4)
    if 0x10 + 0x9C * n > len(b):
        raise ValueError(f"{magic[:3].decode()} table runs past the end ({n} entries)")
    out = []
    for i in range(n):
        e = b[0x10 + 0x9C * i:0x10 + 0x9C * (i + 1)]
        y, h = struct.unpack_from(">2f", e, 8)
        q = struct.unpack_from(">8f", e, 0x14)
        out.append({"i": i, "version": ver, "type": e[0x35], "index": e[0x36], "trigger": e[0x38],
                    "y": y, "h": h, "poly": [(q[2 * k], q[2 * k + 1]) for k in range(4)], "raw": e})
    return out


def esl_read(b: bytes, room: int) -> list[dict]:
    """Enemy set list entries of one room."""
    out = []
    for i in range(len(b) // 32):
        e = b[32 * i:32 * i + 32]
        if struct.unpack_from(">H", e, 0x18)[0] != room:
            continue
        x, y, z = (10.0 * v for v in struct.unpack_from(">3h", e, 0x0C))
        out.append({"esl": i, "em": e[1], "type": e[2], "flags": e[0], "hp": struct.unpack_from(">H", e, 8)[0],
                    "pos": [x, y, z], "facing": round(struct.unpack_from(">h", e, 0x14)[0] * math.pi / 32768, 4),
                    "param": struct.unpack_from(">H", e, 0x1A)[0]})
    return out


def _item_names() -> dict[int, str]:
    names = dict(ITEM_NAMES)
    try:
        d = json.loads((DATA_DIR / f"{GAME_ID}-items.json").read_text())
        for it in d.get("items", []):
            names.setdefault(int(it["id"], 16), it["name"])
    except (OSError, ValueError, KeyError):
        pass
    return names


def _r(v, nd=1):
    return [round(float(x), nd) for x in v]


def room_events(aev: list[dict], ita: list[dict]) -> list[dict]:
    """AEV + ITA -> events: hourglasses (time_bonus / combo_bonus), ladders, areas, doors, other items."""
    names, out = _item_names(), []
    zones = [e for e in aev if e["type"] != 4]

    def zone_of(x, z):
        return next((e for e in zones if _in_poly(x, z, e["poly"])), None)
    for e in ita:
        x, y, z = struct.unpack_from(">3f", e["raw"], 0x5C)
        iid, flag, amount = struct.unpack_from(">HHH", e["raw"], 0x78)
        if x == 0 and y == 0 and z == 0:
            continue                                         # inside a breakable (ETS object), no own position
        kind = {ITEM_TIME: "time_bonus", ITEM_COMBO: "combo_bonus"}.get(iid, "item")
        ev = {"kind": kind, "pos": _r((x, y, z)), "item_id": iid, "name": names.get(iid, f"item {iid:#x}"),
              "amount": amount, "flag": flag, "source": f"ITA[{e['i']}]"}
        if kind != "item":
            ev["seconds"] = amount
        zn = zone_of(x, z)
        if zn is not None:
            ev["zone"] = {"source": f"AEV[{zn['i']}]", "poly": [_r(p) for p in zn["poly"]],
                          "y": _r((zn["y"], zn["y"] + zn["h"])), "trigger": "action" if zn["trigger"] == 2 else "enter"}
        out.append(ev)
    for e in aev:
        cx = sum(p[0] for p in e["poly"]) / 4
        cz = sum(p[1] for p in e["poly"]) / 4
        ev = {"pos": _r((cx, e["y"], cz)), "poly": [_r(p) for p in e["poly"]], "y": _r((e["y"], e["y"] + e["h"])),
              "aev_type": e["type"], "index": e["index"], "trigger": "action" if e["trigger"] == 2 else "enter",
              "source": f"AEV[{e['i']}]"}
        if e["type"] == 0x10:
            x, y, z, ang = struct.unpack_from(">4f", e["raw"], 0x5C)
            rungs = struct.unpack_from(">b", e["raw"], 0x6C)[0]
            ev.update(kind="ladder", pos=_r((x, y, z)), facing=round(ang, 4), rungs=rungs,
                      top=_r((x, y + 1000.0 * rungs, z)))
        elif e["type"] == 4:
            ev["kind"] = "area"
        elif e["type"] == 1:
            ev["kind"] = "door"
        else:
            hit = [o for o in out if o.get("zone", {}).get("source") == ev["source"]]
            ev["kind"] = "pickup_zone" if hit else f"aev_{e['type']:#04x}"
        out.append(ev)
    return out


def _in_poly(x: float, z: float, poly) -> bool:
    inside = False
    for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1]):
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1) + x1:
            inside = not inside
    return inside


# ================================================================ the layered grid

class NavGrid:
    """2.5D occupancy grid: every cell holds 0..n floor layers (storeys), each with a height and a state."""

    def __init__(self, x0, z0, nx, nz, lc, lh, ls, lr=None, cell=CELL):
        self.x0, self.z0, self.nx, self.nz, self.cell = float(x0), float(z0), int(nx), int(nz), float(cell)
        order = np.lexsort((lh, lc))
        self.lc = np.asarray(lc, np.int64)[order]
        self.lh = np.asarray(lh, np.float64)[order]
        self.ls = np.asarray(ls, np.int8)[order]
        self.lr = (np.full(len(order), 2, np.int8) if lr is None else np.asarray(lr, np.int8)[order])
        self.count = np.bincount(self.lc, minlength=nx * nz).astype(np.int64)
        self.first = np.concatenate(([0], np.cumsum(self.count)[:-1])).astype(np.int64)
        self._g = None

    # ---- lookups
    def cell_of(self, x: float, z: float):
        ix, iz = int(math.floor((x - self.x0) / self.cell)), int(math.floor((z - self.z0) / self.cell))
        return (ix, iz) if 0 <= ix < self.nx and 0 <= iz < self.nz else None

    def center(self, c: int) -> tuple[float, float]:
        return self.x0 + (c % self.nx + 0.5) * self.cell, self.z0 + (c // self.nx + 0.5) * self.cell

    def layers_at(self, x: float, z: float) -> list[tuple[float, str]]:
        """[(floor height, state name)] of the cell under (x, z), lowest first."""
        cz = self.cell_of(x, z)
        if cz is None:
            return []
        c = cz[1] * self.nx + cz[0]
        f = self.first[c]
        return [(float(self.lh[k]), STATE_NAMES[int(self.ls[k])]) for k in range(f, f + self.count[c])]

    def node_at(self, x: float, z: float, y: float | None = None, radius: int = 4, tol: float = 1200.0) -> int | None:
        """The walkable layer (index) for a position: its own cell first, then rings out to `radius` cells. With y,
        layers within tol of that height (the nearest wins); without y, the lowest storey. Reachable layers first."""
        ix, iz = int(math.floor((x - self.x0) / self.cell)), int(math.floor((z - self.z0) / self.cell))
        if not (-radius <= ix < self.nx + radius and -radius <= iz < self.nz + radius):
            return None
        for t in ((tol, math.inf) if y is not None else (math.inf,)):
            for r in range(radius + 1):
                best = None
                for jz in range(iz - r, iz + r + 1):
                    for jx in range(ix - r, ix + r + 1):
                        if max(abs(jx - ix), abs(jz - iz)) != r or not (0 <= jx < self.nx and 0 <= jz < self.nz):
                            continue
                        c = jz * self.nx + jx
                        for k in range(self.first[c], self.first[c] + self.count[c]):
                            h = float(self.lh[k])
                            if self.ls[k] not in (FREE, NEAR) or (y is not None and abs(h - y) > t):
                                continue
                            key = (2 - int(self.lr[k]), abs(h - y) if y is not None else h,
                                   (jx - ix) ** 2 + (jz - iz) ** 2, int(self.ls[k]))
                            if best is None or key < best[0]:
                                best = (key, k)
                if best is not None:
                    return int(best[1])
        return None

    def state_at(self, x: float, z: float, y: float | None = None) -> str:
        """State of the floor layer under (x, z) nearest y (the lowest without y): free, near (a wall), vault, wall,
        or void (no floor)."""
        cz = self.cell_of(x, z)
        if cz is None:
            return "void"
        c = cz[1] * self.nx + cz[0]
        ks = range(self.first[c], self.first[c] + self.count[c])
        if not ks:
            return "void"
        k = min(ks, key=lambda k: abs(self.lh[k] - y) if y is not None else self.lh[k])
        return STATE_NAMES[int(self.ls[k])]

    def top_view(self) -> tuple[np.ndarray, np.ndarray]:
        """(state, height) per cell of the highest layer, shape (nz, nx): what a camera above the level sees."""
        st = np.zeros(self.nx * self.nz, np.int8)
        hh = np.full(self.nx * self.nz, np.nan)
        cells = np.nonzero(self.count)[0]
        top = self.first[cells] + self.count[cells] - 1     # layers are sorted by height within a cell
        st[cells], hh[cells] = self.ls[top], self.lh[top]
        return st.reshape(self.nz, self.nx), hh.reshape(self.nz, self.nx)

    # ---- encoding
    def to_json(self) -> dict:
        def pack(a, dt):
            return base64.b64encode(zlib.compress(np.asarray(a).astype(dt).tobytes(), 9)).decode()
        return {"x0": self.x0, "z0": self.z0, "nx": self.nx, "nz": self.nz, "cell": self.cell,
                "layers": len(self.lc),
                "encoding": "zlib+base64 little-endian: cell int32 (iz * nx + ix), height int16, state int8 "
                            "(1 free, 2 near a wall, 3 vault, 4 wall), reach int8 (2 there and back, 1 one way, 0 no)",
                "cell_index": pack(self.lc, "<i4"), "height": pack(np.round(self.lh), "<i2"),
                "state": pack(self.ls, "<i1"), "reach": pack(self.lr, "<i1")}

    @classmethod
    def from_json(cls, d: dict) -> "NavGrid":
        def unpack(s, dt):
            return np.frombuffer(zlib.decompress(base64.b64decode(s)), dt)
        return cls(d["x0"], d["z0"], d["nx"], d["nz"], unpack(d["cell_index"], "<i4").astype(np.int64),
                   unpack(d["height"], "<i2").astype(np.float64), unpack(d["state"], "<i1"),
                   unpack(d["reach"], "<i1"), d.get("cell", CELL))

    # ---- graph (built once per grid, on first use)
    def _has_layer(self, cells: np.ndarray, h: np.ndarray, mask: np.ndarray, tol: float) -> np.ndarray:
        ok = np.zeros(len(cells), bool)
        valid = cells >= 0
        safe = np.where(valid, cells, 0)
        for k in range(int(self.count.max(initial=0))):
            sel = valid & (self.count[safe] > k)
            li = self.first[safe[sel]] + k
            ok[sel] |= mask[li] & (np.abs(self.lh[li] - h[sel]) <= tol)
        return ok

    def _neighbour_cells(self, dx: int, dz: int) -> np.ndarray:
        ix, iz = self.lc % self.nx + dx, self.lc // self.nx + dz
        inb = (ix >= 0) & (ix < self.nx) & (iz >= 0) & (iz < self.nz)
        return np.where(inb, iz * self.nx + ix, -1)

    def edges(self, links: list | None = None) -> dict:
        """CSR adjacency over layers: walk / vault / drop moves to the 8 neighbours, plus ladder links."""
        L, K = len(self.lc), int(self.count.max(initial=0))
        notwall = self.ls != WALL
        us, vs, cs, ks = [], [], [], []
        for dx, dz in DIRS:
            nc = self._neighbour_cells(dx, dz)
            diag = dx != 0 and dz != 0
            src = notwall & (nc >= 0)
            if diag:                                     # no corner cutting past a wall
                src &= self._has_layer(self._neighbour_cells(dx, 0), self.lh, notwall, STEP)
                src &= self._has_layer(self._neighbour_cells(0, dz), self.lh, notwall, STEP)
            safe = np.where(nc >= 0, nc, 0)
            for k in range(K):
                sel = src & (self.count[safe] > k)
                u = np.nonzero(sel)[0]
                v = self.first[nc[sel]] + k
                su, sv, dh = self.ls[u], self.ls[v], self.lh[v] - self.lh[u]
                vault = (su == VAULT) | (sv == VAULT)
                ok = (sv != WALL) & np.where(vault, (dh <= STEP) & (dh >= -DROP_MAX), np.abs(dh) <= STEP)
                u, v, su, sv, dh = u[ok], v[ok], su[ok], sv[ok], dh[ok]
                mult = np.where(sv == NEAR, NEAR_COST, np.where(sv == VAULT, 2.0, 1.0))
                kind = np.where((sv == VAULT) & (su != VAULT), E_VAULT, np.where(dh < -STEP, E_DROP, E_WALK))
                us.append(u)
                vs.append(v)
                cs.append(self.cell * (math.sqrt(2) if diag else 1.0) * mult + np.where(dh < -STEP, -dh, 0.0))
                ks.append(kind)
        for a, b, cost in links or []:
            for s, t in ((a, b), (b, a)):
                us.append(np.array([s]))
                vs.append(np.array([t]))
                cs.append(np.array([float(cost)]))
                ks.append(np.array([E_LADDER]))
        u = np.concatenate(us) if us else np.zeros(0, np.int64)
        order = np.argsort(u, kind="stable")
        indptr = np.searchsorted(u[order], np.arange(L + 1))
        return {"indptr": indptr, "to": np.concatenate(vs)[order] if us else u,
                "cost": np.concatenate(cs)[order] if us else np.zeros(0), "kind": np.concatenate(ks)[order]
                if us else u, "n": L}


def _as_lists(E: dict) -> dict:
    """The planner walks plain lists (much faster per element than numpy scalars)."""
    return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in E.items()}


# ================================================================ building a stage from the collision

def _floor_samples(V, tris, x0, z0, nx, nz, cell, sub=3):
    """(cell index, height) of every sub-sample point (sub x sub per cell) covered by a floor triangle."""
    offs = (np.arange(sub) + 0.5) / sub
    cells, ys = [], []
    for a, b, c in tris:
        P = V[[a, b, c]]
        (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = P
        det = (z2 - z3) * (x1 - x3) + (x3 - x2) * (z1 - z3)
        if abs(det) < 1e-6:
            continue
        ix0 = max(0, int(math.floor((P[:, 0].min() - x0) / cell)))
        ix1 = min(nx - 1, int(math.floor((P[:, 0].max() - x0) / cell)))
        iz0 = max(0, int(math.floor((P[:, 2].min() - z0) / cell)))
        iz1 = min(nz - 1, int(math.floor((P[:, 2].max() - z0) / cell)))
        if ix0 > ix1 or iz0 > iz1:
            continue
        gx = (np.arange(ix0, ix1 + 1)[:, None] + offs[None, :]).ravel()
        X = x0 + gx * cell
        for r0 in range(iz0, iz1 + 1, 128):              # row blocks keep the giant ground triangles small
            r1 = min(iz1, r0 + 127)
            gz = (np.arange(r0, r1 + 1)[:, None] + offs[None, :]).ravel()
            XX, ZZ = np.meshgrid(X, z0 + gz * cell)
            l1 = ((z2 - z3) * (XX - x3) + (x3 - x2) * (ZZ - z3)) / det
            l2 = ((z3 - z1) * (XX - x3) + (x1 - x3) * (ZZ - z3)) / det
            l3 = 1.0 - l1 - l2
            inside = (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
            if not inside.any():
                continue
            rz, rx = np.nonzero(inside)
            cells.append((r0 + rz // sub) * nx + (ix0 + rx // sub))
            ys.append((l1 * y1 + l2 * y2 + l3 * y3)[inside])
    if not cells:
        return np.zeros(0, np.int64), np.zeros(0)
    return np.concatenate(cells), np.concatenate(ys)


def _surface_samples(V, tris, step=CELL / 4):
    """Points covering each triangle (3D) about `step` apart -> (points (n,3), triangle index (n,))."""
    pts, idx = [], []
    for t, (a, b, c) in enumerate(tris):
        A, B, C = V[a], V[b], V[c]
        nu = max(2, int(math.ceil(np.linalg.norm(B - A) / step)) + 1)
        nv = max(2, int(math.ceil(np.linalg.norm(C - A) / step)) + 1)
        U, W = np.meshgrid(np.linspace(0, 1, nu), np.linspace(0, 1, nv), indexing="ij")
        m = U + W <= 1 + 1e-9
        p = A + U[m][:, None] * (B - A) + W[m][:, None] * (C - A)
        pts.append(p)
        idx.append(np.full(len(p), t))
    if not pts:
        return np.zeros((0, 3)), np.zeros(0, np.int64)
    return np.concatenate(pts), np.concatenate(idx)


def build_grid(col: dict, cell: float = CELL, bounds=None) -> NavGrid:
    """SAT collision -> NavGrid (all layers, states classified; reach not yet known)."""
    V, T, N, attr = col["verts"], col["tris"], col["normals"], col["attr"]
    ny = N[:, 1]
    floor = ny >= 0.7
    if bounds is None:
        fv = V[np.unique(T[floor])]
        bounds = (fv[:, 0].min(), fv[:, 0].max(), fv[:, 2].min(), fv[:, 2].max())
    x0 = math.floor(bounds[0] / cell) * cell
    z0 = math.floor(bounds[2] / cell) * cell
    nx = int(math.ceil((bounds[1] - x0) / cell)) + 1
    nz = int(math.ceil((bounds[3] - z0) / cell)) + 1
    # floors -> layers (cluster each cell's samples by height)
    fc, fy = _floor_samples(V, T[floor], x0, z0, nx, nz, cell)
    order = np.lexsort((fy, fc))
    fc, fy = fc[order], fy[order]
    brk = np.ones(len(fc), bool)
    brk[1:] = (fc[1:] != fc[:-1]) | (fy[1:] - fy[:-1] > LAYER_GAP)
    lc = fc[brk]
    lh = np.maximum.reduceat(fy, np.nonzero(brk)[0])       # a storey stands on the top of its samples
    g = NavGrid(x0, z0, nx, nz, lc, lh, np.full(len(lc), FREE, np.int8), cell=cell)
    # a floor with another floor less than CLEAR above it has no headroom: r400 has a catch-all y=0 plane under
    # the whole map, also under the hills, that must not become a tunnel
    above = np.zeros(len(g.lc), bool)
    same = g.lc[1:] == g.lc[:-1]
    above[:-1] = same & (g.lh[1:] - g.lh[:-1] < CLEAR)
    # walls / ceilings / steep slopes -> which layers they block
    wall = ~floor
    wp, wt = _surface_samples(V, T[wall])
    wattr = attr[wall][wt]
    ceiling = ny[wall][wt] <= -0.3
    ix = np.floor((wp[:, 0] - x0) / cell).astype(np.int64)
    iz = np.floor((wp[:, 2] - z0) / cell).astype(np.int64)
    inb = (ix >= 0) & (ix < nx) & (iz >= 0) & (iz < nz)
    wc, wy = iz[inb] * nx + ix[inb], wp[inb, 1]
    wattr, ceiling = wattr[inb], ceiling[inb]
    jump = ((wattr & VAULT_BITS) != 0) & ~ceiling
    inv = ((wattr & BLOCKER_BIT) != 0) & ~jump
    solid = ~jump & ~inv
    L = len(g.lc)
    has_solid, has_jump, has_inv = np.zeros(L, bool), np.zeros(L, bool), np.zeros(L, bool)
    jump_top = np.full(L, -np.inf)
    for k in range(int(g.count.max(initial=0))):
        sel = g.count[wc] > k
        li = g.first[wc[sel]] + k
        F, y = g.lh[li], wy[sel]
        band = (y > F + STEP) & (y < F + CLEAR)
        has_solid[li[band & solid[sel]]] = True
        has_inv[li[band & inv[sel]]] = True
        jb = band & jump[sel]
        has_jump[li[jb]] = True
        np.maximum.at(jump_top, li[jb], y[jb] - F[jb])
    vault = has_jump & ~has_solid & (jump_top <= VAULT_TOP) & ~above
    blocked = has_solid | (has_jump & ~vault) | (has_inv & ~has_jump) | above
    ls = np.full(L, FREE, np.int8)
    ls[vault] = VAULT
    ls[blocked] = WALL
    g.ls = ls
    # free layers next to a wall or an edge get a cost (keeps paths off the walls)
    passable = (ls == FREE) | (ls == VAULT)
    near = np.zeros(L, bool)
    for dx, dz in DIRS:
        near |= ~g._has_layer(g._neighbour_cells(dx, dz), g.lh, passable, STEP)
    g.ls[(ls == FREE) & near] = NEAR
    return g


def _ladder_links(g: NavGrid, events: list[dict]) -> list[tuple[int, int, float]]:
    out = []
    for e in events:
        if e.get("kind") != "ladder":
            continue
        a = g.node_at(e["pos"][0], e["pos"][2], e["pos"][1], radius=3)
        b = g.node_at(e["top"][0], e["top"][2], e["top"][1], radius=6)
        if a is not None and b is not None and abs(g.lh[b] - g.lh[a]) > STEP:
            out.append((a, b, abs(float(g.lh[b] - g.lh[a]))))
    return out


def _flood(n: int, ip: list, to: list, seeds) -> np.ndarray:
    seen = np.zeros(n, bool)
    stack = [s for s in seeds if s is not None]
    seen[stack] = True
    while stack:
        u = stack.pop()
        for j in range(ip[u], ip[u + 1]):
            v = to[j]
            if not seen[v]:
                seen[v] = True
                stack.append(v)
    return seen


def _reach(E: dict, seed: int) -> np.ndarray:
    """Per layer: 2 = there and back from seed (the playable area), 1 = one way only (a drop with no way back),
    0 = not reachable."""
    n = E["n"]
    fwd = _flood(n, E["indptr"].tolist(), E["to"].tolist(), [seed])
    frm = np.repeat(np.arange(n), np.diff(E["indptr"]))
    order = np.argsort(E["to"], kind="stable")
    rip = np.searchsorted(E["to"][order], np.arange(n + 1))
    back = _flood(n, rip.tolist(), frm[order].tolist(), [seed])
    return np.where(fwd & back, 2, np.where(fwd, 1, 0)).astype(np.int8)


def rtp_read(b: bytes) -> dict:
    """RTP (enemy route graph): '2RTP', u32 #nodes, u32, u32 node table, u32 link table, u32 next-hop matrix; nodes
    are f32 x y z + u16 first link + u16 link count, links u16 node + u16 distance / 10."""
    if b[:4] != b"2RTP":
        raise ValueError("not an RTP route table")
    n, _u, no, lo = struct.unpack_from(">IIII", b, 4)
    nodes, links = [], set()
    for i in range(n):
        x, y, z = struct.unpack_from(">3f", b, no + 16 * i)
        f, c = struct.unpack_from(">HH", b, no + 16 * i + 12)
        nodes.append(_r((x, y, z)))
        for k in range(c):
            j = struct.unpack_from(">H", b, lo + 4 * (f + k))[0]
            if j < n:
                links.add((min(i, j), max(i, j)))
    return {"nodes": nodes, "links": sorted(links)}


def _stands(g: NavGrid, events: list[dict], reach: np.ndarray, pickup: float = 900.0):
    """Where Leon stands to take each hourglass: inside its action zone when it has one (the zone's height band),
    else floor within `pickup` of the item and not far below or above it. Sets e["stand"] and e["reachable"]."""
    ok = (reach == 2) & ((g.ls == FREE) | (g.ls == NEAR))
    cx = g.x0 + (g.lc % g.nx + 0.5) * g.cell
    cz = g.z0 + (g.lc // g.nx + 0.5) * g.cell
    for e in events:
        if e["kind"] not in ("time_bonus", "combo_bonus"):
            continue
        x, y, z = e["pos"]
        zone = e.get("zone")
        if zone:
            ylo, yhi = zone["y"]
            box = ok & (g.lh >= ylo - STEP) & (g.lh <= yhi)
            idx = [k for k in np.nonzero(box)[0] if _in_poly(cx[k], cz[k], [tuple(p) for p in zone["poly"]])]
        else:
            d2 = (cx - x) ** 2 + (cz - z) ** 2
            idx = np.nonzero(ok & (d2 <= pickup ** 2) & (g.lh >= y - CLEAR) & (g.lh <= y + STEP))[0].tolist()
        if idx:
            k = min(idx, key=lambda k: ((cx[k] - x) ** 2 + (cz[k] - z) ** 2, g.ls[k]))
            e["stand"], e["reachable"] = _r((cx[k], g.lh[k], cz[k])), True
        else:
            e["stand"], e["reachable"] = None, False


def _wall_segments(col: dict) -> list[list]:
    """Steep collision triangles as top-down segments [x0, z0, x1, z1, y_low, y_high, attr] (the two vertices that
    are furthest apart in x/z) - enough for line-of-sight tests and drawing."""
    V, T, N, A = col["verts"], col["tris"], col["normals"], col["attr"]
    out = []
    for t in np.nonzero(np.abs(N[:, 1]) < 0.7)[0]:
        P = V[T[t]]
        pairs = [(0, 1), (1, 2), (0, 2)]
        i, j = max(pairs, key=lambda q: (P[q[0], 0] - P[q[1], 0]) ** 2 + (P[q[0], 2] - P[q[1], 2]) ** 2)
        out.append([*_r((P[i, 0], P[i, 2], P[j, 0], P[j, 2], P[:, 1].min(), P[:, 1].max())), int(A[t] & 0x1FFFFFFF)])
    return out


def extract(disc_path, room: str = "r400", cell: float = CELL, log=None) -> dict:
    """The disc (ISO or GCZ, read only) -> the stage JSON for one room."""
    from .gcdisc import GCDisc
    log = log or (lambda *a: None)
    r = int(room.lstrip("rR"), 16)
    disc = GCDisc(disc_path)
    if disc.game_id != DISC_ID:
        raise ValueError(f"{disc_path}: disc id {disc.game_id}, expected {DISC_ID} (RE4 GC USA disc 1)")
    name = next((n for n in disc.files if n.lower() == f"st{r >> 8:x}/r{r:03x}.das"), None)
    if name is None:
        raise ValueError(f"r{r:03x}.das is not on this disc")
    das = disc.read(name)
    t0 = time.time()
    files = room_files(das)
    log(f"{name}: {len(files)} room files unpacked in {time.time() - t0:.1f} s")
    esl = {n: disc.read(n) for n in sorted(k for k in disc.files if k.startswith("etc/") and k.endswith(".esl"))}
    src = {"room_file": name, "room_sha256": hashlib.sha256(das).hexdigest()}
    return build_stage(files, esl, f"r{r:03x}", cell, src, log)


def build_stage(files: list[tuple[str, bytes]], esl: dict[str, bytes], room: str = "r400", cell: float = CELL,
                source: dict | None = None, log=None) -> dict:
    """Unpacked room files [(ext, bytes)] + the disc's ESL files {name: bytes} -> the stage JSON."""
    log = log or (lambda *a: None)
    r = int(room.lstrip("rR"), 16)
    first = {}
    for ext, b in files:
        first.setdefault(ext, b)
    for need in ("SAT", "AEV", "ITA"):
        if need not in first:
            raise ValueError(f"r{r:03x}: room DAT has no {need}")
    col = sat_read(first["SAT"])
    aev, ita = events_read(first["AEV"], b"AEV\0"), events_read(first["ITA"], b"ITA\0")
    spawns, esl_name = [], None
    for n, b in sorted(esl.items()):
        got = esl_read(b, r)
        if got:
            spawns, esl_name = got, n
            break
    for s in spawns:
        s["name"] = EM_NAMES.get(s["em"], f"em{s['em']:02x}")
    events = room_events(aev, ita)
    t0 = time.time()
    g = build_grid(col, cell)
    log(f"grid {g.nx} x {g.nz}, {len(g.lc)} layers in {time.time() - t0:.1f} s")
    links = _ladder_links(g, events)
    E = g.edges(links)
    # the playable area: what a central spawn can walk to and back from (try a few, keep the one that holds the
    # most spawns; r400 also has floor outside the village walls, e.g. under ITA[34], that is not playable)
    nodes = [(g.node_at(s["pos"][0], s["pos"][2], s["pos"][1]), s) for s in spawns]
    nodes = [(k, s) for k, s in nodes if k is not None]
    if nodes:
        mx = sum(s["pos"][0] for _, s in nodes) / len(nodes)
        mz = sum(s["pos"][2] for _, s in nodes) / len(nodes)
        nodes.sort(key=lambda ks: (ks[1]["pos"][0] - mx) ** 2 + (ks[1]["pos"][2] - mz) ** 2)
        tries = [k for k, _ in nodes[:3]]
    else:
        tries = [k for k in (g.node_at(e["pos"][0], e["pos"][2], e["pos"][1]) for e in events) if k is not None][:1]
    if not tries:
        raise ValueError(f"r{r:03x}: no spawn or event stands on walkable floor - collision not understood")
    reach, held = None, -1
    for k in tries:
        rr = _reach(E, k)
        n_in = sum(rr[j] == 2 for j, _ in nodes)
        if n_in > held:
            reach, held = rr, n_in
        if 2 * held > len(nodes):
            break
    # crop to the reachable part (+ a margin of walls) so the cache stays small
    rc = g.lc[reach > 0]
    ixs, izs = rc % g.nx, rc // g.nx
    m = 3
    ax0, ax1 = max(0, ixs.min() - m), min(g.nx - 1, ixs.max() + m)
    az0, az1 = max(0, izs.min() - m), min(g.nz - 1, izs.max() + m)
    cx, cz = g.lc % g.nx, g.lc // g.nx
    keep = (cx >= ax0) & (cx <= ax1) & (cz >= az0) & (cz <= az1)
    ncx = ax1 - ax0 + 1
    crop = NavGrid(g.x0 + ax0 * cell, g.z0 + az0 * cell, ncx, az1 - az0 + 1,
                   (cz[keep] - az0) * ncx + (cx[keep] - ax0), g.lh[keep], g.ls[keep], reach[keep], cell)
    _stands(crop, events, crop.lr)
    for s in spawns:
        k = crop.node_at(s["pos"][0], s["pos"][2], s["pos"][1])
        s["reachable"] = bool(k is not None and crop.lr[k] == 2)
    log(f"playable area {int((crop.lr == 2).sum())} layers; {sum(s['reachable'] for s in spawns)}/{len(spawns)} "
        f"spawns and {sum(bool(e.get('reachable')) for e in events)} hourglasses in it")
    walk = crop.lc[(crop.lr == 2) & (crop.ls != WALL)]
    wx = crop.x0 + (walk % crop.nx + 0.5) * cell
    wz = crop.z0 + (walk // crop.nx + 0.5) * cell
    return {
        "format": FORMAT, "game_id": GAME_ID, "disc_id": DISC_ID, "room": f"r{r:03x}",
        "source": {**(source or {}), "esl_file": esl_name, "room_dat": [ext for ext, _ in files],
                   "generated": time.strftime("%Y-%m-%d"),
                   "regenerate": f"python -m gbox.re4_navmap --iso <disc> --room r{r:03x} --out <json>"},
        "units": "RE4 world units (mm), y up, [x, y, z] like Leon's player+0x94 floats",
        "params": {"cell": cell, "step": STEP, "clear": CLEAR, "vault_top": VAULT_TOP, "drop_max": DROP_MAX,
                   "vault_bits": VAULT_BITS, "blocker_bit": BLOCKER_BIT},
        "bounds": {"x": _r((wx.min() - cell / 2, wx.max() + cell / 2), 0),
                   "z": _r((wz.min() - cell / 2, wz.max() + cell / 2), 0),
                   "y": _r((crop.lh[crop.lr == 2].min(), crop.lh[crop.lr == 2].max()), 0)},
        "collision": {"verts": len(col["verts"]), "tris": len(col["tris"]),
                      "floor_tris": int((col["normals"][:, 1] >= 0.7).sum()),
                      "vault_tris": int(((col["attr"] & VAULT_BITS) != 0).sum())},
        "grid": crop.to_json(),
        "walls": _wall_segments(col),
        "events": events,
        "spawns": spawns,
        "routes": _routes(first.get("RTP")),
    }


def _routes(b: bytes | None) -> dict | None:
    try:
        return rtp_read(b) if b else None
    except (ValueError, struct.error):
        return None                                     # the enemy route graph is extra information only


# ================================================================ loading + planning

class Waypoint(NamedTuple):
    x: float
    y: float
    z: float
    action: str | None = None        # None run there, "vault" jump over / through (press A), "ladder" climb


class Stage(dict):
    """A loaded stage: the JSON keys (room, grid -> NavGrid, events, spawns, bounds, walls, ...) plus
    st["hourglasses"] (time_bonus + combo_bonus events) and the planner's graph (built on first use)."""

    def __init__(self, d: dict):
        super().__init__(d)
        self["grid"] = d["grid"] if isinstance(d["grid"], NavGrid) else NavGrid.from_json(d["grid"])
        self["hourglasses"] = [e for e in self["events"] if e["kind"] in ("time_bonus", "combo_bonus")]
        self._graph = None
        self._walls = None

    @property
    def graph(self) -> dict:
        if self._graph is None:
            g = self["grid"]
            G = _as_lists(g.edges(_ladder_links(g, self["events"])))
            G.update(lc=g.lc.tolist(), lh=g.lh.tolist(), ls=g.ls.tolist(), first=g.first.tolist(),
                     count=g.count.tolist())
            self._graph = G
        return self._graph


_CACHE: dict = {}


def stage_path(room: str = "r400") -> Path:
    env = os.environ.get("GBOX_RE4_NAVMAP_DIR")
    for d in ([Path(env)] if env else []) + [DATA_DIR]:
        p = d / f"re4_{room.lower()}_navmap.json"
        if p.is_file():
            return p
    return DATA_DIR / f"re4_{room.lower()}_navmap.json"


def stage(room: str = "r400", path=None) -> Stage:
    """The cached navigation map of a room (no disc needed): {grid, events, spawns, bounds, walls, hourglasses}."""
    p = Path(path) if path else stage_path(room)
    key = (str(p), p.stat().st_mtime)
    if key not in _CACHE:
        d = json.loads(p.read_text())
        if d.get("format") != FORMAT:
            raise ValueError(f"{p}: not a {FORMAT} stage")
        for old in [k for k in _CACHE if k[0] == key[0]]:
            del _CACHE[old]
        _CACHE[key] = Stage(d)
    return _CACHE[key]


def _xyz(p) -> tuple[float, float | None, float]:
    """(x, y|None, z) of (x, z), (x, y, z) or an event / spawn dict (its "stand" point when it has one)."""
    if isinstance(p, dict):
        p = p.get("stand") or p["pos"]
    return (float(p[0]), None, float(p[1])) if len(p) == 2 else (float(p[0]), float(p[1]), float(p[2]))


def _node(g: NavGrid, p) -> int | None:
    if isinstance(p, dict) and p.get("reachable") is False:
        return None                                      # an event nobody can stand at (see its "stand")
    x, y, z = _xyz(p)
    return g.node_at(x, z, y)


def _search(st: Stage, src: int, goals: set, vault_cost: float, ladder_cost: float, goal_xz=None, full=False):
    """A* (goal_xz given) or Dijkstra from src. Returns (dist dict, parent dict, reached goal or None)."""
    G, g = st.graph, st["grid"]
    ip, to, cost, kind, lc = G["indptr"], G["to"], G["cost"], G["kind"], G["lc"]
    extra = (0.0, vault_cost, 0.0, ladder_cost)
    nx, cell, inf = g.nx, g.cell, math.inf
    gx, gz = goal_xz if goal_xz is not None else (0, 0)
    astar = goal_xz is not None
    dist, parent = [inf] * G["n"], {src: None}
    dist[src] = 0.0
    heap = [(0.0, 0.0, src)]
    left = set(goals)
    while heap:
        _, d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        if u in left:
            left.discard(u)
            if not left and not full:
                return dist, parent, u
        for j in range(ip[u], ip[u + 1]):
            v = to[j]
            nd = d + cost[j] + extra[kind[j]]
            if nd < dist[v]:
                dist[v], parent[v] = nd, (u, kind[j])
                if astar:                                    # octile distance to the goal cell
                    c = lc[v]
                    dx, dz = abs(c % nx - gx), abs(c // nx - gz)
                    heapq.heappush(heap, (nd + cell * (max(dx, dz) + 0.41421356 * min(dx, dz)), nd, v))
                else:
                    heapq.heappush(heap, (nd, nd, v))
    return dist, parent, None


def _los(G: dict, nx: int, a: int, b: int) -> bool:
    """A straight run from layer a to layer b over free cells without big steps (the segment between the cell
    centres, sampled every quarter cell)."""
    lc, lh, ls, first, count = G["lc"], G["lh"], G["ls"], G["first"], G["count"]
    ca, cb = lc[a], lc[b]
    ax, az, bx, bz = ca % nx + 0.5, ca // nx + 0.5, cb % nx + 0.5, cb // nx + 0.5
    n = int(max(abs(bx - ax), abs(bz - az)) * 4) + 1
    h, cur = lh[a], ca
    for i in range(1, n + 1):
        t = i / n
        c = int(az + (bz - az) * t) * nx + int(ax + (bx - ax) * t)
        if c == cur:
            continue
        if c == cb:
            break
        best = None
        for k in range(first[c], first[c] + count[c]):
            if ls[k] == FREE and abs(lh[k] - h) <= STEP and (best is None or abs(lh[k] - h) < abs(lh[best] - h)):
                best = k
        if best is None:
            return False
        h, cur = lh[best], c
    return abs(lh[b] - h) <= STEP


def path(st: Stage, start, goal, vault_cost: float = VAULT_COST, ladder_cost: float = LADDER_COST,
         smooth: bool = True) -> list[Waypoint]:
    """Waypoints from start to goal ((x, z), (x, y, z) or an event dict): A* over the layered grid, 8-connected,
    fences / windows crossed at vault_cost, ladders at ladder_cost, then pulled to few straight runs. The start
    itself is not in the list; the last waypoint is the goal. [] when there is no way."""
    g, G = st["grid"], st.graph
    tx, _, tz = _xyz(goal)
    a, b = _node(g, start), _node(g, goal)
    if a is None or b is None:
        return []
    bc = int(g.lc[b])
    _, parent, got = _search(st, a, {b}, vault_cost, ladder_cost, goal_xz=(bc % g.nx, bc // g.nx))
    if got is None:
        return []
    nodes, kinds, u = [], [], b
    while u is not None:
        nodes.append(u)
        pu = parent[u]
        kinds.append(None if pu is None else pu[1])
        u = None if pu is None else pu[0]
    nodes.reverse()
    kinds.reverse()                                       # kinds[i] = how nodes[i] was entered
    wps: list[Waypoint] = []

    def wp(k, action=None):
        x, z = g.center(int(g.lc[k]))
        return Waypoint(round(x, 1), round(float(g.lh[k]), 1), round(z, 1), action)
    i, n = 0, len(nodes)
    while i < n - 1:
        j = i                                             # nodes[i..j]: a plain run (walk moves, no vault cells)
        while j + 1 < n and kinds[j + 1] == E_WALK and g.ls[nodes[j + 1]] != VAULT:
            j += 1
        k = i
        while k < j:                                      # string-pull the run to few straight legs
            nxt = k + 1
            if smooth:
                if _los(G, g.nx, nodes[k], nodes[j]):
                    nxt = j
                else:
                    while nxt < j and _los(G, g.nx, nodes[k], nodes[nxt + 1]):
                        nxt += 1
            wps.append(wp(nodes[nxt]))
            k = nxt
        if j >= n - 1:
            break
        if kinds[j + 1] == E_LADDER:                      # climb from the foot (last waypoint) to the top
            wps.append(wp(nodes[j + 1], "ladder"))
            i = j + 1
            continue
        m = j + 1                                         # cross the vault cells, land on the other side
        while m < n - 1 and g.ls[nodes[m]] == VAULT:
            m += 1
        wps.append(wp(nodes[m], "vault"))
        i = m
    if wps and wps[-1].action is None:
        wps[-1] = Waypoint(round(tx, 1), wps[-1].y, round(tz, 1), None)
    else:
        wps.append(Waypoint(round(tx, 1), round(float(g.lh[b]), 1), round(tz, 1), None))
    return wps


def path_length(wps: list[Waypoint], start=None) -> float:
    pts = ([(_xyz(start)[0], _xyz(start)[2])] if start is not None else []) + [(w.x, w.z) for w in wps]
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))


def tour(st: Stage, start, targets=None, vault_cost: float = VAULT_COST, ladder_cost: float = LADDER_COST,
         return_to_start: bool = False) -> list[int]:
    """Order to visit targets (default: st["hourglasses"]) from start: exact (Held-Karp) on path costs up to 10
    targets, nearest neighbour + 2-opt above. Returns indices into targets; unreachable ones are left out."""
    g = st["grid"]
    targets = st["hourglasses"] if targets is None else targets
    s = _node(g, start)
    tn = [_node(g, t) for t in targets]
    if s is None:
        return []
    srcs = [s] + tn
    goals = {k for k in tn if k is not None}
    D = [[math.inf] * len(srcs) for _ in srcs]
    for i, u in enumerate(srcs):
        if u is None:
            continue
        dist, _, _ = _search(st, u, goals | {s}, vault_cost, ladder_cost)
        for j, v in enumerate(srcs):
            if v is not None:
                D[i][j] = dist[v]
    idx = [i for i in range(len(targets)) if D[0][i + 1] < math.inf]
    n = len(idx)
    if n == 0:
        return []
    c = [[D[0][i + 1] for i in idx]] + [[D[a + 1][b + 1] for b in idx] for a in idx]   # row 0 = start
    back = [D[a + 1][0] for a in idx]
    if n <= 10:
        full = (1 << n) - 1
        best = {(1 << k, k): (c[0][k], -1) for k in range(n)}
        for mask in range(1, full + 1):
            for last in range(n):
                cur = best.get((mask, last))
                if cur is None:
                    continue
                for nxt in range(n):
                    if mask & (1 << nxt):
                        continue
                    key = (mask | (1 << nxt), nxt)
                    val = cur[0] + c[last + 1][nxt]
                    if val < best.get(key, (math.inf,))[0]:
                        best[key] = (val, last)
        last = min(range(n), key=lambda k: best.get((full, k), (math.inf,))[0] + (back[k] if return_to_start else 0))
        order, mask = [], full
        while last != -1:
            order.append(last)
            last, mask = best[(mask, last)][1], mask & ~(1 << last)
        order.reverse()
    else:
        order, left = [], set(range(n))
        cur = None
        while left:
            nxt = min(left, key=lambda k: c[0][k] if cur is None else c[cur + 1][k])
            order.append(nxt)
            left.discard(nxt)
            cur = nxt

        def length(o):
            return c[0][o[0]] + sum(c[a + 1][b] for a, b in zip(o, o[1:]))
        improved = True
        while improved:
            improved = False
            for i in range(n - 1):
                for j in range(i + 1, n):
                    o2 = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                    if length(o2) + 1e-6 < length(order):
                        order, improved = o2, True
    return [idx[k] for k in order]


def sight(st: Stage, a, b, see_through: bool = True) -> bool:
    """Does a straight ray from a to b ([x, y, z]) clear every wall of the room? see_through: fences / window
    openings (0x20 / 0x40 / 0x400 walls) let it pass, as they do for most of the game's rays."""
    if st._walls is None:
        w = np.asarray(st["walls"], np.float64).reshape(-1, 7)
        st._walls = w
    w = st._walls
    if see_through:
        w = w[(w[:, 6].astype(np.int64) & (VAULT_BITS | BLOCKER_BIT)) == 0]
    ax, ay, az = (float(v) for v in a)
    bx, by, bz = (float(v) for v in b)
    dx, dz = bx - ax, bz - az
    ex, ez = w[:, 2] - w[:, 0], w[:, 3] - w[:, 1]
    den = dx * ez - dz * ex
    ok = np.abs(den) > 1e-9
    den = np.where(ok, den, 1.0)
    t = ((w[:, 0] - ax) * ez - (w[:, 1] - az) * ex) / den
    s = ((w[:, 0] - ax) * dz - (w[:, 1] - az) * dx) / den
    y = ay + (by - ay) * t
    hit = ok & (t > 1e-6) & (t < 1 - 1e-6) & (s >= 0) & (s <= 1) & (y >= w[:, 4]) & (y <= w[:, 5])
    return not bool(hit.any())


# ================================================================ picture

def render(st: Stage, out: Path, sample: list[Waypoint] | None = None, sample_from=None, px: int = 4) -> Path:
    """Top-down PNG: floor shaded by height (highest storey), walls dark, vaults orange, hourglasses yellow
    (time) / gold-ringed (combo), spawns red, the ladder magenta, an optional path in cyan."""
    from PIL import Image, ImageDraw
    g = st["grid"]
    state, height = g.top_view()
    lo, hi = np.nanmin(height), np.nanmax(height)
    t = np.clip((np.nan_to_num(height, nan=lo) - lo) / max(hi - lo, 1.0), 0, 1)
    img = np.zeros((g.nz, g.nx, 3), np.uint8)
    img[:] = (24, 26, 32)
    for c0, c1, m in (((70, 110, 70), (205, 190, 150), (state == FREE) | (state == NEAR)),):
        for k in range(3):
            img[..., k] = np.where(m, (c0[k] + (c1[k] - c0[k]) * t).astype(np.uint8), img[..., k])
    reach = np.zeros(g.nx * g.nz, bool)
    reach[g.lc[g.lr == 2]] = True
    dim = ((state == FREE) | (state == NEAR)) & ~reach.reshape(g.nz, g.nx)
    img[dim] = (img[dim] * 0.45).astype(np.uint8)
    img[state == WALL] = (12, 12, 14)
    img[state == VAULT] = (255, 140, 0)
    im = Image.fromarray(img).resize((g.nx * px, g.nz * px), Image.NEAREST)
    dr = ImageDraw.Draw(im)

    def P(x, z):
        return ((x - g.x0) / g.cell * px, (z - g.z0) / g.cell * px)
    for wseg in st.get("walls", []):
        x0, z0, x1, z1, ylo, yhi, attr = wseg
        if attr & VAULT_BITS:
            dr.line([P(x0, z0), P(x1, z1)], fill=(255, 165, 0), width=2)
    for s in st.get("spawns", []):
        x, _, z = s["pos"]
        cx, cz = P(x, z)
        dr.ellipse([cx - 3, cz - 3, cx + 3, cz + 3], fill=(230, 30, 30))
    for e in st["events"]:
        x, _, z = e["pos"]
        cx, cz = P(x, z)
        if e["kind"] == "ladder":
            dr.rectangle([cx - 6, cz - 6, cx + 6, cz + 6], outline=(255, 0, 255), width=3)
            dr.text((cx + 9, cz - 6), "ladder", fill=(255, 0, 255))
        elif e["kind"] in ("time_bonus", "combo_bonus"):
            col = (255, 230, 0) if e.get("reachable", True) else (150, 140, 90)
            if e.get("stand"):
                dr.line([(cx, cz), P(e["stand"][0], e["stand"][2])], fill=col, width=1)
            dr.polygon([(cx, cz - 9), (cx + 8, cz), (cx, cz + 9), (cx - 8, cz)], fill=col, outline=(0, 0, 0))
            if not e.get("reachable", True):
                dr.line([(cx - 9, cz - 9), (cx + 9, cz + 9)], fill=(230, 30, 30), width=2)
                dr.line([(cx - 9, cz + 9), (cx + 9, cz - 9)], fill=(230, 30, 30), width=2)
            if e["kind"] == "combo_bonus":
                dr.ellipse([cx - 13, cz - 13, cx + 13, cz + 13], outline=(255, 230, 0), width=2)
            dr.text((cx + 12, cz - 7), f"+{e['seconds']}s" + (" combo" if e["kind"] == "combo_bonus" else ""),
                    fill=(255, 240, 120))
    if sample:
        pts = ([P(*_xz(sample_from))] if sample_from is not None else []) + [P(w.x, w.z) for w in sample]
        dr.line(pts, fill=(0, 230, 255), width=3)
        for w in sample:
            cx, cz = P(w.x, w.z)
            r = 5 if w.action else 3
            dr.ellipse([cx - r, cz - r, cx + r, cz + r], fill=(0, 230, 255) if not w.action else (255, 255, 255),
                       outline=(0, 90, 110))
        for (cx, cz), label in ((pts[0], "A"), (pts[-1], "B")):
            dr.rectangle([cx - 16, cz - 22, cx - 4, cz - 8], fill=(0, 0, 0))
            dr.text((cx - 13, cz - 21), label, fill=(0, 230, 255))
    hg = st.get("hourglasses", [])
    legend = [((70, 110, 70), "floor (low)"), ((205, 190, 150), "floor (high)"), ((35, 50, 35), "floor not reachable"),
              ((12, 12, 14), "wall"), ((255, 140, 0), "vault (JUMP OVER / window)"),
              ((255, 230, 0), "hourglass (ring = combo)"), ((150, 140, 90), "hourglass, X = not on foot"),
              ((230, 30, 30), "spawn"), ((255, 0, 255), "ladder"), ((0, 230, 255), "sample path A -> B"),
              ((255, 255, 255), "vault waypoint")]
    y = 8
    dr.rectangle([4, 4, 214, 30 + 16 * len(legend)], fill=(0, 0, 0))
    for col, label in legend:
        dr.rectangle([10, y + 2, 22, y + 12], fill=col)
        dr.text((28, y), label, fill=(235, 235, 235))
        y += 16
    dr.text((10, y + 2), f"{sum(e['kind'] == 'time_bonus' for e in hg)} time + "
                         f"{sum(e['kind'] == 'combo_bonus' for e in hg)} combo hourglasses, "
                         f"{len(st.get('spawns', []))} spawns", fill=(255, 240, 120))
    dr.text((8, im.height - 16), f"RE4 GC {st['room']} - {g.nx}x{g.nz} cells of {g.cell:.0f} units, x right, z down",
            fill=(220, 220, 220))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def _xz(p) -> tuple[float, float]:
    x, _, z = _xyz(p)
    return x, z


# ================================================================ command line

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RE4 GC room -> navigation map JSON (+ PNG)")
    ap.add_argument("--iso", type=Path, help="RE4 GC USA disc 1 image (.iso / .gcm / Dolphin .gcz), read only")
    ap.add_argument("--room", default="r400")
    ap.add_argument("--out", type=Path, help="stage JSON to write (default: profiles/gamedata/re4_<room>_navmap.json)")
    ap.add_argument("--stage", type=Path, help="render / inspect an existing stage JSON instead of reading a disc")
    ap.add_argument("--png", type=Path, help="write a top-down picture with a sample path between two hourglasses")
    a = ap.parse_args(argv)
    if a.iso:
        d = extract(a.iso, a.room, log=lambda m: print(m, file=sys.stderr))
        out = a.out or DATA_DIR / f"re4_{a.room.lower()}_navmap.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes((json.dumps(d, separators=(",", ":")) + "\n").encode())
        print(f"wrote {out} ({out.stat().st_size // 1024} KB)", file=sys.stderr)
        st = stage(path=out)
    elif a.stage:
        st = stage(path=a.stage)
    else:
        ap.error("--iso or --stage")
    hg = st["hourglasses"]
    for e in hg:
        print(f"{e['kind']:12s} {e['source']:8s} +{e['seconds']:3d}s at {e['pos']} stand {e.get('stand')} "
              f"reachable={e.get('reachable')}")
    if a.png:
        sample, frm = None, None
        ok = [e for e in hg if e.get("reachable")]
        runs = [(e, path(st, e, f)) for i, e in enumerate(ok) for f in ok[i + 1:]]
        runs = [(e, w) for e, w in runs if w]
        if runs:                                          # the longest one, preferring one that vaults
            frm, sample = max(runs, key=lambda r: (any(w.action == "vault" for w in r[1]), path_length(r[1], r[0])))
            print(f"sample path from {frm['source']}: {len(sample)} waypoints, {path_length(sample, frm):.0f} units, "
                  f"actions {[w.action for w in sample if w.action]}", file=sys.stderr)
        print(f"wrote {render(st, a.png, sample, frm)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
