"""Stranglehold (PS3) bullet-time interception helpers.

Registers the `stranglehold_shot` tool and exposes the minimum set of
systems the game uses to resolve a precision-aim (bullet-time) shot, so
the chat/agent can list them, locate them in RAM, arm the player for
survival, fire an immediate hit/miss verdict, or start a cross-game
link that lets another game decide the result.

Register with:  from . import stranglehold  # noqa: F401
"""
import json
from pathlib import Path

from pydantic import BaseModel

from .models import Permission
from .registry import Ctx, tool

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profiles" / "stranglehold-ps3-us.json"


def _load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


class StrangleholdShotIn(BaseModel):
    op: str = "systems"                    # systems | locate | arm | fire | link
    session_id: str = ""                   # running Stranglehold session (required except systems)
    verdict: str = "hit"                   # hit | miss (used by fire and link on_win/on_lose)
    guest_session_id: str = ""             # guest session for link (e.g. Puyo Puyo Tetris)
    trigger: dict = {}                     # host: bullet-cam / precision-aim start flag
    win: dict = {}                         # guest: player won the minigame
    lose: dict = {}                        # guest: player lost the minigame


class StrangleholdShotOut(BaseModel):
    result: dict


def minimum_systems() -> dict:
    """Return the profile's documented minimum set of systems."""
    prof = _load_profile()
    serials = prof.get("match", {}).get("serial", [])
    return {
        "profile_id": prof.get("id"),
        "title": prof.get("title"),
        "serial": serials[0] if serials else None,
        "systems": prof.get("systems", []),
        "presets": sorted(prof.get("script_patches", {}).get("presets", {}).keys()),
    }


@tool("stranglehold_shot", "1.0", StrangleholdShotIn, StrangleholdShotOut,
      capabilities=["runtime", "memory", "mod"], permissions=[Permission.MEMORY_WRITE, Permission.EXECUTE],
      side_effects=["may pause/resume a live session and apply same-length UnrealScript bytecode patches"],
      timeout_s=300)
def stranglehold_shot(inp: StrangleholdShotIn, ctx: Ctx):
    """Expose the Stranglehold bullet-time interception systems and drive them.

    op=systems: list the minimum set of systems (shot type, suspend point,
                presentation verdict, damage verdict, slow motion, aim state).
    op=locate:  find the profile's script functions in RAM for the running session.
    op=arm:     apply the 'god' preset so the player can survive while testing.
    op=fire:    immediately apply the 'hit' or 'miss' preset, overriding the shot result.
    op=link:    start a game_link with this Stranglehold session as host and a guest
                session (e.g. Puyo Puyo Tetris) deciding the verdict. Requires trigger,
                win and lose memory watch specs.
    """
    if inp.op == "systems":
        return {"result": minimum_systems()}

    if not inp.session_id:
        raise ValueError("session_id is required for locate/arm/fire/link")

    # Import here to avoid a circular import at module load time: tools.py loads
    # this module via _load_tool_modules after it has finished defining LinkIn /
    # ScriptPatchIn.
    from . import tools as T

    if inp.op == "locate":
        r = T.script_patch(T.ScriptPatchIn(session_id=inp.session_id, op="locate"), ctx)
        return {"result": {"op": "locate", **r["result"]}}

    if inp.op == "arm":
        r = T.script_patch(T.ScriptPatchIn(session_id=inp.session_id, op="preset", preset="god"), ctx)
        return {"result": {"op": "arm", "active": r["result"]["active"], "functions": r["result"]["functions"]}}

    if inp.op == "fire":
        preset = "hit" if inp.verdict == "hit" else "miss"
        r = T.script_patch(T.ScriptPatchIn(session_id=inp.session_id, op="preset", preset=preset), ctx)
        return {"result": {"op": "fire", "verdict": inp.verdict, "active": r["result"]["active"],
                           "functions": r["result"]["functions"]}}

    if inp.op == "link":
        if not inp.guest_session_id:
            raise ValueError("guest_session_id is required for link")
        for name, spec in (("trigger", inp.trigger), ("win", inp.win), ("lose", inp.lose)):
            if not spec.get("address"):
                raise ValueError(f"{name} needs a memory watch address")
        r = T.game_link(T.LinkIn(
            op="start", host=inp.session_id, guest=inp.guest_session_id,
            trigger=inp.trigger, win=inp.win, lose=inp.lose,
            on_win="god_hit", on_lose="god_miss"), ctx)
        return {"result": {"op": "link", **r["result"]}}

    raise ValueError(f"unknown op {inp.op!r}")
