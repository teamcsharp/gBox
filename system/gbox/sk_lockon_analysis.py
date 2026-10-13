"""Sonic & Knuckles lock-on build: native player-sprite analysis (#1333).

Game 286b3fae79e33f17 is the S&K + Sonic 1 REV00 combined image (see
``gbox.sk_inventory``).  S&K's boot code (DetermineWhichGame) compares the attached
cart's serial at $200180 with LockonSerialsText (Sonic 2 REV00/01/02, Sonic 3).
Sonic 1 matches none of them, so this build boots Blue Spheres, and the only
playable sprite is the special-stage player object (skdisasm ``Obj_SStage_8FAA``).
The main-game Sonic/Knuckles tables are still in the segment but unreachable here.

Everything below is pinned from the 68k code of the exact segment, not from labels:

* ``lockon_mode``: the serial table, its ``lea (table).l,a1`` xref, the
  ``lea ($200180).l,a0`` read and the resulting mode.
* ``sstage_loaders`` / ``sstage_players``: the special-stage DPLC loader has one
  shared S3K core (``add.w d0,d0; adda.w (a2,d0.w),a2; move.w (a2)+,d5; subq #1,d5;
  bmi``) preceded by per-character ``lea PLC,a2 / move.l #Art,d6 / move.w #VRAM,d4``
  groups; ``cmpi.w #N,(Player_mode).w; bne.s`` right before a group selects it
  (2 = Tails, 3 = Knuckles, otherwise Sonic).  The object init pairs each mapping
  table with its art_tile word under the same guards.
* ``sstage_palette``: the special-stage palette copy and the Knuckles override.
* ``main_players``: the main-game tables through ``gbox.sk_sprites`` (the stock
  S&K reader from #1365), checked against its pinned stock offsets.
* ``roundtrip``: a byte-identical no-op re-encode of each pinned mapping/DPLC table
  (back-to-back offset heads such as PLC_Sonic/PLC_SuperSonic are rebuilt together).
* ``compat``: optional diff against stock S&K (World); no pinned range may differ.

CLI: ``python -m gbox.sk_lockon_analysis SOURCE.zip [--reference SK.zip] [--out J]``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from gbox import sk_inventory, sk_sprites
from gbox.sk_sprites import SkError, _offsets, mapping_fits, parse_dplc, parse_mappings

SK_SIZE = 0x200000
CONSOLE_AT = 0x200100
SERIAL_AT = 0x200180
LOCKON_SERIALS = (b"GM 00001051-00", b"GM 00001051-01", b"GM 00001051-02", b"GM MK-1079 -00")
SEGA_HEADERS = (b"SEGA MEGA DRIVE ", b"SEGA GENESIS    ")
MODE_NAMES = {None: "sonic", 2: "tails", 3: "knuckles"}

# Main-game player tables pinned on stock S&K (World) by #1365 (gbox.sk_sprites, PR #113).
STOCK_MAIN = {
    "sonic": {"mappings": 0x146620, "plc": 0x148182, "art": 0x100000, "extra_art": 0x140060},
    "knuckles": {"mappings": 0x14A8D6, "plc": 0x14BD0A, "art": 0x1200E0},
}

# lea (PLC).l,a2; move.l #Art,d6; move.w #VRAM,d4
_GROUP = re.compile(rb"\x45\xf9(....)\x2c\x3c(....)\x38\x3c(..)", re.S)
# cmpi.w #N,(abs).w; bne.s
_GUARD = re.compile(rb"\x0c\x78\x00([\x00-\x0f])(..)\x66[\x01-\xff]", re.S)
# move.l #Map,$C(a0); move.w #tile,$A(a0)
_MAP_TILE = re.compile(rb"\x21\x7c(....)\x00\x0c\x31\x7c(..)\x00\x0a", re.S)
# lea (src).l,a1; lea (dst).w,a2; move.w #n,d0; loop: move.w (a1)+,(a2)+; dbf d0,loop
_PAL_COPY = re.compile(rb"\x43\xf9(....)\x45\xf8(..)\x30\x3c(..)\x34\xd9\x51\xc8\xff\xfc", re.S)


def _u16(b: bytes, o: int = 0) -> int:
    return struct.unpack_from(">H", b, o)[0]


def _u32(b: bytes, o: int = 0) -> int:
    return struct.unpack_from(">I", b, o)[0]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _guard(d: bytes, at: int) -> dict | None:
    """Player_mode guard (cmpi.w #N,(abs).w; bne.s) ending exactly at ``at``."""
    if at < 8:
        return None
    m = _GUARD.fullmatch(d, at - 8, at)
    return {"at": at - 8, "value": m.group(1)[0], "ram": _u16(m.group(2))} if m else None


# --------------------------------------------------------------------------- lock-on
def lockon_mode(rom: bytes) -> dict:
    """Reproduce DetermineWhichGame from the S&K segment's own serial table."""
    sk = rom[:SK_SIZE]
    table = sk.find(b"".join(LOCKON_SERIALS))
    if table < 0:
        raise SkError("LockonSerialsText not found in the S&K segment")
    xrefs = [m.start() for m in re.finditer(re.escape(b"\x43\xf9" + struct.pack(">I", table)), sk)]
    reads = [m.start() for m in re.finditer(re.escape(b"\x41\xf9" + struct.pack(">I", SERIAL_AT)), sk)]
    console = rom[CONSOLE_AT:CONSOLE_AT + 16]
    serial = rom[SERIAL_AT:SERIAL_AT + 14]
    if len(rom) <= SK_SIZE or console not in SEGA_HEADERS:
        mode = "sonic_and_knuckles"
    elif serial in LOCKON_SERIALS[:3]:
        mode = "knuckles_in_sonic2"
    elif serial == LOCKON_SERIALS[3]:
        mode = "sonic3_and_knuckles"
    else:
        mode = "blue_spheres"
    return {"serial_table": table, "serial_table_xrefs": xrefs, "serial_read_xrefs": reads,
            "attached_console": console.decode("latin1"), "attached_serial": serial.decode("latin1"),
            "mode": mode}


# --------------------------------------------------------------------------- encoders
def encode_dplc_frame(ents) -> bytes:
    for t, k in ents:
        if not (0 <= t <= 0xFFF and 1 <= k <= 16):
            raise SkError(f"DPLC entry ({t}, {k}) outside 12-bit tile / 1-16 count")
    return struct.pack(f">H{len(ents)}H", len(ents), *[((k - 1) << 12) | t for t, k in ents])


def encode_map_frame(ps) -> bytes:
    out = bytearray(struct.pack(">H", len(ps)))
    for p in ps:
        if not (1 <= p["w"] <= 4 and 1 <= p["h"] <= 4 and 0 <= p["tile"] <= 0x7FF):
            raise SkError(f"mapping piece out of range: {p}")
        size = ((p["w"] - 1) << 2) | (p["h"] - 1)
        tile = (p["pri"] << 15) | (p["pal"] << 13) | (p["vf"] << 12) | (p["hf"] << 11) | p["tile"]
        out += struct.pack(">bBHh", p["y"], size, tile, p["x"])
    return bytes(out)


def encode_layout(start: int, head: bytes, frames: dict, piece: int) -> bytes:
    """Offset head(s) followed by every distinct frame in address order, contiguous."""
    enc = encode_dplc_frame if piece == 2 else encode_map_frame
    out = bytearray(head)
    for a in sorted(frames):
        if a != start + len(out):
            raise SkError(f"frame data at 0x{a:x} is not contiguous (next free 0x{start + len(out):x})")
        out += enc(frames[a])
    return bytes(out)


def block_heads(d: bytes, tables) -> list[tuple[int, int, int]]:
    """Expand ``[(offset, frames, piece)]`` into the back-to-back offset heads of one block.

    A table whose head is directly followed by another head of the same kind that no
    caller names (PLC_Sonic -> PLC_SuperSonic) gets it chained in.  The special-stage
    files put Map_SStage*'s head straight before PLC_SStage*'s head and interleave both
    tables' frames, so they are rebuilt as one block of mixed heads."""
    known = {off for off, _, _ in tables}
    heads = []
    for off, n, piece in tables:
        heads.append((off, n, piece))
        first = min(off + r for r in _offsets(d, off, count=n))
        cur = off + 2 * n
        while cur < first and cur not in known:
            avail = (first - cur) // 2
            rels = [_u16(d, cur + 2 * i) for i in range(avail)]
            lo = min(rels)
            k = min(avail, lo // 2) if lo else avail
            if k <= 0:
                raise SkError(f"unreadable offset head at 0x{cur:x}")
            heads.append((cur, k, piece))
            known.add(cur)
            first = min(first, min(cur + r for r in rels[:k]))
            cur += 2 * k
    heads.sort()
    pos = heads[0][0]
    for off, n, _ in heads:
        if off != pos:
            raise SkError(f"offset heads are not back to back at 0x{off:x} (expected 0x{pos:x})")
        pos += 2 * n
    return heads


def rebuild_block(d: bytes, heads) -> tuple[bytes, list[tuple[int, int]]]:
    """Re-encode every referenced frame behind ``heads`` in address order.

    Bytes no head references (dead frames) are kept verbatim and returned as gaps;
    an address read as two different frames, or overlapping frames, is an error."""
    start = heads[0][0]
    head = bytearray()
    frames: dict[int, bytes] = {}
    for off, n, piece in heads:
        rels = _offsets(d, off, count=n)
        if piece == 2:
            blobs = [encode_dplc_frame(f) for f in parse_dplc(d, off, count=n)]
        else:
            blobs = [encode_map_frame(f) for f in parse_mappings(d, off, count=n)]
        head += struct.pack(f">{n}H", *rels)
        for r, b in zip(rels, blobs):
            if frames.setdefault(off + r, b) != b:
                raise SkError(f"0x{off + r:x} is read as two different frames")
    out = bytearray(head)
    gaps = []
    for a in sorted(frames):
        pos = start + len(out)
        if a < pos:
            raise SkError(f"frame at 0x{a:x} overlaps the previous one (next free 0x{pos:x})")
        if a > pos:
            gaps.append((pos, a - pos))
            out += d[pos:a]
        out += frames[a]
    return bytes(out), gaps


def roundtrip(d: bytes, tables) -> dict:
    """No-op probe: parse pinned tables ``[(offset, frames, piece)]`` that share one block
    and re-encode them; the result must be byte-identical to the ROM."""
    try:
        heads = block_heads(d, tables)
        rebuilt, gaps = rebuild_block(d, heads)
    except (SkError, struct.error, ValueError) as e:
        return {"ok": False, "error": str(e)}
    start = heads[0][0]
    orig = d[start:start + len(rebuilt)]
    rec = {"ok": rebuilt == orig, "start": start, "size": len(rebuilt), "sha256": _sha(rebuilt),
           "heads": [[h, n, k] for h, n, k in heads], "gaps": [[a, n] for a, n in gaps]}
    if not rec["ok"]:
        rec["first_diff"] = start + next((i for i, (x, y) in enumerate(zip(rebuilt, orig)) if x != y),
                                         min(len(rebuilt), len(orig)))
    return rec


def _dma_crossings(art: int, frames, split: int | None = None, extra: int | None = None) -> int:
    """DPLC entries whose source run crosses a 128 KiB bank (the DMA queue does not split)."""
    n = 0
    for i, f in enumerate(frames):
        base = extra if (split is not None and extra is not None and i >= split) else art
        for t, k in f:
            s = base + 32 * t
            n += (s >> 17) != ((s + 32 * k - 1) >> 17)
    return n


# --------------------------------------------------------------------------- special stage
def sstage_loaders(d: bytes, window: int = 0x80) -> list[dict]:
    """DPLC loaders whose per-character setup groups precede a shared S3K core."""
    out = []
    for m in sk_sprites._DPLC_CORE.finditer(d):
        c = m.start()
        groups = []
        for g in _GROUP.finditer(d, max(0, c - window), c):
            guard = _guard(d, g.start())
            groups.append({"at": g.start(), "plc": _u32(g.group(1)), "art": _u32(g.group(2)),
                           "vram": _u16(g.group(3)), "guard": guard,
                           "player_mode": guard["value"] if guard else None})
        if groups:
            out.append({"core": c, "groups": groups})
    return out


def sstage_players(d: bytes) -> dict:
    """Per-character special-stage sprite tables of the Player_1 object (Blue Spheres)."""
    d = d[:SK_SIZE]
    loaders = sstage_loaders(d)
    p1 = [ld for ld in loaders if any(g["player_mode"] is None for g in ld["groups"])
          and any(g["player_mode"] is not None for g in ld["groups"])]
    if not p1:
        raise SkError("special-stage player DPLC loader not found")
    ld = p1[0]
    vram_bases = sorted({g["vram"] for x in loaders for g in x["groups"]})
    inits = [(m.start(), _u32(m.group(1)), _u16(m.group(2)), _guard(d, m.start()))
             for m in _MAP_TILE.finditer(d, max(0, ld["core"] - 0x400), ld["core"])]
    chars = {}
    for g in ld["groups"]:
        mode = g["player_mode"]
        name = MODE_NAMES.get(mode, f"mode{mode}")
        rec = {"setup": g["at"], "guard": g["guard"], "vram_byte": g["vram"], "vram_tile": g["vram"] // 32,
               "player_mode": "default (0 or 1)" if mode is None else mode,
               "art": {"offset": g["art"], "in_cart": g["art"] < SK_SIZE}}
        if g["plc"] >= len(d) or g["art"] >= len(d):
            rec.update({"status": "lock_on_only", "plc": {"offset": g["plc"], "in_cart": False}})
            chars[name] = rec
            continue
        try:
            n = len(_offsets(d, g["plc"]))
        except struct.error as e:
            raise SkError(f"{name}: PLC head at 0x{g['plc']:x} runs past the image") from e
        best = None
        for at, mp, tile, guard in reversed(inits):
            if (guard["value"] if guard else None) != mode or mp >= len(d):
                continue
            try:
                cnt = min(n, len(_offsets(d, mp)))
                maps, dp = parse_mappings(d, mp, cnt), parse_dplc(d, g["plc"], count=cnt)
            except (SkError, struct.error):
                continue
            if mapping_fits(maps, dp):
                best = (at, mp, tile, maps, dp, cnt)
                break
        if best is None:
            raise SkError(f"{name}: no special-stage mapping table fits PLC 0x{g['plc']:x}")
        at, mp, tile, maps, dp, cnt = best
        plc_end = sk_sprites._table_end(d, g["plc"], 2, count=cnt)
        map_end = sk_sprites._table_end(d, mp, 6, count=cnt)
        tiles = max((t + k for f in dp for t, k in f), default=0)
        art_end = g["art"] + 32 * tiles
        # Tails (Player2) only exists in Player_mode 0, so Knuckles (mode 3) may run into its slot
        tails = {x["vram"] for x in ld["groups"] if x["player_mode"] == 2}
        higher = [v for v in vram_bases if v > g["vram"] and not (mode == 3 and v in tails)]
        budget = (min(higher) - g["vram"]) // 32 if higher else None
        max_tiles = max(sum(k for _, k in f) for f in dp)
        rec.update({
            "status": "in_cart",
            "plc": {"offset": g["plc"], "frames": cnt, "size": plc_end - g["plc"],
                    "sha256": _sha(d[g["plc"]:plc_end]), "max_tiles_per_frame": max_tiles,
                    "max_entries_per_frame": max(len(f) for f in dp)},
            "mappings": {"offset": mp, "init_xref": at, "frames": cnt, "size": map_end - mp,
                         "sha256": _sha(d[mp:map_end]), "pieces": sum(len(f) for f in maps),
                         "max_pieces_per_frame": max(len(f) for f in maps),
                         "piece_palette_lines": sorted({p["pal"] for f in maps for p in f})},
            "art_tile": {"word": tile, "tile": tile & 0x7FF, "palette_line": (tile >> 13) & 3,
                         "priority": tile >> 15},
            "vram_budget_tiles": budget, "fits_vram": budget is None or max_tiles <= budget,
            "dma_bank_crossings": _dma_crossings(g["art"], dp),
            "roundtrip": roundtrip(d, [(mp, cnt, 6), (g["plc"], cnt, 2)]),
        })
        rec["art"].update({"tiles": tiles, "size": 32 * tiles, "end": art_end,
                           "sha256": _sha(d[g["art"]:art_end]),
                           "overlaps_tables": any(g["art"] < e and s < art_end
                                                  for s, e in ((mp, map_end), (g["plc"], plc_end)))})
        chars[name] = rec
    rams = sorted({g["guard"]["ram"] for g in ld["groups"] if g["guard"]})
    return {"loader_core": ld["core"], "player_mode_ram": rams, "vram_bases": vram_bases,
            "init_sites": [{"at": a, "map": m, "art_tile": t, "guard": gd} for a, m, t, gd in inits],
            "characters": chars}


def sstage_palette(d: bytes) -> dict:
    """Pal_SStage_Main copy followed by the Player_mode 3 (Knuckles) line-0 override."""
    d = d[:SK_SIZE]
    hits = list(_PAL_COPY.finditer(d))
    for a, b in zip(hits, hits[1:]):
        gb = _guard(d, b.start())
        if gb and gb["value"] == 3 and 0 <= b.start() - a.end() <= 0x10:
            def rec(m):
                off, words = _u32(m.group(1)), _u16(m.group(3)) + 1
                return {"offset": off, "ram": _u16(m.group(2)), "words": words, "xref": m.start(),
                        "sha256": _sha(d[off:off + 2 * words])}
            main, knux = rec(a), rec(b)
            knux["guard"] = gb
            return {"main": main, "knuckles_override": knux,
                    "knuckles_from_colour": (knux["ram"] - main["ram"]) // 2}
    raise SkError("special-stage palette copy not found")


def player_mode_writes(d: bytes, ram: int) -> dict:
    """Code that sets Player_mode: move.w #N / move.w (abs).w / clr.w on the RAM word."""
    d = d[:SK_SIZE]
    r = struct.pack(">H", ram)
    imm = [{"at": m.start(), "value": _u16(m.group(1))}
           for m in re.finditer(rb"\x31\xfc(..)" + re.escape(r), d, re.S) if not m.start() & 1]
    copy = [{"at": m.start(), "from_ram": _u16(m.group(1))}
            for m in re.finditer(rb"\x31\xf8(..)" + re.escape(r), d, re.S) if not m.start() & 1]
    clr = [m.start() for m in re.finditer(rb"\x42\x78" + re.escape(r), d) if not m.start() & 1]
    return {"move_imm": imm, "copy": copy, "clr": clr}


# --------------------------------------------------------------------------- main game
def main_players(sk: bytes) -> dict:
    inv = sk_sprites.player_inventory(sk[:SK_SIZE])
    chars = inv["characters"]
    pins = {}
    for name, ref in STOCK_MAIN.items():
        c = chars.get(name, {})
        got = {k: c.get(k, {}).get("offset") for k in ref}
        pins[name] = {"got": got, "matches_stock_pins": got == ref}
    for name in ("sonic", "knuckles"):
        c = chars[name]
        n = c["plc"]["frames"]
        dp = parse_dplc(sk, c["plc"]["offset"], count=n)
        x = c.get("extra_art", {})
        c["dma_bank_crossings"] = _dma_crossings(c["art"]["offset"], dp, x.get("from_frame"), x.get("offset"))
        c["roundtrip"] = {"plc": roundtrip(sk, [(c["plc"]["offset"], n, 2)]),
                          "mappings": roundtrip(sk, [(c["mappings"]["offset"], n, 6)])}
    return {"dispatch": inv["dispatch"], "characters": chars, "stock_pins": pins}


# --------------------------------------------------------------------------- compat
def compat(sk: bytes, ref: bytes, ranges: dict[str, tuple[int, int]]) -> dict:
    """Byte runs where this segment differs from stock S&K, and pinned ranges they touch."""
    n = min(len(sk), len(ref))
    runs: list[list[int]] = []
    count = 0
    for c0 in range(0, n, 4096):
        if sk[c0:c0 + 4096] == ref[c0:c0 + 4096]:
            continue
        for i in range(c0, min(c0 + 4096, n)):
            if sk[i] != ref[i]:
                count += 1
                if runs and runs[-1][1] >= i - 16:
                    runs[-1][1] = i + 1
                else:
                    runs.append([i, i + 1])
    touched = [{"name": k, "range": [a, b], "diff": [s, e]}
               for k, (a, b) in sorted(ranges.items()) for s, e in runs if s < b and a < e]
    return {"diff_bytes": count, "diff_runs": len(runs), "runs": runs[:64], "touched": touched}


def pointer_changes(sk: bytes, ref: bytes) -> list[dict]:
    """Decode the same loader/init sites in stock S&K and report changed table pointers."""
    out = []
    a = {g["at"]: g for ld in sstage_loaders(sk[:SK_SIZE]) for g in ld["groups"]}
    b = {g["at"]: g for ld in sstage_loaders(ref[:SK_SIZE]) for g in ld["groups"]}
    for at in sorted(set(a) & set(b)):
        for f in ("plc", "art", "vram"):
            if a[at][f] != b[at][f]:
                out.append({"site": at, "kind": f"sstage.{MODE_NAMES.get(a[at]['player_mode'])}.{f}",
                            "stock": b[at][f], "ours": a[at][f]})
    la = {x["code"]: x for x in sk_sprites.find_dplc_loaders(sk[:SK_SIZE])}
    lb = {x["code"]: x for x in sk_sprites.find_dplc_loaders(ref[:SK_SIZE])}
    for at in sorted(set(la) & set(lb)):
        for f in ("plc", "art", "vram", "extra_art"):
            if la[at].get(f) != lb[at].get(f):
                out.append({"site": at, "kind": f"dplc_loader.{f}", "stock": lb[at].get(f), "ours": la[at].get(f)})
    ma = {m.start(): (_u32(m.group(1)), _u16(m.group(2))) for m in _MAP_TILE.finditer(sk[:SK_SIZE])}
    mb = {m.start(): (_u32(m.group(1)), _u16(m.group(2))) for m in _MAP_TILE.finditer(ref[:SK_SIZE])}
    for at in sorted(set(ma) & set(mb)):
        if ma[at] != mb[at]:
            out.append({"site": at, "kind": "object_init.mappings/art_tile", "stock": list(mb[at]), "ours": list(ma[at])})
    return out


def pinned_ranges(r: dict) -> dict[str, tuple[int, int]]:
    out = {}
    for name, c in r["special_stage"]["characters"].items():
        if c["status"] != "in_cart":
            continue
        for k in ("plc", "mappings", "art"):
            out[f"sstage.{name}.{k}"] = (c[k]["offset"], c[k]["offset"] + c[k]["size"])
        out[f"sstage.{name}.setup"] = (c["setup"], c["setup"] + 16)
    core = r["special_stage"]["loader_core"]
    out["sstage.loader_core"] = (core - 16, core + 0x36)  # frame-cache prologue .. rts
    for k in ("main", "knuckles_override"):
        p = r["special_stage"]["palette"][k]
        out[f"sstage.palette.{k}"] = (p["offset"], p["offset"] + 2 * p["words"])
    for name in ("sonic", "knuckles"):
        c = r["main_game"]["characters"][name]
        for k in ("plc", "mappings", "art", "extra_art"):
            if k in c and "size" in c[k]:
                out[f"main.{name}.{k}"] = (c[k]["offset"], c[k]["offset"] + c[k]["size"])
    t = r["lockon"]["serial_table"]
    out["lockon.serial_table"] = (t, t + 56)
    return out


def analyze(src: str | Path, reference: str | Path | None = None) -> dict:
    p = Path(src)
    raw = p.read_bytes()
    rom, meta = sk_inventory.read_rom(p)
    sk = rom[:SK_SIZE]
    ss = sstage_players(sk)
    ss["palette"] = sstage_palette(sk)
    if ss["player_mode_ram"]:
        ss["player_mode_writes"] = player_mode_writes(sk, ss["player_mode_ram"][0])
    r = {
        "source": {"path": str(p), "sha256": _sha(raw), "size": len(raw), "member": meta.get("member")},
        "rom": {"sha256": _sha(rom), "size": len(rom), "sk_segment_sha256": _sha(sk)},
        "lockon": lockon_mode(rom),
        "special_stage": ss,
        "main_game": main_players(sk),
        "constraints": {
            "art": "uncompressed 4bpp 8x8 tiles (32 B each), streamed per mapping frame by the DPLC",
            "dplc": "u16 offset head; frame = u16 n + n x u16 ((tiles-1)<<12 | first_tile): <=16 tiles "
                    "and a 12-bit first tile per entry, one DMA-queue slot per entry",
            "dma": "an entry's source run must stay inside one 128 KiB bank (dma_bank_crossings)",
            "mappings": "u16 offset head; frame = u16 n + n x {s8 y, u8 (w-1)<<2|(h-1), u16 "
                        "pri|pal<<13|vf|hf|tile, s16 x}; piece tiles index the frame's DPLC stream",
            "vram": "a frame's DPLC total must fit vram_budget_tiles at the player slot",
            "palette": "the player's art_tile line; Pal_SStage_Main supplies line 0 for Sonic, "
                       "Knuckles overrides colours 8-15 of line 0",
        },
    }
    if reference:
        ref, _ = sk_sprites.read_rom(reference)
        r["compat"] = {"reference_sha256": _sha(ref), **compat(sk, ref, pinned_ranges(r)),
                       "pointer_changes": pointer_changes(sk, ref)}
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="S&K lock-on build: native player sprite analysis")
    ap.add_argument("src")
    ap.add_argument("--reference", help="stock Sonic & Knuckles (World) ROM/zip for the compat diff")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    s = json.dumps(analyze(a.src, a.reference), indent=1)
    if a.out:
        Path(a.out).write_text(s)
        print(f"wrote {a.out}")
    else:
        print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
