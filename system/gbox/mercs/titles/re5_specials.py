"""RE5 Switch Mercenaries United (No Mercy): every character's special moves in play.

The operator, 2026-11-09: the bot must use each character's special abilities and finishers in gameplay "for added
entertainment value ... we don't want the bot standing around, losing the combo, getting lost or dying while having
them do these moves in gameplay and have them maintaining the combo" (Wesker's dash, for one).

The sources are docs/research/mercenaries-character-specials.md (the [Sx] keys are its section 8): section 3.2 and 3.3
are the melee tables, 3.4 Wesker's dash, 4.2 the scoring and combo rules, 5.2 the bosses and 6.2 the ranked moves.
Section 9 there says what the bot does with them and what to check live.

What the game gives a solo player (RE5 United on Switch, every character):
  * a stagger: a gun shot to a Majini's head (he reels holding it) or his legs (he drops to a knee or stumbles); the
    knife seldom staggers [S5][S7];
  * the melee prompt while he is staggered and the player is within reach. It is the action button, Y on Switch, and
    re5_switch_prompt reads it from RAM. The move depends on the stagger and on whether the player stands in front of
    him or behind [S2][S5];
  * i-frames for the move's animation [S34][S55], and +5 s on the round clock for each melee kill (knife kills
    excluded) [S2].

The layer per character (PLANS), from the research's ranking in section 6.2:
  #1 the rear leg-stun instant kills: Chris Neckbreaker, Sheva Throat Slit, Jill Head Grab, Josh Suplex and Excella
     First Aid. A thigh shot, then in behind him for the prompt. When he is still in front, the game gives the front
     move instead; that is the fallback, followed by the grounded move on the Majini it floored;
  #2 the head-stun kill melees: Wesker Cobra Strike (1,200, a kill on any regular Majini), Rebecca Flame Spray (800-900,
     several at once) and Barry Headbutt (a high critical). A head shot, then in for the prompt;
  #3 Wesker's dash and Knee Cannon, behind DASH (off): the Switch input is not confirmed live;
  #4 the bosses' solo chains. Their stagger states are not mapped on Switch, so no setup is ever made on a boss. The
     prompts they show are still pressed by the bot's prompt rule, as always, and counted here. After the second melee
     on an Executioner or a Chainsaw Majini the bot steps away (the axe answer, the berserk swing [S20][S22]);
  #5 the grounded melee after a knockdown (stand over him): the follow-up to a front move that did not kill.

One special (Specials, driven by re5_switch.Bot) runs through these phases:
  aim     the fight's own target, when it qualifies, is shot at the plan's site (Bot._aim_h asks site_h). A hit that
          leaves him alive is the stagger. Once STAGGER_MOTIONS has been measured, his motion must agree;
  rush    the gun goes down and he runs in to the approach point (behind the Majini for a rear move) while the stun
          lasts (STUN_S). The game shows the prompt, and the bot's prompt rule (re5_switch Bot._prompt) presses it at
          once. REAR_DEFER_S (off) can hold a front prompt for a moment while he gets behind;
  press   the move. No trigger is pulled during its animation (ANIM_S), and it is credited when the target dies
          within COMPLETE_S (MOVE_KILL_S for one that should kill) with no trigger pulled on him since;
  ground  the follow-up for a move that did not kill.

The schedule follows the doctrine's combo clock (gbox.mercs.core.doctrine.KILL_PACE_S). A special starts only in the
window right after a kill (more than COMBO_WINDOW_S - KILL_PACE_S left) or when no combo is running. One not yet
pressed is dropped when the window falls under ABORT_LEFT_S, and the fight's gun then finishes him: the combo is never
traded for a move.

The gates:
  * never while he is held, dying or healing, under SAFE_HP of his health, or under the operator's hand;
  * never on a boss, on a Majini winding up, or on a lit dynamite carrier;
  * never with another Majini within ISOLATE_R of him or of his target, nor with more than CROWD_SAFE_N within
    CROWD_SAFE_R of him (87 % of the health he loses is lost with 3+ within 6 m: docs/research/re5-ss-campaign.md);
  * never a head move where a head kill rolls a Cephalo: Missile Area, and the female Majini of Public Assembly
    [S49][S52];
  * never standing: the aim is the fight's own, and the rush and the follow-up move him on every tick.

Nothing here reads or writes the game. The bot's pad is the only output, through re5_switch.Bot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import re5_weapons

try:
    from ..core import doctrine as _doctrine
    KILL_PACE_S = float(getattr(_doctrine, "KILL_PACE_S", 3.0))
except ImportError:                      # (a worker holding no doctrine module yet)
    KILL_PACE_S = 3.0

# --- the switches -------------------------------------------------------------------------------------------------------
SPECIALS = True
# Thigh shots for the leg-stun plans. The operator disliked the aim at the legs and feet on 2026-10-28 ("raise the gun
# and then lower the gun and shoot them in the leg"). The leg stun is the thigh only (LEG_AIM_H), at SETUP_MIN_R or
# more, so the camera pitch stays within CAM_DOWN_MAX of the chest. Off: the leg-plan characters use their head move
# instead.
LEG_STUNS = True
# Wesker's dash: the right-stick click [S2][S57], or both sticks [S56][S59]; the Knee Cannon on the fire button [S2][S56]
# or the action button [S57]. None of these inputs is confirmed on Switch, so the dash is off until a live round shows
# them. It verifies itself: DASH_TRIES presses with no dash seen switch to DASH_FALLBACK_KEYS, then turn it off for the
# run (stats specials_dash_status).
DASH = False
DASH_KEYS, DASH_FALLBACK_KEYS, KNEE_KEYS = ("rstick",), ("lstick", "rstick"), ("zr",)
# A front melee prompt on a Majini leg-stunned for a rear plan is pressed at once (the operator 2026-10-28: "resolve any
# QTE events that ever pop up ... always"). With this above 0, a prompt shown while he is still in front of the Majini
# waits up to this long while he gets behind him (specials_rear_defers).
REAR_DEFER_S = 0.0

# --- the clock -----------------------------------------------------------------------------------------------------------
COMBO_WINDOW_S = 10.0                    # the game's window [S2][S46] (re5_switch.COMBO_WINDOW_S)
START_LEFT_S = COMBO_WINDOW_S - KILL_PACE_S   # a special starts with more than this left: right after a kill
ABORT_LEFT_S = 3.0                       # a special not yet pressed is dropped under this: the gun finishes him
SETUP_MAX_S = 2.0                        # the site shot has this long to land
SITE_PATIENCE_S = 0.6                    # the trigger waits at most this long for the dot to reach the site (never longer:
                                         # the doctrine's "never holding fire"); then any hit on him will do
SITE_PULL_S = 0.05                       # the site shot is one pull this long, then HIT_WINDOW_S for its stagger
STUN_S = 2.2                             # a stun lasts about this long (re5_combat.STUN_S, the PS3 bot's measure)
HIT_WINDOW_S = 0.5                       # his health falls within this of the pull that hit him
COMPLETE_S = 2.5                         # the target dead this soon after the press: the move's kill
ANIM_S = 1.2                             # after a press no trigger this long: the move's animation plays (a pull in it
                                         # does nothing in the game, and would make the move's kill the gun's)
MOVE_KILL_S = 2.0                        # a move that should kill him has this long after its prompt went to do it
GROUND_DELAY_S, GROUND_S = 0.8, 2.0      # a move that did not: then onto him for the grounded prompt, this long
GAP_S, RETRY_S = 1.5, 8.0                # between two specials; a Majini whose special failed is left alone this long

# --- where and who -------------------------------------------------------------------------------------------------------
SETUP_MIN_R, SETUP_MAX_R = 300.0, 900.0  # cm: the site shot from this band (nearer: a grab threat; farther: a long run)
HEAD_AIM_H, LEG_AIM_H = 160.0, 72.0      # cm above his feet: the head (re5_switch.HEAD_H), the thighs (brain.body.THIGH_H)
HEAD_SITE_MIN, LEG_SITE_MAX, SITE_R = 135.0, 100.0, 60.0   # the dot's height on him: head above, legs below; on him
PROMPT_R = 250.0                         # a melee prompt is a Majini's within this (re5_switch.PROMPT_CLEAR_R)
ISOLATE_R = 300.0                        # no other Majini this near him or his target
CROWD_SAFE_R, CROWD_SAFE_N = 600.0, 2    # at most this many others this near him
SAFE_HP = 0.4                            # of his maximum: under it, no special
BOSS_HP = 3000                           # this much health is a boss (gbox.mercs.core.doctrine.BOSS_HP_MIN)
BEHIND_CM, SIDE_CM, SIDE_DEG = 90.0, 130.0, 75.0   # the rear approach: past his side (while within SIDE_DEG of his front)
REACH_CM, RUN_CM = 110.0, 250.0          # the approach point reached; farther than this from it he runs (B)
BEHIND_DEG = 100.0                       # this far round from his front he is behind him (the rear move)
TURN_TOL = math.radians(14)              # re5_switch.TURN_TOL
SITE_FAMILIES = frozenset({"handgun", "automatic", "rifle", "magnum"})   # guns that put one shot where it is aimed
CEPHALO_STAGES = frozenset({"Missile Area"})     # "always avoid any type of melees that hit the head" [S52]
FEMALE_STAGES, FEMALE_HP = frozenset({"Public Assembly"}), 700   # its female Majini (700 HP [S47]) [S49]
# The boss answer: after the second melee on an Executioner or Chainsaw Majini (this much health or more [S47]) within
# BOSS_CHAIN_S, he steps away for BOSS_STEP_S.
BOSS_STEP_HP, BOSS_CHAIN_S, BOSS_STEP_S, BOSS_ANIM_S = 7000, 8.0, 1.0, 0.8   # (the step after BOSS_ANIM_S)
# Wesker's dash: a Majini in a straight lane on his floor, DASH_MIN_R to DASH_MAX_R ahead within DASH_CONE, his health
# at DASH_HP or more (it costs health and neither Wesker carries a First Aid Spray [S2][S8]); the knee within KNEE_R or
# DASH_KNEE_S after the start; the dash seen when he covers DASH_SEEN_CM within DASH_VERIFY_S.
DASH_MIN_R, DASH_MAX_R, DASH_CONE, DASH_HP, DASH_GAP_S = 400.0, 1000.0, math.radians(10), 0.6, 8.0
KNEE_R, DASH_KNEE_S, DASH_END_S, DASH_SEEN_CM, DASH_VERIFY_S, DASH_TRIES = 170.0, 0.9, 1.6, 200.0, 0.6, 3
# The stagger in RAM: the target's own motion byte (+0x8F8) after a site hit. Not measured on Switch yet, so the rush
# starts on the hit alone and the prompt is the confirmation. specials_motions_text records what was seen (after a head
# hit, a leg hit, and when the prompt showed) so these can be filled; with a set filled, the rush needs one of its
# motions within STAGGER_SEE_S of the hit.
STAGGER_MOTIONS = {"head": frozenset(), "leg": frozenset()}
STAGGER_SEE_S = 0.3

# The same as re5_switch's (tests/test_re5_specials.py checks they agree): this module never imports re5_switch.
LEVEL_DY, DYING_HP, PHASE_PLAYING = 120.0, 1, 1
HELD_MOTIONS = frozenset({100, 106, 107, 113, 114})
WINDUP_MOTIONS, E_ATTACKING = frozenset({80, 81, 60, 91}), 0x40
DYNAMITE_CLASSES, DYNAMITE_MOTIONS = ("uEm21", "uEm62"), frozenset({70, 71})
LABEL_TIME_BONUS, LABEL_BREAK_FREE, LABEL_RESUSCITATE, LABEL_PICKUP, LABEL_PLACE = 112, 28, 55, 1, 100
TRAVERSE_LABELS = frozenset({7, 8, 9, 14, 58})
KIND_AREA = 3
NOT_MELEE = frozenset({LABEL_TIME_BONUS, LABEL_BREAK_FREE, LABEL_RESUSCITATE, LABEL_PICKUP, LABEL_PLACE}) | TRAVERSE_LABELS
SURVIVAL_DOINGS = frozenset({"held", "heal", "escape", "mine", "flashbang", "dead", "rearm", "native_equip"})
PLAYER_FAMILIES = {"00": "Chris", "01": "Sheva", "02": "Jill", "03": "Wesker", "04": "Josh", "05": "Excella",
                   "06": "Barry", "07": "Rebecca"}
FAMILIES = tuple(PLAYER_FAMILIES.values())

# The round's counters (re5_switch.RE5Switch.round_counters: the engine records each one's amount as round_<key>)
COUNTERS = ("specials_attempts", "specials_presses", "specials_completions", "specials_kills", "specials_aborts",
            "specials_s", "specials_rushes", "specials_rear", "specials_rear_defers", "specials_opportunistic",
            "specials_ground", "specials_site_waits", "specials_site_holds", "specials_anim_holds",
            "specials_boss_melees", "specials_boss_steps",
            "specials_dash_attempts", "specials_dash_seen")


# --- the moves -----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Move:
    """One melee: who, from which stagger and side ("head", "arm_front", "arm_back", "leg_front", "leg_back",
    "finisher_front", "finisher_back", "grounded", "dash"), its damage on a regular Majini (None: an instant kill) and
    its hits, the other source's value, the source keys."""
    name: str
    family: str
    position: str
    damage: int | None
    hits: int = 1
    note: str = ""
    sources: str = ""

    def kills(self, hp) -> bool:
        """Whether the move takes this much health (a regular Majini's 700-900; his health after the stagger shot)."""
        return self.damage is None or (isinstance(hp, (int, float)) and self.damage * self.hits >= hp)

    @property
    def key(self) -> str:
        return f"{self.family} {self.name}"


POSITIONS = ("head", "arm_front", "arm_back", "leg_front", "leg_back", "finisher_front", "finisher_back", "grounded")


def _table(family, sources, rows):
    return {pos: Move(name, family, pos, dmg, hits, note, sources) for pos, (name, dmg, hits, note) in zip(POSITIONS, rows)}


# The research's tables 3.2 (the base set: in United every Chris and Sheva costume uses it [S4]) and 3.3 (Reunion's four):
# the first value is [S2] / [S3]; the other source's in the note.
MOVES = {
    "Chris": _table("Chris", "[S2]", (
        ("Straight", 400, 1, ""), ("Hook", 300, 1, ""), ("Kick", 300, 1, ""), ("Uppercut", 400, 1, ""),
        ("Neckbreaker", None, 1, "instant kill, no Plaga [S5]"), ("Haymaker", 3000, 1, ""), ("Backhand", 3000, 1, ""),
        ("Stomp", 600, 1, "head critical"))),
    "Sheva": _table("Sheva", "[S2][S47]", (
        ("Roundhouse", 350, 1, ""), ("Twist Kick", 250, 1, "[S47]: 225"), ("Knee", 250, 1, "[S47]: 225"),
        ("Somersault", 350, 1, ""), ("Throat Slit", None, 1, "instant kill"), ("Skull Crusher", None, 1, "[S47]: 3,000"),
        ("Spinning Back Kick", 3000, 1, "[S7]: instant kill"), ("Impale", 800, 1, ""))),
    "Jill": _table("Jill", "[S2][S47]", (
        ("High Kick", 350, 1, ""), ("Roundhouse", 250, 1, ""), ("Reverse Roundhouse", 250, 1, ""),
        ("Sweep Kick", 350, 1, ""), ("Head Grab", None, 1, "instant kill"), ("Flip Kick", 2000, 2, "[S47]: 2,000"),
        ("Cartwheel Kick", 2000, 2, ""), ("Double Knee Drop", 1200, 1, "kills a downed regular Majini"))),
    "Wesker": _table("Wesker", "[S2][S8][S48]", (
        ("Cobra Strike", 1200, 1, "kills any regular Majini (700-900 HP, the Agitator 1,400) [S47]"),
        ("Panther Fang", 300, 1, ""), ("Jaguar Kick", 300, 1, ""), ("Tiger Uppercut", 400, 1, ""),
        ("Mustang Kick", 500, 1, ""), ("Ghost Butterfly", 4000, 1, ""), ("Rhino Charge", 4000, 1, ""),
        ("Windfall", 600, 1, ""))),
    "Josh": _table("Josh", "[S3][S17]", (
        ("Hammer Blow", 700, 1, "[S17]: 500"), ("Backhand", 400, 1, "[S17]: 300"), ("Iron Tackle", 800, 1, "[S17]: 500"),
        ("Power Kick", 400, 1, ""), ("Suplex", None, 1, "instant kill"), ("Chokeslam", None, 1, "[S17]: 4,000"),
        ("Dynamite Kick", 3000, 1, "[S17]: 4,000"), ("Elbow Drop", 1000, 1, "[S17]: 1,200"))),
    "Excella": _table("Excella", "[S3][S16]", (
        ("High Heel", 400, 1, ""), ("Slap", 50, 1, "[S16]: 100"), ("Back Hand", 50, 1, ""),
        ("Humiliate", 800, 1, "[S16]: 750"), ("First Aid", None, 1, "instant kill, no Plaga, the corpse explodes [S16]"),
        ("Disco Spin", 3000, 2, "[S16]: 4,000"), ("Disco Spin", 3000, 2, ""), ("Heel Stomp", 500, 4, "[S16]: 600 x2"))),
    "Barry": _table("Barry", "[S3][S18]", (
        ("Headbutt", 400, 1, "a high critical [R3]"), ("Barry Sandwich", 300, 1, ""), ("Knee", 300, 1, "[S18]: 250"),
        ("Burton Boot", 400, 1, "[S18]: 250"), ("Gun Bash", 600, 1, "[S18]: 800, instant death but parasites may appear"),
        ("Hurricane", 2000, 4, "[S18]: 1,500 x4"), ("Hurricane", 2000, 4, ""),
        ("Miranda Rights", 5000, 1, "[S18]: 1,200, head critical"))),
    "Rebecca": _table("Rebecca", "[S3][S19]", (
        ("Flame Spray", 900, 1, "[S19]: 800; kills most normal Majini and hits several at once"),
        ("Tear Gas", 200, 1, ""), ("Rump Shaker", 200, 1, ""), ("Jump Hit", 300, 1, ""), ("Head Cracker", 400, 1, ""),
        ("Stun Gun", 8000, 1, "[S19]: 5,000"), ("Stun Gun", 8000, 1, ""), ("Kick", 500, 1, ""))),
}
KNEE_CANNON = Move("Knee Cannon", "Wesker", "dash", 1000, 1, "usually kills a normal Majini; ends the dash",
                   "[S2][S5][S47][S48][S57]")


@dataclass(frozen=True)
class Plan:
    """A character's special: the stagger site ("head" / "leg"), the move wanted, the move the game gives when he is
    in front instead (None: the head move has no side), whether the grounded move follows a move that did not kill,
    and the research's rank."""
    site: str
    want: str
    fallback: str | None
    grounded: bool
    rank: str


REAR_KILL = Plan("leg", "leg_back", "leg_front", True, "6.2 #1: the rear leg-stun instant kill")
HEAD_KILL = Plan("head", "head", None, True, "6.2 #2: the head-stun kill melee")
REAR_SAFE = Plan("leg", "leg_back", "leg_front", True, "6.2 #1 site: the leg stun (a head move rolls a Cephalo here)")
HEAD_ONLY = Plan("head", "head", None, True, "the head move (LEG_STUNS off)")
PLANS = {"Chris": REAR_KILL, "Sheva": REAR_KILL, "Jill": REAR_KILL, "Josh": REAR_KILL, "Excella": REAR_KILL,
         "Wesker": HEAD_KILL, "Rebecca": HEAD_KILL, "Barry": HEAD_KILL}
# The select's names (re5_switch.CHARACTERS) and United's other costumes [S4]. Every costume plays its character's set;
# the notes are what the loadout changes for the specials (section 3.5).
COSTUMES = {
    "Chris (BSAA)": ("Chris", "M92F / Ithaca: handgun site shots"),
    "Chris (Safari)": ("Chris", "SIG P226 handgun; sunglasses: his own flash does not blind him [S2]"),
    "Chris (STARS)": ("Chris", "SIG 556 automatic, S&W M29 magnum"),
    "Chris (Warrior)": ("Chris", "H&K P8 handgun, PSG-1 rifle"),
    "Chris (Heavy Metal)": ("Chris", "the Gatling (automatic); a Stun Rod kill also adds 5 s [S35]"),
    "Sheva (BSAA)": ("Sheva", "M92F handgun, VZ61"),
    "Sheva (Clubbin)": ("Sheva", "AK-74 automatic, S75 rifle"),
    "Sheva (Tribal)": ("Sheva", "longbow and grenade launcher only: no laser gun, so no site shot (the bow's own "
                                "controller fights)"),
    "Sheva (Business)": ("Sheva", "SIG P226 handgun, L. Hawk magnum"),
    "Sheva (Fairy Tale)": ("Sheva", "SIG 556 automatic, S&W M500 magnum"),
    "Jill (BSAA)": ("Jill", "Px4 handgun, MP5"),
    "Jill (Battle Suit)": ("Jill", "VZ61 x300 automatic, PSG-1 rifle"),
    "Wesker (Midnight)": ("Wesker", "H&K P8 handgun, M500; no First Aid Spray: the dash's health is budgeted"),
    "Wesker (STARS)": ("Wesker", "Samurai Edge handgun, L. Hawk; no First Aid Spray"),
    "Josh (BSAA)": ("Josh", "M92F x100 handgun"),
    "Excella": ("Excella", "M93R handgun, AK-74; the flash launcher kills Plaga forms [S16]"),
    "Barry (STARS)": ("Barry", "Samurai Edge handgun, M29; no healing item [S18]"),
    "Rebecca (STARS)": ("Rebecca", "MP5 automatic; First Aid Spray x2"),
}


def identify(stats: dict) -> tuple:
    """(family, costume) of the character in play: the player object's RAM class names the character (uPl03Wesker:
    PLAYER_FAMILIES), the round's name (stats character, else the queued selection's) the costume. A name of another
    character than the class is not used; with no class, the name alone."""
    cls = (stats or {}).get("player_class")
    by_class = PLAYER_FAMILIES.get(cls[3:5]) if isinstance(cls, str) and cls.startswith("uPl") else None
    names = [(stats or {}).get("character")]
    queued = (stats or {}).get("queued_selection")
    if isinstance(queued, str) and queued.count("/") >= 2:
        names.append(queued.split("/")[1].strip())        # "no_mercy / Wesker (STARS) / Ancient Ruins"
    for name in names:
        if not isinstance(name, str):
            continue
        family = next((f for f in FAMILIES if name.startswith(f)), None)
        if family is not None and (by_class is None or family == by_class):
            return family, name if name in COSTUMES else None
    return by_class, None


def cephalo_risk(stage, target) -> bool:
    """A head melee here may roll a Cephalo from the Majini it kills: Missile Area [S52], and the female Majini (700 HP
    [S47]) of Public Assembly [S49]."""
    if stage in CEPHALO_STAGES:
        return True
    return stage in FEMALE_STAGES and (target or {}).get("hp_max") == FEMALE_HP


def plan_for(family, stage=None, target=None) -> Plan | None:
    """The character's special against this Majini on this stage (None: none)."""
    plan = PLANS.get(family)
    if plan is None:
        return None
    if plan.site == "leg" and not LEG_STUNS:
        plan = HEAD_ONLY
    if plan.site == "head" and cephalo_risk(stage, target):
        return REAR_SAFE if LEG_STUNS else None
    return plan


def move(family, position) -> Move | None:
    return MOVES.get(family, {}).get(position)


# --- geometry ------------------------------------------------------------------------------------------------------------
def key_of(e) -> object:
    return e.get("ptr", e.get("slot"))


def flat(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def site_of(dot, foot) -> str | None:
    """Where on him the laser dot sits: "head", "leg" (the thighs), "body", None (not on him)."""
    if not dot or not foot or math.hypot(dot[0] - foot[0], dot[2] - foot[2]) > SITE_R:
        return None
    dy = dot[1] - foot[1]
    return "head" if dy >= HEAD_SITE_MIN else "leg" if dy <= LEG_SITE_MAX else "body"


def facing(e, toward=None) -> tuple | None:
    """The unit (x, z) he faces: his heading when the snapshot read one (enemy rot), else toward `toward` (a Majini
    shot faces the shooter)."""
    rot = e.get("rot")
    if isinstance(rot, (int, float)) and not isinstance(rot, bool) and math.isfinite(rot):
        return math.sin(rot), math.cos(rot)
    if toward is None:
        return None
    dx, dz = toward[0] - e["pos"][0], toward[2] - e["pos"][2]
    n = math.hypot(dx, dz)
    return (dx / n, dz / n) if n > 1.0 else None


def round_angle(pos, e, face) -> float | None:
    """How far round from his front the player stands (degrees: 0 in front, 180 behind), None without a facing."""
    if face is None:
        return None
    dx, dz = pos[0] - e["pos"][0], pos[2] - e["pos"][2]
    n = math.hypot(dx, dz)
    if n < 1.0:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, (dx * face[0] + dz * face[1]) / n))))


def approach_point(pos, e, face, rear: bool) -> tuple:
    """Where to run for the prompt: onto him for a front or head move; for a rear move first past his side (while he
    stands within SIDE_DEG of the Majini's front), then BEHIND_CM behind him."""
    tx, ty, tz = e["pos"]
    if not rear or face is None:
        return tx, ty, tz
    angle = round_angle(pos, e, face)
    if angle is not None and angle < SIDE_DEG:
        lx, lz = face[1], -face[0]                       # his left (a larger heading)
        side = 1.0 if (pos[0] - tx) * lx + (pos[2] - tz) * lz >= 0 else -1.0
        return tx + side * SIDE_CM * lx, ty, tz + side * SIDE_CM * lz
    return tx - BEHIND_CM * face[0], ty, tz - BEHIND_CM * face[1]


def combo_left(snap) -> float | None:
    combo, left = (snap or {}).get("combo"), (snap or {}).get("combo_timer")
    if type(combo) is not int or combo <= 0 or isinstance(left, bool) or not isinstance(left, (int, float)):
        return None
    return float(left) if 0.0 < left < 600.0 else None


def winding(e) -> bool:
    return e.get("motion") in WINDUP_MOTIONS or bool((e.get("act") or 0) & E_ATTACKING)


def dynamite(e) -> bool:
    return any(str(e.get("class") or "").startswith(c) for c in DYNAMITE_CLASSES) and e.get("motion") in DYNAMITE_MOTIONS


def held_weapon(snap):
    """(item, family) of the weapon in hand, (None, None) without one."""
    held = next((s for s in (snap or {}).get("inventory") or () if s.get("hand")), None)
    if not held or held.get("type") != 1:
        return None, None
    w = re5_weapons.WEAPONS.get(held.get("item"))
    return held.get("item"), (w.family if w else None)


def melee_prompt(pr, snap, pos):
    """The Majini a shown prompt is a melee for, or None. A melee is a press prompt that names a living Majini (its
    owner or target), or any other press prompt with a living Majini on his floor within PROMPT_R. Never the hourglass,
    Break free, Resuscitate, a pickup, the bomb's Place, the ledges and doors (TRAVERSE_LABELS) or an area pickup."""
    if not pr or not pos or not str(pr.get("token") or "").startswith("press:"):
        return None
    if pr.get("label") in NOT_MELEE or pr.get("kind") == KIND_AREA:
        return None
    alive = [e for e in (snap or {}).get("enemies") or () if (e.get("hp") or 0) > 0 and e.get("pos")]
    named = next((e for e in alive if e.get("ptr") and e.get("ptr") in (pr.get("target"), pr.get("owner"))), None)
    if named is not None:
        return named
    near = [e for e in alive if flat(e["pos"], pos) <= PROMPT_R and abs(e["pos"][1] - pos[1]) <= LEVEL_DY]
    return min(near, key=lambda e: flat(e["pos"], pos), default=None)


# --- one special ---------------------------------------------------------------------------------------------------------
class Attempt:
    """One special under way: kind "stun" (a site shot, then in for the prompt), "dash", "ground" (the follow-up),
    "opportunistic" (a melee prompt with no setup of his) or "boss" (a boss's chain prompt)."""

    def __init__(self, kind, family, target, plan, want, now, hp, kills, site=None):
        self.kind, self.family, self.target, self.plan, self.want = kind, family, target, plan, want
        self.move = None                     # the move pressed
        self.site = site
        self.phase = "aim" if kind == "stun" else kind if kind in ("dash", "ground") else "press"
        self.started = self.phase_at = now
        self.hp, self.kills0 = hp, kills
        self.hit_at = None
        self.face = None                     # the unit (x, z) he faces: his heading read, else toward the player
        self.first_press = None
        self.presses = 0
        self.gone_at = None                  # the prompt gone after the press
        self.fired = False                   # a trigger pulled after the press: a gun kill, not the move's
        self.prompt_at = None                # a melee prompt first shown during the rush (REAR_DEFER_S)
        self.labels: list = []
        self.off_site = 0
        self.pull_at = None                  # the site shot's pull
        self.prev = None                     # a follow-up's: the move before it (name, family, its press, kills then)
        self.dash: dict = {}
        self.why = ""

    @property
    def name(self) -> str:
        m = self.move or self.want
        return m.key if m is not None else f"{self.family} special"


class Specials:
    """The special-move layer's state for one bot. re5_switch.Bot calls: observe (every tick, before its decisions),
    defer (before its prompt rule), pressed (when its prompt rule pressed this tick), drive (in the fight, before the
    crowd fire), consider (in the fight, once the target is chosen), site_h (the aim height), post (the tick's final
    pad), new_round."""

    def __init__(self, stats: dict):
        self.stats = stats
        self.att: Attempt | None = None
        self.last_end = -1e9
        self.blocked: dict = {}              # target -> until (RETRY_S)
        self.zr_at = -1e9
        self.site = (None, -1e9)             # the dot's site on the attempt's target at the last pull, when
        self.t = None
        self.last_doing = None
        self.melee_at = None                 # the tick a melee prompt was first pressed
        self.boss_melees: dict = {}          # boss -> [the press times]
        self.step: tuple | None = None       # (boss, from, until): stepping away from him
        self.dash = {"keys": DASH_KEYS, "misses": 0, "seen": 0, "off": False, "at": -1e9, "costs": [], "pending": None}
        self.reason = ""                     # why none runs now (the last gate's)
        self.site_tick = None                # (now, his foot, the site's height): the camera guards' aim this tick
        for k in COUNTERS:
            stats.setdefault(k, 0)

    # --- accounting ---
    def _move_row(self, key) -> dict:
        moves = self.stats.setdefault("specials_moves", {})
        return moves.setdefault(key, {"attempts": 0, "presses": 0, "completions": 0, "kills": 0, "s": 0.0})

    def _char_row(self, family) -> dict:
        rows = self.stats.setdefault("specials_by_character", {})
        return rows.setdefault(family or "unknown", {"attempts": 0, "presses": 0, "completions": 0, "kills": 0,
                                                     "played_s": 0.0, "per_min": 0.0, "completions_per_min": 0.0})

    def _count(self, key, n=1) -> None:
        self.stats[key] = round((self.stats.get(key) or 0) + n, 2)

    def _note(self, table, key, value) -> None:
        """A small histogram in stats (labels / motions per move: for the prompt map, spark2 ticket #9187)."""
        rows = self.stats.setdefault(table, {})
        row = rows.setdefault(str(key), {})
        if str(value) in row or len(row) < 24:
            row[str(value)] = row.get(str(value), 0) + 1
        self.stats[table + "_text"] = " | ".join(
            f"{k}: " + " ".join(f"{v}x{n}" for v, n in sorted(r.items(), key=lambda x: -x[1])[:8])
            for k, r in sorted(rows.items()))[:600]

    def _summary(self, family) -> None:
        moves = self.stats.get("specials_moves") or {}
        rows = sorted(moves.items(), key=lambda kv: -(kv[1]["presses"] + kv[1]["attempts"]))
        ch = self._char_row(family)
        head = (f"{family or 'unknown'} {ch['per_min']:.1f}/min ({ch['presses']} moves, {ch['completions']} kills by "
                f"the move)")
        self.stats["specials_summary"] = " | ".join(
            [head] + [f"{k} {r['completions']}/{r['attempts']} done, {r['presses']} pressed, {r['kills']} kills, "
                      f"{r['s']:.1f} s" for k, r in rows[:8]])[:600]

    def _end(self, now, outcome: str, completed=False, kills=0) -> None:
        att, self.att = self.att, None
        if att is None:
            return
        self.last_end = now
        secs = max(0.0, now - att.started)
        row = self._move_row(att.name)
        row["attempts"] += 1
        row["s"] = round(row["s"] + secs, 2)
        ch = self._char_row(att.family)
        ch["attempts"] += 1
        self._count("specials_s", round(secs, 2))
        if completed:
            row["completions"] += 1
            row["kills"] += max(1, kills)
            ch["completions"] += 1
            ch["kills"] += max(1, kills)
            self._count("specials_completions")
            self._count("specials_kills", max(1, kills))
        elif att.first_press is None:
            self._count("specials_aborts")
            reasons = self.stats.setdefault("specials_abort_reasons", {})
            reason = outcome.split(":")[0][:60]
            if reason in reasons or len(reasons) < 24:
                reasons[reason] = reasons.get(reason, 0) + 1
            self.stats["specials_abort_reasons_text"] = " | ".join(
                f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:10])[:400]
            if att.target is not None:
                self.blocked[att.target] = now + RETRY_S
        self.stats["specials_last"] = (f"{att.name} ({att.kind}): {outcome} after {secs:.1f} s"
                                       + (f", {max(1, kills)} kill(s)" if completed else ""))[:200]
        self._summary(att.family)
        self._per_min(att.family)

    def _late_credit(self, now, prev, kills) -> None:
        """The follow-up was waiting, unpressed, when the move before it killed him after all: that move completed (its
        attempt is already in the ledger), and the follow-up never ran (no attempt of its own)."""
        name, family, _first, _k0 = prev
        self.att, self.last_end = None, now
        n = max(1, kills)
        row, ch = self._move_row(name), self._char_row(family)
        row["completions"] += 1
        row["kills"] += n
        ch["completions"] += 1
        ch["kills"] += n
        self._count("specials_completions")
        self._count("specials_kills", n)
        self._count("specials_ground", -1)
        self.stats["specials_last"] = f"{name}: the move killed him (late in its animation), {n} kill(s)"[:200]
        self._summary(family)
        self._per_min(family)

    def _per_min(self, family) -> None:
        ch = self._char_row(family)
        played = ch["played_s"]
        ch["per_min"] = round(60.0 * ch["presses"] / played, 2) if played >= 1.0 else 0.0
        ch["completions_per_min"] = round(60.0 * ch["completions"] / played, 2) if played >= 1.0 else 0.0
        self.stats["specials_per_min"] = ch["per_min"]
        self.stats["specials_completions_per_min"] = ch["completions_per_min"]

    # --- the gates ---
    def gate(self, bot, snap, tgt, *, start: bool) -> str | None:
        """None when a special may start (start) or go on, else why not."""
        st = self.stats
        p = snap.get("player") or {}
        hp, top = p.get("hp") or 0, p.get("hp_max") or 0
        if not SPECIALS:
            return "off"
        if st.get("operator_control"):
            return "the operator has the pad"
        if snap.get("mercenaries_phase") not in (None, PHASE_PLAYING):
            return "not playing"
        if hp <= DYING_HP:
            return "dying"
        if p.get("motion") in HELD_MOTIONS:
            return "held"
        if getattr(bot, "healing", None) is not None:
            return "healing"
        if top > 0 and hp < SAFE_HP * top:
            return f"health {hp / top:.0%}: under {SAFE_HP:.0%}"
        left = combo_left(snap)
        if start and left is not None and left <= START_LEFT_S:
            return f"combo {left:.1f} s left: a special starts only right after a kill (over {START_LEFT_S:.0f} s)"
        if not start and left is not None and left < ABORT_LEFT_S:
            return f"combo {left:.1f} s left: the gun finishes him"
        if tgt is None or (tgt.get("hp") or 0) <= 0:
            return "no target"
        if (tgt.get("hp_max") or 0) >= BOSS_HP:
            return "a boss: his stagger states are not mapped"
        if winding(tgt):
            return "he winds up an attack"
        if dynamite(tgt):
            return "lit dynamite"
        pos = p.get("pos")
        if not pos:
            return "no position"
        tk = key_of(tgt)
        others = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and e.get("pos") and key_of(e) != tk
                  and abs(e["pos"][1] - pos[1]) <= LEVEL_DY]
        close = [e for e in others if flat(e["pos"], pos) < ISOLATE_R or flat(e["pos"], tgt["pos"]) < ISOLATE_R]
        if close:
            return f"another Majini {min(flat(e['pos'], pos) for e in close) / 100:.1f} m from him or his target"
        crowd = sum(1 for e in others if flat(e["pos"], pos) <= CROWD_SAFE_R)
        if crowd > CROWD_SAFE_N:
            return f"{crowd} others within {CROWD_SAFE_R / 100:.0f} m"
        return None

    # --- every tick ---
    def observe(self, bot, snap, now) -> None:
        """Before the bot decides: the round's played seconds, the attempt's hit, stagger, death, time and gates."""
        dt = 0.0 if self.t is None else max(0.0, min(now - self.t, 0.25))
        self.t = now
        p = snap.get("player") or {}
        family, _costume = identify(self.stats)
        self.stats["specials_character"] = family
        alive = (p.get("hp") or 0) > 0 and snap.get("mercenaries_phase") in (None, PHASE_PLAYING)
        if alive and family and dt:
            ch = self._char_row(family)
            ch["played_s"] = round(ch["played_s"] + dt, 2)
            if int(ch["played_s"]) != int(ch["played_s"] - dt):
                self._per_min(family)
        if self.step is not None and now >= self.step[2]:
            self.step = None
        if self.dash.get("pending") is not None and now - self.dash["pending"]["t0"] >= DASH_VERIFY_S:
            self._dash_verify(p, now)
        att = self.att
        if att is None:
            return
        if not alive:
            self._end(now, "he went down")
            return
        enemies = {key_of(e): e for e in snap.get("enemies") or ()}
        tgt = enemies.get(att.target)
        dead = tgt is None or (tgt.get("hp") or 0) <= 0
        kills = snap.get("kills")
        killed = (kills - att.kills0) if type(kills) is int and type(att.kills0) is int else 0
        if att.phase == "press" and att.first_press is not None:
            if dead:
                if att.fired:
                    self._end(now, "finished by the gun after the move")
                elif now - att.first_press <= COMPLETE_S + MOVE_KILL_S:
                    self._end(now, "the move killed him", completed=True, kills=killed)
                else:
                    self._end(now, "he died long after the move")
                return
            shown = melee_prompt(snap.get("prompt"), snap, p.get("pos")) is not None
            if not shown and att.gone_at is None:
                att.gone_at = now
            mv = att.move
            expect = mv is not None and mv.position not in ("unknown", "boss") and mv.kills(att.hp)
            if att.gone_at is not None and now - att.gone_at >= (MOVE_KILL_S if expect else GROUND_DELAY_S):
                nxt = move(att.family, "grounded")
                if att.kind in ("stun", "opportunistic") and att.plan is not None and att.plan.grounded \
                        and nxt is not None and mv is not None and mv.position != "grounded" \
                        and self.gate(bot, snap, tgt, start=False) is None:
                    plan, prev = att.plan, (att.name, att.family, att.first_press, att.kills0)
                    self._end(now, f"floored him: the {nxt.name} next")
                    g = self.att = Attempt("ground", att.family, att.target, plan, nxt, now, tgt["hp"], kills)
                    g.face, g.prev = att.face, prev
                    self._count("specials_ground")
                else:
                    self._end(now, "he survived the move")
                return
            if now - att.first_press > COMPLETE_S + MOVE_KILL_S:
                self._end(now, "the prompt stayed up")
                return
            return
        if self.last_doing in SURVIVAL_DOINGS and att.first_press is None:
            self._end(now, f"survival first: {self.last_doing}")
            return
        if att.phase == "aim":
            if dead:
                self._end(now, "the gun killed him before a stagger")
                return
            if tgt["hp"] < att.hp and now - self.zr_at <= HIT_WINDOW_S:
                site = self.site[0] if now - self.site[1] <= HIT_WINDOW_S else None
                if site is not None:
                    self._note("specials_motions", f"{site} hit", tgt.get("motion"))
                if site is None or site == att.site:
                    need = STAGGER_MOTIONS.get(att.site) or frozenset()
                    if not need or tgt.get("motion") in need or tgt.get("motion") is None:
                        att.phase, att.phase_at, att.hit_at = "rush", now, now
                        att.face = facing(tgt, p.get("pos"))
                        self._count("specials_rushes")
                else:
                    att.off_site += 1
            att.hp = tgt["hp"]
            if att.phase == "aim" and now - att.started > SETUP_MAX_S:
                self._end(now, f"no {att.site} stagger in {SETUP_MAX_S:.0f} s")
                return
        elif att.phase == "rush":
            if dead:
                self._end(now, "he died before the prompt")
                return
            if now - att.hit_at > STUN_S:
                self._end(now, f"no prompt within the {STUN_S:.1f} s stun")
                return
            att.hp = tgt["hp"]
            why = self.gate(bot, snap, tgt, start=False)
            if why is not None:
                self._end(now, f"stopped: {why}")
                return
        elif att.phase == "ground":
            if dead:
                prev = getattr(att, "prev", None)
                if prev is not None and not att.fired and now - prev[2] <= COMPLETE_S + MOVE_KILL_S:
                    self._late_credit(now, prev, killed)     # the first move's kill, late in its animation
                else:
                    self._end(now, "he died before the grounded prompt")
                return
            if now - att.started > GROUND_S:
                self._end(now, f"no grounded prompt in {GROUND_S:.0f} s")
                return
            why = self.gate(bot, snap, tgt, start=False)
            if why is not None:
                self._end(now, f"stopped: {why}")
                return
        elif att.phase == "dash":
            if dead:
                if att.dash.get("knee_at") is not None and not att.fired:
                    self._end(now, "the knee killed him", completed=True, kills=killed)
                else:
                    self._end(now, "he died before the knee")
                return
            if now - att.started > DASH_END_S + 0.5:
                self._end(now, "the dash ended without the kill")
                return
            why = self.gate(bot, snap, tgt, start=False)
            if why is not None and att.dash.get("knee_at") is None:
                self._end(now, f"stopped: {why}")
                return

    def defer(self, bot, snap, now) -> dict | None:
        """REAR_DEFER_S: a front prompt held a moment while he gets behind the Majini (the rush's move instead)."""
        att = self.att
        if REAR_DEFER_S <= 0 or att is None or att.phase != "rush" or att.plan is None or att.plan.want != "leg_back":
            return None
        p = snap.get("player") or {}
        m = melee_prompt(snap.get("prompt"), snap, p.get("pos"))
        if m is None or key_of(m) != att.target:
            return None
        att.prompt_at = att.prompt_at or now
        angle = round_angle(p["pos"], m, facing(m) or att.face)
        if now - att.prompt_at > REAR_DEFER_S or now - att.hit_at > STUN_S - 0.5 or angle is None \
                or angle >= BEHIND_DEG:
            return None
        self._count("specials_rear_defers")
        return self.drive(bot, p, snap, now)

    def _close(self, now, snap, why) -> None:
        """The attempt under way ends because another melee comes: its move's kill if he is dead already."""
        att = self.att
        if att is None:
            return
        tgt = next((e for e in (snap or {}).get("enemies") or () if key_of(e) == att.target), None)
        dead = tgt is None or (tgt.get("hp") or 0) <= 0
        if att.first_press is not None and dead and not att.fired:
            kills = snap.get("kills")
            n = kills - att.kills0 if type(kills) is int and type(att.kills0) is int else 0
            self._end(now, "the move killed him", completed=True, kills=n)
        else:
            self._end(now, why)

    def pressed(self, bot, snap, now) -> None:
        """The bot's prompt rule pressed the shown prompt this tick: a melee prompt's first press is a move."""
        pr = snap.get("prompt") or {}
        p = snap.get("player") or {}
        st = getattr(bot, "_pr", None) or {}
        m = melee_prompt(pr, snap, p.get("pos"))
        if m is None or st.get("presses") != 1:
            return
        self.melee_at = now
        family, _ = identify(self.stats)
        label = pr.get("label")
        mk = key_of(m)
        kills = snap.get("kills")
        att = self.att
        if (m.get("hp_max") or 0) >= BOSS_HP:              # a boss's chain: each melee its own move, counted
            times = [t for t in self.boss_melees.get(mk, []) if now - t <= BOSS_CHAIN_S] + [now]
            self.boss_melees = {k: v for k, v in self.boss_melees.items() if v and now - v[-1] <= BOSS_CHAIN_S}
            self.boss_melees[mk] = times
            self._count("specials_boss_melees")
            if len(times) >= 2 and (m.get("hp_max") or 0) >= BOSS_STEP_HP:
                self.step = (mk, now + BOSS_ANIM_S, now + BOSS_ANIM_S + BOSS_STEP_S)   # after the move's animation
            self._close(now, snap, "a boss's prompt came")
            att = self.att = Attempt("boss", family, mk, None, Move("boss melee", family or "", "boss", 0), now,
                                     m.get("hp"), kills)
            att.move = att.want
        elif att is not None and att.target == mk and att.first_press is not None:
            # his second melee on the same Majini: the one that floored him, then the grounded move
            plan = att.plan
            self._close(now, snap, "floored him: another melee followed")
            att = self.att = Attempt("ground", family, mk, plan, move(family, "grounded"), now, m.get("hp"), kills)
            self._count("specials_ground")
        elif att is None or att.target != mk:
            self._close(now, snap, "another Majini's prompt came first")
            plan = plan_for(family, self._stage(), m)
            att = self.att = Attempt("opportunistic", family, mk, plan, None, now, m.get("hp"), kills)
            self._count("specials_opportunistic")
        if att.first_press is None:
            att.move = att.move or self._which(att, m, p, family, label)
            att.phase, att.first_press, att.kills0 = "press", now, kills
        att.presses += 1
        att.labels.append(label)
        att.why = f"{att.name} pressed (label {label})"
        self._count("specials_presses")
        if att.move is not None and att.move.position == "leg_back":
            self._count("specials_rear")
        self._move_row(att.name)["presses"] += 1
        self._char_row(att.family)["presses"] += 1
        self._per_min(att.family)
        self._note("specials_labels", att.move.position if att.move else "unknown", label)
        self._note("specials_motions", "prompt", m.get("motion"))
        bot.why = f"{bot.why} | specials: {att.why}" if bot.why else f"specials: {att.why}"

    def _which(self, att, m, p, family, label) -> Move:
        """The move this press is: the follow-up's own; by the attempt's site and where he stands round the Majini;
        with no site of his (a prompt he did not set up), "melee" by the prompt's label."""
        if att.kind in ("ground", "boss") and att.want is not None:
            return att.want
        site = att.site if att.kind == "stun" else None
        mv = None
        if site == "head":
            mv = move(family, "head")
        elif site == "leg":
            angle = round_angle(p.get("pos"), m, facing(m) or att.face)
            mv = move(family, "leg_back" if angle is not None and angle >= BEHIND_DEG else "leg_front")
        return mv or Move(f"melee (label {label})", family or "unknown", "unknown", 0)

    def _stage(self):
        for k in ("ss_stage", "stage"):
            v = self.stats.get(k)
            if isinstance(v, str) and v:
                return v
        return None

    # --- in the fight ---
    def drive(self, bot, p, snap, now) -> dict | None:
        """A phase that moves him (the rush, the follow-up, the dash, the boss step): this tick's pad, else None."""
        if self.step is not None and self.step[1] <= now < self.step[2] \
                and (self.att is None or self.att.first_press is not None):
            boss = next((e for e in snap.get("enemies") or () if key_of(e) == self.step[0] and (e.get("hp") or 0) > 0),
                        None)
            if boss is not None and getattr(bot, "_pr", None) is None:
                err = wrap(heading(boss["pos"][0] - p["pos"][0], boss["pos"][2] - p["pos"][2]) - p["rot"])
                bot._gun_down()
                if self.stats.get("specials_step_at") != self.step[2]:
                    self.stats["specials_step_at"] = self.step[2]
                    self._count("specials_boss_steps")
                bot.doing, bot.why = "backoff", (f"specials: stepping away from the boss after his second melee "
                                                 f"({flat(boss['pos'], p['pos']) / 100:.1f} m)")
                return {"hold": ("ldown",) + bot._turn(err, TURN_TOL)}
        att = self.att
        if att is None or att.phase not in ("rush", "ground", "dash"):
            return None
        tgt = next((e for e in snap.get("enemies") or () if key_of(e) == att.target and (e.get("hp") or 0) > 0), None)
        if tgt is None:
            return None
        pos = p["pos"]
        if att.phase == "dash":
            return self._dash_step(bot, p, tgt, snap, now)
        rear = att.phase == "rush" and att.plan is not None and att.plan.want == "leg_back"
        face = facing(tgt) or att.face
        goal = approach_point(pos, tgt, face, rear) if att.phase == "rush" else tgt["pos"]
        d_goal, d_tgt = flat(goal, pos), flat(tgt["pos"], pos)
        bot._gun_down()
        if getattr(bot, "_aim_wait", None) is not None:
            bot._aim_wait = None                              # (a reposition step does not take the rush over)
        if d_goal <= REACH_CM:                                # there: face him and step in (the prompt shows)
            err = wrap(heading(tgt["pos"][0] - pos[0], tgt["pos"][2] - pos[2]) - p["rot"])
            keys = ("lup",) + bot._turn(err, TURN_TOL)
        else:
            err = wrap(heading(goal[0] - pos[0], goal[2] - pos[2]) - p["rot"])
            keys = (("lup", "b") if d_goal > RUN_CM else ("lup",)) + bot._turn(err, TURN_TOL)
        angle = round_angle(pos, tgt, face)
        if att.phase == "rush":
            left = STUN_S - (now - att.hit_at)
            where = ("behind him" if angle is not None and angle >= BEHIND_DEG else "round his side" if rear
                     else "in")
            att.why = (f"{att.name}: {att.site} stun at {d_tgt / 100:.1f} m, {where} for the prompt "
                       f"({left:.1f} s of the stun)")
        else:
            att.why = f"{att.name}: onto the floored Majini {d_tgt / 100:.1f} m for the grounded prompt"
        bot.doing, bot.why = "walk", f"specials: {att.why}"
        return {"hold": keys}

    def consider(self, bot, p, snap, tgt, now) -> dict | None:
        """The fight chose `tgt` this tick: the setup goes on, ends, or starts on him; Wesker's dash may start (its
        first pad returned)."""
        att = self.att
        tk = key_of(tgt) if tgt is not None else None
        if att is not None:
            if att.phase == "aim":
                if tk != att.target:
                    self._end(now, "the fight took another target")
                else:
                    why = self.gate(bot, snap, tgt, start=False)
                    d = flat(tgt["pos"], p["pos"])
                    if why is None and d < 0.5 * SETUP_MIN_R:
                        why = f"he closed to {d / 100:.1f} m"
                    if why is not None:
                        self._end(now, f"stopped: {why}")
                    else:
                        side = "head" if att.site == "head" else "thighs"
                        left = combo_left(snap)
                        att.why = (f"{att.name}: aiming his {side} at {d / 100:.1f} m"
                                   + (f", combo {left:.1f} s left" if left is not None else ""))
            return None
        if tgt is None or now - self.last_end < GAP_S or self.blocked.get(tk, -1e9) > now:
            return None
        family, _ = identify(self.stats)
        if family is None:
            self.reason = "the character is not known yet"
            return None
        why = self.gate(bot, snap, tgt, start=True)
        if why is not None:
            self.reason = why
            return None
        pos = p["pos"]
        d = flat(tgt["pos"], pos)
        if abs(tgt["pos"][1] - pos[1]) > LEVEL_DY:
            self.reason = "off his floor"
            return None
        item, fam = held_weapon(snap)
        if DASH and family == "Wesker" and not self.dash["off"]:
            act = self._dash_start(bot, p, snap, tgt, d, now)
            if act is not None:
                return act
        if not SETUP_MIN_R <= d <= SETUP_MAX_R:
            self.reason = f"target {d / 100:.1f} m: outside {SETUP_MIN_R / 100:.0f}-{SETUP_MAX_R / 100:.0f} m"
            return None
        if fam not in SITE_FAMILIES:
            self.reason = f"the weapon in hand ({fam or 'none'}) cannot place a site shot"
            return None
        plan = plan_for(family, self._stage(), tgt)
        if plan is None:
            self.reason = "no special for this Majini here"
            return None
        want = move(family, plan.want)
        self.att = Attempt("stun", family, tk, plan, want, now, tgt.get("hp"), snap.get("kills"), site=plan.site)
        self._count("specials_attempts")
        self.reason = ""
        left = combo_left(snap)
        self.att.why = (f"{want.key if want else family}: aiming his {'head' if plan.site == 'head' else 'thighs'} at "
                        f"{d / 100:.1f} m" + (f", combo {left:.1f} s left" if left is not None else ""))
        return None

    def site_h(self, bot, tgt, now) -> float | None:
        """The aim height on `tgt` while a setup aims at him (Bot._aim_h), else None."""
        att = self.att
        if att is None or att.phase != "aim" or tgt is None or key_of(tgt) != att.target or not tgt.get("pos"):
            return None
        h = HEAD_AIM_H if att.site == "head" else LEG_AIM_H
        self.site_tick = (now, tuple(tgt["pos"]), h)
        return h

    def aim_h_at(self, bot, foot, now) -> float | None:
        """The same for a foot position this tick (the camera pitch guards know only his foot)."""
        tick = getattr(self, "site_tick", None)
        if tick is None or tick[0] != now or not foot or flat(tick[1], foot) > 1.0:
            return None
        return tick[2]

    def post(self, bot, act, snap, now) -> dict:
        """The tick's final pad: the site shot (the trigger waits up to SITE_PATIENCE_S while the dot is on him away
        from the site), the pull's site on the target, a trigger after a press, the why line. Returns the pad."""
        hold = set(act.get("hold") or ())
        att = self.att
        if "zr" in hold and att is not None and att.phase == "aim":
            tgt = next((e for e in snap.get("enemies") or () if key_of(e) == att.target), None)
            lz = snap.get("laser") or {}
            site = site_of(lz["at"], tgt["pos"]) if tgt is not None and lz.get("up") and lz.get("at") else None
            age = now - att.pull_at if att.pull_at is not None else None
            part = "head" if att.site == "head" else "thighs"
            if site is not None and site != att.site and now - att.started < SITE_PATIENCE_S:
                hold.discard("zr")                       # the dot on his body, short of the site: a moment more
                self._count("specials_site_waits")
                att.why = f"{att.name}: the dot on his {site}, onto his {part} first"
            elif age is None or age >= SITE_PULL_S + HIT_WINDOW_S:
                att.pull_at, self.site = now, (site, now)   # a pull at the site
            elif age <= SITE_PULL_S:
                self.site = (site, now)                  # (the pull, to its end)
            else:
                hold.discard("zr")                       # one pull, then the stagger it makes is waited for (the
                self._count("specials_site_holds")       # held trigger repeats: up to 25 shots/s with fire_rate)
                att.why = (f"{att.name}: one shot at his {part}, its stagger awaited "
                           f"{SITE_PULL_S + HIT_WINDOW_S - age:.1f} s more")
            if "zr" not in hold:
                act = dict(act, hold=tuple(sorted(hold)))
                self._release(bot, now)
                if getattr(bot, "doing", None) == "fire":
                    bot.doing = "aim"
        if "zr" in hold and att is not None and att.phase == "press" and att.first_press is not None \
                and now - att.first_press < ANIM_S:
            hold.discard("zr")                           # the move's animation: no trigger in it (the stance may stay)
            act = dict(act, hold=tuple(sorted(hold)))
            self._release(bot, now)
            self._count("specials_anim_holds")
            if getattr(bot, "doing", None) == "fire":
                bot.doing = "aim"
        if "zr" in hold or act.get("tap") == "zr":
            self.zr_at = now
            if att is not None and att.first_press is not None and now - att.first_press > 0.15:
                att.fired = True                         # (the dash's knee is its own press: 0.15 s after it)
        self.last_doing = "prompt" if self.melee_at == now else getattr(bot, "doing", None)
        if att is not None and att.why and "specials:" not in (bot.why or ""):
            bot.why = f"{bot.why} | specials: {att.why}" if bot.why else f"specials: {att.why}"
        self.stats["specials_status"] = (f"{att.phase}: {att.why}" if att is not None
                                         else f"idle: {self.reason}" if self.reason else "idle")[:200]
        return act

    @staticmethod
    def _release(bot, now) -> None:
        """The trigger up without a slip (the bot's pull ends; the next press is the next shot)."""
        if getattr(bot, "fire_down", False):
            end = getattr(bot, "_pull_end", None)
            if callable(end):
                end(now)
        bot.fire_down = False

    def new_round(self, bot, now) -> None:
        if self.att is not None:
            self._end(now, "the round began again")
        self.blocked, self.boss_melees, self.step = {}, {}, None

    # --- Wesker's dash ---
    def _dash_start(self, bot, p, snap, tgt, d, now) -> dict | None:
        dash = self.dash
        hp, top = p.get("hp") or 0, p.get("hp_max") or 0
        if now - dash["at"] < DASH_GAP_S or not DASH_MIN_R <= d <= DASH_MAX_R or (top and hp < DASH_HP * top):
            return None
        err = wrap(heading(tgt["pos"][0] - p["pos"][0], tgt["pos"][2] - p["pos"][2]) - p["rot"])
        if abs(err) > DASH_CONE:
            return None
        mesh = snap.get("nav")
        if mesh is not None and hasattr(mesh, "floor_segment"):
            try:
                if not mesh.floor_segment(tuple(p["pos"]), tuple(tgt["pos"])):
                    return None                          # a wall stops the dash [S2]
            except Exception:                            # noqa: BLE001 - the mesh never costs a tick
                return None
        family, _ = identify(self.stats)
        att = self.att = Attempt("dash", family, key_of(tgt), None, KNEE_CANNON, now, tgt.get("hp"), snap.get("kills"))
        att.dash = {"t0": now, "step": 0, "keys": dash["keys"], "knee_at": None}
        dash["at"] = now
        self._count("specials_attempts")
        self._count("specials_dash_attempts")
        return self._dash_step(bot, p, tgt, snap, now)

    def _dash_verify(self, p, now) -> None:
        """DASH_VERIFY_S after a click: did he dash (DASH_SEEN_CM covered)? Its health cost (stats
        specials_dash_hp_cost: the research's open question, "a small amount" [S2] / about 15 % [S58]); no dash seen in
        DASH_TRIES clicks: the fallback keys, then off for the run."""
        dash = self.dash
        st, dash["pending"] = dash["pending"], None
        if not p.get("pos"):
            return
        moved = flat(p["pos"], st["pos0"])
        if moved >= DASH_SEEN_CM:
            dash["seen"] += 1
            dash["misses"] = 0
            self._count("specials_dash_seen")
            cost = st["hp0"] - (p.get("hp") or 0)
            if cost >= 0:
                dash["costs"] = (dash["costs"] + [cost])[-20:]
                self.stats["specials_dash_hp_cost"] = round(sum(dash["costs"]) / len(dash["costs"]), 1)
            self.stats["specials_dash_status"] = (f"dash seen ({moved / 100:.1f} m in {DASH_VERIFY_S:.1f} s, keys "
                                                  f"{'+'.join(st['keys'])})")
            return
        dash["misses"] += 1
        if dash["misses"] < DASH_TRIES or dash["seen"]:
            return
        if tuple(dash["keys"]) == tuple(DASH_KEYS) and DASH_FALLBACK_KEYS:
            dash["keys"], dash["misses"] = DASH_FALLBACK_KEYS, 0
            self.stats["specials_dash_status"] = (f"no dash after {DASH_TRIES} clicks of {'+'.join(DASH_KEYS)}: "
                                                  f"trying {'+'.join(DASH_FALLBACK_KEYS)}")
        else:
            dash["off"] = True
            self.stats["specials_dash_status"] = (f"no dash after {DASH_TRIES} clicks of {'+'.join(dash['keys'])} "
                                                  f"either: off for the run")

    def _dash_step(self, bot, p, tgt, snap, now) -> dict:
        att, dash = self.att, self.dash
        st = att.dash
        pos = p["pos"]
        d = flat(tgt["pos"], pos)
        err = wrap(heading(tgt["pos"][0] - pos[0], tgt["pos"][2] - pos[2]) - p["rot"])
        bot._gun_down()
        steer = bot._turn(err, TURN_TOL)                  # "tilt the right stick to steer" [S2]
        if dash.get("pending") is not None and now - dash["pending"]["t0"] >= DASH_VERIFY_S:
            self._dash_verify(p, now)
        if st["step"] == 0:                               # the dash: one tick of the click
            dash["pending"] = {"t0": now, "pos0": tuple(pos), "hp0": p.get("hp") or 0, "keys": tuple(st["keys"])}
            st["step"] = 1
            keys = tuple(st["keys"]) + ("lup",)
            att.why = f"{att.name}: the dash at him {d / 100:.1f} m ({'+'.join(st['keys'])})"
        elif st["step"] == 1 and (d <= KNEE_R or now - st["t0"] >= DASH_KNEE_S):
            st["step"], st["knee_at"] = 2, now            # the knee: one tick of the fire button
            att.first_press, att.kills0 = now, snap.get("kills")
            keys = tuple(KNEE_KEYS) + steer
            self._count("specials_presses")
            self._move_row(att.name)["presses"] += 1
            self._char_row(att.family)["presses"] += 1
            self._per_min(att.family)
            att.why = f"{att.name}: the knee at {d / 100:.1f} m ({'+'.join(KNEE_KEYS)})"
        else:
            keys = ("lup",) + steer                       # (never standing: he pushes on at him)
            if st["step"] == 2 and now - st["t0"] >= DASH_END_S:
                st["step"] = 3
        bot.doing, bot.why = "walk", f"specials: {att.why}"
        return {"hold": keys}
