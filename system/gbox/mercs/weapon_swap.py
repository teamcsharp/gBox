"""Instant RAM active-weapon swap DECISION layer for the Mercenaries bots.

Operator directive (2026-11-04): the bot should use the FULL arsenal and swap at
will -- default MAGNUM, instant-swap to the GRENADE LAUNCHER (plus the existing
grenade / flash / remote-bomb / mine systems) while a crowd is on him, then swap
back to the magnum when the circle thins -- and the on-screen ITEM WHEEL must NEVER
appear, because a RAM swap looks cooler and reads as mastery on stream.

WHERE THE "SET ACTIVE SLOT INSTANTLY" PRIMITIVE LIVES
-----------------------------------------------------
It already exists, per title, as the guarded native-equip controller:

  * RE6 Switch: gbox.mercs.titles.re6_switch_native (action26 request) and the
    higher-level re6_switch_weapon_native.select(); the driver holds it as
    Bot.native_equip and calls .select(player, index). Measured ~37 ms live
    (2026-10-29): it writes the pending-selection / request cells and the game's
    OWN cPlAction_pl_act_weapon_change attaches and enables the native hand object.
  * RE5 Switch: gbox.mercs.titles.re5_switch_equip.Controller -- Bot.native_equip,
    .select(grid, id) -- publishes action 0x20's pending byte; the game's own
    weapon-change action then attaches the loaded hand object.

Both are RAM-write-triggered swaps that drive the game's own equip action and
attach the loaded native hand object WITHOUT ever opening the item wheel. That IS
the operator's preferred "write the equipped slot directly in memory" path.

We deliberately do NOT poke the raw active-slot / active-object cells directly
(RE6 player+0x5050 ACTIVE_OBJECT / +0x5064 ACTIVE_INDEX; the RE5 equivalents).
Those external writes are not an atomic game-thread transaction and corrupt the
hand-object lifecycle (crash / wrong model), as both native modules document at
length. So "set the active slot instantly" == "ask the native-equip controller to
select the LOADED slot of the wanted weapon," and the wheel never shows.

WHAT THIS MODULE ADDS
---------------------
The title-agnostic DECISION engine on top of that primitive: a pure policy
(`decide`) that, from the crowd state and which weapon families are loaded, picks
the weapon FAMILY to hold, plus thin per-title resolvers that map that family to
the currently-loaded slot the driver's EXISTING native-equip path then equips.
The title drivers call this through a single, clearly-commented hook each, so the
item-wheel-free swap is driven entirely from here and a later merge with the
parallel QTE work stays trivial. 3DS / VR follow by adding a resolver once they
expose a native-equip primitive (gbox-mods-parity-across-editions).

Nothing here emits movement or fires: the bot's own hard rules -- keep moving, NO
wall shots, NO standing on own mines (gbox-bot-no-wall-shots-no-mine-standing) --
and the grenade / flash / bomb / mine systems stay exactly where they are. This
only chooses which loaded weapon is in his hands.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SwapProfile:
    """The operator's crowd-swap combat profile for one title.

    Mutable and module-level so a profile op (re*_switch_mods.bot_options arsenal=)
    can flip `enabled` without the driver importing anything new. `enabled` False
    makes every resolver return None, i.e. the driver keeps its stock behaviour.
    """
    enabled: bool = False
    default_family: str = "magnum"          # what he holds with no crowd on him
    crowd_family: str = "launcher"          # swapped to while a crowd is on him
    # tried in order when the preferred family above is not loaded this round:
    crowd_fallback: tuple = ("launcher", "shotgun", "magnum")
    default_fallback: tuple = ("magnum", "shotgun")
    crowd_n: int = 3                        # this many foes within crowd_r == a crowd
    crowd_r: float = 500.0                  # cm, on his level (level_dy)
    level_dy: float = 250.0                 # cm, vertical band that counts as "his level"
    crowd_clear_hold_s: float = 1.2         # keep the heavy weapon this long after it thins


# Per-title profiles. RE6 gets the full magnum<->grenade-launcher swap (its launcher
# is a verified direct-fire gun on this build). RE5's launcher firing is NOT verified
# (re5_weapons.fire_policy refuses it without a decoded round type), so RE5's crowd
# weapon falls back to the verified shotgun/magnum and the native-flash grenade bursts
# + mines already carry the "heavy" crowd answer there -- see re5_rampage_families.
PROFILES = {
    "re6": SwapProfile(crowd_family="launcher",
                       crowd_fallback=("launcher", "shotgun", "magnum")),
    "re5": SwapProfile(crowd_family="shotgun",
                       crowd_fallback=("shotgun", "magnum", "automatic")),
}


def set_enabled(title: str, on: bool) -> bool:
    PROFILES[title].enabled = bool(on)
    return PROFILES[title].enabled


def _state(bot) -> dict:
    st = getattr(bot, "_arsenal", None)
    if st is None:
        st = bot._arsenal = {"heavy_until": -1e9, "family": None}
    return st


def decide(profile: SwapProfile, *, loaded_families, crowd_count, now, state) -> str | None:
    """Pure: the weapon FAMILY to hold, or None to leave the stock logic in charge.

    loaded_families: the set/iterable of families that have a LOADED slot right now.
    crowd_count: live foes within the profile's crowd radius on his level.
    state: the per-bot dict from _state (carries the crowd-clear hold across ticks).
    """
    if not profile.enabled:
        return None
    loaded = set(loaded_families)
    if crowd_count >= profile.crowd_n:
        state["heavy_until"] = now + profile.crowd_clear_hold_s
    heavy = now < state.get("heavy_until", -1e9)
    order = profile.crowd_fallback if heavy else profile.default_fallback
    want = profile.crowd_family if heavy else profile.default_family
    chosen = want if want in loaded else next((f for f in order if f in loaded), None)
    state["family"] = chosen
    return chosen


# --- RE6 Switch resolver ------------------------------------------------------
# Weapon TYPES (0x100 + item id) per family on this RE6 build; mirrors the family
# maps in re6_switch_mods (MAGNUM_TYPES / SHOTGUN_TYPES, launcher item 18 = 0x112).
RE6_FAMILY_TYPES = {
    "magnum": (0x107, 0x108),
    "launcher": (0x112,),
    "shotgun": (0x104, 0x105, 0x106),
    "machine gun": (0x10E, 0x10F, 0x111),
}


def _re6_crowd(bot, p, profile: SwapProfile) -> int:
    import math
    snap = getattr(bot, "_snap", None) or {}
    px, py, pz = p["pos"]
    n = 0
    for e in snap.get("enemies") or ():
        if (e.get("hp") or 0) <= 0:
            continue
        ex, ey, ez = e["pos"]
        if abs(ey - py) <= profile.level_dy and math.hypot(ex - px, ez - pz) <= profile.crowd_r:
            n += 1
    return n


def re6_desired_index(bot, p, held, now):
    """The wheel index RE6's Bot._weapon_switch should equip under the arsenal
    profile, or None to defer to its stock logic. `held` maps weapon TYPE (0x1xx)
    -> loaded wheel index (the driver has already dropped empty-magazine slots).

    The index is handed back to the SAME native-equip path, so no item wheel ever
    appears; returning the already-equipped index is a safe no-op there.
    """
    profile = PROFILES["re6"]
    if not profile.enabled:
        return None
    loaded = {fam for fam, types in RE6_FAMILY_TYPES.items() if any(t in held for t in types)}
    family = decide(profile, loaded_families=loaded, crowd_count=_re6_crowd(bot, p, profile),
                    now=now, state=_state(bot))
    if family is None:
        return None
    for t in RE6_FAMILY_TYPES.get(family, ()):            # first loaded slot of that family
        if t in held:
            return held[t]
    return None


# --- RE5 Switch resolver ------------------------------------------------------
# RE5 already swaps with no wheel: the driver equips by D-pad quick slot and
# re5_switch._native_equipment attaches it through re5_switch_equip (the native
# action, no wheel). Its crowd answer is the shotgun/magnum rampage plus native-flash
# grenade bursts and mines. The arsenal profile only re-orders that family
# preference; the launcher stays out of it because its firing is unverified on this
# build. Returns None (-> keep the driver's RAMPAGE_FAMILIES) unless arsenal is on.
RE5_FAMILY_ORDER = ("magnum", "shotgun", "automatic")


def re5_rampage_families(bot):
    profile = PROFILES["re5"]
    if not profile.enabled:
        return None
    # Magnum first by default (operator: rapid-fire magnums), shotgun for the circle.
    return RE5_FAMILY_ORDER
