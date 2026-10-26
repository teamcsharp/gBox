"""Marvel vs. Capcom 2 (Dreamcast, USA T1212N V1.001) native writer: PLxx_DAT.BIN slot swap.

Source identity: Redump GDI sha256(archive) cab7f970..9fec; PLxx_DAT.BIN layout decoded in gbox.mvc2_dat.

A DAT is a 0x40-byte table of 16 absolute u32 slot offsets followed by the slot payloads back to back
(each slot runs to the next non-zero offset / EOF). Everything inside a slot is addressed relative to the
slot base (GFX1 part table, GFX2 sprite table, slot-5 animation tables), so a slot can be moved between
characters and only the 16-entry table needs relocation. That makes the writer lossless:

* ``rebuild_dat(dat)`` with no replacements is byte-identical (every unknown byte/padding stays inside its slot);
* ``swap_slots(target, donor, slots)`` replaces exactly the listed slots, preserves every other slot and
  unknown header words, and recomputes only the offset table;
* ``replace_part`` re-encodes one GFX1 part with a literal-only LZSS stream (valid for decodeA), growing that
  one slot and relocating the later part offsets.

Visual donor swap = slots 0 (parts), 1 (sprite assembly), 2+3 (palette), 5 (animation cells, which index the
donor's own sprite table). Slots 4/6+ (hitboxes etc.) and the per-character S_PLxx code modules remain the
target's, so the donor's look and frame data replace the target's while the target's moves/hitboxes stay.
This is a sprite/animation replacement, not a move-set transplant.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from . import mvc2_dat as M

GAME_ID = "02db6d37c0e20375"
GAME_IDS = {GAME_ID: "Marvel vs. Capcom 2 (USA) (Dreamcast)"}
VISUAL_SLOTS = (0, 1, 2, 3, 5)
DAT_NAME = "PL{id:02X}_DAT.BIN"


def split_dat(dat: bytes) -> dict:
    """{table, pre, slots:{i: bytes}, order:[i...]} - slots in file order; nothing is dropped."""
    tab = M.dat_sections(dat)
    live = sorted((o, i) for i, o in enumerate(tab) if o)
    if not live or live[0][0] < 0x40 or live[-1][0] > len(dat):
        raise ValueError("malformed DAT section table")
    if len({o for o, _ in live}) != len(live):
        raise ValueError("two slots share an offset")
    slots = {}
    for n, (o, i) in enumerate(live):
        end = live[n + 1][0] if n + 1 < len(live) else len(dat)
        slots[i] = dat[o:end]
    return {"table": tab, "pre": dat[0x40:live[0][0]], "slots": slots, "order": [i for _, i in live]}


def rebuild_dat(dat_or_parts, replacements: dict[int, bytes] | None = None) -> bytes:
    """Reassemble a DAT, optionally replacing whole slots (bytes). No replacements => byte-identical."""
    parts = split_dat(dat_or_parts) if isinstance(dat_or_parts, (bytes, bytearray)) else dat_or_parts
    rep = dict(replacements or {})
    for i in rep:
        if i not in parts["slots"]:
            raise ValueError(f"slot {i} is empty in the target; refusing to invent a slot")
    tab = [0] * 16
    body = bytearray(parts["pre"])
    off = 0x40 + len(body)
    for i in parts["order"]:
        data = rep.get(i, parts["slots"][i])
        if i in rep and len(data) % 4:
            data = data + b"\0" * (4 - len(data) % 4)
        tab[i] = off
        body += data
        off += len(data)
    return struct.pack("<16I", *tab) + bytes(body)


def swap_slots(target: bytes, donor: bytes, slots=VISUAL_SLOTS) -> bytes:
    """Target DAT with `slots` taken from donor. Slot presence must match on both sides."""
    t, d = split_dat(target), split_dat(donor)
    for i in slots:
        if (i in t["slots"]) != (i in d["slots"]):
            raise ValueError(f"slot {i} present on only one of target/donor; unknown semantics, not swapping")
        if i not in t["slots"]:
            raise ValueError(f"slot {i} absent on both")
    return rebuild_dat(t, {i: d["slots"][i] for i in slots})


def encode_part_literal(indices_display: bytes, w: int, h: int) -> bytes:
    """Display-order 4bpp indices -> literal-only LZSS stream (flag byte 0 + 8 literals)."""
    tw = M.twiddle_pal4(M.vflip(indices_display, w, h), w, h)
    out = bytearray()
    for i in range(0, len(tw), 8):
        out.append(0)
        out += tw[i:i + 8]
    return bytes(out)


def replace_part(dat: bytes, sel: int, indices_display: bytes) -> bytes:
    """Replace GFX1 part `sel` (same W/H, header preserved) and relocate later part offsets."""
    gfx1, o0, o1, w, h = M.part_geom(dat, sel)
    if len(indices_display) != w * h:
        raise ValueError(f"part {sel} is {w}x{h}: need {w * h} indices")
    parts = split_dat(dat)
    g = bytearray(parts["slots"][0])
    n = struct.unpack_from("<I", g, 0)[0] // 4
    offs = list(struct.unpack_from(f"<{n}I", g, 0))
    ends = offs[1:] + [len(g)]
    blobs = [bytes(g[a:b]) for a, b in zip(offs, ends)]
    hdr = blobs[sel][:4]
    blobs[sel] = hdr + encode_part_literal(indices_display, w, h)
    cur = n * 4
    new_offs = []
    for b in blobs:
        new_offs.append(cur)
        cur += len(b)
    new_g = struct.pack(f"<{n}I", *new_offs) + b"".join(blobs)
    # bytes between the part table and first blob (if any) are not expected; guard for exactness
    if offs[0] != n * 4:
        raise ValueError("unexpected gap after GFX1 part table")
    return rebuild_dat(parts, {0: new_g})


def read_back(dat: bytes) -> dict:
    """Independent decode (via gbox.mvc2_dat) used as proof: counts, part/sprite/anim digests."""
    h = hashlib.sha256()
    n = M.part_count(dat)
    for sel in range(n):
        idx, _, _ = M.part_indices(dat, sel)
        h.update(idx)
    gfx2 = M.dat_sections(dat)[1]
    ns = struct.unpack_from("<I", dat, gfx2)[0] // 4
    return {"parts": n, "sprites": ns, "parts_sha256": h.hexdigest(),
            "anim_groups": len(M.animation_groups(dat)),
            "palette0": M.palette_bank(dat, 0)[:4]}


def parse_cid(token: str) -> int:
    from .mvc2_inventory import ROSTER
    t = (token or "").strip().lower()
    if t in ("", "player"):
        return 0x00
    t = t.removeprefix("fighter:").removeprefix("pl")
    try:
        return int(t, 16)
    except ValueError:
        pass
    for cid, name in enumerate(ROSTER):
        if name.lower() == t:
            return cid
    raise ValueError(f"unknown MVC2 fighter {token!r} (use a hex id 00-3A, PLxx or a roster name)")


def pick_sacrifice(disc, target: str, need_bytes: int) -> str:
    """Smallest free-slack file whose own sectors + gap to the next file hold a `need_bytes` moved file.

    Deterministic: smallest free slack first, then name order. Never picks ``target`` or 1ST_READ.BIN.
    The chosen file's directory entry is repointed by patch_gdi to the moved data; it stops
    resolving on the mod (the mod gives it up) - the original GDI is untouched.
    """
    entries = sorted(((k, v[0], v[1]) for k, v in disc.files.items()), key=lambda kv: kv[1])
    cands = []
    for i, (n, lb, sz) in enumerate(entries):
        if n == target or n == "1ST_READ.BIN":
            continue
        slack = (entries[i + 1][1] - lb if i + 1 < len(entries) else (sz + 2047) // 2048) * 2048
        if slack >= need_bytes:
            cands.append((slack, n))
    if not cands:
        raise ValueError(f"no file has enough free sectors for a {need_bytes}-byte replacement (target {target})")
    cands.sort()
    return cands[0][1]


def build_mod(gdi: str | Path, out_dir: str | Path, target_cid: int, donor_cid: int, slots=VISUAL_SLOTS,
              name: str | None = None, progress=None, sacrifice: str | None = None) -> dict:
    """Write a separate GDI (original untouched) whose PL<target>_DAT.BIN carries the donor's visual slots.

    If the swapped DAT no longer fits the target's own sectors, the replacement is moved into a
    sacrificed file's sectors (``sacrifice`` names one explicitly; otherwise :func:`pick_sacrifice`
    picks the smallest-sacrifice automatically). The mod's directory entry for the sacrifice is
    repointed to the moved data, so the mod no longer resolves it - the original GDI is untouched."""
    from .gdrom import GDRom, patch_gdi
    disc = GDRom(str(gdi))
    tname, dname = DAT_NAME.format(id=target_cid), DAT_NAME.format(id=donor_cid)
    tdat, ddat = disc.read(tname), disc.read(dname)
    new = swap_slots(tdat, ddat, slots)
    name = name or f"mvc2_{target_cid:02x}_{donor_cid:02x}"
    tslack = disc.files[tname]
    tlba, tsize = tslack[0], tslack[1]
    entries = sorted(((k, v[0], v[1]) for k, v in disc.files.items()), key=lambda kv: kv[1])
    nxt = next((l for l in [e[1] for e in entries] if l > tlba), None)
    room = (nxt - tlba) * 2048 if nxt else (tsize + 2047) // 2048
    donors = []
    if len(new) > room:
        sac = sacrifice or pick_sacrifice(disc, tname, len(new))
        donors = [sac]
    out = patch_gdi(gdi, out_dir, name, {tname: new}, progress, donors=donors)
    return {"mod": name, "gdi": str(out), "target": tname, "donor": dname, "slots": list(slots),
            "target_sha256": hashlib.sha256(tdat).hexdigest(), "donor_sha256": hashlib.sha256(ddat).hexdigest(),
            "mod_file_sha256": hashlib.sha256(new).hexdigest(), "old_size": len(tdat), "new_size": len(new),
            "sacrifice": donors[0] if donors else None,
            "message": (f"{tname} no longer resolves on this mod (sacrificed for space)" if donors
                        else "no sacrifice needed") }


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for MVC2: slot ``player`` / ``fighter:<id|name>`` is the target; the donor is the
    library entry's own MVC2 fighter id (extracted by gbox.mvc2_chars). Builds a separate disc mod, no launch."""
    from . import mvc2_chars as C
    src = meta.get("source") or {}
    cid = meta.get("cid", src.get("cid"))
    if cid is None:
        return {"status": "unsupported",
                "message": "MVC2 native replacement needs a donor that is itself an MVC2 fighter (extracted with "
                           "characters op=extract); a 3D model has no 2D sprite sheet to write."}
    target = parse_cid(getattr(inp, "slot", "player"))
    gdi = C._dc_gdi(ctx, game)
    out_dir = Path(ctx.config.cache) / "mods" / game["game_id"]
    res = build_mod(gdi, out_dir, target, int(cid), progress=getattr(ctx, "progress", None))
    return res | {"status": "built",
                  "message": f"PL{target:02X} now shows {meta.get('name')} (PL{int(cid):02X} sprites, palette, animation "
                             "cells); target's hitboxes/code kept. Runtime verification still required."}
