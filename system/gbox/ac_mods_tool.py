"""`ac_mods`: the player's Armored Core assembly, live, across the Armored Core games in the library.

ops: games | build (current parts by slot, with names + EP/weight check) | equip (part=<name or id>, slot optional:
     "the karasawa", "moonlight", "WG-1-KARASAWA", "back_weapon_r:24") | remove (slot) | apply_build (parts=[names...],
     e.g. a community build) | unlock_all_parts (every part in the owned-parts list so the garage offers it) |
     money (value=credits) | parts_search (query: name / type / slot) | best_build (goal: returns the current build +
     catalog summary + how to apply a community build; the agent picks the parts, then apply_build) | ap (mission:
     refill armor).
Per-game layout: gbox/ac_games.py. Part catalog: profiles/gamedata/<key>-parts.json (same file the UI's Ctrl+click
picker loads from GET /api/gamedata/<key>-parts).
Every write is read back (verified) and listed with before/after bytes.

Register with:  from . import ac_mods_tool  # noqa: F401
"""
import json
import re
import struct
from pathlib import Path

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool
from .ac_games import GAMES

CATALOG_DIR = Path(__file__).resolve().parent.parent / "profiles" / "gamedata"
_CAT = {}


def catalog(key: str) -> dict:
    g = GAMES[key]
    f = CATALOG_DIR / f"{g['catalog']}.json"
    mt = f.stat().st_mtime
    if _CAT.get(key, (None, 0))[1] != mt:
        _CAT[key] = (json.loads(f.read_text(encoding="utf-8")), mt)
    return _CAT[key][0]


# --- memory -------------------------------------------------------------------------------------------------------------

def _phys(platform: str, a: int) -> int:
    if platform == "psx":
        return a & 0x1FFFFF                          # RetroArch/pcsx_rearmed exposes main RAM at offset 0 (verified)
    if platform == "psp":
        return a                                     # PPSSPP core: user memory at its native 0x08xxxxxx address
    return a


class Mem:
    def __init__(self, ad, platform):
        self.ad, self.platform, self.log, self.pending = ad, platform, [], []

    def rd(self, a, n):
        return bytes(self.ad.read_memory(_phys(self.platform, a), n))

    def wr(self, a, data: bytes):
        before = self.rd(a, len(data))
        if before != data:
            self.ad.write_memory(_phys(self.platform, a), data)
        self.log.append({"addr": hex(a), "before": before.hex(), "after": data.hex()})

    def verify(self):
        return all(self.rd(int(w["addr"], 16), len(w["after"]) // 2).hex() == w["after"] for w in self.log)

    def changes(self):
        return [w for w in self.log if w["before"] != w["after"]]


# --- names --------------------------------------------------------------------------------------------------------------

ALIASES = {"karasawa": "WG-1-KARASAWA", "moonlight": "LS-99-MOONLIGHT", "moonlight sword": "LS-99-MOONLIGHT",
           "laser blade": "LS-2001", "blade": "LS-2001", "sword": "LS-2001", "rifle": "WG-RF35"}
SLOT_WORDS = {"head": "head", "core": "core", "arms": "arms", "arm": "arms", "legs": "legs", "leg": "legs",
              "booster": "booster", "boosters": "booster", "boost": "booster", "fcs": "fcs", "generator": "generator",
              "gen": "generator", "radiator": "radiator", "inside": "inside", "extension": "extension",
              "back l": "back_weapon_l", "back left": "back_weapon_l", "left back": "back_weapon_l", "back_weapon_l": "back_weapon_l",
              "back r": "back_weapon_r", "back right": "back_weapon_r", "right back": "back_weapon_r", "back_weapon_r": "back_weapon_r",
              "arm weapon r": "arm_weapon_r", "right hand": "arm_weapon_r", "right arm": "arm_weapon_r", "weapon": "arm_weapon_r",
              "hand": "arm_weapon_r", "arm_weapon_r": "arm_weapon_r", "arm weapon l": "arm_weapon_l", "left hand": "arm_weapon_l",
              "left arm": "arm_weapon_l", "arm_weapon_l": "arm_weapon_l", "option": "option", "options": "option",
              "optional": "option"}


def _n(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _slot_name(s: str) -> str:
    t = re.sub(r"[_\-]+", " ", (s or "").lower()).strip()
    return SLOT_WORDS.get(t) or SLOT_WORDS.get(t.replace(" ", "_")) or (s or "")


def search(cat: dict, q: str, slot: str = "") -> list:
    """Parts matching a name / alias / type / slot query, best first."""
    parts = cat["parts"]
    if slot:
        parts = [p for p in parts if p["slot"] == slot or slot in p.get("slots", [])]
    m = re.fullmatch(r"\s*([a-z_]+):(\d+)\s*", q or "")
    if m:
        return [p for p in parts if p["code"] == f"{m.group(1)}:{m.group(2)}" or
                (m.group(1) in p.get("slots", []) and p["id"] == int(m.group(2)))]
    q0 = re.sub(r"^(the|a|an|my)\s+", "", (q or "").strip().lower())
    q0 = ALIASES.get(q0, q0)
    nq = _n(q0)
    if not nq:
        return []
    exact = [p for p in parts if _n(p["name"]) == nq]
    if exact:
        return exact
    sub = [p for p in parts if nq in _n(p["name"])]
    if sub:
        return sorted(sub, key=lambda p: len(p["name"]))
    typ = [p for p in parts if nq in _n(p.get("type", "")) or nq == _n(p["slot"])]
    if typ:
        return typ
    import difflib
    names = {_n(p["name"]): p for p in parts}
    return [names[k] for k in difflib.get_close_matches(nq, list(names), n=5, cutoff=0.6)]


def detect(title: str, platform: str):
    t = (title or "").lower()
    for key, g in GAMES.items():
        if platform in g["platforms"] and re.search(g["match"], t) and not (g.get("exclude") and re.search(g["exclude"], t)):
            return key, g
    raise ValueError(f"no Armored Core table for {title!r} ({platform}) yet; supported: "
                     + ", ".join(f"{g['name']} ({'/'.join(g['platforms'])})" for g in GAMES.values()))


# --- assembly -------------------------------------------------------------------------------------------------------------

def _list(cat, g, slot):
    lst = g.get("list_of", {}).get(slot, slot)
    return {p["id"]: p for p in cat["parts"] if p["slot"] == lst}


def read_build(m: Mem, g: dict, cat: dict) -> dict:
    out = {}
    for slot, a in g["assembly"].items():
        v = m.rd(a, 1)[0]
        p = _list(cat, g, slot).get(v)
        out[slot] = {"id": v, "name": p["name"] if p else (None if v == g["none"] else f"#{v}"),
                     "type": p.get("type") if p else None}
    if g.get("options_mask"):
        mask = struct.unpack("<H", m.rd(g["options_mask"], 2))[0]
        out["option"] = [p["name"] for p in cat["parts"] if p["slot"] == "option" and mask >> p["bit"] & 1]
    return out


def check(build_ids: dict, g: dict, cat: dict) -> dict:
    """Garage rules: EP, legs weight, core (arms) weight, from the catalog stats."""
    parts = {s: _list(cat, g, s).get(v) for s, v in build_ids.items()}
    st = lambda s, k: ((parts.get(s) or {}).get("stats") or {}).get(k, 0)
    ep = sum(st(s, "energy_drain") for s in parts)
    out = {"ep": ep, "ep_max": st("generator", "energy_output")}
    out["legs_weight"] = sum(st(s, "weight") for s in parts if s != "legs")
    out["legs_max"] = st("legs", "max_weight")
    cw = g["rules"].get("core_weight") or ()
    out["core_weight"] = sum(st(s, "weight") for s in cw)
    out["core_max"] = st("core", "max_weight_arms")
    problems = []
    if out["ep_max"] and ep > out["ep_max"]:
        problems.append(f"Not Enough Energy: EP {ep} > generator {out['ep_max']}")
    if out["legs_max"] and out["legs_weight"] > out["legs_max"]:
        problems.append(f"Overweight: {out['legs_weight']} > legs limit {out['legs_max']}")
    if out["core_max"] and out["core_weight"] > out["core_max"]:
        problems.append(f"Overweight (arms): {out['core_weight']} > core limit {out['core_max']}")
    out["ok"] = not problems
    out["note"] = "optional parts' effects (e.g. energy reducers/amplifiers) are not counted; the garage may show less EP"
    if problems:
        out["problems"] = problems
    return out


def _own(m: Mem, g: dict, p: dict):
    """Queue the part for the owned-parts list (written only once the build passes the garage check)."""
    base = g.get("owned_base", {}).get(p["slot"])
    if g.get("owned") and base is not None:
        m.pending.append((g["owned"] + base + p["id"], b"\x01"))


def _pick_slot(p: dict, slot: str, cur: dict) -> str:
    if p["slot"] != "back_weapon":
        return p["slot"]
    if p["name"].startswith(("WX-", "XCS-")):
        return "back_weapon_l"                       # both-shoulder weapons live in the left slot
    if slot in ("back_weapon_l", "back_weapon_r"):
        return slot
    if p.get("type", "").lower() == "radar":
        return "back_weapon_r"
    return "back_weapon_l"


def _equip(m, g, cat, p, slot, ids, notes):
    s = _pick_slot(p, slot, ids)
    if p["slot"] == "option":
        mask = struct.unpack("<H", m.rd(g["options_mask"], 2))[0] | (1 << p["bit"])
        m.pending.append((g["options_mask"], struct.pack("<H", mask)))
        _own(m, g, p)
        return "option"
    ids[s] = p["id"]
    wa = g.get("weapon_arms")
    if wa and s == "arms" and p["id"] >= wa["min"]:
        ids[wa["pair"][0]] = wa["pair"][1]
        for c in wa.get("clear", []):
            ids[c] = g["none"]
        notes.append(f"{p['name']} is a weapon arm: hand weapon set to NO WEAPON and the laser blade removed")
    if wa and s in ["arm_weapon_r"] + wa.get("clear", []) and ids.get("arms", 0) >= wa["min"] and p["id"] != wa["pair"][1]:
        ids["arms"] = 1 if 1 in _list(cat, g, "arms") else 0
        if ids.get(wa["pair"][0]) == wa["pair"][1] and s != wa["pair"][0]:
            ids[wa["pair"][0]] = g["none"]
        notes.append("hand weapons / blades need normal arms: arms set to " + _list(cat, g, "arms")[ids["arms"]]["name"])
    _own(m, g, p)
    return s


def _resolve(cat, q, slot=""):
    hits = search(cat, q, slot if slot not in ("back_weapon_l", "back_weapon_r") else "back_weapon")
    if not hits:
        raise ValueError(f"no part matching {q!r}" + (f" for {slot}" if slot else "") + " (try op=parts_search)")
    if len(hits) > 1 and _n(hits[0]["name"]) != _n(q) and not q.lower().startswith(("the ", "a ")):
        same = [h for h in hits if _n(h["name"]).startswith(_n(q))]
        if len(hits) > 6 and not same:
            raise ValueError(f"{q!r} is ambiguous: " + ", ".join(h["name"] for h in hits[:12]))
    return hits[0]


def run(ad, title: str, platform: str, op: str = "build", part: str = "", slot: str = "", parts=None,
        value: int = 0, query: str = "", goal: str = "", force: bool = False) -> dict:
    op = (op or "build").strip().lower().replace(" ", "_")
    op = {"status": "build", "list": "build", "show": "build", "give": "equip", "unequip": "remove",
          "unlock": "unlock_all_parts", "unlock_all": "unlock_all_parts", "all_parts": "unlock_all_parts",
          "credits": "money", "cash": "money", "search": "parts_search", "find": "parts_search",
          "build_apply": "apply_build", "set_build": "apply_build", "best": "best_build", "heal": "ap"}.get(op, op)
    if op == "games":
        return {"games": {k: {"name": g["name"], "platforms": g["platforms"], "catalog": g["catalog"]}
                          for k, g in GAMES.items()}}
    key, g = detect(title, platform)
    cat = catalog(key)
    res = {"game": g["name"], "op": op}
    if op == "parts_search":
        sl = _slot_name(slot) if slot else ""
        hits = search(cat, query or part, sl if sl not in ("back_weapon_l", "back_weapon_r") else "back_weapon")
        return {**res, "matches": hits[:40], "count": len(hits)}
    m = Mem(ad, platform)
    ids = {s: m.rd(a, 1)[0] for s, a in g["assembly"].items()}
    notes = []
    if op == "build":
        return {**res, "build": read_build(m, g, cat), "check": check(ids, g, cat)}
    if op == "best_build":
        bysl = {}
        for p in cat["parts"]:
            bysl.setdefault(p["slot"], []).append(p["name"])
        return {**res, "goal": goal or "all-round", "build": read_build(m, g, cat), "check": check(ids, g, cat),
                "parts_by_slot": bysl, "how_to": g.get("build_guide", ""),
                "next": "web_search a community build for this goal (or pick from parts_by_slot using catalog stats via "
                        "parts_search), then call op=apply_build parts=[names]. Keep check.ok true."}
    if op in ("equip", "remove", "apply_build"):
        new = dict(ids)
        touched = []
        if op == "equip":
            sl = _slot_name(slot) if slot else ""
            p = _resolve(cat, part, sl)
            touched.append((_equip(m, g, cat, p, sl, new, notes), p["name"]))
        elif op == "remove":
            sl = _slot_name(slot or part)
            if sl == "option":
                p = _resolve(cat, part, "option") if part and _slot_name(part) != "option" else None
                mask = struct.unpack("<H", m.rd(g["options_mask"], 2))[0]
                mask = mask & ~(1 << p["bit"]) if p else 0
                m.wr(g["options_mask"], struct.pack("<H", mask))
                touched.append(("option", p["name"] if p else "all"))
            else:
                if sl not in g["assembly"]:
                    raise ValueError(f"slot? one of {', '.join(g['assembly'])}")
                if sl in ("head", "core", "arms", "legs", "generator", "booster", "fcs") and not force:
                    raise ValueError(f"the {sl} can't be empty in the garage; equip another part instead")
                new[sl] = g.get("no_weapon", {}).get(sl, g["none"]) if sl == "arm_weapon_r" and new.get("arms", 0) >= g.get(
                    "weapon_arms", {}).get("min", 999) else g["none"]
                touched.append((sl, None))
        else:
            seq = parts or []
            if isinstance(seq, str):
                seq = [x for x in re.split(r"[,\n;]+", seq) if x.strip()]
            backs = []
            for item in seq:
                if isinstance(item, dict):
                    sl, q = _slot_name(item.get("slot", "")), item.get("part") or item.get("name") or ""
                else:
                    mm = re.match(r"\s*([A-Za-z _]+?)\s*[:=]\s*(.+)$", str(item))
                    sl, q = (_slot_name(mm.group(1)), mm.group(2)) if mm and _slot_name(mm.group(1)) in (
                        set(g["assembly"]) | {"option"}) else ("", str(item))
                if _n(q) in ("", "none", "nothing", "empty"):
                    if sl in g["assembly"]:
                        new[sl] = g["none"]
                        touched.append((sl, None))
                    continue
                p = _resolve(cat, q, sl)
                if p["slot"] == "back_weapon" and not sl:
                    sl = "back_weapon_l" if not backs else "back_weapon_r"
                    if p.get("type", "").lower() == "radar" and not backs:
                        sl = "back_weapon_r"
                    backs.append(sl)
                touched.append((_equip(m, g, cat, p, sl, new, notes), p["name"]))
        dual = g["rules"].get("dual_back")
        if dual and new.get("back_weapon_l", g["none"]) != g["none"]:
            bl = _list(cat, g, "back_weapon_l").get(new["back_weapon_l"])
            if bl and bl["name"].startswith(tuple(dual)) and new.get("back_weapon_r") != g["none"]:
                new["back_weapon_r"] = g["none"]
                notes.append(f"{bl['name']} uses both shoulders: back right emptied")
        if g["rules"].get("caterpillar_no_booster") and "booster" in new:
            lg = _list(cat, g, "legs").get(new.get("legs"))
            if lg and "caterpillar" in lg.get("type", "").lower() and new["booster"] != g["none"]:
                new["booster"] = g["none"]
                notes.append("caterpillar legs can't take a booster (built-in): booster slot emptied")
        chk = check(new, g, cat)
        if not chk["ok"] and not force:
            m.log.clear()
            raise ValueError("the garage would refuse this build (" + "; ".join(chk["problems"]) +
                             "). Pick lighter / lower-drain parts or a stronger generator, or pass force=true.")
        for a, data in m.pending:
            m.wr(a, data)
        for s, v in new.items():
            if v != ids[s]:
                m.wr(g["assembly"][s], bytes([v]))
        res.update(equipped=[{"slot": s, "part": n} for s, n in touched], check=chk, build=read_build(m, g, cat))
        res["note"] = g.get("apply_note", "")
    elif op == "unlock_all_parts":
        m.wr(g["owned"], b"\x01" * g["owned_count"])
        res["unlocked"] = g["owned_count"]
        res["note"] = "the garage lists them the next time Assembly / Optional Parts is opened"
    elif op == "money":
        v = max(0, min(int(value or g["credits_max"]), g["credits_max"]))
        before = struct.unpack("<i", m.rd(g["credits"], 4))[0]
        m.wr(g["credits"], struct.pack("<i", v))
        res.update(credits_before=before, credits=v, note="shown the next time the shop / a menu redraws credits")
    elif op == "ap":
        # player AP is stored x4 as u16 (current, max); max = sum of head/core/arms/legs armor points
        scale = (g.get("ap") or (0, 4))[1]
        mx = sum((_list(cat, g, s).get(ids[s]) or {}).get("stats", {}).get("armor_point", 0)
                 for s in ("head", "core", "arms", "legs")) * scale
        want = struct.pack("<H", mx & 0xFFFF)
        cands = [g["ap"][0]] if g.get("ap") else []
        a = next((c for c in cands if m.rd(c + 2, 2) == want), None)
        if a is None:
            lo, hi = g.get("ap_scan", (0x80100000, 0x80200000))
            for base in range(lo, hi, 0x10000):
                blk = m.rd(base, 0x10000)
                i = blk.find(want)
                while 0 <= i < len(blk) - 1:
                    c = struct.unpack_from("<H", blk, i - 2)[0] if i >= 2 else 0
                    if (i - 2) % 4 == 0 and 0 < c <= mx and c % scale == 0:
                        a = base + i - 2
                        break
                    i = blk.find(want, i + 1)
                if a is not None:
                    break
        if a is None:
            raise ValueError("not in a mission (player AP not found)")
        cur = struct.unpack("<H", m.rd(a, 2))[0]
        m.wr(a, struct.pack("<H", mx))
        res.update(ap_before=cur // scale, ap=mx // scale, ap_addr=hex(a))
    else:
        raise ValueError("op: games | build | equip | remove | apply_build | unlock_all_parts | money | parts_search | "
                         "best_build | ap")
    if notes:
        res["notes"] = notes
    res["changes"] = m.changes()
    res["verified"] = m.verify()
    return res


# --- gBox tool ---------------------------------------------------------------------------------------------------------------

class AcIn(BaseModel):
    session_id: str
    op: str = "build"          # games | build | equip | remove | apply_build | unlock_all_parts | money | parts_search | best_build | ap
    part: str = ""             # equip/remove: part name or alias ("karasawa", "WG-1-KARASAWA", "moonlight") or slot:id
    slot: str = ""             # optional: head core arms legs arm_weapon_r arm_weapon_l back_weapon_l back_weapon_r booster fcs generator option
    parts: list | str | None = None   # apply_build: ["HD-ONE", "XCA-00", "back_weapon_r: RZ-A0", ...]
    value: int = 0             # money: credits (0 = max)
    query: str = ""            # parts_search
    goal: str = ""             # best_build: all-round | speed | heavy | energy | missile ...
    force: bool = False        # apply even if the garage would show Not Enough Energy / Overweight


class AcOut(BaseModel):
    result: dict


@tool("ac_mods", "1.0", AcIn, AcOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=120)
def ac_mods(inp: AcIn, ctx):
    """Armored Core (PS1/PSP): read the player's AC build, equip parts by name (weapons, head, legs...), apply a whole
    build, unlock every part in the garage, set credits, search the parts catalog. Verified by read-back."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    return {"result": run(ad, g.get("title", ""), g.get("platform", ""), inp.op, inp.part, inp.slot, inp.parts,
                          inp.value, inp.query, inp.goal, inp.force)}
