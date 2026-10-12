"""A/B evidence for a player-model swap with no vision model: stock vs mod frames of the same deterministic sequence.

Many games play a deterministic attract/demo sequence when left idle (Super Mario 64: 800 idle frames on the title
screen start demo 1, about 41-64 s after a fresh boot). Boot the stock ROM and the mod on an EMPTY node, so a same-game
relaunch can't carry the previous session's RAM over, and capture both without any input. Then:

  * best_pairs() aligns each mod frame to its closest stock frame (mean absolute difference at 160x120 grey);
  * player_blob() finds where an aligned pair differs: a swap changes ONE compact region (the player), so the largest
    4-connected group of changed 8x8 blocks should hold nearly all changed blocks;
  * compare() counts the old character's signature colours on the changed pixels of that region (Mario: saturated red cap/shirt, blue
    overalls) in the stock crop and in the mod crop.

A swap is shown when the scenes match, the difference is one blob, and the stock signature colour vanishes in the mod.
CLI: python -m gbox.frame_ab MOD_DIR STOCK_DIR [--mod-window 41 64] [--stock-window 36 70] [--json out.json]
(frames named <tag>_<seconds>.jpg, as written by the capture harness).
"""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path

import numpy as np


def _rgb(img) -> np.ndarray:
    a = np.asarray(img)
    if a.ndim == 2:
        a = np.stack([a] * 3, -1)
    return a[..., :3].astype(np.int16)


def small_gray(img, size=(160, 120)) -> np.ndarray:
    """Block-mean grey thumbnail (vectorised, no PIL): frames of one source share a size, so pairs compare like for like."""
    a = _rgb(img).mean(2)
    h, w = a.shape
    cols, rows = size
    if h >= rows and w >= cols:
        ry, rx = h // rows, w // cols
        return a[:ry * rows, :rx * cols].reshape(rows, ry, cols, rx).mean((1, 3)).astype(np.float32)
    return a[np.arange(rows) * h // rows][:, np.arange(cols) * w // cols].astype(np.float32)


def best_pairs(mod: list, stock: list, k: int = 4, min_gap: float = 2.0) -> list[tuple[float, int, int]]:
    """mod/stock: [(t_seconds, rgb array)]. -> up to k (mad, mod_index, stock_index), best first, mod frames >= min_gap s apart."""
    if not mod or not stock:
        return []
    ss = np.stack([small_gray(f) for _, f in stock])
    pairs = []
    for i, (_, f) in enumerate(mod):
        d = np.abs(ss - small_gray(f)).mean((1, 2))
        j = int(d.argmin())
        pairs.append((float(d[j]), i, j))
    pairs.sort()
    out: list[tuple[float, int, int]] = []
    for p in pairs:
        if all(abs(mod[p[1]][0] - mod[q[1]][0]) >= min_gap for q in out):
            out.append(p)
        if len(out) == k:
            break
    return out


def player_blob(a, b, thresh: int = 45, block: int = 8, fill: float = 0.25, pad: int = 16) -> dict:
    """Largest connected region where two aligned frames differ -> {bbox [x1,y1,x2,y2] | None, blob_blocks, all_blocks,
    changed_frac}."""
    a, b = _rgb(a), _rgb(b)
    diff = np.abs(a - b).max(2) > thresh
    h, w = diff.shape
    hb, wb = h // block, w // block
    blk = diff[:hb * block, :wb * block].reshape(hb, block, wb, block).mean((1, 3)) > fill
    seen = np.zeros_like(blk)
    best: list[tuple[int, int]] = []
    for y0, x0 in zip(*np.nonzero(blk)):
        if seen[y0, x0]:
            continue
        comp, q = [], deque([(int(y0), int(x0))])
        seen[y0, x0] = True
        while q:
            y, x = q.popleft()
            comp.append((y, x))
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < hb and 0 <= xx < wb and blk[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    q.append((yy, xx))
        if len(comp) > len(best):
            best = comp
    out = {"bbox": None, "blob_blocks": len(best), "all_blocks": int(blk.sum()), "changed_frac": round(float(diff.mean()), 4)}
    if best:
        ys, xs = [p[0] for p in best], [p[1] for p in best]
        out["bbox"] = [max(0, min(xs) * block - pad), max(0, min(ys) * block - pad),
                       min(w, (max(xs) + 1) * block + pad), min(h, (max(ys) + 1) * block + pad)]
    return out


def mario_colors(crop, mask=None) -> dict:
    """Pixels in Mario's palette: saturated red (cap, shirt) and saturated blue (overalls); only where mask is set."""
    c = _rgb(crop).astype(np.float32)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    m = np.ones(r.shape, bool) if mask is None else mask
    return {"red": int(((r > 120) & (r > 2.2 * g) & (r > 2.2 * b) & m).sum()),
            "blue": int(((b > 90) & (b > 1.8 * r) & (b > 1.5 * g) & m).sum())}


def compare(mod_frame, stock_frame, min_red: int = 300, keep: float = 0.05, one_blob: float = 0.8) -> dict:
    """One aligned pair -> blob + signature colours + verdict (swapped: Mario's red is gone from the player region)."""
    blob = player_blob(mod_frame, stock_frame)
    res = dict(blob, stock_red=0, mod_red=0, stock_blue=0, mod_blue=0, swapped=False)
    if blob["bbox"] is None:
        return res
    x1, y1, x2, y2 = blob["bbox"]
    sc, mc = _rgb(stock_frame)[y1:y2, x1:x2], _rgb(mod_frame)[y1:y2, x1:x2]
    changed = np.abs(sc - mc).max(2) > 45                 # count only pixels that differ: shared background cancels out
    s, m = mario_colors(sc, changed), mario_colors(mc, changed)
    res.update(stock_red=s["red"], mod_red=m["red"], stock_blue=s["blue"], mod_blue=m["blue"])
    res["swapped"] = bool(s["red"] >= min_red and m["red"] <= keep * s["red"]
                          and blob["blob_blocks"] >= one_blob * max(1, blob["all_blocks"]))
    return res


def _frames(folder: Path, lo: float, hi: float) -> list:
    from PIL import Image
    out = []
    for p in sorted(Path(folder).glob("*.jpg")):
        m = re.search(r"_(\d+(?:\.\d+)?)\.jpg$", p.name)
        if m and lo <= float(m.group(1)) <= hi:
            out.append((float(m.group(1)), np.asarray(Image.open(p).convert("RGB")), p.name))
    return out


def main(argv=None) -> dict:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("mod_dir")
    ap.add_argument("stock_dir")
    ap.add_argument("--mod-window", nargs=2, type=float, default=(41, 64))
    ap.add_argument("--stock-window", nargs=2, type=float, default=(36, 70))
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    mod, stock = _frames(Path(a.mod_dir), *a.mod_window), _frames(Path(a.stock_dir), *a.stock_window)
    rows = []
    for mad, i, j in best_pairs([(t, f) for t, f, _ in mod], [(t, f) for t, f, _ in stock]):
        rows.append({"mod": mod[i][2], "stock": stock[j][2], "mad": round(mad, 2)} | compare(mod[i][1], stock[j][1]))
    rep = {"pairs": rows, "swapped": bool(rows) and all(r["swapped"] for r in rows)}
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    main()
