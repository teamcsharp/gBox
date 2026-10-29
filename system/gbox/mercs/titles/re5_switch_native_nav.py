"""RE5 Switch native navigation mesh reader.

Ports the RE6 Switch rNavigationMesh discovery pattern (re6_switch.navmesh) to RE5
Switch, reusing the RE5 PS3 navmesh decoder (re5_nav.NavMesh) which already understands
the MT Framework triangle-mesh layout.

The RE5 Switch binary keeps its stage navmesh behind the same sAI -> cAIPathFinding ->
rNavigationMesh chain as the PS3 build, but the singleton's address is not yet mapped
(docs/research/re5-switch-ram.md has sMain / sPlayer / sEnemy / sUnit, not sAI).
This module therefore exposes two paths:

1. ``read(m, s_ai=...)`` -- decode through a caller-supplied sAI address (live discovery
   or a future RAM-map entry).
2. ``find_sai(m, base)`` -- scan main's statics for the sAI singleton by matching the
   cAIPathFinding -> rNavigationMesh -> plausible-record chain.

Until sAI is found the bot continues on the learned occupancy grid (re5_switch_nav).

Pointer model
-------------
Following re6_switch.navmesh, the navmesh record stores **32-bit** point/node pointers
and counts even on the 64-bit Switch build (the records live in a 32-bit-addressable
pool).  ``read()`` accepts a ``ptr_base`` argument that is added to every 32-bit
pointer to form the full guest address; when None it defaults to ``m.base``.
"""
from __future__ import annotations

import struct

from . import re5_nav

__all__ = ["NavMesh", "read", "find_sai", "navmesh_available", "get_navmesh"]

# RE5 Switch main-module offsets (relative to the NSO base) that are already mapped.
# sAI is not yet among them; when it is, drop it here and read() picks it up.
S_AI: int | None = None          # e.g. 0x1CFxxxx once measured

# The cAIPathFinding / rNavigationMesh field offsets are the PS3 ones; the Switch
# port kept the object layout (only the pointer size changed).
AI_PATHFINDING, PF_NAVMESH = 0x24, 0x14

# rNavigationMesh header offsets (PS3 layout; verified against RE6's Ghidra dump).
# The Switch record keeps 32-bit point/node pointers just like RE6 Switch.
NM_MAGIC = 0x80                   # 'NAV' v0x22 in RE6; RE5 PS3 does not expose a magic,
                                  # but the Switch port may -- checked opportunistically.
NM_POINTS, NM_NPOINTS = 0xA0, 0xA4
NM_NODES, NM_NNODES = 0xC0, 0xC4


def _u32(m, a) -> int:
    return struct.unpack("<I", m.rd(a, 4))[0]


def _u64(m, a) -> int:
    return struct.unpack("<Q", m.rd(a, 8))[0]


def _ok(p) -> bool:
    """A plausible heap pointer in the Switch emulator's address space."""
    return isinstance(p, int) and 0x1000000000 <= p < 0x8000000000


def navmesh_available() -> bool:
    """Whether a native sAI address is known for this build."""
    return S_AI is not None


# One-shot sAI discovery state: find_sai() scans main's statics, which is a
# few hundred thousand reads; do it once per process and cache the result.
_sai_scanned = False
_NAV_CACHE: dict = {}


def get_navmesh(m, base: int | None = None):
    """The stage's NavMesh via one-shot sAI discovery, or None.

    First call scans main's statics for the sAI singleton (bounded, cached);
    subsequent calls read through the discovered address.  Returns None when
    sAI is not found or the navmesh chain does not decode.
    """
    global S_AI, _sai_scanned
    if S_AI is None and not _sai_scanned:
        _sai_scanned = True
        try:
            S_AI = find_sai(m, base or getattr(m, "base", 0))
        except Exception:
            S_AI = None
    if S_AI is None:
        return None
    return read(m, cache=_NAV_CACHE, ptr_base=base)


def read(m, cache: dict | None = None, s_ai: int | None = None, ptr_base: int | None = None):
    """The stage's NavMesh from RAM, or None when sAI is unknown / between rounds.

    Uses the RE5 PS3 decoder (re5_nav.read) with a caller-supplied sAI address.
    The PS3 reader walks 32-bit pointers; on Switch the fields are 64-bit, so we
    do the chain walk here and hand the navmesh record to re5_nav's decoder with
    pre-fetched 32-bit-compatible addresses.
    """
    sai = s_ai if s_ai is not None else S_AI
    if sai is None or not _ok(sai):
        return None
    base = ptr_base if ptr_base is not None else getattr(m, "base", 0)
    try:
        # 64-bit chain: sAI + 0x24 -> cAIPathFinding, + 0x14 -> rNavigationMesh.
        # The PS3 offsets are byte offsets into the object, not pointer-size scaled,
        # so they hold on Switch as well.
        pf = _u64(m, sai + AI_PATHFINDING)
        if not _ok(pf):
            return None
        nav = _u64(m, pf + PF_NAVMESH)
        if not _ok(nav):
            return None
        return _read_switch_record(m, nav, cache, base)
    except (ValueError, OSError, struct.error):
        return None


def _read_switch_record(m, nav: int, cache: dict | None, base: int):
    """Decode a Switch rNavigationMesh record at *nav* into a re5_nav.NavMesh.

    The Switch record keeps 32-bit point/node pointers just like RE6 Switch
    (re6_switch.navmesh); *base* is added to each to form the full guest address.
    """
    pts, npts = _u32(m, nav + NM_POINTS), _u32(m, nav + NM_NPOINTS)
    nodes, nnodes = _u32(m, nav + NM_NODES), _u32(m, nav + NM_NNODES)
    pts_full, nodes_full = base + pts, base + nodes
    if not (0 < npts <= re5_nav.MAX_POINTS and 0 < nnodes <= re5_nav.MAX_NODES):
        if cache is not None:
            cache.clear()
        return None
    source = (pts, npts, nodes, nnodes)
    if cache is not None and nav in cache and getattr(cache[nav], "_source", None) == source:
        return cache[nav]
    raw = m.rd(pts_full, 16 * npts)
    points = [struct.unpack("<3f", raw[16 * i:16 * i + 12]) for i in range(npts)]
    raw = m.rd(nodes_full, re5_nav.NODE_SIZE * nnodes)
    tris, links = [], []
    for i in range(nnodes):
        rec = raw[re5_nav.NODE_SIZE * i:re5_nav.NODE_SIZE * (i + 1)]
        # Switch records keep the PS3 32-bit layout: vertex / link pointers are
        # 4-byte pool offsets, counts are 4 bytes.
        vptr, nv = struct.unpack_from("<II", rec, re5_nav.NODE_VERTS)
        lptr, nl = struct.unpack_from("<II", rec, re5_nav.NODE_LINKS)
        vs = struct.unpack_from("<3I", m.rd(base + vptr, 12)) if nv >= 3 else (0, 0, 0)
        tris.append(tuple(v if v < npts else 0 for v in vs))
        ls = []
        if 0 < nl <= 8:
            lr = m.rd(base + lptr, re5_nav.LINK_SIZE * nl)
            for k in range(nl):
                nb, _, edge, cost = struct.unpack_from("<IIIf", lr, re5_nav.LINK_SIZE * k)
                ls.append((nb, edge, cost))
        links.append(ls)
    mesh = re5_nav.NavMesh(points, tris, links, ptr=nav)
    mesh.__dict__["_source"] = source
    if cache is not None:
        cache.clear()
        cache[nav] = mesh
    return mesh


def find_sai(m, base: int, statics_lo: int = 0x1C00000, statics_hi: int = 0x2800000,
             stride: int = 8) -> int | None:
    """Scan main's statics for the sAI singleton by following the navmesh chain.

    Walks every 8-byte pointer in [base+statics_lo, base+statics_hi), treats each as a
    candidate sAI, and checks whether sAI+0x24 -> cAIPathFinding +0x14 -> rNavigationMesh
    yields a record whose points/nodes pointers and counts look like a real mesh.
    Returns the first candidate that decodes, or None.

    This is a bounded one-time scan (a few hundred thousand reads); call it once per
    boot and cache the result.
    """
    for off in range(statics_lo, statics_hi, stride):
        try:
            sai = _u64(m, base + off)
            if not _ok(sai):
                continue
            pf = _u64(m, sai + AI_PATHFINDING)
            if not _ok(pf):
                continue
            nav = _u64(m, pf + PF_NAVMESH)
            if not _ok(nav):
                continue
            pts = _u32(m, nav + NM_POINTS)
            npts = _u32(m, nav + NM_NPOINTS)
            nodes = _u32(m, nav + NM_NODES)
            nnodes = _u32(m, nav + NM_NNODES)
            if 0 < npts <= re5_nav.MAX_POINTS and 0 < nnodes <= re5_nav.MAX_NODES:
                return sai
        except (ValueError, OSError, struct.error):
            continue
    return None
