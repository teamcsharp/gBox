"""Metal Gear Solid: The Twin Snakes (GC): the WHOLE cast replaced in one disc image - every character model of every
stage (gameplay areas, cut-scene stages, close-ups, first-person arms) by who it is, and the codec portraits.

* Who a model is comes from its texture set (gbox.twin_snakes.IDENTITIES: sna_def / sna_dmo / sna_nkd_dmo ... are
  all Snake). Every humanoid model of a planned character (the MGS2 skeleton: 21 bones, 53 on cut-scene models with
  fingers and face) is refitted with that character's donor (gbox.twin_snakes_swap: shared retarget, atlas over the
  model's colour image, re-encoded in the model's own byte size); the character's props are hidden; each stage is
  rebuilt in its own sector span, shrinking the budgets of that stage's models until it fits. Models whose colour
  image is not in their own stage (they draw with another stage's textures) are left original and reported.
* demo.dat is the cut scenes' command stream (camera, actor and motion packets, no models): the cut scenes draw the
  models of the demo* / r_demo* / r_dmo* stages, which this build replaces, so demo.dat stays as it is.
* Codec (shared/face.dat): one uncompressed stage per call setup (f00a .. f20a), one .tri set per speaker
  (twin_snakes.CODEC). A set holds 104 x 178 CMPR portraits (expressions) and smaller eye / mouth patches that the
  codec draws over them. Each portrait becomes a front bust render of the speaker's donor (head and shoulders),
  tinted with the set's own codec green (luminance histogram and colour ramp taken from the stock portrait, its scan
  lines kept); each patch becomes the crop of the new portrait where the patch sits on the stock one (found by
  template matching), so blinking and talking frames show the donor too. Name tags and voices are not touched.

  python -m gbox.twin_snakes_cast <disc.iso> <library dir> <mapping.json> <out dir>   (writes <out>/disc<N>.iso)
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import time
from pathlib import Path

import numpy as np

from . import twin_snakes as TS
from . import twin_snakes_swap as W
from . import ts_kms as K
from . import ts_stage as S
from . import ts_tex as T

SCALES = (1.0, 0.85, 0.72, 0.6, 0.5, 0.4)
FACE_DAT = "shared/face.dat"

# The operator's full-cast request (2026-10-13): Sonic Adventure 1 / 2 characters, distinct where the pool allows.
SONIC_CAST = {
    "snake": "sonic", "meryl": "sa2_amy_rose", "otacon": "sa2_tails", "liquid": "sa2_shadow",
    "ocelot": "sa2_dr_eggman", "wolf": "sa2_rouge", "mantis": "sa2_chaos_0", "raven": "sa1_big",
    "ninja": "sa2_metal_sonic", "decoy": "sa1_tikal", "anderson": "sa1_tails", "baker": "sa2_super_sonic",
    "naomi": "sa2_tikal", "campbell": "sa1_amy", "johnny": "sa1_sonic", "soldier_arctic": "sa2_knuckles",
    "soldier_indoor": "sa1_knuckles", "soldier_gas": "sa2_super_shadow", "soldier_heavy": "sa1_e102",
    # codec-only speakers
    "mei_ling": "sa1_super_sonic", "nastasha": "sa1_tikal", "miller": "sa2_shadow", "houseman": "sa2_dr_eggman",
}


class Skip(Exception):
    pass


def humanoid(data: bytes) -> bool:
    """A model on the MGS2 skeleton (21 bones, or 53 with fingers / face after them)."""
    if len(data) < 0x60:
        return False
    nb, g = struct.unpack_from(">I", data, 4)[0], struct.unpack_from(">I", data, 0x5C)[0]
    if not 21 <= nb <= 200 or g < 0x60 + 0x40 * nb or g > len(data):
        return False
    return [struct.unpack_from(">i", data, 0x60 + 0x40 * k + 4)[0] for k in range(21)] == K.PARENTS


class Fits:
    """Fits cached by (model bytes, donor, budget scale): the same model sits in many stages."""

    def __init__(self, progress=None):
        self.cache: dict = {}
        self.progress = progress or (lambda p, m: None)

    def get(self, donor: W.Donor, data: bytes, own_set: T.TextureSet | None, scale: float, label: str):
        sha = hashlib.sha1(data).hexdigest()
        if sha not in self.cache:
            m = K.parse(data)
            layer = W.main_colour(m)
            self.cache[sha] = (m, layer, K.colour_texture(layer) if layer else 0)
        m, layer, col = self.cache[sha]
        img = own_set.by_hash(col) if own_set is not None and col else None    # per stage: is its texture here?
        if img is None:
            raise Skip("its colour texture is not in its own stage (drawn with another stage's set)")
        key = (sha, donor.slug, round(scale, 3), img.w, img.h)
        if key not in self.cache:
            try:
                self.progress(None, f"Fitting {donor.name} on {label} (x{scale:.2f})")
                fit, atlas = W.fit_model(donor, m, label, scale, (img.w, img.h))
                self.cache[key] = (fit.data, atlas, layer, m.tex_set, fit.report)
            except Exception as e:                        # noqa: BLE001 - reported per model
                self.cache[key] = Skip(f"fit failed: {str(e)[:200]}")
        got = self.cache[key]
        if isinstance(got, Skip):
            raise got
        return got


def build_stage_dat(stage_dat: bytes, plan: dict[str, W.Donor], progress=None) -> tuple[bytes, dict]:
    """Every stage: every humanoid model of a planned character refitted (gameplay and cut scenes)."""
    progress = progress or (lambda p, m: None)
    sd = S.StageDat.from_bytes(stage_dat)
    out = bytearray(stage_dat)
    fits = Fits(progress)
    reports = []
    for i, (name, _sec) in enumerate(sd.entries):
        off, span = sd.span(i)
        if span <= 0:
            continue
        try:
            st = sd.stage(i)
        except Exception:                                 # noqa: BLE001 - not a model stage
            continue
        cands = []
        for f in st.files():
            if f.type == S.MODEL and humanoid(f.data):
                who = TS.identity_of(f.data)
                if who in plan:
                    cands.append((f, who))
        if not cands:
            continue
        progress(100 * i / len(sd.entries), f"Stage {name}: {len(cands)} character model(s)")
        sets = {f.hash: T.TextureSet(f.data) for f in st.files() if f.type == S.TEXTURES}
        done = None
        for scale in SCALES:
            models, layers, atlases, owners, who_of, skipped = {}, [], [], [], {}, {}
            for f, who in cands:
                own = sets.get(struct.unpack_from(">I", f.data, 0x0C)[0] & 0xFFFFFF)
                try:
                    data, atlas, layer, tex_set, _rep = fits.get(plan[who], f.data, own, scale, f"{f.hash:06x}")
                except Skip as e:
                    skipped[f"{f.hash:06x}"] = f"{who}: {e}"
                    continue
                models[f.hash] = data
                layers.append(layer)
                atlases.append(atlas)
                owners.append(tex_set)
                who_of[f"{f.hash:06x}"] = who
            if not models:
                done = (None, {"stage": name, "replaced": {}, "skipped": skipped})
                break
            st = sd.stage(i)                              # fresh pages (a rebuild edits them in place)
            new, rep = W.swap_stage(st, models, layers, atlases, set(models), owners)
            try:
                blob = S.rebuild_stage(st, new)
            except S.StageTooBig:
                continue
            done = (blob, {"stage": name, "replaced": who_of, "skipped": skipped, "hidden": rep["hidden"],
                           "texture_sets": rep["texture_sets"], "budget_scale": scale, "bytes": len(blob), "span": span})
            break
        if done is None:
            reports.append({"stage": name, "replaced": {}, "error": "does not fit its sector span at any budget",
                            "skipped": {f"{f.hash:06x}": who for f, who in cands}})
            continue
        blob, rep = done
        if blob is not None:
            out[off:off + span] = blob + bytes(span - len(blob))
        reports.append(rep)
    covered = {}
    for r in reports:
        for h, who in (r.get("replaced") or {}).items():
            covered.setdefault(who, set()).add(r["stage"])
    return bytes(out), {"stages": reports, "characters": {k: sorted(v) for k, v in covered.items()},
                        "models_fitted": len([k for k, v in fits.cache.items() if isinstance(k, tuple) and not isinstance(v, Skip)])}


# ----------------------------------------------------------------------------------------------- codec

def _barycentric_raster(tris, box, size, ss=3):
    """Front orthographic render of triangles [(P (3,3), UV (3,2), img, colour)] inside box = (x0, x1, y0, y1)
    (world, +Y up, camera on +Z) -> (rgb (h, w, 3) float, alpha (h, w))."""
    w, h = size[0] * ss, size[1] * ss
    x0, x1, y0, y1 = box
    zbuf = np.full((h, w), -np.inf)
    rgb = np.zeros((h, w, 3))
    light = np.array([0.25, 0.45, 0.85])
    light /= np.linalg.norm(light)
    for P, UV, img, col in tris:
        px = (P[:, 0] - x0) / (x1 - x0) * w
        py = (y1 - P[:, 1]) / (y1 - y0) * h
        lo_x, hi_x = int(max(0, np.floor(px.min()))), int(min(w - 1, np.ceil(px.max())))
        lo_y, hi_y = int(max(0, np.floor(py.min()))), int(min(h - 1, np.ceil(py.max())))
        if lo_x > hi_x or lo_y > hi_y:
            continue
        d = (py[1] - py[2]) * (px[0] - px[2]) + (px[2] - px[1]) * (py[0] - py[2])
        if abs(d) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(lo_x, hi_x + 1) + 0.5, np.arange(lo_y, hi_y + 1) + 0.5)
        a = ((py[1] - py[2]) * (gx - px[2]) + (px[2] - px[1]) * (gy - py[2])) / d
        b = ((py[2] - py[0]) * (gx - px[2]) + (px[0] - px[2]) * (gy - py[2])) / d
        c = 1 - a - b
        inside = (a >= -1e-6) & (b >= -1e-6) & (c >= -1e-6)
        if not inside.any():
            continue
        z = a * P[0, 2] + b * P[1, 2] + c * P[2, 2]
        sub = zbuf[lo_y:hi_y + 1, lo_x:hi_x + 1]
        win = inside & (z > sub)
        if not win.any():
            continue
        n = np.cross(P[1] - P[0], P[2] - P[0])
        ln = np.linalg.norm(n)
        shade = 0.45 + 0.55 * abs(float(n @ light) / ln) if ln > 1e-12 else 0.7
        if img is not None:
            u = a * UV[0, 0] + b * UV[1, 0] + c * UV[2, 0]
            v = a * UV[0, 1] + b * UV[1, 1] + c * UV[2, 1]
            th, tw = img.shape[:2]
            tx = np.clip(((u % 1.0) * tw).astype(int), 0, tw - 1)
            ty = np.clip(((v % 1.0) * th).astype(int), 0, th - 1)
            colr = img[ty, tx, :3].astype(float) * (np.asarray(col, float) / 255.0)
        else:
            colr = np.broadcast_to(np.asarray(col, float), gx.shape + (3,))
        sub[win] = z[win]
        rgb[lo_y:hi_y + 1, lo_x:hi_x + 1][win] = colr[win] * shade
    alpha = np.isfinite(zbuf).astype(float)
    # downsample
    rgb = rgb.reshape(size[1], ss, size[0], ss, 3).mean((1, 3))
    alpha = alpha.reshape(size[1], ss, size[0], ss).mean((1, 3))
    return rgb, alpha


def bust(glb: Path, roles: dict, size=TS.PORTRAIT) -> tuple[np.ndarray, np.ndarray]:
    """The donor's head and shoulders seen from the front, framed like a codec portrait (top of the head to below
    the chest joint). -> (rgb float (h, w, 3), coverage (h, w))."""
    from . import characters as C
    from .sm64_swap import load_rig
    rig = load_rig(Path(glb), roles)
    J, ri = rig["joints"], rig["roles"]
    tris = C._triangles(Path(glb))
    head = J[ri["head"]]
    chest = J[ri.get("chest", ri["hip"])]
    allp = np.concatenate([t[0] for t in tris])
    above = allp[allp[:, 1] > chest[1]]
    top = float(above[:, 1].max()) if len(above) else float(allp[:, 1].max())
    span = max(top - float(chest[1]), 1e-6)
    y0, y1 = float(chest[1]) - 0.3 * span, top + 0.04 * span
    h = y1 - y0
    wd = h * size[0] / size[1]
    cx = float(head[0])
    return _barycentric_raster(tris, (cx - wd / 2, cx + wd / 2, y0, y1), size)


def _lum(rgb):
    rgb = np.asarray(rgb, float)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def tint(rgb: np.ndarray, alpha: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """A render in a stock codec portrait's look: its luminance distribution, its colour ramp (the codec green), its
    scan lines; uncovered pixels take the portrait's dark background. -> RGBA uint8."""
    ref = np.asarray(ref, float)[..., :3]
    rl = _lum(ref)
    src = _lum(rgb)
    bg = np.percentile(rl, 8)
    src = np.where(alpha > 0.5, src, -1)
    # histogram match the covered pixels to the stock portrait's luminance
    cov = src >= 0
    out_l = np.full(src.shape, bg)
    if cov.any():
        order = np.argsort(src[cov])
        q = np.sort(rl.ravel())
        ranks = np.empty(cov.sum())
        ranks[order] = np.linspace(0, 1, cov.sum())
        out_l[cov] = np.interp(ranks, np.linspace(0, 1, len(q)), q)
    edge = (alpha > 0.05) & (alpha < 0.95)                # soft silhouette
    out_l[edge] = bg + (out_l[edge] - bg) * alpha[edge]
    # colour ramp: mean stock colour per luminance
    bins = np.clip(rl.astype(int), 0, 255)
    ramp = np.zeros((256, 3))
    have = np.zeros(256, bool)
    for k in range(256):
        m = bins == k
        if m.any():
            ramp[k] = ref[m].mean(0)
            have[k] = True
    idx = np.arange(256)
    for ch in range(3):
        ramp[:, ch] = np.interp(idx, idx[have], ramp[have, ch]) if have.any() else idx
    out = ramp[np.clip(out_l.astype(int), 0, 255)]
    rows = rl.mean(1)
    smooth = np.convolve(rows, np.ones(9) / 9, mode="same")
    factor = np.clip(rows / np.maximum(smooth, 1e-6), 0.6, 1.4)
    out *= factor[:, None, None]
    rgba = np.concatenate([np.clip(out, 0, 255), np.full(out.shape[:2] + (1,), 255.0)], -1)
    return rgba.astype(np.uint8)


def _match(patch: np.ndarray, portraits: list[np.ndarray]) -> tuple[int, int, int]:
    """(portrait index, x, y) where the patch fits a stock portrait best (grey sum of squared differences)."""
    from numpy.lib.stride_tricks import sliding_window_view
    p = _lum(patch)
    ph, pw = p.shape
    best = (np.inf, 0, 0, 0)
    for k, por in enumerate(portraits):
        g = _lum(por)
        if g.shape[0] < ph or g.shape[1] < pw:
            continue
        win = sliding_window_view(g, (ph, pw))
        e = ((win - p) ** 2).mean((2, 3))
        y, x = np.unravel_index(int(np.argmin(e)), e.shape)
        if e[y, x] < best[0]:
            best = (float(e[y, x]), k, int(x), int(y))
    return best[1], best[2], best[3]


def swap_codec_set(ts: T.TextureSet, bust_rgb, bust_alpha) -> dict:
    """Every portrait of a speaker's set replaced by the tinted bust (one look per set: the first stock portrait's
    ramp and scan lines, encoded once), every patch by its crop of the new portrait where it sat on the stock one."""
    ports = [im for im in ts.images if (im.w, im.h) == TS.PORTRAIT]
    if not ports:
        return {"portraits": 0, "patches": 0}
    stock = [ts.rgba(im) for im in ports]
    portrait = tint(bust_rgb, bust_alpha, stock[0])
    patches = 0
    for im in ts.images:
        if (im.w, im.h) == TS.PORTRAIT:
            continue
        _k, x, y = _match(ts.rgba(im), stock)
        crop = portrait[y:y + im.h, x:x + im.w]
        if crop.shape[:2] == (im.h, im.w):
            ts.replace_image(im, crop)
            patches += 1
    encoded: dict = {}
    for im in ports:
        if im.fmt not in encoded:
            encoded[im.fmt] = T.encode(im.fmt, im.w, im.h, portrait) if im.fmt not in (8, 9) else None
        if encoded[im.fmt] is None:
            ts.replace_image(im, portrait)
        else:
            o = ts.tpl + im.data_off
            ts.data[o:o + len(encoded[im.fmt])] = encoded[im.fmt]
    return {"portraits": len(ports), "patches": patches}


def build_face_dat(face_dat: bytes, speakers: dict[str, tuple[Path, dict]], progress=None) -> tuple[bytes, dict]:
    """speakers: {speaker: (donor GLB, rig roles)} -> (new face.dat, report). Same size, every stage in place."""
    progress = progress or (lambda p, m: None)
    sd = S.StageDat.from_bytes(face_dat)
    out = bytearray(face_dat)
    renders, report, done = {}, {}, {}
    for i, (name, _sec) in enumerate(sd.entries):
        off, span = sd.span(i)
        st = sd.stage(i)
        new = {}
        for f in st.files():
            who = TS.CODEC.get(f.hash)
            if f.type != S.TEXTURES or who not in speakers:
                continue
            if who not in renders:
                progress(None, f"Codec portrait: {who}")
                renders[who] = bust(*speakers[who])
            key = (who, hashlib.sha1(f.data).hexdigest())  # the same speaker set sits in many call setups
            if key not in done:
                ts = T.TextureSet(f.data)
                r = swap_codec_set(ts, *renders[who])
                done[key] = (bytes(ts.data), r)
            data, r = done[key]
            new[(S.TEXTURES, f.hash)] = data
            report.setdefault(who, {"stages": [], "portraits": 0, "patches": 0})
            report[who]["stages"].append(name)
            report[who]["portraits"] += r["portraits"]
            report[who]["patches"] += r["patches"]
        if new:
            blob = S.rebuild_stage(st, new)
            out[off:off + span] = blob + bytes(span - len(blob))
    return bytes(out), report


# ----------------------------------------------------------------------------------------------- the disc

def donors_from_library(root: Path, mapping: dict[str, str]) -> dict[str, W.Donor]:
    out, by_slug = {}, {}
    for who, slug in mapping.items():
        if slug not in by_slug:
            meta = json.loads((Path(root) / slug / "meta.json").read_text(encoding="utf-8"))
            rig = meta.get("rig") or {}
            by_slug[slug] = W.load_donor(slug, Path(root) / slug / meta["model"], rig.get("roles"),
                                         meta.get("name", slug), rig.get("scale"))
        out[who] = by_slug[slug]
    return out


def build_disc(cfg, game: dict, image: Path, name: str, root: Path, mapping: dict[str, str], progress=None) -> dict:
    """The full-cast disc image (cache/mods/<game>/<name>): stage.dat and shared/face.dat rewritten in place."""
    import types
    from . import filemods
    from .gcdisc import GCDisc
    progress = progress or (lambda p, m: None)
    t0 = time.time()
    disc = GCDisc(str(image))
    try:
        if disc.game_id != TS.DISC_ID:
            raise ValueError(f"{Path(image).name}: expected {TS.DISC_ID}, got {disc.game_id}")
        sdat, fdat = disc.read(S.STAGE_DAT), disc.read(FACE_DAT)
        disc_no = TS.disc_of(header=disc._r(0, 8))
    finally:
        disc.f.close()
    donors = donors_from_library(root, mapping)
    plan = {k: v for k, v in donors.items() if k in TS.IDENTITIES}
    new_sd, rep = build_stage_dat(sdat, plan, progress)
    t1 = time.time()
    speakers = {who: (donors[who].glb, donors[who].roles) for who in set(TS.CODEC.values()) if who in donors}
    new_fd, frep = build_face_dat(fdat, speakers, progress)
    t2 = time.time()
    work = Path(cfg.cache) / "characters_build" / "twin_snakes" / name
    work.mkdir(parents=True, exist_ok=True)
    (work / "stage.dat").write_bytes(new_sd)
    (work / "face.dat").write_bytes(new_fd)
    cfg_ = cfg if hasattr(cfg, "cache") else types.SimpleNamespace(cache=Path(cfg))
    b = filemods.build_image(cfg_, game["game_id"], Path(image), name,
                             {S.STAGE_DAT: {"from": str(work / "stage.dat")}, FACE_DAT: {"from": str(work / "face.dat")}},
                             progress)
    d = GCDisc(b["image"])
    try:
        for k, v in ((S.STAGE_DAT, new_sd), (FACE_DAT, new_fd)):
            if hashlib.sha256(d.read(k)).digest() != hashlib.sha256(v).digest():
                raise ValueError(f"the image does not hold the rebuilt {k}")
    finally:
        d.f.close()
    for f in ("stage.dat", "face.dat"):
        (work / f).unlink(missing_ok=True)
    return b | {"disc": disc_no, "report": rep, "codec": frep,
                "seconds": {"stages": round(t1 - t0, 1), "codec": round(t2 - t1, 1), "total": round(time.time() - t0, 1)}}


def main(argv=None) -> int:
    import argparse
    import types
    ap = argparse.ArgumentParser(description="Twin Snakes: the whole cast (models + codec) from a mapping")
    ap.add_argument("image")
    ap.add_argument("library")
    ap.add_argument("mapping", help="JSON {character: library slug} or 'sonic' for SONIC_CAST")
    ap.add_argument("cache", help="cache dir: the mod is written to <cache>/mods/<game id>/<name>")
    ap.add_argument("--game-id", default="twin_snakes_cli")
    ap.add_argument("--name", default="tts_full_cast")
    a = ap.parse_args(argv)
    mapping = SONIC_CAST if a.mapping == "sonic" else json.loads(Path(a.mapping).read_text())
    r = build_disc(types.SimpleNamespace(cache=Path(a.cache)), {"game_id": a.game_id}, Path(a.image), a.name,
                   Path(a.library), mapping, lambda p, m: print(m, flush=True))
    print(json.dumps({"image": r["image"], "disc": r["disc"], "seconds": r["seconds"],
                      "characters": r["report"]["characters"], "codec": r["codec"]}, indent=1, default=str))
    (Path(r["dir"]) / "tts-full-cast-report.json").write_text(json.dumps(r["report"] | {"codec": r["codec"]},
                                                                        indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
