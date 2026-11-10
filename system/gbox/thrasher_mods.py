"""Thrasher: Skate and Destroy (PS1, USA) - viewer/mod-panel command catalog (request #6085).

This is the *contract* for realtime modifications requested through the Pinebox radio
station and the mod panel, plus the bot-behaviour knobs. It deliberately carries NO
RAM addresses: none have been verified because the disc image
(\\\\10.89.1.125\\QuickSwap2\\Emulation\\PS1 Thrasher - Skate and Destroy (USA).7z) was
not reachable from the build host. Every command therefore starts ``resolved=False``
and names the RAM/code evidence the decompilation stage must produce before it can
be enabled. ``resolve()`` is the single place an address may be recorded.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

GAME_TITLE = "Thrasher: Skate and Destroy"
PLATFORM = "ps1"
DISC_ARCHIVE = r"\\10.89.1.125\QuickSwap2\Emulation\PS1 Thrasher - Skate and Destroy (USA).7z"
VARIANTS = ("retail_usa", "demo")  # the demo is to be analysed and hacked too

KINDS = ("ram_poke", "code_hook", "spawn", "asset_swap", "level_load", "camera", "overlay")


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    kind: str
    params: dict = field(default_factory=dict)  # name -> {"type":..., plus bounds}
    needs: str = ""                              # evidence required to resolve
    resolved: bool = False
    addresses: dict = field(default_factory=dict)  # name -> int, only once verified


def _c(id, label, kind, needs, **params):
    return Command(id, label, kind, params, needs)


def _mult(lo, hi, default=1.0):
    return {"type": "float", "min": lo, "max": hi, "default": default}


COMMANDS: tuple[Command, ...] = (
    _c("gravity", "Change gravity", "ram_poke", "gravity/vertical-accel constant in skater physics", scale=_mult(0.1, 4.0)),
    _c("spawn_cop", "Insert a cop at a random spot", "spawn", "cop actor table + spawn routine + valid-position source"),
    _c("spawn_two_cops", "Insert 2 cops at random spots", "spawn", "cop actor table + spawn routine + valid-position source", count={"type": "int", "min": 2, "max": 2, "default": 2}),
    _c("slow_cop_pursuit", "Slow cop pursuit", "ram_poke", "cop chase speed / AI tick fields", scale=_mult(0.1, 1.0, 0.5)),
    _c("cop_cam", "Cycle to cop cam", "camera", "camera mode variable and cop-cam entry"),
    _c("game_speed", "Increase game speed", "code_hook", "frame/time-step driver", scale=_mult(0.25, 4.0)),
    _c("reset_score", "Reset score", "ram_poke", "score accumulator(s)"),
    _c("trick_score_multiplier", "Multiply next trick score by x", "code_hook", "trick-score award routine", x={"type": "int", "min": 1, "max": 100, "default": 2}),
    _c("no_fall", "Character cannot fall off board (toggle)", "code_hook", "bail/fall state transition", enabled={"type": "bool", "default": True}),
    _c("jump_multiplier", "Jump distance multiplier", "ram_poke", "ollie impulse / air velocity fields", scale=_mult(0.25, 4.0)),
    _c("trick_speed_multiplier", "Trick speed multiplier", "ram_poke", "trick animation rate field", scale=_mult(0.25, 4.0)),
    _c("replace_skater_model", "Live skater model replacement", "asset_swap", "skater model/TIM/TMD load path and VRAM slot", model={"type": "model_ref"}),
    _c("replace_cop_model", "Live cop model replacement", "asset_swap", "cop model load path and VRAM slot", model={"type": "model_ref"}),
    _c("change_level", "Change level to", "level_load", "level index variable + level-load trigger", level={"type": "enum_from_levels"}),
    _c("restart_level", "Restart level", "level_load", "level-load trigger with current level index"),
    _c("place_character", "Place character (2D map)", "ram_poke", "skater world position fields + level bounds for the 2D map", x={"type": "int"}, z={"type": "int"}),
    _c("shirt_logo", "Change shirt logo to a gallery image", "asset_swap", "shirt texture page / CLUT in VRAM", image={"type": "gallery_ref"}),
    _c("camera_mode", "Camera: follow / pursuit / cinematic", "camera", "camera mode variable and mode table", mode={"type": "enum", "values": ["follow", "pursuit", "cinematic"]}),
    _c("perfect_balance", "Perfect balance (toggle)", "code_hook", "balance meter update", enabled={"type": "bool", "default": True}),
    _c("add_random_skaters", "Add random skaters", "spawn", "NPC skater actor table + spawn routine", count={"type": "int", "min": 1, "max": 8, "default": 1}),
)

BOT_KNOBS: tuple[dict, ...] = (
    {"id": "trick_bias", "type": "map", "keys": ["grind", "flip", "grab", "manual", "lip"], "min": 0.0, "max": 1.0, "default": 0.5},
    {"id": "explore_vs_objective", "type": "float", "min": 0.0, "max": 1.0, "default": 0.5},
    {"id": "police_evasion", "type": "float", "min": 0.0, "max": 1.0, "default": 0.8},
    {"id": "speedrun_mode", "type": "bool", "default": False},
)

EXTERNAL_SURFACES = ("pinebox_radio", "mod_panel")


def by_id() -> dict[str, Command]:
    return {c.id: c for c in COMMANDS}


def resolve(cmd_id: str, addresses: dict[str, int]) -> Command:
    """Return the command with verified addresses recorded (caller persists it)."""
    cmd = by_id()[cmd_id]
    if not addresses or not all(isinstance(v, int) and v >= 0 for v in addresses.values()):
        raise ValueError("addresses must be non-empty non-negative ints")
    return replace(cmd, addresses=dict(addresses), resolved=True)


def validate(cmd_id: str, args: dict) -> dict:
    """Check/clamp-reject viewer args against the declared params. Raises ValueError."""
    cmd = by_id().get(cmd_id)
    if cmd is None:
        raise ValueError(f"unknown command {cmd_id!r}")
    out = {}
    for name, spec in cmd.params.items():
        if name not in args:
            if "default" in spec:
                out[name] = spec["default"]
                continue
            raise ValueError(f"missing {name}")
        v, t = args[name], spec["type"]
        if t in ("float", "int"):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or (t == "int" and not isinstance(v, int)):
                raise ValueError(f"{name} must be {t}")
            if "min" in spec and v < spec["min"] or "max" in spec and v > spec["max"]:
                raise ValueError(f"{name} out of range")
        elif t == "bool" and not isinstance(v, bool):
            raise ValueError(f"{name} must be bool")
        elif t == "enum" and v not in spec["values"]:
            raise ValueError(f"{name} not in {spec['values']}")
        out[name] = v
    extra = set(args) - set(cmd.params)
    if extra:
        raise ValueError(f"unexpected args {sorted(extra)}")
    return out


def dispatchable(cmd_id: str) -> bool:
    """Only commands with verified addresses may reach a running game."""
    return by_id()[cmd_id].resolved


def manifest() -> dict:
    return {
        "game": GAME_TITLE, "platform": PLATFORM, "variants": list(VARIANTS),
        "surfaces": list(EXTERNAL_SURFACES), "disc_archive": DISC_ARCHIVE,
        "commands": [{"id": c.id, "label": c.label, "kind": c.kind, "params": c.params,
                      "needs": c.needs, "resolved": c.resolved} for c in COMMANDS],
        "bot_knobs": list(BOT_KNOBS),
    }
