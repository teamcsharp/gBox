"""Give a fitted VR Missions player model its own textures by repainting Snake's texture slots in place.

What the disc allows (US VR Missions, init.stg entry 1 = texture DAR 1_0.dar, 128 .pcc textures; gbox.mgs_pcc):
  * Snake's KMD (init/39213.kmd = GV_StrCode("snake")) names 28 textures.  Each is a 4bpp image with a fixed VRAM
    rectangle and CLUT position in its header; KMD face UVs (0..255) are scaled into that rectangle.  The game loads
    them at boot into VRAM, so a slot keeps its size, place and format: only pixels and palette can change.
  * Those 28 slots use two 16-colour CLUTs, (784,226) with 20 slots and (768,226) with 8, each shared with two
    textures of other models (15620/62675 and 54560/62721; models 6049, 16964, 57810).  A CLUT is one palette in
    VRAM, so every member of a group gets the same new palette; the foreign members are re-indexed against it.
  * Snake's textures are also named by three small init models (56141, 16964, 57810: hand/attachment parts).
  * The texture DAR (PSX layout: per entry u16 hash, u8 ext, u8 0, u32 size, data padded to 4 bytes) keeps its total
    size, so init.stg keeps its allocation; bytes are pooled across the repainted entries (pack_dar).

paint(): images are split between the two CLUT groups by colour (32 colours in all), the most used image gets the
largest slot of its group, and the untextured colours share one swatch slot.  Slots no image needs are filled flat.
"""
from __future__ import annotations

import struct

import numpy as np

from . import mgs_pcc as C

SWATCH = ("swatch",)


# ---------------------------------------------------------------------------------------------- DAR (PSX)
def parse_dar(data: bytes) -> list[tuple[int, int, bytes]]:
    """[(hash, ext byte, body)] of a PSX DAR."""
    out, o = [], 0
    while o + 8 <= len(data):
        h, ext, zero, size = struct.unpack_from("<HBBI", data, o)
        if ext == 0 and size == 0:
            break
        out.append((h, ext, bytes(data[o + 8:o + 8 + size])))
        o += 8 + (size + 3 & ~3)
    return out


def pack_dar(entries: list, size: int | None = None) -> bytes:
    """Pack [(hash, ext, body)]; with *size*, pad the last body so the archive is exactly that long."""
    def blob(es):
        return b"".join(struct.pack("<HBBI", h, e, 0, len(b)) + b + b"\0" * (-len(b) % 4) for h, e, b in es)
    data = blob(entries)
    if size is not None:
        if len(data) > size:
            raise ValueError(f"texture archive grew to {len(data)} bytes (allocation {size})")
        h, e, b = entries[-1]
        entries = entries[:-1] + [(h, e, b + b"\0" * (size - len(data)))]
        data = blob(entries)
    return data


# ---------------------------------------------------------------------------------------------- painting
def _wrap(uv: np.ndarray) -> np.ndarray:
    """glTF repeat-wrapped corner UVs of one face -> 0..1 (shift by the floor of the centroid, then clamp)."""
    return np.clip(uv - np.floor(uv.mean(0)), 0.0, 1.0)


def _nearest(rgba: np.ndarray, pal: np.ndarray) -> np.ndarray:
    """Palette index per pixel; transparent pixels take the palette's black entry when it has one."""
    rgb = rgba[..., :3].reshape(-1, 1, 3).astype(np.int32)
    d = ((rgb - pal[None].astype(np.int32)) ** 2).sum(-1)
    clear = np.nonzero((pal.astype(int) // 8).sum(1) == 0)[0]
    if len(clear):
        d[:, clear] = 1 << 30
    idx = d.argmin(1).reshape(rgba.shape[:2]).astype(np.uint8)
    if len(clear):
        idx[rgba[..., 3] < 128] = clear[0]
    return idx


def _encode(like: C.Pcc, pal: np.ndarray, idx: np.ndarray) -> bytes:
    return C.dumps(C.Pcc(like.width, like.height, pal, idx, like.vram, like.clut, like.flags, like.header))


def _levels(like: C.Pcc, pic: np.ndarray, pal: np.ndarray) -> list[bytes]:
    """Encodings from full detail down to one flat colour (each smaller or equal in practice)."""
    from PIL import Image
    out = [_encode(like, pal, _nearest(pic, pal))]
    step = 2
    while step <= max(like.width, like.height):
        small = Image.fromarray(pic, "RGBA").resize((max(1, like.width // step), max(1, like.height // step)),
                                                    Image.Resampling.BOX)
        out.append(_encode(like, pal, _nearest(np.array(small.resize((like.width, like.height),
                                                                     Image.Resampling.NEAREST)), pal)))
        step *= 2
    mean = pic[pic[..., 3] >= 128][:, :4].mean(0) if (pic[..., 3] >= 128).any() else np.array([8, 8, 8, 255])
    flat = np.broadcast_to(mean.astype(np.uint8), pic.shape).copy()
    out.append(_encode(like, pal, _nearest(flat, pal)))
    return out


def paint(snake_textures: dict, pcc_bytes: dict, faces: list) -> tuple[dict, list, dict]:
    """Repaint Snake's texture slots for *faces*.

    snake_textures: {hash: Pcc} of the textures Snake's KMD names (decoded).
    pcc_bytes:      {hash: bytes} of every texture in the archive (to re-index CLUT-sharing foreign textures).
    faces:          [(image key or None, rgba image or None, uv (3,2), rgb colour)] per fitted triangle.
    Returns ({hash: new pcc bytes}, [(texture hash, 8 uv bytes)] per face, report).  The new textures together
    take no more archive bytes (4-byte aligned) than the originals they replace.
    """
    from PIL import Image
    decoded = {h: C.loads(b) for h, b in pcc_bytes.items()}
    use, images, colors = {}, {}, []
    work = []                                             # per face: [key, wrapped uv (3,2)] (key SWATCH: flat colour)
    for key, img, uv, col in faces:
        if key is None or img is None:
            c = tuple(int(v) for v in col[:3])
            if c not in colors:
                colors.append(c)
            work.append([SWATCH, np.full((3, 2), (colors.index(c) + 0.5) / 1.0)])
            key = SWATCH
        else:
            images.setdefault(key, img)
            work.append([key, _wrap(np.asarray(uv, float))])
        use[key] = use.get(key, 0) + 1
    # few images: split the busiest large one into 2x2 tiles (more slots, more texels, both palettes)
    while 0 < len([k for k in images if k != SWATCH]) < 6:
        big = [k for k in images if k != SWATCH and min(images[k].shape[:2]) >= 64]
        if not big:
            break
        k = max(big, key=lambda k: use[k])
        img = images.pop(k)
        use.pop(k)
        h2, w2 = img.shape[0] // 2, img.shape[1] // 2
        for f in work:
            if f[0] != k:
                continue
            cx, cy = (int(f[1][:, 0].mean() >= 0.5), int(f[1][:, 1].mean() >= 0.5))
            t = (k, cx, cy)
            f[0] = t
            f[1] = np.clip((f[1] - (cx * 0.5, cy * 0.5)) * 2.0, 0.0, 1.0)
            images.setdefault(t, img[cy * h2:(cy + 1) * h2, cx * w2:(cx + 1) * w2])
            use[t] = use.get(t, 0) + 1
    if colors:
        images[SWATCH] = np.array([[list(c) + [255]] for c in colors], np.uint8)
    order = sorted(images, key=lambda k: -use[k])
    cluts = sorted({t.clut for t in snake_textures.values()}, key=lambda c: -sum(
        1 for t in snake_textures.values() if t.clut == c))
    slots = {c: sorted((h for h, t in snake_textures.items() if t.clut == c),
                       key=lambda h: -(snake_textures[h].width * snake_textures[h].height)) for c in cluts}
    # colour split: the images farthest in mean colour from the most used one go to the second CLUT group
    means = {k: images[k][..., :3].reshape(-1, 3).mean(0) for k in order}
    group = {k: cluts[0] for k in order}
    if len(cluts) > 1 and len(order) > 1:
        ref = means[order[0]]
        far = sorted(order[1:], key=lambda k: -np.linalg.norm(means[k] - ref))
        for k in far[:min(len(slots[cluts[1]]), max(1, len(order) // 3))]:
            group[k] = cluts[1]
    slot_of, free = {}, {c: list(s) for c, s in slots.items()}
    for k in order:
        c = group[k] if free[group[k]] else next(c for c in cluts if free[c])
        slot_of[k] = free[c].pop(0)
    # every slot's picture: its image, or (no image left) a flat colour of its group's first image
    canvas, primary = {}, {}
    for k, h in slot_of.items():
        t = snake_textures[h]
        mode = Image.Resampling.NEAREST if k == SWATCH else Image.Resampling.LANCZOS
        canvas[h] = np.array(Image.fromarray(images[k], "RGBA").resize((t.width, t.height), mode))
        primary[h] = use[k]
    for c in cluts:
        lead = next((canvas[slot_of[k]] for k in order if snake_textures[slot_of[k]].clut == c), None)
        for h in free[c]:
            t = snake_textures[h]
            colour = lead.reshape(-1, 4).mean(0) if lead is not None else np.array([128, 128, 128, 255])
            canvas[h] = np.broadcast_to(colour.astype(np.uint8), (t.height, t.width, 4)).copy()
    # palettes per CLUT group (+ foreign members re-indexed), then fit the pooled byte budget
    cands, report = {}, {"slots": len(snake_textures), "images": len(order), "flat_colours": len(colors), "groups": {}}
    for c in cluts:
        members = [h for h, t in decoded.items() if t.clut == c]
        pics = {h: canvas[h] if h in canvas else decoded[h].rgba() for h in members}
        mosaic = np.concatenate([pics[h].reshape(-1, 4) for h in members])[None]
        pal, _ = C.quantize(mosaic, 16)
        for h in members:
            lv = _levels(decoded[h], pics[h], pal)
            cands[h] = lv if h in primary else lv[:1] if h not in snake_textures else lv[-1:]
        report["groups"][f"{c[0]},{c[1]}"] = {"members": len(members), "images": sum(
            1 for k in order if snake_textures[slot_of[k]].clut == c), "foreign": sorted(set(members) - set(slots[c]))}
    budget = sum(len(pcc_bytes[h]) + (-len(pcc_bytes[h]) % 4) for h in cands)
    level = {h: 0 for h in cands}
    size = lambda: sum(len(cands[h][level[h]]) + (-len(cands[h][level[h]]) % 4) for h in cands)  # noqa: E731
    ladder = sorted(primary, key=lambda h: primary[h])                 # least used image degrades first
    while size() > budget:
        movable = [h for h in ladder if level[h] < len(cands[h]) - 1]
        if not movable:
            raise ValueError("the repainted textures do not fit the texture archive")
        h = min(movable, key=lambda h: (level[h], primary[h]))
        level[h] += 1
    new = {h: cands[h][level[h]] for h in cands}
    report.update(bytes=size(), budget=budget, detail_levels={str(h): level[h] for h in primary},
                  slot_of={str(k if k == SWATCH else order.index(k)): h for k, h in slot_of.items()})
    out = []
    for k, uv in work:
        if k == SWATCH:
            v = int(round(uv[0, 0] / len(colors) * 255))
            corners = [(128, v)] * 3
        else:
            corners = [(int(round(a * 255)), int(round(b * 255))) for a, b in uv]
        a, b, c = corners
        out.append((slot_of[k], bytes([*a, *b, *b, *c])))
    return new, out, report
