"""RE5 Mercenaries (Reunion, solo) recommended-run plans for all eight stages.

Source: docs/mercenaries_re5_meta.md section 3 (Berserker solo routes, kouryakutsushin / stv_tribute Reunion maps,
RE5 Zone hourglass counts). This is static data: stage name, hourglass inventory (counts agree with the in-game
starting time budget), ordered route legs, stands, boss schedule and reference score. The RAM navmesh remains the
truth for positions; legs name landmarks the route follower matches to navmesh regions.

`route_legs(stage, kills)` returns the legs the bot should be executing at a kill count, so the screensaver run can
follow the recommended route. Disputed hourglass layouts carry uncertain=True and use the RE5 Zone counts.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Leg:
    start: int          # first kill count at which this leg applies
    end: int            # last kill count (inclusive)
    goal: str           # landmark name
    note: str = ""
    bonus: int = 0      # hourglass seconds collected at the goal (0 = none)


@dataclass(frozen=True)
class StagePlan:
    key: str
    name: str
    start_seconds: int           # starting clock budget in the stage (hourglass total is added to this)
    hourglasses: tuple           # seconds per hourglass
    hourglass_total: int         # expected sum (in game: total shown time minus base 0:00 per source)
    legs: tuple
    stands: tuple
    bosses: tuple = ()
    record: str = ""
    uncertain: bool = False
    notes: str = ""


def _plan(**kw):
    return StagePlan(**kw)


STAGES = {p.key: p for p in (
    _plan(
        key="public_assembly", name="Public Assembly", start_seconds=0, hourglass_total=420, record="846,708 Rebecca",
        hourglasses=(30, 30, 60, 30, 60, 60, 60, 60, 30),
        legs=(
            Leg(0, 2, "platform_start", "shoot the hill Majini once; grenade the central house wall if quiet"),
            Leg(0, 10, "north_shack", "drop between the two buildings, not over the roofs", 30),
            Leg(0, 12, "west_waterway", "grenade the chicken (+2000), melee the opening crowd", 30),
            Leg(13, 30, "waterway_strip", "stand between the ramp and the north wall; Executioner 1 below the west building"),
            Leg(20, 45, "back_alley", "take it when few are near", 60),
            Leg(20, 50, "columns", "30 s when few are near", 30),
            Leg(50, 70, "rooftop", "roof at 50-70 combo", 60),
            Leg(50, 75, "bus", "drop off the east side onto a Majini", 60),
            Leg(70, 100, "transformer_alley", "fight between the buildings; grenade the cracked wall, take the 60 s after a kill", 60),
            Leg(100, 140, "south_bus_side", "cocktails from ~100 combo, avoid oil canisters"),
            Leg(141, 149, "south_building_ladder", "60 s before the last kill; gun the last Majini (no melee)", 60),
        ),
        stands=("waterway strip", "alley by transformer", "bus side"),
        bosses=("Executioner 1 @20", "Executioner 2 @50", "Executioner 3 @70"),
    ),
    _plan(
        key="mines", name="The Mines", start_seconds=0, hourglass_total=360, record="810k Josh",
        hourglasses=(30, 90, 30, 60, 30, 30, 60, 30),
        legs=(
            Leg(0, 10, "upper_cave", "north tunnel; kill chicken 1 on the way", 30),
            Leg(0, 20, "tall_platform", "ladder up to the 90 s, back down", 90),
            Leg(10, 30, "bottom_tunnel", "pass the red-wrench camper; chicken 2; fight the narrow corridor"),
            Leg(30, 45, "back_cave", "Reaper 1 at 30 from the back-fence ledge", 30),
            Leg(35, 60, "dead_end_cave", "30 s + chest after the first kill", 30),
            Leg(40, 70, "dead_end_tunnel", "60 s by the back chest on the way", 60),
            Leg(60, 90, "long_tunnel_south", "Reapers 2 @70 and 3 @90; stay inside until ~90"),
            Leg(90, 120, "north_area", "open north only when Majini stop grouping at the tunnel mouth"),
            Leg(100, 130, "west_dead_end", "60 s west dead-end tunnel", 60),
            Leg(130, 149, "wooden_bridge", "30 s on the bridge before the last kills", 30),
        ),
        stands=("narrow lower corridor", "long tunnel south end", "tunnel mouth"),
        bosses=("Reaper @30", "Reaper @70", "Reaper @90"),
    ),
    _plan(
        key="village", name="Village", start_seconds=0, hourglass_total=420, record="1,071K Sheva Business",
        hourglasses=(90, 60, 60, 60, 60, 30, 30, 30),
        legs=(
            Leg(0, 5, "top_start_bridge", "skip the first 60, cross the bridge, hop the gap"),
            Leg(0, 10, "rooftop_under", "90 s under the rooftop; kill the chicken in the pen first", 90),
            Leg(5, 20, "east_walkway", "zipline or drop; 30 s + 30 s + herb", 30),
            Leg(10, 25, "altar_flashes", "three flashes at the central altar"),
            Leg(20, 45, "stairs_building", "window hop, 60 s inside", 60),
            Leg(40, 70, "sw_hut", "three flashes + 60 s behind the hut", 60),
            Leg(60, 90, "west_building_alley", "stand in the alley north of the west building"),
            Leg(90, 100, "north_bridge_wall", "30 s at the bridge wall, strong weapon ready", 30),
            Leg(100, 145, "top_outside_strips", "never fight on the bridge; 60 s middle walkway and top cave before ~146", 60),
            Leg(120, 149, "top_cave", "60 s back of cave kept for the end", 60),
        ),
        stands=("alley north of west building", "chicken pen", "narrow path by hill route"),
        bosses=("Giant @20", "Giant @40", "Giant @60", "Giant @70"),
        notes="Reunion: combos above 150 are legal; save Bui Kichwa for the last flash.",
    ),
    _plan(
        key="ancient_ruins", name="Ancient Ruins", start_seconds=0, hourglass_total=480, record="1,338,705 Josh",
        hourglasses=(90, 90, 60, 60, 30, 30, 30, 30, 30, 30), uncertain=True,
        legs=(
            Leg(0, 5, "chest_left_path", "combo chest on the left path"),
            Leg(0, 20, "sw_stairs_90", "cancel the Duvalia with a rear instant kill; two flashes behind it", 90),
            Leg(20, 40, "stairs_corridor", "fight the 90 s area corridor until ~40 when it dries"),
            Leg(40, 60, "ne_walkway", "wooden walkway round the NE corner", 60),
            Leg(60, 80, "bridge_area", "90 s, herbs, chicken, 30 s alcove, 30 s mid-stairs", 90),
            Leg(60, 80, "below_stairs", "stay below the stairs until ~80"),
            Leg(80, 100, "west_stairs_top", "west 30 s path end", 30),
            Leg(100, 150, "bridge_right_side", "right side of the bridge: nothing spawns on the chest path (100-150 stand)"),
        ),
        stands=("corridor above the first stairs", "right side of the bridge"),
        bosses=("Giant @10", "Giant @~60"),
        notes="Which of the three 90s is a 60 is uncertain; RE5 Zone count 2x90 + 2x60 + 6x30 used. ~6 Duvalias.",
    ),
    _plan(
        key="experimental_facility", name="Experimental Facility", start_seconds=0, hourglass_total=360,
        record="678,125 Rebecca", uncertain=True,
        hourglasses=(60, 60, 60, 60, 30, 30, 30, 30),
        legs=(
            Leg(0, 5, "top_elevator", "30 s across the railing; chicken", 30),
            Leg(0, 15, "top_corridor", "60 s; melee the ladder climber, drop", 60),
            Leg(15, 70, "stairs_floor", "Base Majini wave then Lickers ~40-72; Rocket Launcher Majini at 10/30/40/60/70/80"),
            Leg(70, 100, "second_floor_corridor", "luck transition ~70; ramp is the late stand"),
            Leg(100, 130, "mid_run_60", "60 s once Lickers are easy", 60),
            Leg(130, 149, "bottom_area_90", "hop down the ladder for the bottom-area bonus (130-140)", 60),
        ),
        stands=("stairs floor", "long corridor and ramp"),
        bosses=("Rocket Launcher waves", "possible Gatling (disputed)"),
        notes="Berserker lists a 90 s bottom; RE5 Zone counts 4x60 + 4x30 (used here).",
    ),
    _plan(
        key="missile_area", name="Missile Area", start_seconds=0, hourglass_total=540, record="733,303 Rebecca",
        hourglasses=(60, 30, 30, 90, 60, 60, 30, 30, 60, 60, 30),
        legs=(
            Leg(0, 3, "office_start", "60 s + flash on the control panel", 60),
            Leg(0, 20, "upper_conveyor", "30 s; two explosive canisters ahead", 30),
            Leg(20, 30, "lower_conveyor", "fast kills; jump off with one Majini close behind"),
            Leg(30, 40, "long_ladder", "hardest stretch: landmine first, climb, mine on landing"),
            Leg(40, 80, "island_room", "step on spawn switches; chicken in the room", 60),
            Leg(80, 110, "gatling_stop", "Gatling 2 at ~80; keep re-stepping switches", 30),
            Leg(110, 145, "platform_bridge", "30 s barrel, 30 s middle, 60 s platform", 60),
            Leg(145, 149, "furnace_spray", "furnace 60 s before 145; spray 30 s last", 60),
        ),
        stands=("conveyor", "central shaft doorway"),
        bosses=("Gatling @20", "Gatling @60", "Gatling @90"),
    ),
    _plan(
        key="ship_deck", name="Ship Deck", start_seconds=0, hourglass_total=570, record="1,043,176 Rebecca",
        hourglasses=(30, 60, 60, 90, 30, 60, 30, 60, 60, 30, 60), uncertain=True,
        legs=(
            Leg(0, 5, "south_start_flashes", "flashes; blue Chainsaw 1 drops from the crane tower"),
            Leg(0, 15, "first_stairs", "30 s on the way down", 30),
            Leg(5, 25, "crate_tunnel_60", "ladder, drop, second ladder", 60),
            Leg(15, 30, "west_90", "90 s west of the stairs", 90),
            Leg(25, 40, "tower_top", "30 s + rocket", 30),
            Leg(30, 45, "far_north_ladder", "60 s + chest + chicken", 60),
            Leg(40, 50, "left_stairs", "30 s at ~40", 30),
            Leg(50, 85, "middle_crate_corridor", "main stand to ~85 with its 60 s", 60),
            Leg(85, 140, "west_tunnel", "keep an enemy in view; fight before the tunnel"),
            Leg(140, 149, "crane_top", "60 s below crane, kick gate, 30 s barrel, 60 s crane top", 60),
        ),
        stands=("middle crate corridor", "north end of corridor for chainsaw pairs"),
        bosses=("Chainsaw @0", "Chainsaw @20", "Chainsaw @30", "Chainsaw @40", "Chainsaw @50"),
        notes="Berserker's crates bonus may be one or two 60s (uncertain).",
    ),
    _plan(
        key="prison", name="Prison", start_seconds=0, hourglass_total=510, record="929,701 Sheva Fairy Tale",
        hourglasses=(60, 60, 60, 60, 60, 30, 30, 30, 30, 30, 30, 30), uncertain=True,
        legs=(
            Leg(0, 5, "catwalk_start", "60 s beside the start", 60),
            Leg(0, 10, "rail_tracks", "60 s; hand grenade blows the wooden door", 60),
            Leg(5, 20, "hall_window", "window hop, 60 s at the hall end", 60),
            Leg(10, 25, "chicken_house_roof", "60 s, flash in the crate; chicken and chest", 60),
            Leg(20, 45, "executioner_spot", "Red Executioner 1; plank timer"),
            Leg(45, 70, "lava_pit_90", "basement bonus; two flashes in the first cell", 60),
            Leg(70, 100, "first_floor_central", "front corridor is the solo stand"),
            Leg(100, 138, "cliffside_gas_tank", "return to the Executioner spot before the next red one"),
            Leg(138, 149, "south_window_30", "heal before 138-150; dynamite Majini window", 30),
        ),
        stands=("1F central room front corridor", "cliffside gas tank"),
        bosses=("Red Exec @0", "Black Exec @20", "Red Exec @50", "Black Exec @90", "Red Exec @120"),
        notes="Lava-pit bonus is 60 or 90 (uncertain); RE5 Zone counts 5x60 + 7x30 (used).",
    ),
)}


def hourglass_seconds(stage: str) -> int:
    return sum(STAGES[stage].hourglasses)


def route_legs(stage: str, kills: int) -> list:
    """Legs of the recommended route that apply at this kill count, in route order."""
    plan = STAGES[stage]
    return [leg for leg in plan.legs if leg.start <= kills <= leg.end]


def next_bonus(stage: str, kills: int):
    """The earliest remaining hourglass leg at or after this kill count, or None."""
    plan = STAGES[stage]
    rows = [leg for leg in plan.legs if leg.bonus and leg.end >= kills]
    return min(rows, key=lambda leg: (max(leg.start, kills), leg.start)) if rows else None
