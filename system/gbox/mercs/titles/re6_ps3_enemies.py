"""RE6 PS3 (BLUS30855, RPCS3) live enemy actor-list reader: the sEnemy chain pinned from the decrypted EBOOT.

Evidence scope (request #3368). Every static address below comes from the decrypted EBOOT of BLUS30855 01.00:

  EBOOT.BIN 01.00 (SELF sha256 161788e7c0264b1b9d5cd72ac051c9ce2a64b7c85d04f954b2e35f202834af67, KeyRev 0x001C,
  9,381,200 bytes); decrypted image sha256
  3720224a5eb8b8a2e69871439aa8d8b11c8a4cbc426f4144d0531d6e5648cecb
  (gbox-data/analysis/re6-ps3-eboot/EBOOT.dec.ELF, 25,060,016 bytes, ELF64 PPC BE, segments based 0x10000).

  0x15cd7c  sEnemy DTI registration (verified instruction-by-instruction, the same pattern as sPlayer at 0x1a93d8):
            lis r31,0x183 / addic r3,r31,0x434c    -> node slot 0x183434C
            lis r4,0x141  / addic r4,r4,0x2510     -> name VA 0x1412510 (.rodata bytes "sEnemy\\0" verified)
            lis r5,0x17f  / addic r5,r5,0x36e0     -> category-list object 0x17F36E0
            li r6,0x810                             -> singleton instance size 0x810
            bl 0xcb2a04 (-> 0xcb2898 registrar, identical to sPlayer's), then
            [0x183434C] = 0x14E5EE0 (the sEnemy node class; 0x14DCB00 is the generic pre-store value).
  0x15cddc  sibling registration sEnemy::cLodControl -> node 0x183436C, name 0x1412518, size 0x30 (same function).
  0x66c100  uEnemy unit-class DTI registration: name VA 0x140d9f4 ("uEnemy"), size 0x3700 - the base class every
            uEm#### enemy unit derives from (uPlayer, same registrar chain, is 0x4670 at 0x780734).
  The uEm#### family table below was extracted with the same scanner (every entry cross-checked name bytes);
  entries whose node slot the scanner could not pin cleanly are omitted - the class names are still usable live
            through an instance's DTI name pointer.

Candidate live offsets (inherited, must be confirmed by a live RPCS3 read before any aiming trusts them):
  RE5 PS3 (BLUS30491, measured live 2026-10-20, same MT Framework family): sEnemy +0x28 u32 count,
  +0x34 -> array of uEm pointers; uEm +0x30 f32[3] pos, +0x14A4 s16 HP, +0x14A6 s16 HP max.
  The X360 RE6 sibling (docs/re6.md, BH6MasterRelease) instead has pos +0x50 and Life +0xF20 on uPlayer.
  This module tries the RE5 PS3 layout first and answers None whenever the chain fails its sanity bounds,
  so a wrong layout can never fabricate targets. Knocked-down and mutation-state bytes have no static
  evidence yet and are returned as None (TODO: live measurement on the i9-NUC agent session, never the
  operator's PCs).
"""
from __future__ import annotations

import struct

PTR_LO, PTR_HI = 0x10000, 0x300000000            # RPCS3 PPU user VAS (matches re6_ps3)

EBOOT_DEC_SHA256 = "3720224a5eb8b8a2e69871439aa8d8b11c8a4cbc426f4144d0531d6e5648cecb"

ENEMY_REG_VA = 0x15CD7C                # the registration function's entry
ENEMY_NAME_VA = 0x1412510              # .rodata "sEnemy\0" of this exact EBOOT
ENEMY_DTI_NODE = 0x183434C             # .bss DTI node slot registered at 0x15cdb8
ENEMY_NODE_CLASS = 0x14E5EE0           # [node+0] after registration (0x14DCB00 in the boot window)
ENEMY_NODE_LIST = 0x17F36E0            # r5: the node's category-list object
ENEMY_INSTANCE_SIZE = 0x810            # r6: the sEnemy singleton's instance size
ENEMY_LOD_NODE = 0x183436C             # sEnemy::cLodControl (name 0x1412518, size 0x30)
NODE_NAME = 0x4                        # [node+4] = name pointer (stored verbatim)
NODE_INSTANCE_CANDIDATE = 0x14         # [node+0x14] instance slot (zeroed at registration)

UENEMY_NAME_VA = 0x140D9F4             # "uEnemy" base class, size 0x3700 (registration at 0x66c100)
UPLAYER_NAME_VA = 0x140D9EC            # "uPlayer", size 0x4670 (registration at 0x780734)

# Candidate field offsets (RE5 PS3 measured; see module docstring). Live-verify before aiming.
MGR_COUNT, MGR_ARRAY = 0x28, 0x34      # sEnemy instance: u32 count, pointer array
E_POS, E_HP = 0x30, 0x14A4             # uEm: f32[3] pos (y up), s16 hp / s16 hp_max
ALT_E_POS, ALT_E_HP = 0x50, 0xF20      # X360 RE6 sibling layout, tried as fallback
MAX_ENEMIES = 64                       # RE5 PS3's sane bound; RE6 Mercenaries spawns comparably
POS_LIMIT = 100000.0                   # world cm; RE stages are a few thousand cm across
HP_LIMIT = 5000                        # no Mercenaries enemy exceeds this (Napad included)

HEAD_H, TORSO_H = 160.0, 110.0         # cm above the feet (RE5 measured head height)

# Enemy unit-class DTI names from the decrypted EBOOT (name VA -> class name). The scanner-pinned
# registration sites confirm the bytes at these VAs; used to name an instance's DTI live.
KIND_NAMES = {
    0x14215C8: "uEm1370", 0x1421AC0: "uEm3000", 0x14222D8: "uEm3100", 0x1422AE4: "uEm3200",
    0x1423BCC: "uEm4100", 0x142410C: "uEm4200", 0x14247F0: "uEm4300", 0x14252D0: "uEm4400",
    0x1425F9C: "uEm4500", 0x1426374: "uEm4700", 0x1427B3C: "uEm4800", 0x142D4A0: "uEm5100",
    0x142E070: "uEm5120", 0x142E750: "uEm5600", 0x142EB60: "uEm5700", 0x142F6E4: "uEm5800",
    0x142F6EC: "uEm5900", 0x1430DAC: "uEm6000", 0x1431374: "uEm6100", 0x1431F5C: "uEm6200",
    0x1432C18: "uEm6300", 0x1433E00: "uEm6500", 0x14344FC: "uEm7000", 0x14351E0: "uEm7100",
    0x1435B18: "uEm7200", 0x1435ECC: "uEm7300", 0x1437508: "uEm7400", 0x14389E4: "uEm7500",
    0x1438E08: "uEm7600", 0x1439060: "uEm7900", 0x1439998: "uEm8000", 0x143A7F0: "uEm8100",
    0x143AABC: "uEm9000", 0x143AC58: "uEm9010", 0x143AE14: "uEm9020", 0x143B040: "uEm9030",
    0x143B1DC: "uEm9040", 0x143B3C0: "uEm9050", 0x143BAD4: "uEm9900", 0x143C1D4: "uEm9901",
    0x143C3BC: "uEm9902", 0x143C6EC: "uEm9903", 0x143C940: "uEm9904", 0x143CA74: "uEm9907",
    0x143CC7C: "uEm9908", 0x143CE50: "uEm9910", 0x143CF7C: "uEmAnimal", 0x143D948: "uEmChaserBase",
    0x143DE98: "uEmNpcBase", 0x143E26C: "uEmZombieBase", 0x140D9F4: "uEnemy", 0x143E23C: "uEm6000Base",
    0x143EDCC: "uEmBasic",
}
# Only names the class string itself states; the J'avo / Napad / Ogroman gameplay labels still need
# live identification of which uEm#### the Mercenaries stages actually spawn.
ZOMBIE_CLASSES = {"uEmZombieBase", "uEm4100", "uEm4200", "uEm4300", "uEm4400", "uEm4500"}


def ptr_ok(p: int) -> bool:
    return PTR_LO <= p < PTR_HI and p % 4 == 0


def u32(m, a: int) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def enemy_node(m) -> dict | None:
    """Validate the statically pinned sEnemy DTI node (0x183434C) against live RAM. Revision-scoped the
    same way as re6_ps3.splayer_node(): [node+4] must lead to the exact .rodata bytes "sEnemy\\0" of
    this EBOOT. Returns {"node", "name", "class", "instance"}; "instance" is the [node+0x14] candidate
    while it holds a guest pointer."""
    try:
        cls = u32(m, ENEMY_DTI_NODE)
        if cls not in (ENEMY_NODE_CLASS, 0x14DCB00):
            return None
        name_p = u32(m, ENEMY_DTI_NODE + NODE_NAME)
        if not ptr_ok(name_p) or m.rd(name_p, 6) != b"sEnemy":
            return None
        inst = u32(m, ENEMY_DTI_NODE + NODE_INSTANCE_CANDIDATE)
    except Exception:                                   # noqa: BLE001 - guest memory not mapped yet
        return None
    return {"node": ENEMY_DTI_NODE, "name": "sEnemy", "class": cls,
            "instance": inst if ptr_ok(inst) else None}


def _read_layouts(m, inst):
    """Try the candidate (mgr, unit) layouts in order; first one whose whole chain passes sanity wins."""
    for mgr_count, mgr_array, e_pos, e_hp in ((MGR_COUNT, MGR_ARRAY, E_POS, E_HP),
                                              (MGR_COUNT, MGR_ARRAY, ALT_E_POS, ALT_E_HP)):
        try:
            n = u32(m, inst + mgr_count)
            arr = u32(m, inst + mgr_array)
            if not ptr_ok(arr) or not 0 < n <= MAX_ENEMIES:
                continue
            ptrs = struct.unpack(f">{n}I", m.rd(arr, 4 * n))
            foes = []
            ok = True
            for slot, e in enumerate(ptrs):
                if not ptr_ok(e):
                    continue
                pos = struct.unpack(">3f", m.rd(e + e_pos, 12))
                hp, hp_max = struct.unpack(">hh", m.rd(e + e_hp, 4))
                if not all(abs(c) <= POS_LIMIT for c in pos):
                    ok = False
                    break
                if not (0 <= hp <= HP_LIMIT and 0 < hp_max <= HP_LIMIT and hp <= hp_max):
                    ok = False
                    break
                foes.append((slot, e, pos, hp, hp_max))
            if ok and foes:
                return e_pos, e_hp, foes
        except (ValueError, OSError, struct.error):
            continue
    return None


def enemies(m) -> list[dict] | None:
    """The live enemy actor list, or None when the chain cannot be proven. Each entry:
    {"slot", "ptr", "kind" (class name when the instance DTI name matches this EBOOT's table, else None),
    "pos" (x, y up, z, cm), "hp", "hp_max", "alive" (hp > 0), "downed": None, "mutation": None}.
    "downed"/"mutation" need live byte identification (see module docstring) and are honestly absent."""
    n = enemy_node(m)
    if not n or n["instance"] is None:
        return None
    got = _read_layouts(m, n["instance"])
    if got is None:
        return None
    e_pos, _e_hp, foes = got
    out = []
    for slot, e, pos, hp, hp_max in foes:
        kind = None
        try:
            vt = u32(m, e)                       # candidate MT Framework pattern: vtable's getDTI names
            if ptr_ok(vt):
                dti = u32(m, vt + 0x20)          # slot 5 (0x20) = getDTI (measured on RE5 PS3)
                if ptr_ok(dti):
                    name_p = u32(m, dti + NODE_NAME)
                    if ptr_ok(name_p):
                        raw = m.rd(name_p, 16).split(b"\0")[0]
                        txt = raw.decode("ascii", "ignore") if raw else ""
                        kind = KIND_NAMES.get(name_p) or (txt if txt.startswith(("uEm", "uEnemy")) else None)
        except (ValueError, OSError, struct.error):
            kind = None
        out.append({"slot": slot, "ptr": e, "kind": kind, "pos": pos, "hp": hp, "hp_max": hp_max,
                    "alive": hp > 0, "downed": None, "mutation": None,
                    "family": "zombie" if kind in ZOMBIE_CLASSES else None})
    return out


def targets(m) -> list[dict] | None:
    """Aim points for every living enemy: head and torso stay fixed heights above the actor origin;
    correct while an enemy is down once the live downed byte is measured (until then the points are
    the standing-model heights and targets() says so via "downed_known": False)."""
    foes = enemies(m)
    if foes is None:
        return None
    out = []
    for f in foes:
        if not f["alive"]:
            continue
        x, y, z = f["pos"]
        out.append({"slot": f["slot"], "ptr": f["ptr"], "kind": f["kind"], "family": f["family"],
                    "pos": f["pos"], "hp": f["hp"], "hp_max": f["hp_max"],
                    "head": (x, y + HEAD_H, z), "torso": (x, y + TORSO_H, z),
                    "downed_known": False, "downed": None, "mutation": f["mutation"]})
    return out
