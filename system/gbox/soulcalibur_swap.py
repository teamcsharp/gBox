"""SoulCalibur (Dreamcast) native fighter writer: collection donors as SC fighters, every costume a native rebuild.

What gets rewritten (formats in gbox.soulcalibur_dc and docs/soulcalibur_dc.md):

* the costume's LZ model: the fighter's own bone records stay (rest pose, hierarchy, the motion skeleton 0..17 and the
  cloth / face bones), only their skin rows and the strip list are replaced by the donor's geometry, fitted onto the
  rest pose through the shared weighted retarget (gbox.doa2_weighted_retarget) with the 18 body roles of
  soulcalibur_dc.roles. Each donor vertex keeps up to four mapped influences, written the way the engine skins
  (soulcalibur_dc.engine_skin): rows hold the weight-premultiplied bone-local point, the lowest bone stores and the
  others add (bit 15), and each bone's stores are one run of consecutive slots. The tail after the strips (cloth / chain tables the bone records point at)
  keeps its offset: the new rows and strips must fit before it, and the vertex / normal counts stay within the
  fighter's own, so every buffer the game sized from the stock model still fits;
* the costume's texture pages: the donor's textures are packed into the 256x256 YUV422 pages (the face page, which
  the game animates for expressions, is left alone), UVs remapped into them;
* HUMAN.DAT: each rebuilt costume entry goes back into its own olnk slot (never bigger than the stock entry, so no
  other entry moves and the file keeps its size); the compressed model must fit the stock entry's room;
* weapons are not touched: the motion places each fighter's own weapon at the native hand bones, which the donor's
  hands are fitted to;
* 1ST_READ.BIN (optional, the random build): the HUMAN loader (0x8c02e37a) swaps the requested costume 0 / 1 for a
  random one (TMU0 counter bits) each time a fighter is loaded, through two unreachable alignment pads of the
  function (see patch_random_costume).

Builds are copied GD-ROM images (gdrom.patch_gdi); the source disc is never changed. Gameplay verification is
separate: every build is ``built_unverified`` until it has been played.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np

from . import soulcalibur_dc as D

GAME_IDS = D.GAME_IDS
REQUIRED_ROLES = {"hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                  "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}
MAX_INFLUENCES = 4
ROSTER = [k for _g, k, _n, _a in D.FIGHTERS]
# body size relative to the cast (cast_swap by_role): Astaroth and Rock are big, Xianghua / Taki / Seung Mina small
FIGHTER_SIZE = {"AST": 1.25, "ROC": 1.15, "NIG": 1.08, "SIE": 1.05, "LIZ": 1.05, "INF": 1.05, "EDG": 1.03,
                "MAX": 1.0, "MIT": 1.0, "HWA": 1.0, "CER": 1.0, "VOL": 1.0, "YOS": 1.0, "KIL": 0.97, "IVY": 0.97,
                "SOP": 0.95, "SEU": 0.95, "TAK": 0.93, "XIA": 0.9}


def writer_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in ("soulcalibur_swap", "soulcalibur_dc", "doa2_weighted_retarget", "retarget_profile", "gdrom"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name + ".py").read_bytes())
    return digest.hexdigest()


def fighter_slot(slot: str) -> tuple[str, int | None]:
    """'fighter:MIT', 'Mitsurugi:1', 'Sophitia' -> (key, costume or None)."""
    parts = slot.removeprefix("fighter:").split(":")
    if len(parts) > 2:
        raise ValueError("Use a fighter name or fighter:costume")
    q = parts[0].strip()
    if q.casefold() in {"", "player", "default"}:
        raise ValueError("SoulCalibur needs an explicit fighter (slot='fighter:MIT' or 'Mitsurugi:0')")
    _g, key, _n = D.fighter(q)
    costume = None
    if len(parts) == 2:
        if not parts[1].isdigit() or int(parts[1]) not in D.COSTUMES:
            raise ValueError("Costume must be 0..3")
        costume = int(parts[1])
    return key, costume


def group_of(key: str) -> int:
    return D.fighter(key)[0]


# ---------------------------------------------------------------- the native target

def target(model: dict) -> dict:
    """The fighter's rest skeleton as a retarget target (library frame: +Y up, facing +Z, left +X)."""
    sk = D.skin(model)
    F = D.FRAME
    T = np.array([W[:3, 3] for W in sk["world"]]) @ F.T
    rl = D.roles(model)
    P = sk["positions"] @ F.T
    head = rl["head"]
    head_rows = [i for i, inf in enumerate(sk["influences"]) if inf.get(head, 0) > 0.5]
    head_h = float(np.ptp(P[head_rows, 1])) if len(head_rows) > 3 else 0.25
    return {"T": T, "jmap": {r: j for r, j in rl.items() if r in REQUIRED_ROLES | {"neck", "l_clav", "r_clav"}},
            "ground": float(P[:, 1].min()), "head_h": head_h, "joints": len(T), "world": sk["world"],
            "parent": [b["parent"] for b in model["bones"]], "height": float(P[:, 1].max() - P[:, 1].min())}


# ---------------------------------------------------------------- textures: donor images -> free pages

def _solid(color) -> np.ndarray:
    c = np.array(color[:3] if color is not None else (200, 200, 200), np.uint8)
    return np.tile(c, (8, 8, 1))


def _rgb(img) -> np.ndarray:
    a = np.asarray(img)
    if a.ndim == 2:
        a = np.stack([a] * 3, -1)
    a = a[..., :3]
    if a.dtype != np.uint8:
        a = np.clip(a * (255 if a.max() <= 1.0 else 1), 0, 255).astype(np.uint8)
    return a


def _resize(a: np.ndarray, w: int, h: int) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.fromarray(a).resize((w, h), Image.BOX))      # area average / replication: no ringing


def atlas(prims: list[dict], pages: int) -> dict:
    """Pack the donor textures into `pages` 256x256 pages: {images: [rgb], slots: {texture key: (page, x, y, w, h)}}.
    Up to `pages` textures get a page each; more share a grid (k x k slots per page)."""
    keys, images = [], {}
    for p in prims:
        key = id(p["tex"]) if p.get("tex") is not None else ("solid", tuple(p.get("color") or (200, 200, 200)))
        p["_texkey"] = key
        if key not in images:
            keys.append(key)
            images[key] = _rgb(p["tex"]) if p.get("tex") is not None else _solid(p.get("color"))
    n = len(keys)
    if pages < 1:
        raise ValueError("no free texture page for the donor")
    # textures spread over the pages as evenly as possible; a page with c textures is a k x k grid (k a power of
    # two, k * k >= c); the biggest textures go to the pages that hold the fewest
    per = [n // pages + (1 if i < n % pages else 0) for i in range(pages)]
    per = [c for c in per if c] or [0]
    order = sorted(keys, key=lambda kk: -images[kk].shape[0] * images[kk].shape[1])
    out = [np.zeros((D.PAGE, D.PAGE, 3), np.uint8) for _ in range(len(per))]
    slots, grids, i = {}, [], 0
    for page, c in sorted(enumerate(per), key=lambda pc: pc[1]):
        k = 1
        while k * k < c:
            k *= 2
        grids.append(k)
        size = D.PAGE // k
        for cell in range(c):
            key = order[i]
            i += 1
            y, x = divmod(cell, k)
            out[page][y * size:(y + 1) * size, x * size:(x + 1) * size] = _resize(images[key], size, size)
            slots[key] = (page, x * size, y * size, size, size)
    return {"images": out, "slots": slots, "grid": max(grids), "textures": n}


def _bf16(x: np.ndarray) -> np.ndarray:
    """float -> the upper 16 bits of its float32 (round to nearest)."""
    b = np.asarray(x, np.float32).view(np.uint32).astype(np.uint64)
    return ((b + 0x8000) >> 16).astype(np.uint16)


def map_uv(uv: np.ndarray, slot: tuple) -> np.ndarray:
    """Donor UVs (one triangle's corners) -> page UVs inside the slot (wrapped into [0,1], half a texel inset)."""
    _page, x, y, w, h = slot
    u = np.asarray(uv, float)
    shift = np.floor(u.min(0))
    u = np.clip(u - shift, 0.0, 1.0)
    inset = 0.5 / max(w, 1)
    u = inset + u * (1 - 2 * inset)
    return np.stack([(x + u[:, 0] * w) / D.PAGE, (y + u[:, 1] * h) / D.PAGE], -1)


# ---------------------------------------------------------------- strips

def stripify(tris: list[tuple[int, int, int]]) -> list[list[int]]:
    """Triangles (outward winding as the game reads strip triangle k: even (k, k+1, k+2), odd (k+1, k, k+2)) ->
    greedy strips of at most 255 vertices; every triangle is kept with its winding."""
    edge: dict = {}
    for t, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            edge.setdefault(e, []).append(t)
    used = [False] * len(tris)

    def take(e):
        for t in edge.get(e, ()):
            if not used[t]:
                return t
        return None
    strips = []
    for t0 in range(len(tris)):
        if used[t0]:
            continue
        used[t0] = True
        a, b, c = tris[t0]
        best = None
        for s0 in ((a, b, c), (b, c, a), (c, a, b)):
            st, tk = list(s0), []
            while len(st) < 255:
                i = len(st) - 2                           # index of the next triangle in the strip
                # next triangle k=i: even -> (st[i], st[i+1], x), odd -> (st[i+1], st[i], x) outward
                e = (st[i], st[i + 1]) if i % 2 == 0 else (st[i + 1], st[i])
                t = take(e)
                if t is None:
                    break
                tri = tris[t]
                x = next((v for v in tri if v not in e), None)
                rot = [tri[j:] + tri[:j] for j in range(3)]
                if x is None or e + (x,) not in [tuple(r) for r in rot]:
                    break
                used[t] = True
                tk.append(t)
                st.append(x)
            if best is None or len(tk) > len(best[1]):
                if best:
                    for t in best[1]:
                        used[t] = False
                best = (st, tk)
            else:
                for t in tk:
                    used[t] = False
        for t in best[1]:
            used[t] = True
        strips.append(best[0])
    return strips


# ---------------------------------------------------------------- encode one costume model

class BudgetError(ValueError):
    """The donor does not fit the stock model's room (rows + strips, vertex counts or compressed size)."""


def _stock_gloss(model: dict) -> int:
    """The highlight byte (low byte of a normal row's z, read by 0x8c03ca9c) most of the stock rows carry."""
    counts: dict[int, int] = {}
    for b in model["bones"]:
        k = b["positions"]
        z = np.frombuffer(b["raw"], "<u4").reshape(-1, 4)[k:, 2]
        for v, c in zip(*np.unique(z & 0xFF, return_counts=True)):
            counts[int(v)] = counts.get(int(v), 0) + int(c)
    return max(counts, key=counts.get) if counts else 25


def _weight_words(inf: dict[int, float], store_bone: int, slot: int) -> dict[int, tuple[int, int]]:
    """{bone: (weight bits, add flag)} of one vertex. The engine uses the whole w word as the row's 4th component
    (slot and flag bits included), so the weights are rounded to the upper 16 bits and the storing bone's weight
    (bit 15 clear; bits 12..14, which the engine ignores, refine it) takes up the rest, so the effective weights sum
    to 1 within about 2^-11."""
    if slot & ~D.SLOT_MASK:
        raise ValueError(f"slot {slot} does not fit 12 bits")
    out, total = {}, 0.0
    for j, w in inf.items():
        if j == store_bone:
            continue
        bits = (int(np.float32(max(w, 0.0)).view(np.uint32)) + 0x8000) & D.WEIGHT_MASK
        out[j] = (bits, D.ADD_FLAG)
        total += D._w(bits | D.ADD_FLAG | slot)
    target = 1.0 - total
    base = int(np.float32(max(target, 1e-6)).view(np.uint32)) & D.WEIGHT_MASK
    best = min(((c & D.WEIGHT_MASK) | (k << 12) for c in (base - 0x10000, base, base + 0x10000) for k in range(8)),
               key=lambda bits: abs(D._w(bits | slot) - target))
    out[store_bone] = (best, 0)
    return out


def corner_normals(prims: list[dict], *, agree: float = 0.5) -> list[np.ndarray]:
    """Per-corner unit normals for the donor (library frame, outward): the smooth geometric normal of the fitted
    surface (area-weighted face normals of every prim, the counter-clockwise glTF winding taken as outward, welded by
    position so seams stay smooth), replaced by the donor's own normal where that one agrees with it (keeps authored
    creases). Some library donors carry normals unrelated to their faces (the SM64DS ones agree with their own
    triangles about half the time), which lit them in dark, blotchy patches in game."""
    def key(v):
        return tuple(np.round(v, 4))
    acc: dict = {}
    for p in prims:
        pos = np.asarray(p["pos"], float)
        t = np.asarray(p["tris"], int).reshape(-1, 3)
        if not len(t):
            continue
        f = np.cross(pos[t[:, 1]] - pos[t[:, 0]], pos[t[:, 2]] - pos[t[:, 0]])     # length = 2 x area
        for c in range(3):
            for v, n in zip(t[:, c], f):
                k = key(pos[v])
                acc[k] = acc.get(k, 0.0) + n
    out = []
    for p in prims:
        pos = np.asarray(p["pos"], float).reshape(-1, 3)
        g = np.array([acc.get(key(v), np.zeros(3)) for v in pos], float).reshape(-1, 3)
        gl = np.linalg.norm(g, axis=1, keepdims=True)
        g = np.where(gl > 1e-12, g / np.maximum(gl, 1e-12), 0.0)
        d = np.asarray(p["nrm"], float).reshape(-1, 3) if p.get("nrm") is not None else np.zeros_like(pos)
        dl = np.linalg.norm(d, axis=1, keepdims=True)
        d = np.where(dl > 1e-12, d / np.maximum(dl, 1e-12), 0.0)
        use_donor = ((d * g).sum(1) > agree) | (gl[:, 0] <= 1e-12)
        n = np.where(use_donor[:, None], d, g)
        n[np.linalg.norm(n, axis=1) < 0.5] = (0.0, 1.0, 0.0)
        out.append(n)
    return out


def encode_model(stock: bytes, prims: list[dict], page_map: list[int], *, max_influences: int = MAX_INFLUENCES) -> dict:
    """Retargeted donor prims (library frame, J = native bone, W) -> a new model with the stock bone records.

    page_map: the costume's page indices the donor may use (atlas page i -> material page page_map[i])."""
    model = D.parse_model(stock)
    bones = model["bones"]
    nb = len(bones)
    world = D.bone_world(bones)
    inv = [np.linalg.inv(W) for W in world]
    F = D.FRAME
    stock_pos = struct.unpack_from("<H", stock, 0x14)[0]
    stock_nrm = struct.unpack_from("<H", stock, 0x16)[0]
    # unique positions (with their influences) and per-corner records
    pos_key: dict = {}
    P, Nsum, infl = [], [], []
    corners = []                                          # per prim: list of (pos slot, uv) per vertex
    for p, cn in zip(prims, corner_normals(prims)):
        pos = np.asarray(p["pos"], float) @ F.T           # library -> game frame (X mirrored)
        nrm = cn @ F.T                                    # normals mirror with the positions
        J, W = np.asarray(p["J"], int), np.asarray(p["W"], float)
        slots = []
        for v in range(len(pos)):
            order = np.argsort(-W[v])[:max_influences]
            inf = {}
            for c in order:
                if W[v, c] > 1e-4:
                    inf[int(J[v, c])] = inf.get(int(J[v, c]), 0.0) + float(W[v, c])
            if not inf:                                   # no usable weight: the top joint takes it all
                inf = {int(J[v, order[0]]): 1.0}
            tot = sum(inf.values()) or 1.0
            inf = {j: w / tot for j, w in inf.items()}
            key = (tuple(np.round(pos[v], 5)), tuple(sorted((j, round(w, 3)) for j, w in inf.items())))
            s = pos_key.get(key)
            if s is None:
                s = pos_key[key] = len(P)
                P.append(pos[v])
                Nsum.append(np.zeros(3))
                infl.append(inf)
            Nsum[s] = Nsum[s] + nrm[v]
            slots.append(s)
        corners.append(slots)
    npos = len(P)
    if npos > min(stock_pos, D.SLOT_MASK + 1):
        raise BudgetError(f"donor has {npos} distinct vertices; the stock model has room for {stock_pos}")
    for inf in infl:
        for j in inf:
            if not 0 <= j < nb:
                raise ValueError(f"vertex bound to bone {j}, the model has {nb}")
    # The engine (0x8c03c920) writes a bone's position stores to CONSECUTIVE slots from its first row's slot and runs
    # bones in index order, so a vertex is stored by the lowest bone that touches it and added by the others, and the
    # slots are numbered bone by bone: every bone's stores are one consecutive run, as in the shipped models.
    first = [min(inf) for inf in infl]
    order = sorted(range(npos), key=lambda s: (first[s], s))
    renum = {old: new for new, old in enumerate(order)}
    P = np.array([P[s] for s in order])
    N = np.array([Nsum[s] for s in order])
    infl = [infl[s] for s in order]
    first = [first[s] for s in order]
    corners = [[renum[s] for s in slots] for slots in corners]
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    gloss = _stock_gloss(model)
    rows_of = [{"store": [], "add": [], "nstore": [], "nadd": []} for _ in range(nb)]
    # normals are skinned like the positions (the stock rows do the same): one normal slot per distinct (influences,
    # normal), its rows on every influencing bone with the same weights, the lowest bone storing (flag clear) and the
    # others adding (bit 15). Slots are numbered bone by bone, so each bone's normal stores are one consecutive run.
    nslot, nkey = [0] * npos, {}
    for s, inf in enumerate(infl):
        for j, (w, flag) in sorted(_weight_words(inf, first[s], s).items()):
            rows_of[j]["add" if flag else "store"].append((s, w, flag))
        key = (tuple(sorted((j, round(w, 3)) for j, w in inf.items())), tuple(np.round(N[s], 3)))
        if key not in nkey:
            nkey[key] = ns = len(nkey)
            for j, (w, flag) in sorted(_weight_words(inf, first[s], ns).items()):
                rows_of[j]["nadd" if flag else "nstore"].append((ns, s, w, flag))
        nslot[s] = nkey[key]
    nnrm = len(nkey)
    if nnrm > min(stock_nrm, D.SLOT_MASK + 1):
        raise BudgetError(f"donor has {nnrm} distinct normals; the stock model has room for {stock_nrm}")

    def row(vec, wbits):
        return struct.pack("<3fI", *np.asarray(vec, np.float32), wbits)

    bones_out = []
    for j, b in enumerate(bones):
        r = rows_of[j]
        # a position row is the weight-premultiplied bone-local point: the engine's ftrv gives R (w p) + w t
        pos_rows = [row(D._w(w | flag | s) * (inv[j][:3, :3] @ P[s] + inv[j][:3, 3]), w | flag | s)
                    for s, w, flag in r["store"] + r["add"]]
        # normal rows: inward like the stock rows, weight-premultiplied like the positions, stores before adds; the
        # low byte of z is the per-vertex highlight byte 0x8c03ca9c reads (the stock model's usual value)
        nrm_rows = []
        for ns, s, w, flag in r["nstore"] + r["nadd"]:
            n = np.asarray(-D._w(w | flag | ns) * (inv[j][:3, :3] @ N[s]), np.float32)
            n[2] = np.uint32((int(n[2].view(np.uint32)) & ~0xFF) | gloss).view(np.float32)
            nrm_rows.append(row(n, w | flag | ns))
        if r["store"] and [s for s, _w, _f in r["store"]] != list(range(r["store"][0][0], r["store"][0][0] + len(r["store"]))):
            raise AssertionError(f"bone {j}: position stores are not consecutive slots")
        bones_out.append({"index": j, "record": b["record"], "stores": len(r["store"]), "adds": len(r["add"]),
                          "positions": len(pos_rows), "normals": len(nrm_rows),
                          "raw": b"".join(pos_rows) + b"".join(nrm_rows)})
    per_bone_store = [r["store"] for r in rows_of]
    per_bone_add = [r["add"] for r in rows_of]
    # triangles per page, winding outward in the game frame (the library -> game mirror reverses it)
    by_page: dict[int, list] = {}
    for p, slots in zip(prims, corners):
        page = p["_page"]
        uvs = p["_uv"]
        tris = np.asarray(p["tris"], int).reshape(-1, 3)
        for t, (a, b, c) in enumerate(tris):
            if len({slots[a], slots[b], slots[c]}) < 3:
                continue
            ca, cb, cc = (a, slots[a], tuple(uvs[t][0])), (c, slots[c], tuple(uvs[t][2])), (b, slots[b], tuple(uvs[t][1]))
            by_page.setdefault(page, []).append((ca, cb, cc))
    sections = []
    n_tris = n_strips = 0
    for page in sorted(by_page):
        corner_id: dict = {}
        verts = []
        tris = []
        for tri in by_page[page]:
            ids = []
            for _src, s, uv in tri:
                key = (s, _bf16(np.array(uv))[0], _bf16(np.array(uv))[1])
                if key not in corner_id:
                    corner_id[key] = len(verts)
                    verts.append(key)
                ids.append(corner_id[key])
            tris.append(tuple(ids))
        sec = []
        for st in stripify(tris):
            raw = np.array([(verts[v][0], nslot[verts[v][0]] | (0x8000 if k == len(st) - 1 else 0), int(verts[v][1]),
                             int(verts[v][2])) for k, v in enumerate(st)], np.uint16)
            sec.append({"head": bytes((0x30 | (page & 3), 0, 0)), "raw": raw})
            n_strips += 1
            n_tris += len(st) - 2
        sections.append(sec)
    stock_end = model["strips_end"]
    built = {"header_raw": stock[:0x20], "bones": bones_out, "sections": sections, "tail": model["tail"]}
    try:
        out = D.pack_model(built, tail_at=stock_end, size=len(stock))
    except ValueError as error:
        rows_b = sum(len(b["raw"]) for b in bones_out)
        strips_b = sum(4 + 8 * len(s["raw"]) for sec in sections for s in sec) + 4 * len(sections) + 4
        raise BudgetError(f"donor needs {rows_b + strips_b} bytes of rows + strips; the stock model has "
                          f"{stock_end - 0x20 - 32 * nb} before its tail ({error})") from error
    check = D.parse_model(out)
    if check["counts"] != (npos, nnrm):
        raise AssertionError(f"slot counts {check['counts']} != {(npos, nnrm)}")
    end = check["strips_end"]
    return {"model": out, "positions": npos, "triangles": n_tris, "strips": n_strips,
            "rows": sum(len(a) + len(b) for a, b in zip(per_bone_store, per_bone_add)),
            "bytes_used": end, "bytes_room": stock_end,
            "bones_used": sorted({j for inf in infl for j in inf})}


# ---------------------------------------------------------------- a costume entry

def free_pages(model_bytes: bytes, n_pages: int) -> list[int]:
    """Pages a donor may use: all but the face page (page 0) when the model has one (header flag at 0x12)."""
    flags = struct.unpack_from("<H", model_bytes, 0x12)[0]
    pages = list(range(n_pages))
    return pages[1:] if flags and n_pages > 1 else pages


def fit_donor(stock_model: bytes, character_dir: Path, slot_key: str, *, scale=None) -> tuple[list[dict], dict]:
    """Load + retarget a collection donor onto the costume's rest skeleton (library frame)."""
    from .doa2_weighted_retarget import load_rig, retarget
    from . import fit_events as FE, retarget_profile as RP
    directory = Path(character_dir)
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    meta = RP.apply_to_meta(meta, GAME_IDS, slot_key)
    roles = (meta.get("rig") or {}).get("roles") or {}
    if not {"hip", "head"} <= roles.keys():
        raise ValueError(f"{directory.name}: donor needs hip and head body roles")
    model_path = (directory / meta["model"]).resolve()
    if not model_path.is_relative_to(directory.resolve()):
        raise ValueError("donor model must stay inside its character directory")
    tgt = target(D.parse_model(stock_model))
    rig = load_rig(model_path, roles, [p["node"] for p in meta.get("props") or []])
    prims, fit = retarget(rig, tgt, scale if scale is not None else (meta.get("rig") or {}).get("scale"), tgt["jmap"])
    fit["donor"] = meta.get("slug") or directory.name
    fit["retarget_profile_digest"] = meta.get("retarget_profile_digest", "")
    if FE.active():
        FE.stage("weights", data={"mode": f"weighted, up to {MAX_INFLUENCES} influences (native accumulation skin)",
                                  "vertices": int(sum(len(p["pos"]) for p in prims)),
                                  "per_limb": FE.per_limb(prims, {j: r for r, j in tgt["jmap"].items()})})
    return prims, fit | {"model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}


def _decimated(prims: list[dict], tgt: dict, budget: int, work: Path) -> list[dict]:
    """Blender LOD of the fitted donor (skin weights kept), the DOA2 writer's path."""
    from . import sm64_swap as S
    from .re4gc_enemies import decimate
    from .doa2_weighted_retarget import read_rigged
    rig_t = {"T": tgt["T"], "parent": tgt["parent"], "joints": tgt["joints"]}
    src = S.write_rigged(prims, rig_t, work / "fitted.gltf", "donor")
    out = decimate(src, work / f"lod{budget}.glb", float(budget))
    return read_rigged(out, tgt["jmap"])


def build_costume(entry: bytes, prims: list[dict], *, progress=lambda p, m: None) -> tuple[bytes, dict]:
    """One costume entry with the donor: model + pages rebuilt, every other sub-entry kept byte for byte."""
    cp = D.costume_parts(entry)
    stock = cp["model"]
    usable = free_pages(stock, len(cp["pages"]))
    at = atlas(prims, len(usable))
    for p in prims:
        page_i, *_ = at["slots"][p["_texkey"]]
        p["_page"] = usable[page_i]
        tris = np.asarray(p["tris"], int).reshape(-1, 3)
        p["_uv"] = [map_uv(np.asarray(p["uv"], float)[t], at["slots"][p["_texkey"]]) for t in tris]
    enc = encode_model(stock, prims, usable)
    packed = D.lz_compress(enc["model"])
    room = len(cp["bank"][0])
    if len(packed) > room:
        raise BudgetError(f"compressed model is {len(packed)} bytes; the stock entry has {room}")
    pages = list(cp["pages"])
    for i, img in enumerate(at["images"]):
        pages[usable[i]] = D.page_encode(img)
    bank = D.build_table([D.pad32(packed).ljust(room, b"\0")] + pages)
    if len(bank) != len(cp["table"][0]):
        raise AssertionError("bank size changed")
    new_entry = D.build_table([bank] + list(cp["table"][1:]))
    if len(new_entry) != len(entry):
        raise AssertionError("costume entry size changed")
    report = {k: enc[k] for k in ("positions", "triangles", "strips", "rows", "bytes_used", "bytes_room", "bones_used")}
    report.update(compressed=len(packed), compressed_room=room, pages=[usable[i] for i in range(len(at["images"]))],
                  textures=at["textures"], atlas_grid=at["grid"])
    return new_entry, report


def fit_and_build(entry: bytes, character_dir: Path, slot_key: str, work: Path, *, progress=lambda p, m: None):
    """fit_donor + build_costume, with bounded Blender LOD attempts when the donor does not fit."""
    from . import fit_events as FE
    stock = D.costume_parts(entry)["model"]
    prims, fit = fit_donor(stock, character_dir, slot_key)
    source = sum(len(np.asarray(p["tris"]).reshape(-1, 3)) for p in prims)
    attempts = []
    FE.stage("encode", "running", {"triangles": source})
    try:
        new, report = build_costume(entry, prims, progress=progress)
        FE.stage("decimate", "skipped", {"triangles": source})
    except BudgetError as error:
        attempts.append({"triangles": source, "result": str(error)})
        tgt = target(D.parse_model(stock))
        new = None
        for k in range(1, 9):
            budget = max(200, int(source * 0.8 ** k))
            try:
                lod = _decimated(prims, tgt, budget, Path(work))
                new, report = build_costume(entry, lod, progress=progress)
            except BudgetError as again:
                attempts.append({"budget": budget, "result": str(again)})
                continue
            attempts.append({"budget": budget, "result": "fits"})
            FE.stage("decimate", data={"from": source, "to": report["triangles"], "attempts": len(attempts)})
            break
        if new is None:
            FE.stage("encode", "failed", {"error": str(error)[:150]})
            raise BudgetError(f"donor does not fit after LOD attempts: {attempts}") from error
    FE.stage("encode", data={k: report[k] for k in ("triangles", "positions", "compressed", "compressed_room")})
    report.update(fit=fit, source_triangles=source, lod_attempts=attempts)
    return new, report


# ---------------------------------------------------------------- HUMAN.DAT

def replace_entries(human: bytes, changes: dict[int, bytes]) -> bytes:
    """New entries written into their own olnk slots (sizes must not grow; offsets never move)."""
    layout = D.olnk_layout(human)
    out = bytearray(human)
    for i, data in changes.items():
        off, size = layout[i]
        if len(data) > size:
            raise BudgetError(f"HUMAN.DAT entry {i}: {len(data)} bytes > its {size}-byte slot")
        out[off:off + len(data)] = data
        out[off + len(data):off + size] = b"\0" * (size - len(data))
        struct.pack_into("<I", out, 0x14 + 8 * i, len(data))
    return bytes(out)


# ---------------------------------------------------------------- the random costume patch (1ST_READ.BIN)

LOADER_SITE = 0x8C02E38C                  # FUN_8c02e37a after its prologue: mov r6,r8 ; shll8 r8 (r6 = costume)
CAVE_A = 0x8C02E408                       # 12 alignment-pad slots after the loader's "bra 0x8c02e638 ; nop"
CAVE_B = 0x8C02E450                       # 8 pad slots before the 32-byte aligned branch target 0x8c02e460
BASE = 0x8C010000
STOCK_SITE = bytes.fromhex("6368 1848".replace(" ", ""))
NOP = bytes.fromhex("0900")


def _bra(src: int, dst: int) -> bytes:
    d = (dst - (src + 4)) // 2
    if not -2048 <= d < 2048 or (dst - src) % 2:
        raise ValueError("branch out of range")
    return struct.pack("<H", 0xA000 | (d & 0xFFF))


def _bt(src: int, dst: int) -> bytes:
    d = (dst - (src + 4)) // 2
    if not -128 <= d < 128:
        raise ValueError("bt out of range")
    return struct.pack("<H", 0x8900 | (d & 0xFF))


def random_costume_code() -> dict[int, bytes]:
    """{address: bytes} of the patch. Costume r6 0 or 1 -> bit 0 of TCNT0 ^ TCNT0 >> 8 ^ TCNT0 >> 16; 2.. kept."""
    done = CAVE_A + 18
    a = [
        bytes.fromhex("02e0"),                     # mov #2,r0
        bytes.fromhex("0236"),                     # cmp/hs r0,r6
        _bt(CAVE_A + 4, done),                     # bt done
        bytes.fromhex("d8e1"),                     # mov #-40,r1        r1 = 0xffffffd8
        bytes.fromhex("2841"),                     # shll16 r1          r1 = 0xffd80000
        bytes.fromhex("0c71"),                     # add #12,r1         r1 = 0xffd8000c (TMU0 TCNT0)
        bytes.fromhex("1260"),                     # mov.l @r1,r0
        _bra(CAVE_A + 14, CAVE_B),                 # bra cave_b
        bytes.fromhex("0361"),                     # mov r0,r1 (delay slot)
        bytes.fromhex("6368"),                     # done: mov r6,r8
        _bra(CAVE_A + 20, LOADER_SITE + 4),        # bra back to 0x8c02e390
        bytes.fromhex("1848"),                     # shll8 r8 (delay slot)
    ]
    b = [
        bytes.fromhex("1941"),                     # shlr8 r1
        bytes.fromhex("1a20"),                     # xor r1,r0
        bytes.fromhex("1941"),                     # shlr8 r1
        bytes.fromhex("1a20"),                     # xor r1,r0
        bytes.fromhex("01c9"),                     # and #1,r0
        bytes.fromhex("0366"),                     # mov r0,r6
        _bra(CAVE_B + 12, done),                   # bra done
        NOP,
    ]
    return {LOADER_SITE: _bra(LOADER_SITE, CAVE_A) + NOP, CAVE_A: b"".join(a), CAVE_B: b"".join(b)}


def patch_random_costume(exe: bytes) -> bytes:
    """1ST_READ.BIN with the random costume hook (refuses any executable but the verified USA one)."""
    if hashlib.sha256(exe).hexdigest() != D.EXECUTABLE_SHA256:
        raise ValueError("unsupported SoulCalibur executable; the patch addresses are for T-1401N 1ST_READ.BIN")
    return apply_random_costume(exe)


def apply_random_costume(exe: bytes) -> bytes:
    """The hook written into any image that holds the stock site and free caves (patch_random_costume checks the
    executable's identity first)."""
    out = bytearray(exe)
    if out[LOADER_SITE - BASE:LOADER_SITE - BASE + 4] != STOCK_SITE:
        raise ValueError("loader site does not hold the stock instructions")
    for cave, n in ((CAVE_A, 24), (CAVE_B, 16)):
        if out[cave - BASE:cave - BASE + n] != NOP * (n // 2):
            raise ValueError(f"cave 0x{cave:08x} is not free padding")
    for addr, code in random_costume_code().items():
        out[addr - BASE:addr - BASE + len(code)] = code
    return bytes(out)


def verify_random_patch(exe: bytes) -> dict:
    """Read the patch back: the site branches to cave A, cave A to cave B and back, the stock bytes elsewhere."""
    code = random_costume_code()
    ok = all(exe[a - BASE:a - BASE + len(c)] == c for a, c in code.items())
    return {"patched": ok, "site": f"0x{LOADER_SITE:08x}", "caves": [f"0x{CAVE_A:08x}", f"0x{CAVE_B:08x}"],
            "bytes": sum(len(c) for c in code.values())}


def simulate_random_patch(exe: bytes, costume: int, tcnt: int) -> int:
    """What the patched loader passes on for a requested costume and a TCNT0 value (an interpreter of exactly the
    instructions random_costume_code writes, run on the bytes read back from the executable)."""
    r = {0: 0, 1: 0, 6: costume, 8: 0}
    pc = LOADER_SITE
    mem = {0xFFD8000C: tcnt}
    steps = 0
    t = False
    delay = None
    while steps < 64:
        steps += 1
        w = struct.unpack_from("<H", exe, pc - BASE)[0]
        nxt = pc + 2
        hi = w >> 12
        if w == 0x0009:
            pass
        elif hi == 0xE:
            r[(w >> 8) & 15] = (w & 0xFF) - 256 if w & 0x80 else w & 0xFF
        elif hi == 0x3 and w & 15 == 2:                    # cmp/hs Rm,Rn: T = Rn >= Rm (unsigned)
            t = (r[(w >> 8) & 15] & 0xFFFFFFFF) >= (r[(w >> 4) & 15] & 0xFFFFFFFF)
        elif w >> 8 == 0x89:
            if t:
                d = w & 0xFF
                nxt = pc + 4 + 2 * (d - 256 if d & 0x80 else d)
        elif hi == 0x4 and w & 0xFF == 0x28:
            r[(w >> 8) & 15] = (r[(w >> 8) & 15] << 16) & 0xFFFFFFFF
        elif hi == 0x4 and w & 0xFF == 0x18:
            r[(w >> 8) & 15] = (r[(w >> 8) & 15] << 8) & 0xFFFFFFFF
        elif hi == 0x4 and w & 0xFF == 0x19:
            r[(w >> 8) & 15] = (r[(w >> 8) & 15] & 0xFFFFFFFF) >> 8
        elif hi == 0x7:
            imm = w & 0xFF
            r[(w >> 8) & 15] = (r[(w >> 8) & 15] + (imm - 256 if imm & 0x80 else imm)) & 0xFFFFFFFF
        elif hi == 0x6 and w & 15 == 2:
            r[(w >> 8) & 15] = mem[r[(w >> 4) & 15] & 0xFFFFFFFF]
        elif hi == 0x6 and w & 15 == 3:
            r[(w >> 8) & 15] = r[(w >> 4) & 15]
        elif hi == 0x2 and w & 15 == 0xA:
            r[(w >> 8) & 15] ^= r[(w >> 4) & 15]
        elif w >> 8 == 0xC9:
            r[0] &= w & 0xFF
        elif hi == 0xA:
            d = w & 0xFFF
            delay = pc + 4 + 2 * (d - 4096 if d & 0x800 else d)
            pc = nxt
            continue
        else:
            raise ValueError(f"unexpected instruction {w:04x} at {pc:08x}")
        if delay is not None:
            pc, delay = delay, None
            if pc == LOADER_SITE + 4:
                return r[8] >> 8
            continue
        pc = nxt
    raise RuntimeError("patch did not return to the loader")


# ---------------------------------------------------------------- plans and builds

SA2 = ["sonic", "sa2_amy_rose", "sa2_chaos_0", "sa2_dr_eggman", "sa2_knuckles", "sa2_metal_sonic", "sa2_rouge",
       "sa2_shadow", "sa2_super_shadow", "sa2_super_sonic", "sa2_tails", "sa2_tikal"]
SM64DS = ["sm64ds_mario", "sm64ds_luigi", "sm64ds_wario", "sm64ds_yoshi", "sm64ds_metal_wario", "sm64ds_peach",
          "sm64ds_bowser", "sm64ds_koopa_troopa", "sm64ds_ukiki"]
# Sonic vs Mario: costume 0 (and 2) a Sonic Adventure 2 character, costume 1 (and 3) a Super Mario 64 DS one, each
# fighter's pair picked to suit it (Lizardman -> Yoshi, Astaroth / Nightmare -> Bowser, Siegfried -> the metal ones)
SONIC_VS_MARIO = {
    "MIT": ["sonic", "sm64ds_mario"], "SEU": ["sa2_amy_rose", "sm64ds_peach"], "TAK": ["sa2_rouge", "sm64ds_yoshi"],
    "MAX": ["sa2_shadow", "sm64ds_luigi", "sa2_tails"], "VOL": ["sa2_chaos_0", "sm64ds_koopa_troopa", "sa2_tikal",
                                                                 "sm64ds_mario"],
    "SOP": ["sa2_tikal", "sm64ds_peach", "sa2_amy_rose"], "SIE": ["sa2_metal_sonic", "sm64ds_metal_wario",
                                                                  "sa2_super_sonic"],
    "ROC": ["sa2_knuckles", "sm64ds_wario"], "HWA": ["sa2_super_sonic", "sm64ds_luigi"],
    "IVY": ["sa2_rouge", "sm64ds_peach"], "KIL": ["sa2_tails", "sm64ds_luigi"],
    "XIA": ["sa2_amy_rose", "sm64ds_mario", "sa2_tails"], "LIZ": ["sa2_chaos_0", "sm64ds_yoshi"],
    "YOS": ["sa2_super_shadow", "sm64ds_ukiki"], "EDG": ["sa2_dr_eggman", "sm64ds_wario"],
    "NIG": ["sa2_shadow", "sm64ds_bowser"], "AST": ["sa2_dr_eggman", "sm64ds_bowser"],
    "INF": ["sa2_super_shadow", "sm64ds_metal_wario", "sonic"], "CER": ["sa2_knuckles", "sm64ds_koopa_troopa"],
}


def franchise(slug: str) -> str:
    """SM64DS = the Mario side: SM64 DS, SM64 (sm64_* / mario) and HD (*_hd) donors."""
    if slug.startswith(("sm64ds_", "sm64_")) or slug.endswith("_hd") or slug == "mario":
        return "SM64DS"
    return "SA2" if slug in SA2 else "other"


def mario_group(library, assignments: dict[str, list[str]] = SONIC_VS_MARIO) -> dict[str, list[str]]:
    """The assignments with every Mario-side donor upgraded to the collection's best model of that character
    (gbox.cast_swap group 'mario': HD > SM64 > SM64 DS)."""
    from . import cast_swap
    slugs = sorted({s for v in assignments.values() for s in v})
    up = cast_swap.upgrade_slugs(slugs, cast_swap.library_metas(Path(library)))
    return {k: [up.get(s, s) for s in v] for k, v in assignments.items()}


def plan_costumes(human: bytes, assignments: dict[str, list[str]]) -> list[dict]:
    """[{fighter, costume, entry, character}] for every costume slot a fighter has on the disc (extra donors in the
    assignment beyond the disc's costumes are dropped; missing ones repeat the fighter's list)."""
    entries = D.olnk(human)
    rows = []
    for key, donors in assignments.items():
        g, k, name = D.fighter(key)
        if not donors:
            continue
        for i, c in enumerate(D.costumes_of(entries, g)):
            rows.append({"fighter": k, "name": name, "costume": c, "entry": g * D.GROUP + c,
                         "character": donors[i % len(donors)]})
    return rows


def build_roster(gdi, donors_root, out_dir, name: str, plan: list[dict], *, random_select: bool = True,
                 progress=lambda p, m: None) -> dict:
    """One copied GD-ROM: every planned costume rebuilt with its donor, the random costume hook in 1ST_READ.BIN,
    everything read back before the marker is written."""
    from .gdrom import GDRom, patch_gdi
    from . import fit_events as FE
    import tempfile
    disc = GDRom(gdi)
    human = disc.read(D.HUMAN)
    exe = disc.read("1ST_READ.BIN")
    if hashlib.sha256(exe).hexdigest() != D.EXECUTABLE_SHA256:
        raise ValueError("unsupported SoulCalibur executable (the writer is verified on T-1401N USA)")
    entries = D.olnk(human)
    FE.plan([(f"fighter:{r['fighter']}:{r['costume']}", r["character"],
              f"{r['character']} -> {r['name']} (costume {r['costume']})") for r in plan])
    changes, reports, failures = {}, [], []
    with tempfile.TemporaryDirectory(prefix="gbox-sc-") as work:
        for i, row in enumerate(plan):
            progress(80 * i / max(len(plan), 1), f"{row['name']} costume {row['costume']}: {row['character']}")
            FE.model(f"fighter:{row['fighter']}:{row['costume']}")
            donor_dir = Path(donors_root) / row["character"]
            try:
                new, rep = fit_and_build(entries[row["entry"]], donor_dir, f"fighter:{row['fighter']}",
                                         Path(work))
            except Exception as error:                     # noqa: BLE001 - one costume's failure leaves it stock
                failures.append(row | {"error": f"{type(error).__name__}: {error}"[:300]})
                FE.stage("write", "failed", {"error": str(error)[:150]})
                continue
            changes[row["entry"]] = new
            reports.append(row | {k: v for k, v in rep.items() if k != "fit"} |
                           {"fit": {k: rep["fit"].get(k) for k in ("scale", "head_scale", "limb_stretch", "donor",
                                                                    "max_influences", "model_sha256",
                                                                    "retarget_profile_digest")}})
    human2 = replace_entries(human, changes)
    files = {D.HUMAN: human2}
    if random_select:
        files["1ST_READ.BIN"] = patch_random_costume(exe)
    progress(85, "Writing the GD-ROM copy")
    image = patch_gdi(gdi, out_dir, name, files, progress)
    verification = verify_build(image, gdi, files, plan, changes)
    if not verification["ok"]:
        raise AssertionError(f"build read-back failed: {verification['problems'][:5]}")
    for r in plan:
        if r["entry"] in changes:
            FE.model(f"fighter:{r['fighter']}:{r['costume']}")
            FE.stage("write", data={"mod": name, "entry": r["entry"], "bytes": len(changes[r["entry"]])})
    return {"image": Path(image), "reports": reports, "failures": failures, "verification": verification,
            "random_select": verify_random_patch(files["1ST_READ.BIN"]) if random_select else None}


def verify_build(image, source_gdi, files: dict[str, bytes], plan: list[dict], changes: dict[int, bytes]) -> dict:
    """Read the written image back: the two files byte for byte, every entry of HUMAN.DAT (rebuilt ones parse,
    skin and carry the planned triangles; the rest are the stock bytes), the patch in 1ST_READ.BIN, and every
    other file on the disc unchanged."""
    from .gdrom import GDRom
    new, old = GDRom(image), GDRom(source_gdi)
    problems = []
    for key, data in files.items():
        if new.read(key) != data:
            problems.append(f"{key} differs from the planned bytes")
    for key in old.files:
        if key not in files and new.read(key) != old.read(key):
            problems.append(f"{key} changed")
    human_new, human_old = D.olnk(new.read(D.HUMAN)), D.olnk(old.read(D.HUMAN))
    models = []
    for i, (a, b) in enumerate(zip(human_new, human_old)):
        if i in changes:
            try:
                cp = D.costume_parts(a)
                m = D.parse_model(cp["model"])
                tris = sum(len(s["pos"]) - 2 for sec in m["sections"] for s in sec)
                # the game's own skinning maths (D.engine_skin, the 0x8c03c920 / 0x8c03cba0 rules), not the reader's
                # view: every slot a strip draws must be stored this frame and no add may land on a stale slot
                eng = D.engine_skin(m, D.bone_world(m["bones"]))
                ps = sorted({int(x) for sec in m["sections"] for s in sec for x in s["pos"]})
                ns = sorted({int(x) for sec in m["sections"] for s in sec for x in s["nrm"]})
                finite = bool(np.isfinite(eng["positions"][ps]).all() and np.isfinite(eng["normals"][ns]).all())
                models.append({"entry": i, "triangles": tris, "positions": len(ps), "finite": finite,
                               "stale_adds": eng["stale_adds"], "counts": list(m["counts"])})
                if not finite or eng["stale_adds"]:
                    problems.append(f"entry {i}: the engine's skinning leaves drawn vertices unset "
                                    f"(stale adds {eng['stale_adds']})")
                if max(ps, default=-1) >= m["counts"][0] or max(ns, default=-1) >= m["counts"][1]:
                    problems.append(f"entry {i}: strips index past the header's vertex counts")
                stock = D.costume_parts(b)["model"]
                end = D.parse_model(stock)["strips_end"]
                if len(cp["model"]) != len(stock) or cp["model"][end:] != stock[end:]:
                    problems.append(f"entry {i}: model tail moved")
                if m["strips_end"] > end:
                    problems.append(f"entry {i}: strips run into the tail")
            except Exception as error:                     # noqa: BLE001 - every failure is a reported problem
                problems.append(f"entry {i}: {error}")
        elif a != b:
            problems.append(f"entry {i} changed without a plan row")
    patch = verify_random_patch(new.read("1ST_READ.BIN")) if "1ST_READ.BIN" in files else None
    if patch is not None and not patch["patched"]:
        problems.append("random costume hook missing")
    if patch is not None:
        exe = new.read("1ST_READ.BIN")
        patch["simulated"] = {f"{c}:{t:#x}": simulate_random_patch(exe, c, t)
                              for c in (0, 1, 2) for t in (0x0, 0x1, 0x100, 0x12345, 0xFFFF0001)}
    return {"ok": not problems, "problems": problems, "models": models, "random_select": patch,
            "entries_rebuilt": len(changes), "entries_total": len(human_new)}


def marker(name: str, game_id: str, image: Path, plan: list[dict], result: dict, title: str) -> dict:
    """The .gbox-mod.json record (the DOA2 roster mods' fields)."""
    roster = {}
    for r in plan:
        roster.setdefault(r["fighter"], {"fighter": r["fighter"], "name": r["name"], "pool": []})
        roster[r["fighter"]]["pool"].append({"costume": r["costume"], "character": r["character"],
                                             "franchise": franchise(r["character"]),
                                             "built": not any(f["entry"] == r["entry"] for f in result["failures"])})
    for v in roster.values():
        v["character"] = v["pool"][0]["character"]
        v["franchise"] = v["pool"][0]["franchise"]
    chars = sorted({r["character"] for r in plan})
    return {"name": name, "game_id": game_id, "image": Path(image).name, "character": ",".join(chars),
            "files": [D.HUMAN, "1ST_READ.BIN"] if result.get("random_select") else [D.HUMAN],
            "report": {"costumes": result["reports"], "failures": result["failures"], "gameplay_verified": False},
            "writer_sha256": writer_fingerprint(), "profile_digest": "", "gameplay_verified": False,
            "roster": list(roster.values()), "title": title,
            "cast_source": "Sonic Adventure 2 (USA) + Super Mario 64 DS (USA)", "cast_mapping": "mixed_random",
            "random_select": ({"patch": "gbox.soulcalibur_swap.patch_random_costume", "hook": f"0x{LOADER_SITE:08x}",
                               "caves": [f"0x{CAVE_A:08x}", f"0x{CAVE_B:08x}"],
                               "rule": "costume 0 or 1 -> bit 0 of TCNT0 ^ TCNT0>>8 ^ TCNT0>>16 at each fighter load; "
                                       "costumes 2 and 3 (extra costumes) are kept"}
                              if result.get("random_select") else None),
            "verification": {k: v for k, v in result["verification"].items() if k != "models"},
            "verified_in_game": False}


# ---------------------------------------------------------------- gBox routes (characters op=use, cast swap)

def cast_slots() -> list[dict]:
    """The cast menu / whole-cast swap: every selectable fighter (all its costumes take the donor)."""
    return [{"slot": f"fighter:{key}", "name": name, "kind": "fighter", "size": FIGHTER_SIZE.get(key, 1.0),
             "writer": "gbox.soulcalibur_swap"} for _g, key, name, _a in D.FIGHTERS]


def _plan_from_pairs(human: bytes, pairs: list[tuple[str, str]]) -> list[dict]:
    """[(slot, donor slug)] -> plan rows: 'fighter:MIT' fills every costume, 'fighter:MIT:1' one costume."""
    entries = D.olnk(human)
    rows, seen = [], set()
    for slot, slug in pairs:
        key, costume = fighter_slot(slot)
        g, k, name = D.fighter(key)
        for c in ([costume] if costume is not None else D.costumes_of(entries, g)):
            if not entries[g * D.GROUP + c]:
                raise ValueError(f"{name} has no costume {c}")
            if (k, c) in seen:
                raise ValueError(f"{name} costume {c} was assigned twice")
            seen.add((k, c))
            rows.append({"fighter": k, "name": name, "costume": c, "entry": g * D.GROUP + c, "character": slug})
    return rows


def _write_marker(out: Path, name: str, game_id: str, plan, res, title: str, extra: dict | None = None) -> dict:
    rec = marker(name, game_id, res["image"], plan, res, title) | (extra or {})
    Path(out, "build-report.json").write_text(json.dumps(res["reports"], indent=1, default=str), encoding="utf-8")
    Path(out, "verification.json").write_text(json.dumps(res["verification"], indent=1, default=str),
                                              encoding="utf-8")
    Path(out, ".gbox-mod.json").write_text(json.dumps(rec, default=str), encoding="utf-8")      # written last
    return rec


def build_cast(ctx, game: dict, pairs, name: str, *, random_select: bool = False) -> dict:
    """cast_swap pairs [(slot, meta)] -> one disc (every slot's costumes rebuilt), per-slot status."""
    from . import characters as C, filemods
    from .gdrom import GDRom
    gdi = C._dc_gdi(ctx, game)
    human = GDRom(str(gdi)).read(D.HUMAN)
    plan = _plan_from_pairs(human, [(s, m["slug"]) for s, m in pairs])
    out = filemods.mod_dir(ctx.config, game["game_id"], name)
    res = build_roster(gdi, C.library_root(ctx.config), out, name, plan, random_select=random_select,
                       progress=ctx.progress)
    _write_marker(out, name, game["game_id"], plan, res, f"{game.get('title', 'SoulCalibur')}: cast swap {name}")
    failed = {f["fighter"] for f in res["failures"]}
    return {"mod": name, "slots": {s: ({"status": "partial" if fighter_slot(s)[0] in failed and any(
        r["fighter"] == fighter_slot(s)[0] for r in res["reports"]) else "failed" if fighter_slot(s)[0] in failed
        else "built"}) for s, _m in pairs}, "detail": {"failures": res["failures"]}}


def use_roster(ctx, meta, game, inp) -> dict:
    """slot='roster' / 'sonic vs mario': every fighter's costumes from `pairs` (or the Sonic vs Mario plan) in one
    disc; random_select (default on) adds the random costume hook so each load picks costume 0 or 1 at random."""
    from . import characters as C, filemods
    from .gdrom import GDRom
    gdi = C._dc_gdi(ctx, game)
    human = GDRom(str(gdi)).read(D.HUMAN)
    pairs = [(str(p.get("slot") or ""), str(p.get("character") or "")) for p in (inp.pairs or [])]
    from .cast_swap import GROUPS
    mario = (getattr(inp, "source", "") or "").strip().lower() in {"mario", *GROUPS["mario"]["aliases"]}
    plan = _plan_from_pairs(human, pairs) if pairs else plan_costumes(
        human, mario_group(C.library_root(ctx.config)) if mario else SONIC_VS_MARIO)
    digest = hashlib.sha256(json.dumps([(r["entry"], r["character"]) for r in plan]).encode()).hexdigest()[:8]
    name = (("sc_sonic_vs_mario_hd_random" if mario else "sc_sonic_vs_mario_random") if not pairs
            else f"sc_roster_{digest}")
    out = filemods.mod_dir(ctx.config, game["game_id"], name)
    try:
        cached = json.loads((out / ".gbox-mod.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    result = None
    if inp.rebuild or cached.get("writer_sha256") != writer_fingerprint():
        res = build_roster(gdi, C.library_root(ctx.config), out, name, plan, random_select=True,
                           progress=ctx.progress)
        _write_marker(out, name, game["game_id"], plan, res,
                      f"{game.get('title', 'SoulCalibur')}: Sonic Adventure 2 vs Super Mario 64 DS, random costume")
        result = {"built": len(res["reports"]), "failures": res["failures"], "verification": res["verification"]["ok"]}
        for slug in sorted({r["character"] for r in plan}):
            C._api(ctx, "POST", f"/api/characters/{slug}/targets",
                   json={"game_id": game["game_id"], "slot": "roster", "mod": name, "nodes": [C.HOST_OS],
                         "notes": "SoulCalibur roster build (random costume hook). Gameplay verification required."})
    launch = C._launch(ctx, game["game_id"], name, C.HOST_OS) if inp.launch else None
    return {"status": "built_unverified", "mod": name, "build": result, "launch": launch, "gameplay_verified": False,
            "replacement_kind": "native_rom",
            "roster": [{"fighter": r["fighter"], "costume": r["costume"], "character": r["character"]} for r in plan]}


def use(ctx, meta, game, inp) -> dict:
    """characters op=use on SoulCalibur: slot 'fighter:<name>[:<costume>]' (every costume when none is given), or
    'roster' for the whole cast with the random costume hook."""
    from . import characters as C, filemods
    from .gdrom import GDRom
    if (inp.slot or "").strip().casefold() in ("roster", "cast", "everyone", "all fighters", "sonic vs mario", "random"):
        return use_roster(ctx, meta, game, inp)
    key, costume = fighter_slot(inp.slot or "")
    name = f"sc_{key.lower()}{'' if costume is None else costume}_{meta['slug']}"
    out = filemods.mod_dir(ctx.config, game["game_id"], name)
    try:
        cached = json.loads((out / ".gbox-mod.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    result = None
    if inp.rebuild or cached.get("writer_sha256") != writer_fingerprint():
        gdi = C._dc_gdi(ctx, game)
        human = GDRom(str(gdi)).read(D.HUMAN)
        plan = _plan_from_pairs(human, [(inp.slot, meta["slug"])])
        res = build_roster(gdi, C.library_root(ctx.config), out, name, plan, random_select=False,
                           progress=ctx.progress)
        if not res["reports"]:
            raise ValueError(f"no costume could take {meta['slug']}: {res['failures'][:2]}")
        _write_marker(out, name, game["game_id"], plan, res, f"{game.get('title', 'SoulCalibur')}: {meta['name']} as {key}")
        result = {"built": len(res["reports"]), "failures": res["failures"]}
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": game["game_id"], "slot": f"fighter:{key}" + ("" if costume is None else f":{costume}"),
                     "mod": name, "nodes": [C.HOST_OS],
                     "notes": "Native SoulCalibur costume rebuild; fighter motions and weapons kept. Gameplay "
                              "verification required."})
    launch = C._launch(ctx, game["game_id"], name, C.HOST_OS) if inp.launch else None
    return {"status": "built_unverified", "mod": name, "build": result, "fighter": key, "costume": costume,
            "launch": launch, "gameplay_verified": False, "replacement_kind": "native_rom"}


def main(argv=None) -> int:
    """python -m gbox.soulcalibur_swap build GDI DONORS_ROOT OUT_DIR NAME [--no-random] [--mario-group]"""
    import argparse
    ap = argparse.ArgumentParser(prog="gbox.soulcalibur_swap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("gdi")
    b.add_argument("donors")
    b.add_argument("out")
    b.add_argument("name")
    b.add_argument("--game-id", default="c747331797369f74")
    b.add_argument("--no-random", action="store_true")
    b.add_argument("--mario-group", action="store_true",
                   help="Mario-side donors from cast_swap's 'mario' group: the best model per character (HD > SM64 > DS)")
    b.add_argument("--title", default="SoulCalibur (USA): Sonic Adventure 2 vs Super Mario 64 DS, random costume on "
                                      "every fighter load")
    a = ap.parse_args(argv)
    from .gdrom import GDRom
    human = GDRom(a.gdi).read(D.HUMAN)
    assignments = mario_group(a.donors) if a.mario_group else SONIC_VS_MARIO
    plan = plan_costumes(human, assignments)
    res = build_roster(a.gdi, a.donors, a.out, a.name, plan, random_select=not a.no_random,
                       progress=lambda p, m: print(f"{p:5.1f}% {m}", flush=True))
    _write_marker(Path(a.out), a.name, a.game_id, plan, res, a.title)
    print(json.dumps({"image": str(res["image"]), "built": len(res["reports"]), "failed": res["failures"],
                      "ok": res["verification"]["ok"]}, default=str))
    return 0 if res["verification"]["ok"] and not res["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
