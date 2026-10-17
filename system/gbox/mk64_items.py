"""`mario_kart`: Mario Kart 64 (N64) items, live: give an item, always have an item, infinite items (using one does
not consume it), per player. Every write is verified by read-back.

ops: games | items | state | give (item, player) | always (item, player, on) | infinite (player, on) | release (player)
  always   holds the named item in the player's slot: the game's consume_item() zeroes the slot when the item is
           thrown, gBox writes it straight back, so "infinite red shells" = always item="red shell".
  infinite keeps whatever the player picks up (no fixed item): a slot that goes from an item to empty is refilled.

How the game stores the held item (n64decomp/mk64, US target mk64.us.z64 = No-Intro "Mario Kart 64 (USA)", rev 0,
sha1 579c48e211ae952530ffc8738709f078d5dd215e; the operator's ROM per readiness ticket #1409):
  * gObjectList: Object[OBJECT_LIST_SIZE] with sizeof(Object) == 0xE0 (include/objects.h). Each human player's item
    window is one of those objects, viewed as ItemWindowObjects:
        +0xA4  s16 currentItem        (aliases Object.type)   the item the player holds (enum ITEMS)
        +0xD2  s8  textureListIndex                            the HUD icon: gItemWindowTextures[idx] (src/update_objects.c)
    Player.currentItemCopy (+0x10) is "just a synced copy" (include/common_structs.h) rewritten from the window
    every frame (func_8007B34C: sp38->currentItemCopy = object->type), so it is not written here.
  * consume_item(playerId) (src/update_objects.c): itemWindow->currentItem = ITEM_NONE; player->currentItemCopy =
    ITEM_NONE; set_object_timer_state(objectIndex, 0). Holding currentItem is what makes an item infinite.
  * gItemWindowObjectByPlayerId[]: the window object per player, allocated at HUD init with
    find_unused_obj_index(&gItemWindowObjectByPlayerId[n]) + init_item_window() in init_hud_one_player /
    init_hud_two_player_* / init_hud_three_four_player (src/code_8006E9C0.c), which lands them on fixed indices per
    screen mode: objects 3 and 4 in the 1P and 2P screen modes, 5..8 in SCREEN_MODE_3P_4P_SPLITSCREEN.
  * Item ids: include/defines.h enum ITEMS (ITEM_NONE 0 .. ITEM_SUPER_MUSHROOM 15); the USA GameShark "Weapon
    Modifier" value list (almarsguides.com, USA) is the same table.
  Address cross-check, USA GameShark lists (almarsguides.com "P1 and P2 mode only" / "P3 and P4 mode only" codes):
    1P/2P screen: P1 80165F5D + 80165F8A, P2 8016603D + 8016606A
    3P/4P screen: P1 8016611D + 8016614A, P2 801661FD + 8016622A, P3 801662DD + 8016630A, P4 801663BD + 801663EA
  = &gObjectList[n] + 0xA5 (the low byte of the big-endian s16 currentItem) and &gObjectList[n] + 0xD2, with the
  0xE0 object stride, which puts gObjectList at 0x80165C18. Every entry is a 1-byte GameShark write, so the
  cheats tool's decoder (gbox/cheats.py, "n64") lands on the same bytes as this module (test_mk64_items).
Other revisions: the operator owns the USA ROM only. James S.'s PAL v1.1 list has "1P always has an item"
  80165FBD 00xx (= USA + 0x60, so gObjectList would be 0x80165C78 there); unverified, so Europe/Japan titles are
  refused with that note instead of guessing (see LAYOUTS / detect()).
RetroArch's N64 cores expose RDRAM as little-endian 32-bit words; reads/writes go through gbox.oot._rd/_wr.

Register with:  from . import mk64_items  # noqa: F401
"""
import difflib
import re
import struct
import threading

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool

# ------------------------------------------------------------------------------------------------------ item ids
# n64decomp/mk64 include/defines.h enum ITEMS
ITEMS = {0: "none", 1: "banana", 2: "banana bunch", 3: "green shell", 4: "triple green shells", 5: "red shell",
         6: "triple red shells", 7: "blue shell", 8: "lightning", 9: "fake item box", 10: "star", 11: "boo",
         12: "mushroom", 13: "double mushrooms", 14: "triple mushrooms", 15: "super mushroom"}
DECOMP_NAMES = {0: "ITEM_NONE", 1: "ITEM_BANANA", 2: "ITEM_BANANA_BUNCH", 3: "ITEM_GREEN_SHELL", 4: "ITEM_TRIPLE_GREEN_SHELL",
                5: "ITEM_RED_SHELL", 6: "ITEM_TRIPLE_RED_SHELL", 7: "ITEM_BLUE_SPINY_SHELL", 8: "ITEM_THUNDERBOLT",
                9: "ITEM_FAKE_ITEM_BOX", 10: "ITEM_STAR", 11: "ITEM_BOO", 12: "ITEM_MUSHROOM", 13: "ITEM_DOUBLE_MUSHROOM",
                14: "ITEM_TRIPLE_MUSHROOM", 15: "ITEM_SUPER_MUSHROOM"}
# what the operator calls them; plurals of a single item stay single ("red shells" = a red shell held forever, the
# safe reading of "infinite red shells": every throw refills the slot; triples only when asked for 3 / triple)
ALIASES = {
    "none": 0, "nothing": 0, "empty": 0, "no item": 0,
    "banana": 1, "bananas": 1, "banana peel": 1, "single banana": 1,
    "banana bunch": 2, "bunch of bananas": 2, "multi bananas": 2, "5 bananas": 2, "five bananas": 2, "triple bananas": 2,
    "green shell": 3, "green shells": 3, "koopa shell": 3, "single green shell": 3,
    "triple green shells": 4, "triple green shell": 4, "3 green shells": 4, "three green shells": 4, "multi green shells": 4,
    "red shell": 5, "red shells": 5, "single red shell": 5, "homing shell": 5,
    "triple red shells": 6, "triple red shell": 6, "3 red shells": 6, "three red shells": 6, "multi red shells": 6,
    "blue shell": 7, "blue shells": 7, "spiny shell": 7, "spiked shell": 7, "blue spiny shell": 7, "spiny": 7,
    "lightning": 8, "lightning bolt": 8, "thunderbolt": 8, "thunder": 8, "thunder bolt": 8, "shock": 8,
    "fake item box": 9, "fake box": 9, "fake item": 9, "exploding box": 9, "upside down box": 9, "trap box": 9,
    "star": 10, "super star": 10, "invincibility": 10, "invincibility star": 10, "starman": 10,
    "boo": 11, "ghost": 11, "invisibility": 11, "king boo": 11,
    "mushroom": 12, "mushrooms": 12, "single mushroom": 12, "turbo boost": 12, "boost": 12, "speed boost": 12,
    "double mushrooms": 13, "double mushroom": 13, "2 mushrooms": 13, "two mushrooms": 13,
    "triple mushrooms": 14, "triple mushroom": 14, "3 mushrooms": 14, "three mushrooms": 14,
    "super mushroom": 15, "golden mushroom": 15, "gold mushroom": 15, "super mushrooms": 15, "golden mushrooms": 15,
}
_FILLER = {"infinite", "unlimited", "endless", "always", "have", "has", "give", "me", "a", "an", "the", "my", "item", "items",
           "forever", "please", "some", "want", "i", "get", "hold", "keep", "never", "lose", "with", "of"}


_VAGUE = {"any", "anything", "whatever", "all", "everything", "current", "it", "them", "pick", "up", "picked"}


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def names_an_item(item: str) -> bool:
    """False for '', 'items', 'any item', 'whatever I pick up': nothing specific to hold."""
    return any(w not in _FILLER and w not in _VAGUE for w in norm(item).split())


def resolve_item(name: str) -> tuple[int, str]:
    """'red shells' / 'infinite red shells' / '3 red shells' / 'spiny shell' -> (item id, canonical name)."""
    q = norm(name)
    if not q:
        raise ValueError("item required: " + ", ".join(ITEMS[i] for i in range(1, 16)))
    words = [w for w in q.split() if w not in _FILLER]
    q = " ".join(words) or q
    if q.isdigit() and int(q) in ITEMS:
        return int(q), ITEMS[int(q)]
    if q in ALIASES:
        return ALIASES[q], ITEMS[ALIASES[q]]
    hit = difflib.get_close_matches(q, list(ALIASES), n=1, cutoff=0.75)
    if hit:
        return ALIASES[hit[0]], ITEMS[ALIASES[hit[0]]]
    raise ValueError(f"no Mario Kart 64 item like '{name}'; items: " + ", ".join(ITEMS[i] for i in range(1, 16)))


# ------------------------------------------------------------------------------------------------------ addresses
OBJECT_SIZE = 0xE0              # sizeof(Object) == sizeof(ItemWindowObjects), include/objects.h
O_ITEM, O_ICON = 0xA4, 0xD2     # ItemWindowObjects.currentItem (s16, = Object.type), .textureListIndex (s8)
SPLITS = ("1p2p", "3p4p")       # the 1P and 2P screen modes share one window layout; 3P/4P split screen has another

LAYOUTS = {
    "us": {
        "name": "Mario Kart 64 (USA)", "rom": "No-Intro Mario Kart 64 (USA), rev 0, sha1 579c48e2...5dd215e (n64decomp mk64.us.z64)",
        "object_list": 0x80165C18,                          # &gObjectList[0]
        "windows": {"1p2p": (3, 4), "3p4p": (5, 6, 7, 8)},  # gItemWindowObjectByPlayerId[] per screen mode
        "live_checked": False,                              # flip after the maintainer's op=state check on the agent test PC
        "sources": [
            "n64decomp/mk64 include/objects.h: Object/ItemWindowObjects size 0xE0, currentItem +0xA4, textureListIndex +0xD2",
            "n64decomp/mk64 src/update_objects.c consume_item(): itemWindow->currentItem = ITEM_NONE on use",
            "n64decomp/mk64 src/code_8006E9C0.c init_hud_*(): find_unused_obj_index(&gItemWindowObjectByPlayerId[n]) -> objects 3,4 / 5..8",
            "USA GameShark 'Weapon Modifier' (almarsguides.com, P1/P2 and P3/P4 mode lists): 80165F5D/80165F8A, 8016603D/8016606A, "
            "8016611D/8016614A, 801661FD/8016622A, 801662DD/8016630A, 801663BD/801663EA = gObjectList 0x80165C18 + n*0xE0 + 0xA5 / 0xD2",
        ],
    },
}
GAPS = {"eu": "Europe: not mapped. James S.'s PAL v1.1 list has '1P always has an item' 80165FBD 00xx (USA + 0x60, gObjectList "
              "0x80165C78?) but it is unverified and PAL 1.0 may differ; add a layout after a live check.",
        "jp": "Japan: not mapped (no verified code list; the decomp has no JP target)."}


def slot(layout: str = "us", player: int = 1, split: str = "1p2p") -> dict:
    """Addresses of a player's item window: {object, item (s16 currentItem), icon (textureListIndex)}."""
    lay = LAYOUTS[layout]
    if split not in lay["windows"]:
        raise ValueError(f"split must be one of {list(lay['windows'])}")
    wins = lay["windows"][split]
    if not 1 <= int(player) <= len(wins):
        raise ValueError(f"player must be 1..{len(wins)} on a {split} screen" +
                         (" (split='3p4p' for players 3 and 4)" if split == "1p2p" else ""))
    idx = wins[int(player) - 1]
    base = lay["object_list"] + idx * OBJECT_SIZE
    return {"object": idx, "item": base + O_ITEM, "icon": base + O_ICON}


def gameshark(layout: str, player: int, split: str, item_id: int) -> list[str]:
    """The equivalent GameShark lines (what cheats op=add would take): a byte write to the low byte of currentItem
    and one to textureListIndex, e.g. P1 red shell -> ['80165F5D 0005', '80165F8A 0005']."""
    s = slot(layout, player, split)
    return [f"{s['item'] + 1:08X} {item_id:04X}", f"{s['icon']:08X} {item_id:04X}"]


TITLES = ("mario kart 64",)


def detect(title: str, platform: str) -> tuple[str | None, str]:
    """(layout key, note). None when this is not Mario Kart 64; a key of 'eu'/'jp' names an unmapped revision."""
    t = norm(title)
    if platform not in ("n64", "n64dd", "") or not any(n in t for n in TITLES):
        return None, f"'{title}' is not Mario Kart 64 (N64)"
    if re.search(r"\b(europe|eur|pal|e)\b", t):
        return "eu", GAPS["eu"]
    if re.search(r"\b(japan|jpn|jp|j)\b", t):
        return "jp", GAPS["jp"]
    if re.search(r"\b(usa|us|u|ntsc u|world)\b", t):
        return "us", ""
    return "us", "no region tag in the title: assuming the USA ROM (the only mapped revision)"


# ------------------------------------------------------------------------------------------------------ memory
def _rd(ad, a: int, n: int) -> bytes:
    from . import oot
    return oot._rd(ad, a, n)


def _wr(ad, a: int, data: bytes):
    from . import oot
    oot._wr(ad, a, data)


def read_slot(ad, s: dict) -> dict:
    item = struct.unpack(">h", _rd(ad, s["item"], 2))[0]
    icon = struct.unpack(">b", _rd(ad, s["icon"], 1))[0]
    return {"object": s["object"], "item": item, "name": ITEMS.get(item, f"unknown {item}"), "icon": icon,
            "address": f"{s['item']:#x}", "icon_address": f"{s['icon']:#x}"}


def write_slot(ad, s: dict, item_id: int) -> dict:
    """currentItem = item_id (s16) and the HUD icon = item_id; returns the read-back."""
    _wr(ad, s["item"], struct.pack(">h", item_id))
    _wr(ad, s["icon"], struct.pack(">b", item_id))
    back = read_slot(ad, s)
    back["verified"] = back["item"] == item_id and back["icon"] == item_id
    return back


# ------------------------------------------------------------------------------------------------------ holds
HOLDS: dict = {}                  # (id(ad), split, player) -> {"stop": Event, "thread", "mode", "item", "name", "player", "split"}


def _tick(ad, s: dict, hold: dict) -> bool:
    """One pass of a hold. always: rewrite the chosen item whenever the slot differs (consume_item() zeroed it).
    infinite: remember the last item the slot held; refill when it empties. Returns False once the session is gone."""
    try:
        cur = read_slot(ad, s)
        if hold["mode"] == "always":
            if cur["item"] != hold["item"] or cur["icon"] != hold["item"]:
                write_slot(ad, s, hold["item"])
                hold["refills"] = hold.get("refills", 0) + 1
        else:
            if cur["item"] > 0:
                hold["item"] = cur["item"]
            elif hold.get("item", 0) > 0:
                write_slot(ad, s, hold["item"])
                hold["refills"] = hold.get("refills", 0) + 1
        return True
    except Exception:
        return False


def _hold_loop(ad, s: dict, hold: dict):
    stop = hold["stop"]
    while not stop.is_set():
        if not _tick(ad, s, hold):                      # the session is gone: drop the hold so state/release forget it
            if HOLDS.get(hold.get("key")) is hold:
                HOLDS.pop(hold["key"], None)
            return
        stop.wait(0.05)


def _release(ad, split: str | None = None, player: int | None = None) -> list[dict]:
    gone = []
    for key in list(HOLDS):
        if key[0] != id(ad) or (split and key[1] != split) or (player and key[2] != player):
            continue
        h = HOLDS.pop(key)
        h["stop"].set()
        gone.append({"player": h["player"], "split": h["split"], "mode": h["mode"], "item": ITEMS.get(h.get("item", 0))})
    return gone


def _start(ad, s: dict, mode: str, item_id: int, player: int, split: str) -> dict:
    key = (id(ad), split, player)
    if (old := HOLDS.pop(key, None)):
        old["stop"].set()
    hold = {"stop": threading.Event(), "mode": mode, "item": item_id, "player": player, "split": split, "refills": 0, "key": key}
    HOLDS[key] = hold
    first = write_slot(ad, s, item_id) if mode == "always" else read_slot(ad, s)
    if mode == "infinite" and first["item"] > 0:
        hold["item"] = first["item"]
    th = threading.Thread(target=_hold_loop, args=(ad, s, hold), daemon=True)
    hold["thread"] = th
    th.start()
    return first


def active_holds(ad) -> list[dict]:
    return [{"player": h["player"], "split": h["split"], "mode": h["mode"], "item": ITEMS.get(h.get("item", 0)),
             "refills": h.get("refills", 0)} for k, h in HOLDS.items() if k[0] == id(ad)]


# ------------------------------------------------------------------------------------------------------ engine
OPS = ("games", "items", "state", "give", "always", "infinite", "release")
OP_ALIASES = {"list": "state", "status": "state", "show": "state", "read": "state", "set": "give", "write": "give",
              "hold": "always", "freeze": "always", "always_have": "always", "always_item": "always", "infinite_item": "always",
              "keep": "infinite", "never_lose": "infinite", "infinite_items": "infinite", "unlimited": "infinite",
              "off": "release", "stop": "release", "disable": "release", "unfreeze": "release", "clear": "release"}


def run(ad, title: str, platform: str, op: str = "state", item: str = "", player: int = 1, split: str = "1p2p",
        on: bool = True) -> dict:
    """Engine entry (tests drive it through a fake adapter)."""
    op = norm(op).replace(" ", "_") or "state"
    op = OP_ALIASES.get(op, op)
    split = (norm(split).replace(" ", "") or "1p2p")
    split = {"1p": "1p2p", "2p": "1p2p", "12": "1p2p", "3p": "3p4p", "4p": "3p4p", "34": "3p4p", "split": "3p4p"}.get(split, split)
    if op == "items":
        return {"items": {ITEMS[i]: {"id": i, "decomp": DECOMP_NAMES[i]} for i in range(1, 16)},
                "note": "'infinite red shells' = op=always item='red shell'; triples only when asked for 3 / triple"}
    key, note = detect(title, platform)
    if op == "games":
        return {"games": {k: {"name": v["name"], "rom": v["rom"], "live_checked": v["live_checked"], "sources": v["sources"]}
                          for k, v in LAYOUTS.items()}, "gaps": GAPS, "ops": OPS, "detected": key, "note": note}
    if key is None:
        return {"error": note, "games": [v["name"] for v in LAYOUTS.values()]}
    if key not in LAYOUTS:
        return {"error": f"{title}: {note}", "games": [v["name"] for v in LAYOUTS.values()]}
    if op not in OPS:
        return {"error": f"unknown op '{op}' (" + " | ".join(OPS) + ")"}
    lay = LAYOUTS[key]
    res = {"game": lay["name"], "layout": key, "op": op}
    if note:
        res["note"] = note
    if op == "state":
        res["players"] = {sp: {f"p{p}": read_slot(ad, slot(key, p, sp)) for p in range(1, len(wins) + 1)}
                          for sp, wins in lay["windows"].items()}
        res["holds"] = active_holds(ad)
        res["live_checked"] = lay["live_checked"]
        return res
    if op == "release":
        res["released"] = _release(ad, None, int(player) if player else None)
        return res
    if (op in ("always", "infinite")) and not on:
        res["released"] = _release(ad, split, int(player))
        return res
    if op == "infinite" and names_an_item(item):
        op = "always"                                   # "infinite red shells" with the item named = hold that item
    if op == "always" and not names_an_item(item):
        op = "infinite"                                 # "always have an item" with none named = keep what is picked up
    s = slot(key, int(player), split)
    res.update(player=int(player), split=split, object=s["object"], address=f"{s['item']:#x}", icon_address=f"{s['icon']:#x}")
    if op == "give":
        iid, name = resolve_item(item)
        back = write_slot(ad, s, iid)
        res.update(item=name, item_id=iid, read_back=back, verified=back["verified"], codes=gameshark(key, int(player), split, iid),
                   note=(res.get("note", "") + " " if res.get("note") else "") + "written once: the game clears it when used")
        return res
    if op == "always":
        iid, name = resolve_item(item)
        back = _start(ad, s, "always", iid, int(player), split)
        res.update(item=name, item_id=iid, held=True, mode="always", read_back=back, verified=back["verified"],
                   codes=gameshark(key, int(player), split, iid),
                   undo=f"mario_kart op=release player={int(player)}",
                   note=(res.get("note", "") + " " if res.get("note") else "") +
                        f"player {int(player)} holds {name} until released; every use refills it within 50 ms")
        return res
    back = _start(ad, s, "infinite", 0, int(player), split)       # infinite: keep whatever is picked up
    res.update(held=True, mode="infinite", read_back=back, current=back["name"], verified=True,
               undo=f"mario_kart op=release player={int(player)}",
               note=(res.get("note", "") + " " if res.get("note") else "") +
                    "whatever item the player picks up is refilled after each use until released")
    return res


# ------------------------------------------------------------------------------------------------------ gBox tool
class MarioKartIn(BaseModel):
    session_id: str
    op: str = "state"          # games | items | state | give | always | infinite | release
    item: str = ""             # "red shell", "triple red shells", "blue shell", "star", "lightning", "boo", "mushroom"...
    player: int = 1            # 1-4 (3 and 4 only on a 3P/4P split screen)
    split: str = "1p2p"        # 1p2p = one or two human players on screen (default) | 3p4p = 3-4 player split screen
    on: bool = True            # always / infinite: false releases the hold


class MarioKartOut(BaseModel):
    result: dict


@tool("mario_kart", "1.0", MarioKartIn, MarioKartOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      side_effects=["holds a player's item slot in live emulated memory until released or the session ends"], timeout_s=60)
def mario_kart(inp: MarioKartIn, ctx):
    """Mario Kart 64 (N64) items on the live session, verified by read-back. op=always item=<name> holds that item in
    the player's slot so using it never consumes it ('infinite red shells' = op=always item='red shell'); op=infinite
    keeps whatever item the player picks up; op=give writes it once; op=state shows every player's item; op=release
    (or on=false) stops the hold. player=1-4, split=3p4p on a 3-4 player screen."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    return {"result": run(ad, g.get("title", ""), g.get("platform", ""), inp.op, inp.item, inp.player, inp.split, inp.on)}
