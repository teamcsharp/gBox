"""Def Jam: Vendetta PS2 (SLUS_206.39 v1.00) writer: a rigged collection character in a wrestler's place, as a
modded disc image (characters op=use / op=match route here; formats in gbox/defjam_models.py and
docs/defjam_pipeline.md).

How a donor goes in (the game's skeleton, motions and moves stay; only the WRS container's meshes and texture change):
  * Target = the wrestler's own T-pose (BODY's 42-node tree). sm64_swap.load_rig + retarget put the donor on it with
    the body roles (JMAP); every donor vertex is rigid on one joint, encoded as a single-matrix vertex whose matrix
    address is that joint's palette slot (joints without one use the nearest node that has one).
  * The donor is cut by joint, welded/decimated to the budget (aki_wrestling._decimate_parts; Blender when present,
    else the smallest faces are dropped), and baked onto ONE 512 x 512 page (aki_wrestling._bake_parts), quantised to
    256 colours and written back into the container's own GS packet (texels re-swizzled to the CT32 upload, CLUT in
    CSM1 order) so every GIF register stays the game's.
  * Batches follow the game's VU limits seen on the disc: <= 28 triangles and <= 76 vertices, <= 256 qwords, strip
    addresses in the double buffer of the batch's parity (even batches 0x200, odd 0x100, as in all 4413 batches).
  * BODY and BODY2 both carry the donor; FACE and the hands keep their node trees (the face animation data addresses
    them) but draw one zero-area triangle; ALPHA layers keep their layout with every vertex collapsed to a point.
  * The container keeps its slot order and 0x80 slot alignment and must fit the data.bin entry's sectors (the ELF's
    file table is not touched); the image is a copy of the owned ISO with that entry patched in place.

Not verified in an emulator by this module: the build verifies by reading the new container back with the reader.

  python -m gbox.defjam_writer <iso> <character.glb> <roles.json> <out.iso> <wrestler> [...]
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import defjam_inventory as inv
from . import defjam_models as M
from .defjam_inventory import FormatError

GAME_IDS = {"deabd11481aa5a0c": "Def Jam - Vendetta (USA)"}
JMAP = {"hip": 2, "chest": 5, "head": 7, "l_upper": 11, "l_fore": 12, "l_hand": 13, "r_upper": 17, "r_fore": 18,
        "r_hand": 19, "l_thigh": 25, "l_shin": 26, "l_foot": 29, "r_thigh": 35, "r_shin": 36, "r_foot": 39}
MAX_BATCH_TRIS, MAX_BATCH_VERTS = 28, 76
MAX_TRIS = 2000
PAGE = 512
STORY_HEROES = tuple(range(198, 210))         # Briggs, Tank, Proof, Spider x 3 costumes: the story mode's player


# --- target ------------------------------------------------------------------------------------------------------
def _slot(b: bytes, w: dict, i: int) -> bytes:
    s = w["slots"][i]
    return b[s["start"]:s["end"]]


def target(base: bytes) -> dict:
    """tgt for sm64_swap.retarget: BODY's T-pose joint positions (game units), ground 0, the FACE's height."""
    a = M.assemble(base)
    w = inv.parse_wrs(base)
    sk = M.parse_nodes(_slot(base, w, 1))
    T = np.array([m[3, :3] for m in sk["world"]])
    face = next((p for p in a["prims"] if p["name"] == "face"), None)
    Wt = []
    for t in T:
        m = np.eye(4)
        m[3, :3] = t
        Wt.append(m)
    return {"T": T, "W": Wt, "parent": sk["parent"], "ground": float(min(p["pos"][:, 1].min() for p in a["prims"])),
            "head_h": float(np.ptp(face["pos"][:, 1])) if face is not None else 2.7, "joints": sk["count"]}


def palette_of(sk: dict) -> dict[int, int]:
    """node -> palette slot; a node without vertices takes its nearest descendant's, else its nearest ancestor's."""
    pal, parent, n = sk["palette"], sk["parent"], sk["count"]
    kids = {k: [c for c in range(n) if parent[c] == k] for k in range(n)}
    out = {}
    for k in range(n):
        if pal[k] >= 0:
            out[k] = pal[k]
            continue
        q, hit = list(kids[k]), None
        while q and hit is None:
            c = q.pop(0)
            hit = pal[c] if pal[c] >= 0 else None
            q += kids[c]
        p = parent[k]
        while hit is None and p >= 0:
            hit = pal[p] if pal[p] >= 0 else None
            p = parent[p]
        out[k] = hit if hit is not None else min(x for x in pal if x >= 0)
    return out


# --- batches -------------------------------------------------------------------------------------------------------
def make_batches(parts: list[dict]) -> list[dict]:
    """parts [{mtx, P, N, UV (page pixels), F}] -> decode_batches-style batches (loose triangles, VU addresses in the
    double buffer of each batch's parity)."""
    out = []
    for part in parts:
        F = [tuple(int(x) for x in f) for f in part["F"]]
        i = 0
        while i < len(F):
            vmap, tris = {}, []
            while i < len(F) and len(tris) < MAX_BATCH_TRIS:
                new = [v for v in dict.fromkeys(F[i]) if v not in vmap]
                if len(vmap) + len(new) > MAX_BATCH_VERTS:
                    break
                for v in new:
                    vmap[v] = len(vmap)
                tris.append([vmap[v] for v in F[i]])
                i += 1
            if not tris:
                raise FormatError("a triangle does not fit an empty batch")
            verts = []
            for v in vmap:
                u, t = part["UV"][v]
                verts.append({"st": [float(u) / PAGE, float(t) / PAGE - 1.0, 1.0], "n": [*map(float, part["N"][v]), 1.0],
                              "p": [*map(float, part["P"][v]), 1.0], "mtx": part["mtx"]})
            out.append({"verts": verts, "loose": tris, "strips": []})
    for k, bt in enumerate(out):
        base = 0x200 if k % 2 == 0 else 0x100
        bt["loose"] = [[base + 1 + 3 * v for v in t] for t in bt["loose"]]
    return out


def speck(blk: bytes) -> bytes:
    """A model slot with its node records kept and one zero-area triangle drawn at its first palette joint."""
    sk = M.parse_nodes(blk)
    pal = min(p for p in sk["palette"] if p >= 0)
    nn = sk["count"]
    v = {"st": [0.5, -0.5, 1.0], "n": [0.0, 1.0, 0.0, 1.0], "p": [0.0, 0.0, 0.0, 1.0],
         "mtx": M.MATRIX_BASE + M.MATRIX_STRIDE * pal}
    bt = {"verts": [dict(v) for _ in range(3)], "strips": [], "loose": [[0x201, 0x204, 0x207]]}
    return M.encode_model(blk[M.NODE_BASE:M.NODE_BASE + nn * M.NODE_SIZE], nn, [bt],
                          sum(p >= 0 for p in sk["palette"]))


def blank_alpha(blk: bytes) -> bytes:
    """ALPHA layer with the same layout and counts, every vertex position collapsed onto the origin (draws nothing)."""
    al = M.parse_alpha(blk)
    out = bytearray(blk)
    for k in range(len(al["positions"])):
        struct.pack_into("<3f", out, al["vertex_offset"] + k * M.ALPHA_VERTEX, 0.0, 0.0, 0.0)
    return bytes(out)


# --- texture -------------------------------------------------------------------------------------------------------
def quantize(img: np.ndarray, n: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """RGBA page -> (indices, palette RGBA) with Pillow's median cut (alpha kept as opaque / clear)."""
    from PIL import Image
    rgb = Image.fromarray(np.ascontiguousarray(img[..., :3]), "RGB")
    q = rgb.quantize(colors=n - 1, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    idx = np.asarray(q, np.uint8).copy()
    pal = np.zeros((n, 4), np.uint8)
    p = np.array(q.getpalette()[:3 * (n - 1)], np.uint8).reshape(-1, 3)
    pal[:len(p), :3] = p
    pal[:, 3] = 255
    clear = img[..., 3] < 128
    if clear.any():
        idx[clear] = n - 1
        pal[n - 1] = (0, 0, 0, 0)
    return idx, pal


def encode_texture(slot: bytes, rgba: np.ndarray) -> bytes:
    """The container's own texture packet with its texels and CLUT replaced (GIF registers untouched)."""
    if rgba.shape[:2] != (PAGE, PAGE):
        raise FormatError(f"the page is {PAGE}x{PAGE}, got {rgba.shape[1]}x{rgba.shape[0]}")
    size = struct.unpack_from("<I", slot, 4)[0]
    xf = M._gif_transfers(slot[0x80:0x80 + size])
    if len(xf) < 2 or xf[0]["dpsm"] != 0 or (xf[0]["w"], xf[0]["h"]) != (PAGE // 2, PAGE // 2):
        raise FormatError("texture packet is not the 256x256 CT32 upload of a 512x512 PSMT8 page")
    idx, pal = quantize(rgba)
    mem = np.zeros(PAGE * PAGE, np.uint8)
    mem[M._addr8(PAGE, PAGE, PAGE // 64).reshape(-1)] = idx.reshape(-1)
    ct32 = mem[M._addr32(PAGE // 2, PAGE // 2, PAGE // 128).reshape(-1, 1) + np.arange(4)].reshape(-1).tobytes()
    perm = [(i & ~0x18) | ((i & 8) << 1) | ((i & 0x10) >> 1) for i in range(256)]
    clut = np.zeros((256, 4), np.uint8)
    clut[perm] = pal
    clut[:, 3] = np.where(pal[:, 3] >= 128, 0x80, 0)
    out = bytearray(slot)
    for x, data in ((xf[0], ct32), (xf[1], clut.tobytes())):
        if len(data) != len(x["data"]):
            raise FormatError("the new image data does not match the packet's transfer size")
        out[0x80 + x["at"]:0x80 + x["at"] + len(data)] = data
    return bytes(out)


# --- container -------------------------------------------------------------------------------------------------------
def rebuild_wrs(b: bytes, replace: dict[int, bytes]) -> bytes:
    """Same slots in the same order, replaced ones swapped in; each slot starts at 0x10 mod 0x80 like the game's."""
    w = inv.parse_wrs(b)
    head = bytearray(b[:inv.WRS_HEADER])
    body = bytearray()
    order = sorted(w["slots"].values(), key=lambda s: s["start"])
    for k, s in enumerate(order):
        pos = inv.WRS_HEADER + len(body)
        if k:
            pad = (0x10 - pos) % 0x80
            body += bytes(pad)
            pos += pad
        struct.pack_into("<I", head, 0x10 + 4 * s["slot"], pos - (0x10 + 4 * s["slot"]))
        body += replace.get(s["slot"], b[s["start"]:s["end"]])
    struct.pack_into("<I", head, 4, inv.WRS_HEADER + len(body))
    return bytes(head) + bytes(body)


# --- fit ---------------------------------------------------------------------------------------------------------------
def fit_character(base: bytes, model: Path, roles: dict, work: Path, name: str, props=(), scale=None,
                  blender: str | None = None, max_tris: int = MAX_TRIS, progress=lambda p, m: None) -> dict:
    """Library model -> {parts (per joint, game units, page-pixel UVs), page (RGBA 512x512), report}; independent of
    which container it is encoded into (all 58 share the BODY tree)."""
    from .aki_wrestling import _bake_parts, _decimate_parts
    from .sm64_swap import load_rig, retarget
    tgt = target(base)
    progress(15, f"Retargeting {name} onto the Def Jam skeleton")
    rig = load_rig(Path(model), roles, props)
    prims, rep = retarget(rig, tgt, scale, JMAP)
    mats, mkey = [], {}
    P, N, UV, JV, F, FM, n0 = [], [], [], [], [], [], 0
    for p in prims:
        key = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
        if key not in mkey:
            mkey[key] = len(mats)
            mats.append({"tex": p["tex"], "color": p["color"]})
        P.append(p["pos"]); N.append(p["nrm"]); UV.append(p["uv"]); JV.append(p["J"][:, 0])
        F.append(p["tris"] + n0)
        FM.append(np.full(len(p["tris"]), mkey[key]))
        n0 += len(p["pos"])
    P, N, UV, JV, F, FM = (np.concatenate(x) for x in (P, N, UV, JV, F, FM))
    part = np.array([np.bincount(JV[f]).argmax() for f in F])
    src_tris = len(F)
    caps = {}
    for o in set(part.tolist()):
        share = (part == o).sum() / max(len(F), 1)
        nf = max(12, int(max_tris * share))
        caps[o] = (3 * nf, nf + 2)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    progress(35, "Fitting the parts into the triangle budget")
    cur = _decimate_parts(P, N, UV, F, FM, part.astype(object), mats, caps, work, blender, progress)
    keys = sorted(cur)
    progress(60, "Baking the texture page")
    img, parts_v = _bake_parts([cur[o] for o in keys], mats, PAGE, PAGE, [None] * len(keys))
    out, dropped = [], 0
    for o, (vp, vn, vu, faces) in zip(keys, parts_v):
        faces = [list(f) for f in faces]
        cap = caps[o][1]
        while len(faces) > cap:                              # no Blender: drop the smallest faces to the budget
            area = [np.linalg.norm(np.cross(np.subtract(vp[f[1]], vp[f[0]]), np.subtract(vp[f[2]], vp[f[0]]))) for f in faces]
            faces.pop(int(np.argmin(area)))
            dropped += 1
        if faces:
            out.append({"joint": int(o), "P": np.array(vp, float), "N": np.array(vn, float), "UV": np.array(vu, float),
                        "F": np.array(faces, int)})
    rgba = img.copy()
    rgba[..., 3] = 255
    return {"parts": out, "page": rgba, "report": {"retarget": rep, "source_triangles": int(src_tris),
                                                   "triangles": int(sum(len(p["F"]) for p in out)), "dropped": dropped}}


def encode_container(base: bytes, fit: dict) -> tuple[bytes, dict]:
    """A fitted character -> this container with BODY/BODY2 replaced, FACE/hands/alpha hidden, the page swapped."""
    w = inv.parse_wrs(base)
    rep: dict = {}
    replace = {}
    for slot in (1, 2):
        if slot not in w["slots"]:
            continue
        blk = _slot(base, w, slot)
        sk = M.parse_nodes(blk)
        pal = palette_of(sk)
        parts = [{**p, "mtx": M.MATRIX_BASE + M.MATRIX_STRIDE * pal[p["joint"]]} for p in fit["parts"]]
        bts = make_batches(parts)
        nn = sk["count"]
        replace[slot] = M.encode_model(blk[M.NODE_BASE:M.NODE_BASE + nn * M.NODE_SIZE], nn, bts,
                                       sum(p >= 0 for p in sk["palette"]))
        rep[M.PARTS[slot]] = {"batches": len(bts), "bytes": len(replace[slot]), "was": len(blk)}
    for slot in (3, 4, 5):
        if slot in w["slots"]:
            replace[slot] = speck(_slot(base, w, slot))
    for slot in (6, 7):
        if slot in w["slots"]:
            replace[slot] = blank_alpha(_slot(base, w, slot))
    replace[18] = encode_texture(_slot(base, w, 18), fit["page"])
    return rebuild_wrs(base, replace), rep


def verify_container(new: bytes, fit: dict) -> dict:
    """Read the written container back with the reader: BODY's triangles and winding, the page, hidden parts."""
    a = M.assemble(new)
    w = inv.parse_wrs(new)
    body = next(r for r in a["report"] if r["slot"] == 1)
    page = M.parse_texture(_slot(new, w, 18))
    hidden = {r["part"]: r.get("triangles") for r in a["report"] if r["slot"] in (3, 4, 5)}
    want = sum(len(p["F"]) for p in fit["parts"])
    ok = (body["triangles"] == want and body["winding"] >= M.MIN_WINDING and page["width"] == PAGE
          and all(t == 1 for t in hidden.values()))
    return {"ok": bool(ok), "body_triangles": body["triangles"], "expected": want, "winding": body["winding"],
            "hidden_parts": hidden, "assembled": a}


BUDGETS = (MAX_TRIS, 1700, 1450, 1250, 1050, 900, 750)


def fit_fitting(bases: dict[int, bytes], sizes: dict[int, int], jb: dict, work: Path, blender=None,
                progress=lambda p, m: None) -> dict:
    """Fit once, encode into every target container; lower the triangle budget until all of them fit their data.bin
    entries. -> {character, fit, max_tris, entries [{index, wrestler, bytes, budget, slots, sha256, data}],
    preview_from}"""
    first = bases[next(iter(bases))]
    last = None
    for max_tris in BUDGETS:
        fit = fit_character(first, jb["model"], jb["roles"], work, jb["name"], jb.get("props", ()), jb.get("scale"),
                            blender, max_tris, progress)
        rows, over = [], []
        for i, base in bases.items():
            new, enc = encode_container(base, fit)
            if len(new) > sizes[i]:
                over.append((i, len(new), sizes[i]))
                break
            chk = verify_container(new, fit)
            if not chk["ok"]:
                raise FormatError(f"entry {i}: the written container does not read back: "
                                  f"{ {k: v for k, v in chk.items() if k != 'assembled'} }")
            rows.append({"index": i, "wrestler": M.NAMES.get(i), "bytes": len(new), "budget": sizes[i], "slots": enc,
                         "sha256": hashlib.sha256(new).hexdigest(), "data": new})
        if not over:
            return {"character": jb["name"], "fit": fit["report"], "max_tris": max_tris, "entries": rows,
                    "preview_from": rows[0]["data"]}
        last = over[0]
        progress(40, f"{jb['name']}: {last[1]} bytes over the {last[2]}-byte entry at {max_tris} triangles; retrying")
    raise FormatError(f"{jb['name']} does not fit entry {last[0]} even at {BUDGETS[-1]} triangles ({last[1]} > {last[2]})")


# --- disc --------------------------------------------------------------------------------------------------------------
def find_wrestler(query: str) -> list[int]:
    """'player' -> the 12 story heroes; a name (any costume) or 'name 2' / 'wrs205' -> data.bin indices."""
    q = (query or "player").strip().lower()
    if q in ("player", "p1", "hero"):
        return list(STORY_HEROES)
    if re.fullmatch(r"wrs\d{3}", q):
        i = int(q[3:])
        if i in M.NAMES:
            return [i]
    def norm(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())
    key = norm(re.sub(r"costume", "", q))
    ros = M.roster()
    exact = [r["data_index"] for r in ros if key in {norm(a) for a in r["aliases"]} | {r["slug"][8:].replace("_", "")}]
    if exact:
        return exact
    raise LookupError(f"no Def Jam wrestler matches {query!r}")


def build_disc(iso: Path, out_iso: Path, jobs: list[dict], work: Path, blender=None, progress=lambda p, m: None) -> dict:
    """jobs [{indices, model, roles, name, props, scale}] -> a copy of the ISO with each named data.bin entry patched."""
    disc = inv.Iso(iso)
    ident = inv.identify(disc)
    if not ident["exact_build"]:
        raise FormatError(f"{ident['serial']} v{ident['version']}: the writer is built on {inv.SERIAL} v{inv.VERSION} only")
    ents = inv.entries(disc)
    lba = disc.files[inv.DATA_NAME][0]
    patches, reports = [], []
    for jb in jobs:
        bases = {i: inv.read_entry(disc, ents[i]) for i in jb["indices"]}
        rep = fit_fitting(bases, {i: ents[i]["size"] for i in bases}, jb, Path(work) / re.sub(r"\W+", "_", jb["name"])[:40],
                          blender, progress)
        for e in rep["entries"]:
            patches.append({"offset": (lba + ents[e["index"]]["sector"]) * 2048,
                            "data": e.pop("data").ljust(ents[e["index"]]["size"], b"\0")})
        reports.append(rep)
    out_iso = Path(out_iso)
    out_iso.parent.mkdir(parents=True, exist_ok=True)
    progress(85, f"Copying the disc image ({Path(iso).stat().st_size >> 20} MB)")
    shutil.copyfile(iso, out_iso)
    with open(out_iso, "r+b") as f:
        for p in patches:
            f.seek(p["offset"])
            f.write(p["data"])
    back = inv.Iso(out_iso)
    for p in patches:
        with open(out_iso, "rb") as f:
            f.seek(p["offset"])
            if f.read(len(p["data"])) != p["data"]:
                raise RuntimeError("the patched image does not read back")
    if inv.identify(back)["files"] != ident["files"]:
        raise RuntimeError("the patched image's data.bin table changed")
    return {"image": str(out_iso), "reports": reports}


# --- characters op=use / op=match ---------------------------------------------------------------------------------------
def mod_name(pairs: list[tuple[dict, str]], title: str | None = None) -> str:
    if title and len(pairs) > 1:
        return "djv_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:48]
    return "djv_" + "_vs_".join(f"{m['slug']}_as_{re.sub(r'[^a-z0-9]+', '_', w.lower()).strip('_')}" for m, w in pairs)[:96]


def build_mod(cfg, game: dict, pairs: list[tuple[dict, str]], progress=lambda p, m: None, root: Path | None = None,
              title: str | None = None) -> dict:
    from . import characters as C, filemods
    from .sm64_swap import _blender
    root = root or C.library_root(cfg)
    gid = game["game_id"]

    class Ctx:
        config = cfg
    iso = M._source_iso(Ctx(), game)
    jobs = []
    for meta, slot in pairs:
        roles = (meta.get("rig") or {}).get("roles") or {}
        if "hip" not in roles:
            raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't map it onto a wrestler")
        jobs.append({"indices": find_wrestler(slot), "model": root / meta["slug"] / meta["model"], "roles": roles,
                     "name": meta["name"], "props": [p["node"] for p in meta.get("props") or []],
                     "scale": (meta.get("rig") or {}).get("scale")})
    name = mod_name(pairs, title)
    work = Path(cfg.cache) / "characters_build" / name
    shutil.rmtree(work, ignore_errors=True)
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    img = d / Path(iso).name
    b = build_disc(iso, img, jobs, work, _blender(cfg), progress)
    previews = []
    for (meta, _slot_name), rep in zip(pairs, b["reports"]):
        tdir = root / meta["slug"] / "targets"
        tdir.mkdir(parents=True, exist_ok=True)
        new = rep.pop("preview_from")
        a = M.assemble(new)
        page = M.parse_texture(new[inv.parse_wrs(new)["slots"][18]["start"]:])["rgba"]
        glb = M.write_glb(tdir / "djv_wrestler.glb", a, f"{meta['slug']}_djv", page)
        try:
            previews.append(str(C.render_preview(glb, tdir / "djv_preview.png")))
        except Exception:                                  # noqa: BLE001 - previews are informational
            pass
    mj = {"name": name, "game_id": gid, "image": img.name, "title": title or " vs ".join(m["name"] for m, _ in pairs),
          "built": time.time(), "files": ["DATA/DATA.BIN: WRS wrestler entries (gbox.defjam_writer)"],
          "characters": [m["slug"] for m, _ in pairs],
          "replaces": [", ".join(f"{e['wrestler']} #{e['index']}" for e in r["entries"]) for r in b["reports"]],
          "entries": [e for r in b["reports"] for e in r["entries"]], "verified_in_game": False}
    (d / ".gbox-mod.json").write_text(json.dumps(mj))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": img.name, "previews": previews, "reports": b["reports"]}


def use(ctx, meta: dict, game: dict, inp, pairs: list | None = None, title: str | None = None) -> dict:
    """characters op=use / op=match: slot = a wrestler's name ('player' = the four story heroes, every costume)."""
    from . import characters as C, filemods
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "missing": needs(game), "message": needs(game)["have"]}
    if not C.library_root(ctx.config).is_dir():           # not the control plane: build there
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
        args = {"op": inp.op, "character": inp.character, "game_id": gid, "slot": inp.slot, "rebuild": inp.rebuild,
                "launch": False, "pairs": inp.pairs, "title": inp.title}
        j = C._job(ctx, "characters", args, cp, 3600)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        return r
    pairs = pairs or [(meta, inp.slot or "player")]
    name = mod_name(pairs, title)
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    built = None
    if inp.rebuild or not have:
        built = build_mod(ctx.config, game, pairs, ctx.progress, title=title)
        for m, slot in pairs:
            C._api(ctx, "POST", f"/api/characters/{m['slug']}/targets",
                   json={"game_id": gid, "slot": slot, "mod": name, "nodes": [C.HOST_OS],
                         "notes": "replaces the wrestler's meshes and texture page in data.bin (the game's skeleton, "
                                  "moves and animations); not yet verified in an emulator; preview targets/djv_preview.png"})
    res = {"mod": name, "build": built, "replaces": ", ".join(f"{s} -> {m['name']}" for m, s in pairs),
           "verified_in_game": False}
    return res | {"status": "built" if built else "ready",
                  "message": f"Mod {name} is built (a patched copy of the disc). It has not been tested in an emulator "
                             "yet: launch it on a test worker and pick the replaced wrestler."}


def match(ctx, chars: list, game: dict, inp, pairs_in: list[tuple[str, str]], title: str | None = None) -> dict:
    from .characters import best_match
    pairs, used = [], set()
    for cq, wq in pairs_in:
        meta = best_match(chars, cq)
        if not meta:
            raise LookupError(f"{cq!r} isn't in the collection")
        idx = tuple(find_wrestler(wq or "player"))
        if used & set(idx):
            raise ValueError(f"{wq} is already replaced in this build")
        used |= set(idx)
        pairs.append((meta, wq or "player"))
    return use(ctx, pairs[0][0], game, inp, pairs, title)


def needs(game: dict) -> dict:
    return {"target": "a wrestler (data/data.bin WRS container)", "format": "WRS / VIF / GS (gbox/defjam_models.py)",
            "steps": [], "have": "Def Jam - Vendetta (USA) PS2 SLUS_206.39 v1.00 only (gbox/defjam_writer.py)"}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.defjam_writer", description=__doc__.split("\n")[0])
    ap.add_argument("iso")
    ap.add_argument("model")
    ap.add_argument("roles", help="JSON file or inline JSON {role: joint name}")
    ap.add_argument("out")
    ap.add_argument("wrestler", nargs="+")
    ap.add_argument("--max-tris", type=int, default=MAX_TRIS)
    a = ap.parse_args(argv)
    roles = json.loads(Path(a.roles).read_text() if Path(a.roles).is_file() else a.roles)
    jobs = [{"indices": [i for q in a.wrestler for i in find_wrestler(q)], "model": Path(a.model), "roles": roles,
             "name": Path(a.model).stem}]
    r = build_disc(Path(a.iso), Path(a.out), jobs, Path(a.out).with_suffix(".work"))
    for rep in r["reports"]:
        rep.pop("preview_from", None)
    print(json.dumps(r, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
