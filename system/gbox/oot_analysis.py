"""Ocarina of Time: where the game draws Link and loads objects, re-derived from an owned ROM (#1325 analysis stage).

Everything here is found from the ROM's own `code` and `ovl_player_actor` bytes (MIPS big-endian), not from a symbol
file, so it re-checks any retail version `oot_writer.Rom` opens:

* gKaleidoMgrOverlayTable: the 0x1C-byte {loadedRamAddr, vromStart, vromEnd, vramStart, vramEnd, offset, name} rows
  naming ovl_kaleido_scope and ovl_player_actor (the player overlay is loaded by KaleidoManager, not the actor table:
  gActorOverlayTable[ACTOR_PLAYER] is empty).
* PlayerCall_InitFuncPtrs (z_player_call.c): the only four lui/addiu pairs in `code` naming addresses inside the player
  overlay, in source order Player_Init, Player_Destroy, Player_Update, Player_Draw.
* sPlayerDListGroups (z_player_lib.c): the pointer table whose words are the hand / waist / shield DL tables
  `oot_swap.write_link` patches; the first-person tables are named directly by lui/addiu pairs instead.
* gObjectTable and gActorOverlayTable: their lui/addiu xrefs (Object_Spawn / Object_InitContext / Object_UpdateEntries
  read gObjectTable; Actor_Spawn / Actor_FreeOverlay read gActorOverlayTable).
* the writer's patch sites: every (code offset, entry index) `write_link` rewrites, with the object word it replaces.

* the draw chain Player_Draw -> Player_DrawGameplay -> Player_DrawImpl -> SkelAnime_DrawFlexLod (see draw_chain).

USA Rev B (ntsc-1.2, the #1325 owned build), cross-checked with a local Ghidra 12.1 MIPS:BE:32 project of code at
0x800116E0 + ovl_player_actor at 0x808301C0 (~/gbox-cache/1aa2e4bb5797493f/ghidra/oot12.gpr, scripts/OotXrefs.java):
Player_Draw 0x80848704 calls Player_DrawGameplay 0x80848284 twice; that calls Player_DrawImpl 0x8007A5D8(play,
skeleton=this+0x1A8, jointTable=this+0x1C4, dListCount, lod, tunic, boots, face, override, Player_PostLimbDrawGameplay
0x8007BDC4, this). Player_DrawImpl sets segments 8/9 from sEyeTextures 0x800F80F8 / sMouthTextures 0x800F8118, the
tunic env colour from sTunicColors 0x800F8128, stores lod*2 in sDListsLodOffset 0x8011C5F4 and calls
SkelAnime_DrawFlexLod 0x80089AF4; afterwards it draws boots from 0x800F8134/0x800F8138 (adult) or gSPDisplayList
0x06016118 (child Goron bracelet). Limb callbacks then read near/far DLs as table[sDListsLodOffset + age]:
sPlayerDListGroups 0x800F8060 (16 model-type slots, set by 0x80079B8C / 0x80079C78), sPlayerWaistDLs via 0x800F80B0,
first-person tables named directly in 0x8007B410. gObjectTable 0x800F9648 is read by 0x80081920 (sync DMA
0x80000F80, persistent spawn), 0x80081B60 (async DMA 0x80000EB8, slot updates), 0x80081CE8, 0x80081D70, the pause
copy in 0x8007C72C and the player overlay's 0x80838F78 (async, item-get objects) -- so a moved object only needs its
gObjectTable row rewritten, which oot_writer.Rom.build does.

`python -m gbox.oot_analysis ROM [--out analysis.json]` writes the report."""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from . import oot_writer as OW

KALEIDO_ROW = 0x1C
# I-type opcodes whose rs + signed 16-bit immediate complete a lui: addiu, lw, sw, lh, lhu, lb, lbu, sh, sb, lwc1, swc1
_LO_OPS = {0x09, 0x23, 0x2B, 0x21, 0x25, 0x20, 0x24, 0x29, 0x28, 0x31, 0x39}
_ORI = 0x0D
# z_player_lib.c sPlayerDListGroups slots (PLAYER_MODELTYPE_*), in table order
MODEL_TYPES = ["LH_OPEN", "LH_CLOSED", "LH_SWORD", "LH_SWORD_2", "LH_BGS", "LH_HAMMER", "LH_BOOMERANG", "LH_BOTTLE",
               "RH_OPEN", "RH_CLOSED", "RH_SHIELD", "RH_BOW_SLINGSHOT", "RH_BOW_SLINGSHOT_2", "RH_OCARINA", "RH_OOT",
               "RH_HOOKSHOT"]
JR_RA = 0x03E00008
FIRST_PERSON = ("sFirstPersonLeftForearmDLs", "sFirstPersonLeftHandDLs", "sFirstPersonRightShoulderDLs",
                "sFirstPersonForearmDLs", "sFirstPersonRightHandHoldingWeaponDLs")


def words(data: bytes) -> tuple[int, ...]:
    n = len(data) // 4
    return struct.unpack(f">{n}I", data[:4 * n])


def hilo_refs(data: bytes, base: int, lo: int, hi: int, window: int = 40) -> list[tuple[int, int]]:
    """(address of the completing instruction, target) for every `lui rt` followed within `window` instructions by an
    addiu/ori/load/store using rt as its base, whose full address lies in [lo, hi). A second lui of rt ends the
    search, as the compiler's scheduling never interleaves two loads of one register's upper half."""
    W = words(data)
    out = []
    for i, w in enumerate(W):
        if w >> 26 != 0x0F:
            continue
        rt, up = (w >> 16) & 31, (w & 0xFFFF) << 16
        for j in range(i + 1, min(len(W), i + window)):
            x = W[j]
            op = x >> 26
            if (op in _LO_OPS or op == _ORI) and (x >> 21) & 31 == rt:
                imm = x & 0xFFFF
                t = (up | imm) if op == _ORI else (up + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                if lo <= t < hi:
                    out.append((base + 4 * j, t))
            if op == 0x0F and (x >> 16) & 31 == rt:
                break
    return out


def jal_targets(data: bytes, base: int) -> dict[int, list[int]]:
    """target -> [call sites] for every jal in data (loaded at base)."""
    out: dict[int, list[int]] = {}
    for i, w in enumerate(words(data)):
        if w >> 26 == 3:
            out.setdefault((base & 0xF0000000) | ((w & 0x3FFFFFF) << 2), []).append(base + 4 * i)
    return out


def overlay_sections(ovl: bytes) -> dict:
    """An overlay file's footer: {text, data, rodata, bss, relocs, header} sizes / offset."""
    hdr = len(ovl) - struct.unpack_from(">I", ovl, len(ovl) - 4)[0]
    t, d, r, b, n = struct.unpack_from(">5I", ovl, hdr)
    return {"text": t, "data": d, "rodata": r, "bss": b, "relocs": n, "header": hdr}


def _code(rom: OW.Rom) -> bytes:
    return getattr(rom, "_orig_code", None) or rom.file(rom.v["code"])


def kaleido_table(rom: OW.Rom) -> dict:
    """{kaleido, player}: gKaleidoMgrOverlayTable rows (row vram, vrom and vram ranges), found by their vrom pair."""
    code, cv = _code(rom), rom.v["code_vram"]
    out = {}
    for name in ("kaleido", "player"):
        vs, ve = rom.dma[rom.v[name]][:2]
        hits = [o - 4 for o in range(4, len(code) - 0x18, 4) if struct.unpack_from(">II", code, o) == (vs, ve)]
        if len(hits) != 1:
            raise ValueError(f"gKaleidoMgrOverlayTable row for {name}: {len(hits)} candidates")
        o = hits[0]
        _ram, vs, ve, vrs, vre, off, nm = struct.unpack_from(">7I", code, o)
        out[name] = {"row": cv + o, "vrom": (vs, ve), "vram": (vrs, vre), "name_ptr": nm}
    if out["player"]["row"] - out["kaleido"]["row"] != KALEIDO_ROW:
        raise ValueError("kaleido / player rows are not adjacent")
    return out


def player_entry_points(rom: OW.Rom) -> dict:
    """Player_Init/Destroy/Update/Draw: the lui/addiu pairs in code (PlayerCall_InitFuncPtrs) naming player text."""
    code, cv = _code(rom), rom.v["code_vram"]
    p0, _p1 = kaleido_table(rom)["player"]["vram"]
    text_end = p0 + overlay_sections(rom.file(rom.v["player"]))["text"]
    refs = hilo_refs(code, cv, p0, text_end)
    if len(refs) != 4 or refs[-1][0] - refs[0][0] > 0x60:
        raise ValueError(f"PlayerCall_InitFuncPtrs: expected 4 adjacent refs into ovl_player_actor, got {refs}")
    names = ("Player_Init", "Player_Destroy", "Player_Update", "Player_Draw")
    return {n: {"vram": t, "ref": at} for n, (at, t) in zip(names, refs)}


def table_positions(rom: OW.Rom) -> dict:
    """oot_swap.LINK_ARRAYS name -> [vram of every copy in code] (the content search the writer patches)."""
    from .oot_swap import _code_positions
    cv = rom.v["code_vram"]
    return {n: [cv + o for o in offs] for n, offs in _code_positions(rom).items()}


def dlist_groups(rom: OW.Rom) -> dict:
    """sPlayerDListGroups: the code pointer table (16 words) whose entries are the writer's hand / shield / waist
    tables -> {vram, entries: [(slot, table vram, LINK_ARRAYS name)], refs: lui/addiu xrefs to it}."""
    code, cv = _code(rom), rom.v["code_vram"]
    from .oot_swap import LINK_ARRAYS
    pos = table_positions(rom)
    owner = {}                                           # a 4-entry table can also match the head of a 16-entry one
    for n, vs in sorted(pos.items(), key=lambda kv: len(LINK_ARRAYS[kv[0]][1])):
        for a in vs:
            owner[a] = n
    W = words(code)
    best = None
    for i in range(len(W) - 16):
        if all(w in owner for w in W[i:i + 16]):
            best = i
            break
    if best is None:
        raise ValueError("sPlayerDListGroups not found")
    ents = [(MODEL_TYPES[k], W[best + k], owner[W[best + k]]) for k in range(16)]
    va = cv + 4 * best
    refs = [at for at, t in hilo_refs(code, cv, va, va + 64)]
    waist = [cv + 4 * i for i, w in enumerate(W) if w in pos["sPlayerWaistDLs"]]
    return {"vram": va, "entries": ents, "refs": refs, "waist_ptrs": waist}


def patch_sites(rom: OW.Rom) -> list[dict]:
    """Every word oot_swap.write_link may rewrite in code: {table, code_off, vram, index, age, word}."""
    from .oot_swap import LINK_ARRAYS, _code_positions
    code, cv = _code(rom), rom.v["code_vram"]
    out = []
    for name, (limb, arr) in LINK_ARRAYS.items():
        for o in _code_positions(rom)[name]:
            for k, a in enumerate(arr):
                if not a:
                    continue
                age = "child" if (len(arr) == 2 and k == 1) or (len(arr) > 2 and k % 2) else "adult"
                word = struct.unpack_from(">I", code, o + 4 * k)[0]
                out.append({"table": name, "limb": limb, "code_off": o + 4 * k, "vram": cv + o + 4 * k, "index": k,
                            "age": age, "word": word})
    return out


def func_bounds(data: bytes, base: int, addr: int) -> tuple[int, int]:
    """[start, end) of the IDO-compiled function holding addr: from just after the previous `jr ra` + delay slot (and
    any nop padding) to just after its own `jr ra` + delay slot."""
    W = words(data)
    i = (addr - base) // 4
    s = i
    while s > 0 and not (W[s - 2] == JR_RA if s >= 2 else False):
        s -= 1
    while W[s] == 0 and s < i:
        s += 1
    e = i
    while W[e] != JR_RA:
        e += 1
    return base + 4 * s, base + 4 * e + 8


def calls_in(data: bytes, base: int, start: int, end: int) -> list[int]:
    """jal targets between start and end, in code order."""
    return [(base & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
            for w in words(data[start - base:end - base]) if w >> 26 == 3]


def draw_chain(rom: OW.Rom) -> dict:
    """Player_Draw -> Player_DrawGameplay (player overlay, called twice: normal and the mirror/reflection pass) ->
    Player_DrawImpl (code, z_player_lib.c: the code callee that emits gSPDisplayList(0x06016118), the child Goron
    bracelet oot_swap.BLANK clears) -> SkelAnime_DrawFlexLod (the jal right after Player_DrawImpl stores lod * 2 into
    sDListsLodOffset, the BSS word the limb callbacks index each DL table with)."""
    code, cv = _code(rom), rom.v["code_vram"]
    pl = rom.file(rom.v["player"])
    p0 = kaleido_table(rom)["player"]["vram"][0]
    draw = player_entry_points(rom)["Player_Draw"]["vram"]
    d0, d1 = func_bounds(pl, p0, draw)
    in_ovl = [t for t in calls_in(pl, p0, d0, d1) if p0 <= t < p0 + len(pl)]
    gameplay = next(t for t in dict.fromkeys(in_ovl) if in_ovl.count(t) == 2)
    g0, g1 = func_bounds(pl, p0, gameplay)
    impl = None
    for t in dict.fromkeys(calls_in(pl, p0, g0, g1)):
        if cv <= t < cv + len(code):
            f0, f1 = func_bounds(code, cv, t)
            if any(tg == 0x06016118 for _a, tg in hilo_refs(code[f0 - cv:f1 - cv], f0, 0x06016118, 0x06016119)):
                impl = (f0, f1)
                break
    if impl is None:
        raise ValueError("Player_DrawImpl not found")
    cend = cv + len(code)
    lod_store = next((at, t) for at, t in hilo_refs(code[impl[0] - cv:impl[1] - cv], impl[0], cend, 0x80800000)
                     if words(code[at - cv:at - cv + 4])[0] >> 26 == 0x2B)
    after = calls_in(code, cv, lod_store[0], impl[1])
    return {"Player_Draw": {"vram": draw, "end": d1}, "Player_DrawGameplay": {"vram": gameplay, "end": g1},
            "Player_DrawImpl": {"vram": impl[0], "end": impl[1]}, "sDListsLodOffset": lod_store[1],
            "SkelAnime_DrawFlexLod": after[0]}


def object_loaders(rom: OW.Rom) -> dict:
    """Functions reading gObjectTable (code and the player overlay) -> {entry: [jal targets]}; the z_scene.c loaders
    (Object_SpawnPersistent / Object_InitContext / Object_UpdateEntries / Object_...) DMA object files with it."""
    code, cv = _code(rom), rom.v["code_vram"]
    pl = rom.file(rom.v["player"])
    p0 = kaleido_table(rom)["player"]["vram"][0]
    ot = cv + rom.obj_table
    out = {}
    for data, base in ((code, cv), (pl, p0)):
        for at, _t in hilo_refs(data, base, ot, ot + 1):
            f0, f1 = func_bounds(data, base, at)
            out.setdefault(f0, {"end": f1, "refs": [], "calls": calls_in(data, base, f0, f1)})["refs"].append(at)
    return out


def link_skeletons(rom: OW.Rom) -> dict:
    """Both Link skeletons re-decoded: limb count, LOD flag, how many limbs draw, near/far DL words (segment 6)."""
    from .oot_swap import LINK
    out = {}
    for age, L in LINK.items():
        obj = rom.object(L["obj"])
        sk = OW.skeleton(obj, L["skel"])
        out[age] = {"object": L["obj"], "header": L["skel"], "limbs": sk["count"], "lod": sk["lod"],
                    "dlcount": sk["dlcount"], "drawn": sum(1 for lb in sk["limbs"] if lb["dls"][0]),
                    "dls": [lb["dls"] for lb in sk["limbs"]], "size": len(obj)}
    return out


def analysis(rom: OW.Rom) -> dict:
    code, cv = _code(rom), rom.v["code_vram"]
    cend = cv + len(code)
    obj_t, act_t = cv + rom.obj_table, None
    from .oot_swap import actor_table
    act_t = cv + actor_table(rom)
    kt = kaleido_table(rom)
    pl = rom.file(rom.v["player"])
    groups = dlist_groups(rom)
    pos = table_positions(rom)
    fp = {n: [at for at, t in hilo_refs(code, cv, pos[n][0], pos[n][0] + 4)] for n in FIRST_PERSON}
    return {
        "version": rom.version,
        "code": {"dma": rom.v["code"], "vram": cv, "size": len(code)},
        "ovl_player_actor": {"dma": rom.v["player"], **kt["player"], **overlay_sections(pl)},
        "ovl_kaleido_scope": {"dma": rom.v["kaleido"], **kt["kaleido"]},
        "player_entry_points": player_entry_points(rom),
        "gObjectTable": {"vram": obj_t, "refs": [at for at, _t in hilo_refs(code, cv, obj_t, obj_t + 1)]},
        "gActorOverlayTable": {"vram": act_t, "refs": [at for at, _t in hilo_refs(code, cv, act_t, act_t + 1)]},
        "sPlayerDListGroups": groups,
        "first_person_refs": fp,
        "tables": pos,
        "patch_sites": patch_sites(rom),
        "draw_chain": draw_chain(rom),
        "object_loaders": object_loaders(rom),
        "link_skeletons": link_skeletons(rom),
        "code_refs_total": len(hilo_refs(code, cv, cv, cend)),
    }


def main(argv=None) -> int:
    from . import n64_rom
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("rom")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rep = analysis(OW.Rom(n64_rom.read(a.rom)))
    text = json.dumps(rep, indent=1, default=lambda v: list(v) if isinstance(v, tuple) else str(v))
    if a.out:
        Path(a.out).write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
