"""Armored Core per-game data for gbox/ac_mods_tool.py (ac_mods).

Each game: title match, RAM layout of the player's AC (verified live on gBox sessions), catalog key
(profiles/gamedata/<key>-parts.json, read from the game's own parts table) and the weight/energy rules the garage uses.
Addresses are console addresses (PS1 0x80xxxxxx, PSP 0x08xxxxxx); the tool maps them to the adapter's RAM offsets.

Armored Core (USA, SLUS-01323), verified 2026-10-06 on pcsx_rearmed (Spark):
  assembly bytes (per-slot list index, 0xFF = nothing)  0x80031A58 core, 59 booster, 5A head, 5B arms, 5C arm weapon L
      (laser blade), 5D arm weapon R, 5E back L, 5F back R, 60 generator, 61 FCS, 63 legs.  The garage summary, the
      garage 3D preview and the mission all read this array (Assembly copies it to a work struct 0x801A29CC on entry and
      writes it back on exit, so write while NOT inside the Assembly screen).
  owned-parts flags  u8[147] at 0x80031A94 (order: head 10, core 3, arms 16, legs 32, generator 7, FCS 8, options 11,
      booster 6, back weapons 34, arm weapon R 16 (incl. NO WEAPON), laser blade 4). Assembly re-reads them on entry.
  optional parts equipped  u16 bitmask at 0x80039CA0 (bit = option id)
  credits  s32 at 0x80039CA4
  mission: AP*4 u16 at 0x801A2818, max AP*4 at 0x801A281A (player AC)
"""

AC1_ORDER = ["head", "core", "arms", "legs", "generator", "fcs", "option", "booster", "back_weapon", "arm_weapon_r",
             "arm_weapon_l"]
AC1_COUNTS = {"head": 10, "core": 3, "arms": 16, "legs": 32, "generator": 7, "fcs": 8, "option": 11, "booster": 6,
              "back_weapon": 34, "arm_weapon_r": 16, "arm_weapon_l": 4}


def _flag_base(order, counts):
    out, n = {}, 0
    for c in order:
        out[c] = n
        n += counts[c]
    return out, n


_AC1_FLAGS, _AC1_NFLAGS = _flag_base(AC1_ORDER, AC1_COUNTS)
# Project Phantasma: same engine/layout, bigger padded lists (DUMMY entries keep their index)
ACPP_COUNTS = {"head": 18, "core": 11, "arms": 24, "legs": 40, "generator": 15, "fcs": 16, "option": 19, "booster": 14,
               "back_weapon": 59, "arm_weapon_r": 21, "arm_weapon_l": 9}
_ACPP_FLAGS, _ACPP_NFLAGS = _flag_base(AC1_ORDER, ACPP_COUNTS)
ACMOA_COUNTS = {"head": 18, "core": 11, "arms": 24, "legs": 40, "generator": 15, "fcs": 16, "option": 19, "booster": 14,
                "back_weapon": 60, "arm_weapon_r": 26, "arm_weapon_l": 6}
_ACMOA_FLAGS, _ACMOA_NFLAGS = _flag_base(AC1_ORDER, ACMOA_COUNTS)


def _asm(base):
    """AC1-engine assembly byte layout starting at the core byte."""
    return {"core": base, "booster": base + 1, "head": base + 2, "arms": base + 3, "arm_weapon_l": base + 4,
            "arm_weapon_r": base + 5, "back_weapon_l": base + 6, "back_weapon_r": base + 7, "generator": base + 8,
            "fcs": base + 9, "legs": base + 11}

GAMES = {
    "ac1": {
        "name": "Armored Core", "platforms": ["psx"], "catalog": "ac1-parts",
        "match": r"^armored core(\s*\((usa|europe|japan)|$)", "exclude": r"phantasma|master of arena",
        "assembly": {"core": 0x80031A58, "booster": 0x80031A59, "head": 0x80031A5A, "arms": 0x80031A5B,
                     "arm_weapon_l": 0x80031A5C, "arm_weapon_r": 0x80031A5D, "back_weapon_l": 0x80031A5E,
                     "back_weapon_r": 0x80031A5F, "generator": 0x80031A60, "fcs": 0x80031A61, "legs": 0x80031A63},
        "list_of": {"back_weapon_l": "back_weapon", "back_weapon_r": "back_weapon"},   # slot -> catalog list
        "none": 0xFF, "no_weapon": {"arm_weapon_r": 0},
        "weapon_arms": {"min": 8, "pair": ("arm_weapon_r", 0), "clear": ["arm_weapon_l"]},   # arms ids >= 8 (AW-*) carry
        # their own weapon: hand weapon = NO WEAPON and no laser blade (the garage ignores a blade on weapon arms)
        "owned": 0x80031A94, "owned_base": _AC1_FLAGS, "owned_count": _AC1_NFLAGS,
        "options_mask": 0x80039CA0, "credits": 0x80039CA4, "credits_max": 99999999,
        "ap": (0x801A2818, 4),
        # garage rules (verified against the Assembly screen numbers):
        #   EP   = sum(energy_drain of every part) <= generator energy_output
        #   LEGS = sum(weight of every part except legs) <= legs max_weight
        #   CORE = weight(arms + arm weapon R + arm weapon L) <= core max_weight_arms
        "rules": {"dual_back": ("WX-", "XCS-"), "ep": True, "legs_weight": True, "core_weight": ("arms", "arm_weapon_r", "arm_weapon_l")},
        "apply_note": ("The garage (summary list + 3D preview) shows the change the next time the garage menu or "
                       "Assembly is opened; the next sortie launches with it. Don't write while the Assembly screen is "
                       "open: leaving it writes its own copy back."),
        "build_guide": ("AC1 community builds list parts by name (HD-ONE, XCA-00, AN-K1, LN-501, WG-1-KARASAWA, "
                        "LS-99-MOONLIGHT, GBG-10000, B-VR-33, QX-AF...). Pass them to op=apply_build parts=[...]; "
                        "back weapons go L then R; laser blades are arm_weapon_l; weapon arms (AW-*) replace arms + "
                        "right-hand weapon. Keep EP <= generator output and weights under the leg/core limits or the "
                        "garage refuses to sortie (Not Enough Energy / Overweight)."),
    },
    "acpp": {
        "name": "Armored Core: Project Phantasma", "platforms": ["psx"], "catalog": "acpp-parts",
        "match": r"project phantasma",
        "assembly": _asm(0x800342B4),
        "list_of": {"back_weapon_l": "back_weapon", "back_weapon_r": "back_weapon"},
        "none": 0xFF, "no_weapon": {"arm_weapon_r": 0},
        "weapon_arms": {"min": 12, "pair": ("arm_weapon_r", 0), "clear": ["arm_weapon_l"]},
        "owned": 0x800342F0, "owned_base": _ACPP_FLAGS, "owned_count": _ACPP_NFLAGS,
        "options_mask": 0x8003BCCC, "credits": 0x8003BCD0, "credits_max": 99999999,
        "ap": (0x801E2F40, 4),            # verified in the first mission; other missions: scanned (u16 cur, max = AP*4)
        "rules": {"dual_back": ("WX-", "XCS-"), "ep": True, "legs_weight": True, "core_weight": ("arms", "arm_weapon_r", "arm_weapon_l"),
                  "caterpillar_no_booster": True},
        "apply_note": ("The garage (summary + 3D preview) shows the change the next time the garage menu or Assembly is "
                       "opened; the next sortie launches with it. Don't write while the Assembly screen is open."),
        "build_guide": ("Project Phantasma adds parts to the AC1 set (HD-G780, XXA/S0 core, LN-2KZ-SP, AW-DC/2, WG-RFM118, "
                        "WG-XFwPPk, WA-Finger, WM-AT, WC-SPGUN, WC-IR24, RZ-Fw2, B-HP25, FBMB-18X, RATOR, GBX-TL/XL, "
                        "SP-DEhf). Pass community build part names to op=apply_build; same EP/weight rules as AC1."),
    },
    "acmoa": {
        "name": "Armored Core: Master of Arena", "platforms": ["psx"], "catalog": "acmoa-parts",
        "match": r"master of arena",
        "assembly": _asm(0x80036FB0),
        "list_of": {"back_weapon_l": "back_weapon", "back_weapon_r": "back_weapon"},
        "none": 0xFF, "no_weapon": {"arm_weapon_r": 0},
        "weapon_arms": {"min": 12, "pair": ("arm_weapon_r", 0), "clear": ["arm_weapon_l"]},
        "owned": 0x80036FEC, "owned_base": _ACMOA_FLAGS, "owned_count": _ACMOA_NFLAGS,
        "options_mask": 0x8003EA70, "credits": 0x8003EA74, "credits_max": 99999999,
        "ap": (0x801E73B0, 4),            # verified (same as the community GameShark 'infinite AP' code)
        "rules": {"dual_back": ("WX-", "XCS-"), "ep": True, "legs_weight": True, "core_weight": ("arms", "arm_weapon_r", "arm_weapon_l"),
                  "caterpillar_no_booster": True},
        "apply_note": ("The garage (summary + 3D preview) shows the change the next time the garage menu or Assembly is "
                       "opened; the next sortie launches with it. Don't write while the Assembly screen is open. Disc 1 "
                       "and disc 2 share the save data layout."),
        "build_guide": ("Master of Arena has the Project Phantasma parts plus HD-12-RADAR, HD-HELM, HD-H10, HD-4004, XXL-D0, "
                        "LN-S3, LB-H230, LF-TR-0, LC-HTP-H5, AN-891-S, AW-R/4, WG-HG770, WG-XW11, WG-FGI-00, WG-RF/E, "
                        "WG-MG500/E, WM-MVG812, WM-X15-EX, WR-RS7, WRR-10, WX-ED2, WX-C/4, P77-ST, LS-1000W, B-PT000, "
                        "P/CV, SP-DEtq, SP-ABS_Re. Pass community build names to op=apply_build; same EP/weight rules."),
    },
}
