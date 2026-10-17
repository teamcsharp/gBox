"""`stage_warp`: put the player on a named stage / level of the running game, live.

Table-driven: each game maps friendly stage names to what moves the player there - RAM writes
(level/translevel selectors held across the reload) or a title-screen input sequence. Sources are
cited per entry; entries are only promoted to `verified` after a live in-game check.

ops: games | stages (game optional) | warp (stage, game optional) | release (undo the held writes)

Register with:  from . import stage_warp  # noqa: F401
"""
import difflib
import re
import time

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool
from .zelda_tool import Mem


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


# ---------------------------------------------------------------- games

# Super Mario World (SNES): the current level's translevel number lives at $7E:13BF (1 byte).
# The level-load routine (death, exit-and-re-enter) derives the Lunar Magic level number as:
#   if translevel > $24: LM = translevel - $24 + ($100 when the submap flag is set, else 0)
#   else: LM = translevel
# so for every submap level (LM 0x100+) translevel = LM - 0xDC. $7E:13C3 is the current submap
# (0 main, 1 Yoshi, 2 Vanilla, 3 Forest, 4 Bowser, 5 Special, 6 Star) and is written alongside.
# IDs: Lunar Magic level list, kark.at/junkyard/lunarmagic (cross-checked with smwcentral's
# "$700000 overworld flags indexed by $13BF" thread and the $7E13BF/$7E13C3 RAM map pages).
SMW_SUBMAP = {
    "main": 0, "yoshi": 1, "vanilla": 2, "forest": 3, "bowser": 4, "special": 5, "star": 6,
}
# name -> (LM id, submap). Only levels entered from the overworld / normal reloads.
SMW_LEVELS = {
    "yoshi's island 1": (0x105, 1), "yoshi's island 2": (0x106, 1),
    "yoshi's island 3": (0x103, 1), "yoshi's island 4": (0x102, 1),
    "yoshi's house": (0x104, 1), "yellow switch palace": (0x14, 1),
    "donut plains 1": (0x15, 0), "donut plains 2": (0x09, 0), "donut plains 3": (0x05, 0),
    "donut plains 4": (0x06, 0), "donut secret 1": (0x0A, 0), "donut secret 2": (0x10B, 0),
    "donut secret house": (0x13, 0), "donut ghost house": (0x04, 0),
    "green switch palace": (0x08, 0), "top secret area": (0x03, 0),
    "vanilla dome 1": (0x11A, 2), "vanilla dome 2": (0x118, 2), "vanilla dome 3": (0x10A, 2),
    "vanilla dome 4": (0x119, 2), "vanilla ghost house": (0x107, 2),
    "vanilla secret 1": (0x109, 2), "vanilla secret 2": (0x101, 2), "vanilla secret 3": (0x102, 2),
    "vanilla fortress": (0x0B, 0), "red switch palace": (0x11B, 2), "blue switch palace": (0x121, 2),
    "butter bridge 1": (0x0C, 0), "butter bridge 2": (0x0D, 0), "cheese bridge area": (0x0F, 0),
    "soda lake": (0x11, 0), "cookie mountain": (0x01, 0),
    "forest of illusion 1": (0x11E, 3), "forest of illusion 2": (0x120, 3),
    "forest of illusion 3": (0x123, 3), "forest of illusion 4": (0x11F, 3),
    "forest ghost house": (0x11D, 3), "forest secret area": (0x122, 3), "forest fortress": (0x1F, 0),
    "chocolate island 1": (0x22, 0), "chocolate island 2": (0x24, 0), "chocolate island 3": (0x23, 0),
    "chocolate island 4": (0x1D, 0), "chocolate island 5": (0x1C, 0), "choco-ghost house": (0x21, 0),
    "chocolate fortress": (0x1B, 0), "chocolate secret": (0x117, 3),
    "valley of bowser 1": (0x116, 4), "valley of bowser 2": (0x115, 4),
    "valley of bowser 3": (0x113, 4), "valley of bowser 4": (0x10F, 4),
    "valley ghost house": (0x114, 4), "valley fortress": (0x111, 4),
    "bowser's castle": (0x10D, 4), "bowser's castle back door": (0x10E, 4),
    "bowser fight": (0x1C7, 4),
    "star world 1": (0x134, 6), "star world 2": (0x130, 6), "star world 3": (0x132, 6),
    "star world 4": (0x135, 6), "star world 5": (0x136, 6),
    "gnarly": (0x12A, 5), "tubular": (0x12B, 5), "way cool": (0x12C, 5), "awesome": (0x12D, 5),
    "groovy": (0x128, 5), "mondo": (0x127, 5), "outrageous": (0x126, 5), "funky": (0x125, 5),
}
SMW_ALIASES = {
    "final world": "bowser's castle", "final castle": "bowser's castle", "bowser": "bowser's castle",
    "final battle": "bowser fight", "first level": "yoshi's island 2", "start": "yoshi's island 2",
    "special zone": "gnarly", "star road": "star world 1",
}
# Castles entered from the main map.
for _nm, _id in [("#1 iggy's castle", 0x101), ("#2 morton's castle", 0x07), ("#3 lemmy's castle", 0x11C),
                 ("#4 ludwig's castle", 0x0E), ("#5 roy's castle", 0x02), ("#6 wendy's castle", 0x1A),
                 ("#7 larry's castle", 0x110)]:
    SMW_LEVELS[_nm] = (_id, 0)

# Teenage Mutant Ninja Turtles (Konami 1989, FBNeo/MAME 'tmnt'): the game ships a built-in stage
# select. At the title screen: down x5, right x7, B, A, Start opens it (also grants 9 lives).
# Source: The Technodrome forums t=32747 ("TMNT Arcade Chreat Codes"); retroresolve.com TMNT
# Cowabunga Collection guide (same sequence). Then move the cursor and press Start on a stage.
TMNT_SEQUENCE = ["down"] * 5 + ["right"] * 7 + ["b", "a", "start"]
TMNT_STAGES = ["stage 1 - city streets", "stage 2 - sewers", "stage 3 - snowfield",
               "stage 4 - technodrome approach", "stage 5 - technodrome (final)"]

GAMES = {
    "super mario world": {
        "platforms": {"snes"}, "kind": "ram", "verified": False,
        "writes": ((0x7E13BF, 1), (0x7E13C3, 1)),                       # translevel, submap
        "trigger": "die in the current level (or exit and enter any level): the reload uses $13BF",
        "stages": SMW_LEVELS, "aliases": SMW_ALIASES,
        "source": "smwcentral.net RAM map ($7E13BF translevel, $7E13C3 submap); Lunar Magic level ids (kark.at/junkyard/lunarmagic)",
    },
    "tmnt": {
        "platforms": {"arcade_fbneo"}, "kind": "input", "verified": False,
        "sequence": TMNT_SEQUENCE,
        "trigger": "enter at the title screen; it opens the built-in stage select (also grants 9 lives)",
        "stages": {s: i for i, s in enumerate(TMNT_STAGES)},
        "source": "The Technodrome forums t=32747; retroresolve.com TMNT Cowabunga Collection cheats",
    },
}
TITLES = {"super mario world": ["super mario world"], "tmnt": ["teenage mutant ninja turtles", "tmnt"]}
EXCLUDE = {"super mario world": ["yoshi s island", "all stars"], "tmnt": ["turtles in time", "arcade attack", "mutant nightmare", "tournament fighters"]}


def detect(title: str, platform: str) -> str | None:
    t = _norm(title)
    for key, names in TITLES.items():
        if any(n in t for n in names) and not any(x in t for x in EXCLUDE[key]):
            return key
    return None


def translevel(lm: int) -> int:
    """Lunar Magic level id -> the $7E13BF translevel value."""
    return lm - 0xDC if lm > 0x24 else lm


def resolve_stage(game: dict, name: str) -> tuple[str, dict]:
    name = _norm(name).lower()
    if name in game.get("aliases", {}):
        name = game["aliases"][name]
    stages = game["stages"]
    if name in stages:
        return name, ({"index": stages[name]} if game["kind"] == "input"
                      else {"lm": stages[name][0], "submap": stages[name][1]})
    if game["kind"] == "input":                                     # "stage 5", "5", "final"
        m = re.search(r"(\d+)", name)
        if m and 1 <= int(m.group(1)) <= len(stages):
            return list(stages)[int(m.group(1)) - 1], {"index": int(m.group(1)) - 1}
        if "final" in name:
            return list(stages)[-1], {"index": len(stages) - 1}
    best, score = None, 0.0
    for sname in stages:
        sc = difflib.SequenceMatcher(None, name, sname).ratio()
        if sc > score:
            best, score = sname, sc
    if score < 0.55 or best is None:
        raise ValueError(f"no stage like '{name}' in this game; op=stages lists them")
    return best, ({"index": stages[best]} if game["kind"] == "input"
                  else {"lm": stages[best][0], "submap": stages[best][1]})


# ---------------------------------------------------------------- live application

def _apply_ram(m: Mem, g: dict, stage: dict, hold: bool = True) -> dict:
    (waddr, wsize), (saddr, _) = g["writes"]
    tl = translevel(stage["lm"])
    out: dict = {"writes": []}
    for addr, val in ((waddr, tl), (saddr, stage["submap"])):
        before = m.rd(addr, wsize)
        m.poke(addr, bytes([val]), before)
        back = m.rd(addr, wsize)
        out["writes"].append({"address": f"{addr:#x}", "before": before.hex(),
                              "written": f"{val:02x}", "read_back": back.hex(),
                              "verified": back == bytes([val])})
    out.update({"level": f"{stage['lm']:#x}", "translevel": f"{tl:#x}", "submap": stage["submap"],
                "held": hold, "trigger": g["trigger"], "source": g["source"],
                "note": "the level loads after the next reload (die, or exit and re-enter a level)"})
    return out


def _apply_input(ad, g: dict, stage: dict) -> dict:
    from .zelda_tool import _press
    sent = []
    for key in g["sequence"]:
        try:
            _press(ad, key)
            sent.append(key)
        except Exception as e:
            return {"sequence_sent": sent, "error": str(e),
                    "note": "stop and report; do not keep pressing blind"}
    idx = stage["index"]
    out = {"sequence_sent": sent, "stage": list(g["stages"])[idx], "index": idx + 1,
           "note": (f"stage select should be open; move the cursor to stage {idx + 1} and press Start"
                    if idx else "stage select should be open with the cursor on stage 1; press Start"),
           "source": g["source"]}
    return out


def run(ad, title: str, platform: str, op: str = "games", stage: str = "") -> dict:
    key = detect(title, platform)
    if op == "games":
        return {"games": [k for k in GAMES], "note": "op=stages for a game's stages; op=warp stage=<name>"}
    if key is None:
        return {"error": f"no stage-warp recipe for '{title}' ({platform}) yet",
                "games": [k for k in GAMES]}
    g = GAMES[key]
    if op == "stages":
        out = {"game": key, "kind": g["kind"], "verified": g["verified"], "source": g["source"]}
        if g["kind"] == "ram":
            out["stages"] = {n: {"lm": f"{v[0]:#x}", "submap": v[1]} for n, v in g["stages"].items()}
            out["aliases"] = g["aliases"]
        else:
            out["stages"] = list(g["stages"])
        return out
    if op != "warp":
        return {"error": f"unknown op '{op}' (games | stages | warp)"}
    if not stage:
        return {"error": "op=warp needs stage='<name>'"}
    name, resolved = resolve_stage(g, stage)
    if g["kind"] == "ram":
        m = Mem(ad, platform)
        out = _apply_ram(m, g, resolved)
        out["stage"] = name
        return out
    return _apply_input(ad, g, resolved)


class StageWarpIn(BaseModel):
    session_id: str
    op: str = "games"                     # games | stages | warp
    stage: str = ""


class StageWarpOut(BaseModel):
    result: dict


@tool("stage_warp", "1.0", StageWarpIn, StageWarpOut, capabilities=["runtime", "memory"],
      permissions=[P.MEMORY_WRITE], timeout_s=120)
def stage_warp(inp: StageWarpIn, ctx):
    """Put the player on a named stage / level of the live game ('put me on the final world', 'the last
    stage'). op=games lists supported games; op=stages lists a game's stages; op=warp stage='<name>'
    ('final world', 'bowser's castle', 'stage 5') moves the player there: Super Mario World (SNES) writes
    the level's translevel number to $7E13BF and the submap to $7E13C3 (held), then the level reload
    (die, or exit and enter a level) loads it; Teenage Mutant Ninja Turtles (FBNeo arcade) sends the
    title-screen stage-select sequence. RAM writes are verified by read-back."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    return {"result": run(ad, g.get("title", ""), g.get("platform", ""), inp.op, inp.stage)}
