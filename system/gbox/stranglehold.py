"""Stranglehold (PS3) bullet-time interception helpers.

Registers the `stranglehold_shot` tool and exposes the minimum set of
systems the game uses to resolve a precision-aim (bullet-time) shot, so
the chat/agent can list them, locate them in RAM, arm the player for
survival, fire an immediate hit/miss verdict, or start a cross-game
link that lets another game decide the result.

op=link guest=tetris_ds is hands-free: the host trigger (precision aim) and
the guest's win/lose flags come from the profiles, the guest session is found
or launched through the control plane, and game_link runs the rounds.

Register with:  from . import stranglehold  # noqa: F401
"""
import json
import time
from pathlib import Path

from pydantic import BaseModel

from .models import Permission
from .registry import Ctx, tool

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
PROFILE_PATH = PROFILES / "stranglehold-ps3-us.json"

# guest games a shot can be handed to: key -> profile file (its "link" block holds the rounds and watch specs)
GUESTS = {"tetris_ds": "tetris-ds-us.json", "puyo_puyo_tetris": "puyo-puyo-tetris-ps3-jp.json"}


def _load_profile(path: Path = PROFILE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class StrangleholdShotIn(BaseModel):
    op: str = "systems"                    # systems | locate | arm | fire | link
    session_id: str = ""                   # running Stranglehold session (required except systems)
    verdict: str = "hit"                   # hit | miss (used by fire and link on_win/on_lose)
    guest: str = ""                        # link: guest game key (tetris_ds | puyo_puyo_tetris): watch specs from its profile
    round: str = ""                        # link: the guest profile's round preset (tetris_ds: vs_cpu | sprint)
    guest_session_id: str = ""             # guest session; empty with guest=: a running one is found, else one is launched
    guest_node: str = ""                   # where to launch a missing guest (default: the guest profile's, else linux)
    style: str = "pip"                     # link: pip (guest picture over the frozen host) | pause | overlay
    trigger: dict = {}                     # host: bullet-cam / precision-aim start flag (default: the profile's)
    win: dict = {}                         # guest: player won the minigame (default: the guest profile's round)
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
        "trigger": prof.get("link", {}).get("trigger"),
        "guests": sorted(GUESTS),
    }


def _clean(spec: dict) -> dict:
    """A profile watch spec without its documentation fields."""
    return {k: v for k, v in (spec or {}).items() if k not in ("why", "evidence", "confidence", "live_check")}


def link_specs(guest: str, round_: str = "") -> dict:
    """Host trigger + guest win/lose watch specs, and the guest's game id, from the profiles."""
    if guest not in GUESTS:
        raise ValueError(f"unknown guest {guest!r} (known: {', '.join(sorted(GUESTS))})")
    gp = _load_profile(PROFILES / GUESTS[guest])
    link = gp.get("link") or {}
    rounds = link.get("rounds") or {}
    name = round_ or link.get("default_round") or next(iter(rounds), "")
    if name not in rounds:
        raise ValueError(f"{gp.get('title')}: no round {name!r} (known: {', '.join(rounds) or 'none yet'})")
    r = rounds[name]
    return {"trigger": _clean(_load_profile().get("link", {}).get("trigger")), "win": _clean(r.get("win")),
            "lose": _clean(r.get("lose")), "game_id": gp.get("game_id"), "title": gp.get("title"), "round": name,
            "save_state": r.get("save_state"), "node": link.get("node", "")}


def _api(ctx, method: str, path: str, body: dict | None = None):
    import httpx
    if not getattr(ctx, "server", None):
        raise ValueError("no control plane on this worker: pass guest_session_id of a running guest session")
    r = httpx.request(method, f"{ctx.server}{path}", headers=getattr(ctx, "headers", None) or {}, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def guest_session(ctx, game_id: str, node: str = "linux", api=None, wait_s: float = 240) -> dict:
    """A running session of the guest game (newest first), else launch it through the control plane (@launch job, no
    mod swap). The host keeps running: the guest goes to another worker (one emulator per worker)."""
    api = api or _api
    running = [s for s in api(ctx, "GET", "/api/sessions") if s.get("game_id") == game_id and s.get("state") == "running"]
    if running:
        s = max(running, key=lambda s: s.get("started") or 0)
        return {"session_id": s["session_id"], "launched": False}
    j = api(ctx, "POST", "/api/jobs", {"tool": "@launch", "input": {"game_id": game_id, "node": node or "linux", "swap": False}})
    t0 = time.time()
    while j.get("state") in ("queued", "running") and time.time() - t0 < wait_s:
        time.sleep(1)
        j = api(ctx, "GET", f"/api/jobs/{j['id']}")
    sid = (j.get("output") or {}).get("session_id")
    if j.get("state") != "succeeded" or not sid:
        raise RuntimeError(f"guest launch did not start a session: {j.get('state')} {j.get('error') or ''}".strip())
    return {"session_id": sid, "launched": True, "job": j.get("id")}


@tool("stranglehold_shot", "1.1", StrangleholdShotIn, StrangleholdShotOut,
      capabilities=["runtime", "memory", "mod"], permissions=[Permission.MEMORY_WRITE, Permission.EXECUTE],
      side_effects=["may pause/resume a live session and apply same-length UnrealScript bytecode patches",
                    "op=link guest=... may launch the guest game on another worker"],
      timeout_s=300)
def stranglehold_shot(inp: StrangleholdShotIn, ctx: Ctx):
    """Expose the Stranglehold bullet-time interception systems and drive them.

    op=systems: list the minimum set of systems (shot type, suspend point,
                presentation verdict, damage verdict, slow motion, aim state).
    op=locate:  find the profile's script functions in RAM for the running session.
    op=arm:     apply the 'god' preset so the player can survive while testing.
    op=fire:    immediately apply the 'hit' or 'miss' preset, overriding the shot result.
    op=link:    start a game_link with this Stranglehold session as host and a guest
                deciding the verdict. guest=tetris_ds takes the precision-aim trigger
                and the guest's win/lose flags from the profiles and finds or launches
                the guest session; otherwise pass guest_session_id + trigger/win/lose.
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
        trigger, win, lose, info = inp.trigger, inp.win, inp.lose, {}
        guest_sid = inp.guest_session_id
        if inp.guest:
            specs = link_specs(inp.guest, inp.round)
            trigger, win, lose = trigger or specs["trigger"], win or specs["win"], lose or specs["lose"]
            info = {"guest": inp.guest, "round": specs["round"], "guest_title": specs["title"],
                    "guest_save_state": specs["save_state"]}
            if not guest_sid:
                g = guest_session(ctx, specs["game_id"], inp.guest_node or specs["node"] or "linux")
                guest_sid, info = g["session_id"], info | {"guest_launched": g["launched"]}
        if not guest_sid:
            raise ValueError("guest_session_id (or guest=tetris_ds) is required for link")
        for name, spec in (("trigger", trigger), ("win", win), ("lose", lose)):
            if not (spec.get("address") or spec.get("any") or spec.get("all")):
                raise ValueError(f"{name} needs a memory watch address")
        r = T.game_link(T.LinkIn(
            op="start", host=inp.session_id, guest=guest_sid,
            trigger=trigger, win=win, lose=lose, style=inp.style,
            on_win="god_hit", on_lose="god_miss"), ctx)
        return {"result": {"op": "link", "guest_session_id": guest_sid, **info, **r["result"]}}

    raise ValueError(f"unknown op {inp.op!r}")
