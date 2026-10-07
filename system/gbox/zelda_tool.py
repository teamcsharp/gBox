"""`zelda`: Link's inventory / equipment, live, in every Zelda game in the library (any system).

ops: games | list | give (item, count) | equip (item, button) | remove (item) | all_items | noclip (on) | unrestrict (alias any_age /
     any_form: 'let me use/equip anything') | hearts (count) | rupees (count) | max (full hearts, rupees, ammo).
Items are taken by NAME ("hook shot", "bow", "the master sword", "bombs", "bottle"...), fuzzy-matched per game.
Games, tables and sources: gbox/zelda_games.py. Ocarina of Time delegates to gbox/oot.py (v1.2 SaveContext).
Every op returns before/after bytes of what it touched and verified = read-back equals what was written.

Register with:  from . import zelda_tool  # noqa: F401
"""
import difflib
import re
import struct
import time

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool
from .zelda_games import GAMES as _TABLES

GAMES = dict(_TABLES)


# --- memory -----------------------------------------------------------------------------------------------------------

def _ra_offset(platform: str, a: int) -> int:
    """Console address -> RetroAchievements RAM offset (RetroArch READ_CORE_RAM), for cores without a memory map."""
    if platform == "snes" and 0x7E0000 <= a < 0x800000:
        return a - 0x7E0000                               # WRAM at $0 (verified: $7E0010 module, $7EF36C hearts)
    if platform == "gba":
        if 0x03000000 <= a < 0x03008000:
            return a - 0x03000000                         # IWRAM $00000-$07FFF
        if 0x02000000 <= a < 0x02040000:
            return a - 0x02000000 + 0x8000                # EWRAM $08000-$47FFF
    return a                                              # NES / GB / GBC: CPU addresses; N64: the adapter maps 0x80xxxxxx


class Mem:
    """Reads/writes console addresses on a session; records every write (before/after) and verifies it."""

    def __init__(self, ad, platform: str):
        self.ad, self.platform, self.native, self.log, self.base = ad, platform, None, [], 0
        self.be = platform in ("n64", "gamecube", "wii")          # multi-byte values are big-endian there

    def _addr(self, a: int, n: int) -> int:
        if self.native is None:
            try:
                self.ad.read_memory(a, n)
                self.native = True
            except Exception:
                self.native = False
        return a if self.native else _ra_offset(self.platform, a)

    def rd(self, a: int, n: int = 1) -> bytes:
        a += self.base
        if self.platform == "n64":
            from . import oot
            return oot._rd(self.ad, a, n)
        return bytes(self.ad.read_memory(self._addr(a, n), n))

    def wr(self, a: int, data: bytes):
        before = self.rd(a, len(data))
        a += self.base
        if before != data:
            if self.platform == "n64":
                from . import oot
                oot._wr(self.ad, a, data)
            else:
                self.ad.write_memory(self._addr(a, len(data)), data)
        self.log.append({"addr": hex(a - self.base), "before": before.hex(), "after": data.hex()})

    def poke(self, a: int, data: bytes, old: bytes | None = None):
        """Unlogged write (HUD refresh flags, held noclip tables). With `old`, only the changed spans are sent; big
        writes go in 256-byte pieces (RetroArch's network command line is limited)."""
        spans = [(0, len(data))]
        if old is not None:
            spans, i = [], 0
            while i < len(data):
                if data[i] != old[i]:
                    j = i
                    while j < len(data) and data[j] != old[j] and j - i < 256:
                        j += 1
                    spans.append((i, j))
                    i = j
                else:
                    i += 1
        a += self.base
        for lo, hi in spans:
            for k in range(lo, hi, 256):
                piece = data[k:min(hi, k + 256)]
                if self.platform == "n64":
                    from . import oot
                    oot._wr(self.ad, a + k, piece)
                else:
                    self.ad.write_memory(self._addr(a + k, len(piece)), piece)

    def u8(self, a):
        return self.rd(a, 1)[0]

    def changes(self) -> list:
        """One entry per address: first 'before', last 'after'."""
        out = {}
        for w in self.log:
            out[w["addr"]] = {**w, "before": out[w["addr"]]["before"]} if w["addr"] in out and out[w["addr"]]["before"] else dict(w)
        return [w for w in out.values() if w["before"] != w["after"]]

    def verify(self) -> bool:
        last = {w["addr"]: w["after"] for w in self.log}
        return all(self.rd(int(a, 16), len(v) // 2).hex() == v for a, v in last.items())


def _bcd(v: int, n: int = 1) -> bytes:
    v = max(0, min(v, 10 ** (2 * n) - 1))
    digits = f"{v:0{2 * n}d}"
    return bytes(int(digits[i:i + 2], 16) for i in range(0, 2 * n, 2))[::-1]          # little-endian BCD bytes


def _unbcd(b: bytes) -> int:
    return int("".join(f"{x:02x}" for x in b[::-1]) or "0")


# --- names --------------------------------------------------------------------------------------------------------------

_FILLER = {"the", "a", "an", "me", "my", "some", "please", "item", "link"}
COMMON = {"hook shot": "hookshot", "hook": "hookshot", "bow and arrow": "bow", "bow and arrows": "bow", "bomb": "bombs",
          "roc feather": "rocs feather", "rocks feather": "rocs feather", "rocs cape": "rocs cape", "pegasus": "pegasus boots",
          "dash boots": "pegasus boots", "running boots": "pegasus boots", "zora flippers": "zoras flippers", "lens": "lens of truth",
          "hammer": "megaton hammer", "boomerang": "boomerang", "slingshot": "slingshot", "fairy slingshot": "slingshot",
          "sling shot": "slingshot", "deku stick": "deku stick", "sticks": "deku stick", "nuts": "deku nut", "ocarina": "ocarina",
          "flute": "flute", "money": "rupees", "rupee": "rupees", "cash": "rupees", "heart": "hearts", "life": "hearts",
          "heart container": "hearts", "heart containers": "hearts", "health": "hearts"}


def norm(t: str) -> str:
    t = re.sub(r"[’'`]", "", (t or "").lower())
    words = [w for w in re.split(r"[^a-z0-9]+", t) if w and w not in _FILLER]
    return " ".join(words)


def resolve(game: dict, q: str) -> str:
    items = game["items"]
    keys = {norm(k): k for k in items}
    al = {norm(k): v for k, v in {**COMMON, **game.get("aliases", {})}.items()}
    n = norm(q)
    cands = [n, al.get(n, "")]
    cands += [c[:-1] for c in cands if c.endswith("s")] + [c + "s" for c in cands if c]
    cands += [al.get(c, "") for c in list(cands)]
    for c in cands:
        if c and norm(c) in keys:
            return keys[norm(c)]
    words = set(n.split())
    hits = [k for nk, k in keys.items() if words and words <= set(nk.split())]
    if len(hits) == 1:
        return hits[0]
    if hits:                                               # 'sword' -> the basic one if it is among them
        hits.sort(key=len)
        return hits[0]
    close = difflib.get_close_matches(n, list(keys) + list(al), n=1, cutoff=0.72)
    if close:
        c = close[0]
        return keys.get(c) or keys.get(norm(al[c])) or resolve(game, al[c])
    raise ValueError(f"{game['name']} has no item {q!r}; known: {', '.join(sorted(items))}")


def detect(title: str, platform: str):
    t = (title or "").lower()
    for key, g in GAMES.items():
        if platform in g["platforms"] and re.search(g["match"], t) and not (g.get("exclude") and re.search(g["exclude"], t)):
            return key, g
    raise ValueError(f"no Zelda table for {title!r} on {platform}; supported: "
                     + ", ".join(f"{g['name']} ({'/'.join(g['platforms'])})" for g in GAMES.values()))


# --- generic item specs ---------------------------------------------------------------------------------------------------

def _have(m: Mem, g: dict, sp: dict) -> bool:
    k = sp["k"]
    if k == "set":
        b = m.u8(sp["a"])
        return b == sp["v"] if sp.get("ex") else (b >= sp["v"] and sp["v"] > 0)
    if k == "cnt":
        return any(m.rd(sp["a"], sp.get("n", 1)))
    if k == "or":
        return m.u8(sp["a"]) & sp["m"] == sp["m"]
    if k == "slot":
        return sp["v"] in m.rd(g["slots"][0], len(g["slots"]))
    if k == "inv2":
        return bool(m.u8(g["inv2"] + sp["v"] // 4) >> (sp["v"] % 4 * 2) & 3)
    if k == "raw":
        return m.rd(sp["a"], len(sp["data"]) // 2).hex() == sp["data"]
    if k == "tf":
        return bool(m.u8(g["tflags"] + (sp["v"] >> 3)) >> (sp["v"] & 7) & 1)
    if k == "nib":
        return int.from_bytes(m.rd(sp["a"], 2), "big") >> sp["sh"] & 0xF == sp["v"]
    if k == "fn":
        return FN[sp["fn"]](m, g, sp, "have", 0)
    return False


def _count_value(sp, count, g, name):
    if count:
        return count
    return sp["d"]


def _give(m: Mem, g: dict, sp: dict, count: int = 0, name: str = ""):
    k = sp["k"]
    if sp.get("dx") and m.platform != "gbc":
        raise ValueError(f"{name} only exists in the GBC (DX) version")
    if k == "set":
        if not (sp.get("up") and m.u8(sp["a"]) >= sp["v"]):
            m.wr(sp["a"], bytes([sp["v"]]))
    elif k == "cnt":
        n = sp.get("n", 1)
        v = count or sp["d"]
        if sp.get("bcd"):
            m.wr(sp["a"], _bcd(int(f"{v:x}") if not count else v, n))
        else:
            m.wr(sp["a"], v.to_bytes(n, "big" if m.be or sp.get("be") else "little"))
    elif k == "or":
        m.wr(sp["a"], bytes([m.u8(sp["a"]) | sp["m"]]))
    elif k == "slot":
        if sp["v"] not in m.rd(g["slots"][0], len(g["slots"])):
            free = [a for a in list(g["store"]) + [a for a in g["slots"] if a not in g["store"]] if m.u8(a) == 0]
            if not free:
                raise RuntimeError("every inventory slot is full: remove something first")
            m.wr(free[0], bytes([sp["v"]]))
        if g.get("tflags") is not None:
            _tflag(m, g, sp["v"])
    elif k == "inv2":
        for iid in (0, sp["v"]) if sp["v"] < 0x47 else (sp["v"],):
            a, sh = g["inv2"] + iid // 4, iid % 4 * 2
            b = m.u8(a)
            if not b >> sh & 3:
                m.wr(a, bytes([b & ~(3 << sh) | (1 << sh)]))
    elif k == "raw":
        m.wr(sp["a"], bytes.fromhex(sp["data"]))
    elif k == "nib":                                        # N64 u16 BE nibble (MM equipment: worn = owned)
        cur = int.from_bytes(m.rd(sp["a"], 2), "big")
        m.wr(sp["a"], (cur & ~(0xF << sp["sh"]) | sp["v"] << sp["sh"]).to_bytes(2, "big"))
    elif k == "tf":
        _tflag(m, g, sp["v"])
    elif k == "fn":
        FN[sp["fn"]](m, g, sp, "give", count)
    for extra in sp.get("also", []):
        _give(m, g, extra, count if extra["k"] == "cnt" and k != "cnt" else 0, name)


def _tflag(m, g, t):
    a = g["tflags"] + (t >> 3)
    m.wr(a, bytes([m.u8(a) | 1 << (t & 7)]))


def _remove(m: Mem, g: dict, sp: dict):
    k = sp["k"]
    if k in ("set", "cnt"):
        m.wr(sp["a"], bytes(sp.get("n", 1)))
    elif k == "or":
        m.wr(sp["a"], bytes([m.u8(sp["a"]) & ~sp["m"] & 0xFF]))
    elif k == "slot":
        for a in g["slots"]:
            if m.u8(a) == sp["v"]:
                m.wr(a, b"\0")
    elif k == "inv2":
        a, sh = g["inv2"] + sp["v"] // 4, sp["v"] % 4 * 2
        m.wr(a, bytes([m.u8(a) & ~(3 << sh) & 0xFF]))
    elif k == "tf":
        a = g["tflags"] + (sp["v"] >> 3)
        m.wr(a, bytes([m.u8(a) & ~(1 << (sp["v"] & 7)) & 0xFF]))
    elif k == "fn":
        FN[sp["fn"]](m, g, sp, "remove", 0)
    else:
        raise ValueError("this item can't be removed")


# --- game-specific helpers -------------------------------------------------------------------------------------------------

def _alttp_bottle(m, g, sp, op, count):
    base = 0x7EF35C
    b = m.rd(base, 4)
    if op == "have":
        return sp["v"] in b if sp["v"] != 2 else any(b)
    if op == "remove":
        for i, x in enumerate(b):
            if x == sp["v"]:
                m.wr(base + i, b"\0")
        return
    i = b.index(0) if 0 in b else (b.index(2) if 2 in b else 0)                         # first free (or empty) bottle
    m.wr(base + i, bytes([sp["v"]]))
    if not m.u8(0x7EF34F):
        m.wr(0x7EF34F, bytes([i + 1]))                                                   # selected bottle (needed to show it)


def _mc_bottle(m, g, sp, op, count):
    base = 0x02002AF6                                                                    # stats.bottles[4] (contents)
    b = m.rd(base, 4)
    owned = [_have(m, g, {"k": "inv2", "v": 0x1C + i}) for i in range(4)]
    if op == "have":
        return any(owned[i] and (sp["v"] == 0x20 or b[i] == sp["v"]) for i in range(4))
    if op == "remove":
        for i in range(4):
            if owned[i] and b[i] == sp["v"]:
                _remove(m, g, {"k": "inv2", "v": 0x1C + i})
        return
    i = next((i for i in range(4) if not owned[i]), None)
    if i is None:
        i = next((i for i in range(4) if b[i] == 0x20), 0)
    _give(m, g, {"k": "inv2", "v": 0x1C + i})
    m.wr(base + i, bytes([sp["v"]]))


def _la_instruments(m, g, sp, op, count):
    if op == "have":
        return all(x & 2 for x in m.rd(0xDB65, 8))
    for i in range(8):
        a = 0xDB65 + i
        m.wr(a, bytes([m.u8(a) | 0x03 if op == "give" else m.u8(a) & ~0x02 & 0xFF]))


def _z2_magic(m, g, sp, op, count):
    if op == "have":
        return m.u8(0x783) >= 8
    m.wr(0x783, b"\x08")                                    # magic containers 8, MP full (containers*32-1)
    m.wr(0x773, b"\xff")


FN = {"z2_magic": _z2_magic, "alttp_bottle": _alttp_bottle, "mc_bottle": _mc_bottle, "la_instruments": _la_instruments}


# --- equip --------------------------------------------------------------------------------------------------------------------

def _button(g, button: str) -> str:
    b = re.sub(r"[^a-z0-9]", "", (button or "").lower())
    b = {"cleft": "c-left", "cl": "c-left", "left": "c-left", "cdown": "c-down", "cd": "c-down", "down": "c-down",
         "cright": "c-right", "cr": "c-right", "right": "c-right", "c1": "c-left", "c2": "c-down", "c3": "c-right",
         "abutton": "a", "bbutton": "b", "ybutton": "y", "xbutton": "x", "rbutton": "r"}.get(b, b)
    if not b:
        return g["default_button"]
    if b not in g["equip"]:
        raise ValueError(f"{g['name']} buttons: {', '.join(g['equip'])}")
    return b


def _equip(m: Mem, g: dict, name: str, sp: dict, button: str):
    kind, addr = g["equip"][button]
    if sp["k"] == "nib":
        _give(m, g, sp, 0, name)
        return
    if sp.get("gear"):                                                                   # worn gear (OoT/MM): equip nibble
        shift, val, bitem = sp["gear"]
        cur = int.from_bytes(m.rd(g["gear_addr"], 2), "big")
        m.wr(g["gear_addr"], (cur & ~(0xF << shift) | val << shift).to_bytes(2, "big"))
        if bitem is not None:
            m.wr(g["equip"]["b"][1], bytes([bitem]))
        return
    if kind == "oot_b":
        if not sp.get("bitem"):
            raise ValueError(f"only swords go on B; put {name} on c-left / c-down / c-right")
    elif kind == "oot_c":
        slot, iid = sp.get("slot"), sp.get("v")
        if sp["k"] == "fn" and sp["fn"].endswith("_bottle"):
            slots = m.rd(g["bottle_slots"][0], len(g["bottle_slots"]))
            slot = g["bottle_slots"][1] + slots.index(iid)
        if slot is None or not sp.get("c"):
            raise ValueError(f"{name} can't go on a C button")
        m.wr(g["cbtn"] + addr, bytes([iid]))
        m.wr(g["cslot"] + addr - 1, bytes([slot]))
    elif kind == "slotidx":                                  # Wind Waker: button holds the inventory slot + HUD item cache
        sel, cache = addr
        if "slot" not in sp:
            return "worn"                                    # sword/shield/bracelets: owning it equips it
        m.wr(sel, bytes([sp["slot"]]))
        m.wr(cache, bytes([sp["v"]]))
    elif kind == "menu":
        if "menu" not in sp:
            return "worn"                                    # sword/shield/mail/gloves...: owning it is wearing it
        m.wr(addr, bytes([sp["menu"]]))
        if sp.get("k") == "fn" and sp["fn"] == "alttp_bottle":                       # point the bottle cursor at it
            b = m.rd(0x7EF35C, 4)
            if sp["v"] in b:
                m.wr(0x7EF34F, bytes([b.index(sp["v"]) + 1]))
    elif kind == "slot":
        if sp["k"] != "slot":
            raise ValueError(f"{name} isn't a button item (it's passive: owning it is enough)")
        cur = m.u8(addr)
        if cur == sp["v"]:
            return
        where = [a for a in g["slots"] if m.u8(a) == sp["v"]]
        if where:
            m.wr(where[0], bytes([cur]))                                                  # swap: old button item takes its slot
        elif cur:
            free = [a for a in g["store"] if m.u8(a) == 0]
            if free:
                m.wr(free[0], bytes([cur]))
        m.wr(addr, bytes([sp["v"]]))
    elif kind == "id":
        iid = sp.get("id", sp.get("v")) if sp["k"] in ("inv2",) else None
        if sp["k"] == "fn" and sp["fn"] == "mc_bottle":
            b = m.rd(0x02002AF6, 4)
            iid = 0x1C + (b.index(sp["v"]) if sp["v"] in b else 0)
        if not iid or iid > 0x1F:
            raise ValueError(f"{name} can't go on a button")
        other = [a for b2, (k2, a) in g["equip"].items() if a != addr]
        for a in other:
            if m.u8(a) == iid:
                m.wr(a, bytes([m.u8(addr)]))                                              # already on the other button: swap
        m.wr(addr, bytes([iid]))
    if g.get("hud_refresh"):
        m.poke(g["hud_refresh"][0], bytes([m.u8(g["hud_refresh"][0]) | g["hud_refresh"][1]]))


def _refresh_inputs(ad, g, m=None):
    keys = g.get("refresh")
    if not keys or not hasattr(ad, "send_input"):
        return False
    when = g.get("refresh_when")
    if when and m is not None and (m.u8(when[0]) not in when[1] or any(m.rd(when[0] + 1, 1))):
        return False                                       # text box / menu / transition: don't press buttons into it
    for k in keys:
        ad.send_input([{"key": k, "down": True}])
        time.sleep(0.12)
        ad.send_input([{"key": k, "down": False}])
        time.sleep(0.9)
    return True


# --- hearts / rupees --------------------------------------------------------------------------------------------------------

def _hearts(m: Mem, g: dict, n: int | None):
    h = g["hearts"]
    if h.get("fmt") == "z1":                                # $066F: hi = containers-1, lo = full hearts-1; $0670 partial
        if n is None:
            b = m.u8(0x66F)
            return {"hearts": (b & 15) + (1 if m.u8(0x670) >= 0x80 else 0.5 if m.u8(0x670) else 0), "max_hearts": (b >> 4) + 1}
        n = max(1, min(int(n), h["cap"]))
        m.wr(0x66F, bytes([(n - 1) << 4 | (n - 1)]))
        m.wr(0x670, b"\xff")
        return {"hearts": n}
    if h.get("fmt") == "z2":                                # heart containers 4-8, HP = containers*32-1
        if n is None:
            return {"hearts": round(m.u8(0x774) / 32, 2), "max_hearts": m.u8(0x784)}
        n = max(4, min(int(n), h["cap"]))
        m.wr(0x784, bytes([n]))
        m.wr(0x774, bytes([n * 32 - 1]))
        return {"hearts": n}
    (ma, mu), (ca, cu) = h["max"], h["cur"]
    size = h.get("n", 1)
    rd = lambda a: int.from_bytes(m.rd(a, size), "big" if m.be else "little")
    tob = lambda v: v.to_bytes(size, "big" if m.be else "little")
    if n is None:
        return {"hearts": rd(ca) / cu, "max_hearts": rd(ma) // mu}
    n = max(1, min(int(n), h["cap"]))
    if h.get("add"):                                        # Wind Waker: the HUD only redraws when its pending counters run
        life_add, max_add = h["add"]
        m.wr(ma, tob(n * mu - mu))
        m.wr(ca, tob(n * cu - 1))
        m.poke(max_add, mu.to_bytes(2, "big"))
        m.poke(life_add, struct.pack(">f", 1.0))
        time.sleep(1.0)
        m.log = [w for w in m.log if w["addr"] not in (hex(ma), hex(ca))]
        m.log += [{"addr": hex(ma), "before": "", "after": tob(n * mu).hex()},
                  {"addr": hex(ca), "before": "", "after": tob(n * cu).hex()}]
        return {"hearts": n}
    m.wr(ma, tob(n * mu))
    if h.get("bump"):                                       # LA: write one less + bump buffer -> the game redraws the HUD
        m.wr(ca, tob(n * cu - 1))
        m.wr(h["bump"], b"\x01")
        time.sleep(0.3)
        m.log = [w for w in m.log if w["addr"] not in (hex(ca), hex(h["bump"]))]
        m.log.append({"addr": hex(ca), "before": "", "after": tob(n * cu).hex()})
    else:
        m.wr(ca, tob(n * cu))
    return {"hearts": n}


def _rupees(m: Mem, g: dict, n: int | None):
    r = g["rupees"]
    fmt = r["fmt"]
    if fmt == "bcd_la":
        a = r["addr"][0]
        if n is None:
            return {"rupees": m.u8(a) % 16 * 100 + _unbcd(m.rd(a + 1, 1))}
        n = max(0, min(int(n), r["cap"]))
        v = max(n - 1, 0)
        m.wr(a, bytes([v // 100]))
        m.wr(a + 1, _bcd(v % 100))
        if n:
            m.wr(r["bump"], b"\x01")                         # wAddRupeeBuffer low: +1 and the HUD redraws
            time.sleep(0.3)
            m.log = [w for w in m.log if w["addr"] not in (hex(a), hex(a + 1), hex(r["bump"]))]
            m.log += [{"addr": hex(a), "before": "", "after": bytes([n // 100]).hex()},
                      {"addr": hex(a + 1), "before": "", "after": _bcd(n % 100).hex()}]
        return {"rupees": n}
    size = 2
    if fmt == "bcd2":
        if n is None:
            return {"rupees": _unbcd(m.rd(r["addr"][0], 2))}
        n = max(0, min(int(n), r["cap"]))
        for a in r["addr"]:
            m.wr(a, _bcd(n, 2))
        return {"rupees": n}
    if fmt == "nes":                                         # Zelda 1: one byte, 255 max
        if n is None:
            return {"rupees": m.u8(r["addr"][0])}
        n = max(0, min(int(n), 255))
        m.wr(r["addr"][0], bytes([n]))
        return {"rupees": n}
    order = "big" if fmt == "u16be" else "little"
    if n is None:
        return {"rupees": int.from_bytes(m.rd(r["addr"][0], size), order)}
    n = max(0, min(int(n), r["cap"]))
    if r.get("wallet") and n > 100:
        m.wr(r["wallet"], bytes([max(m.u8(r["wallet"]), r.get("wallet_max", 3))]))
    if r.get("wallet_or") and n > 99:
        a, bits = r["wallet_or"]
        m.wr(a, bytes([m.u8(a) | bits]))
    if r.get("add") and n:                                  # Wind Waker: write n-1, let the pending counter add 1 (HUD redraws)
        m.wr(r["addr"][0], (n - 1).to_bytes(size, order))
        m.poke(r["add"], (1).to_bytes(4, "big"))
        time.sleep(1.0)
        m.log = [w for w in m.log if w["addr"] != hex(r["addr"][0])]
        m.log.append({"addr": hex(r["addr"][0]), "before": "", "after": n.to_bytes(size, order).hex()})
        return {"rupees": n}
    for a in r["addr"]:
        m.wr(a, n.to_bytes(size, order))
    return {"rupees": n}


# --- noclip -------------------------------------------------------------------------------------------------------------------
# Per game g["noclip"] = list of steps, each one of:
#   ("patch", addr, original_hex, patched_hex)  one-shot code patch in RAM (N64 code segment); off restores the original.
#                                               The original bytes are checked first, so a wrong revision is refused.
#   ("zero", addr, length)                      held: whenever the area holds anything but zeros (a room loaded), zero it
#                                               (Oracles' wRoomCollisions map).
#   ("hold", addr, hex[, off_hex])              held: rewrite these bytes every ~50 ms; off writes off_hex (if given).
#   ("tick", fn)                                held: fn(m, on) runs every ~50 ms (and once with on=False to switch off).
#   ("scan", lo, hi, original_hex, patched_hex) like "patch", at every 4-aligned match of the original inside [lo, hi).
#   ("emu", code)                               the emulator's cheat engine (Game Genie / ROM patches): toggles the entry of the
#                                               game's libretro .cht that has exactly this code.
HOLDS: dict = {}                                 # (session key) -> (stop Event, Thread)


def _hold_loop(m: "Mem", steps: list, stop):
    while not stop.is_set():
        try:
            for st in steps:
                if st[0] == "zero":
                    cur = m.rd(st[1], st[2])
                    if any(cur):
                        m.poke(st[1], bytes(st[2]), cur)
                elif st[0] == "hold":
                    m.poke(st[1], bytes.fromhex(st[2]))
                elif st[0] == "tick":
                    st[1](m, True)
        except Exception:
            return                                   # session ended
        stop.wait(0.05)


def _flush_code_cache(ad, slot: int = 8):
    """Save state + reload it. RetroArch saves asynchronously, so wait for the slot file to be written completely
    (reloading early would bring back an older state)."""
    from pathlib import Path
    t0 = time.time()
    ad.save_state(slot)
    rt = getattr(getattr(ad, "config", None), "runtime", None)
    if rt is None:
        time.sleep(5)
    else:
        last, end = None, t0 + 20
        while time.time() < end:
            fs = [f for f in (Path(rt) / "states").glob(f"*.state{slot}*") if f.stat().st_mtime >= t0 - 0.5]
            size = max(fs, key=lambda f: f.stat().st_mtime).stat().st_size if fs else None
            if size and size == last:
                break
            last = size
            time.sleep(0.5)
        else:
            raise RuntimeError("the save state used to apply the code patch never finished writing; not reloading")
    ad.load_state(slot)


def _noclip(m: "Mem", ad, g: dict, on: bool) -> dict:
    import threading
    steps = g.get("noclip")
    if not steps:
        raise ValueError(f"no noclip for {g['name']} yet")
    out, key = {"noclip": on}, id(ad)
    old = HOLDS.pop(key, None)
    if old:
        old[0].set()
        old[1].join(timeout=3)                       # let a running pass finish before writing the "off" values
    held = [s for s in steps if s[0] in ("zero", "hold", "tick")]
    for st in steps:
        if st[0] == "scan":
            _, lo, hi, orig, new = st
            blk = m.rd(lo, hi - lo)
            hits = [lo + i for i in range(0, len(blk) - 3, 4) if blk[i:i + 4].hex() in (orig, new)]
            if not hits:
                raise RuntimeError(f"code pattern {orig} not found in {lo:#x}-{hi:#x}: other game revision? not patching")
            for a in hits:
                m.wr(a, bytes.fromhex(new if on else orig))
            out.setdefault("patched_at", []).extend(hex(a) for a in hits)
        if st[0] == "hold" and not on and len(st) > 3:
            m.wr(st[1], bytes.fromhex(st[3]))
        if st[0] == "tick" and not on:
            st[1](m, False)
        if st[0] == "patch":
            _, a, orig, new = st
            cur = m.rd(a, len(bytes.fromhex(orig))).hex()
            want, other = (new, orig) if on else (orig, new)
            if cur not in (want, other):
                raise RuntimeError(f"unexpected code at {a:#x} ({cur}): other game revision? not patching")
            m.wr(a, bytes.fromhex(want))
        elif st[0] == "emu":
            entries = getattr(ad, "cheats", None) or []
            idx = next((i for i, e in enumerate(entries) if (e.get("code") or "").upper() == st[1].upper()), None)
            if idx is None or not hasattr(ad, "cheat_set"):
                raise RuntimeError(f"the emulator's cheat list for this ROM has no '{st[1]}' entry (different ROM dump?)")
            ad.cheat_set(idx, on)
            out.setdefault("emulator_cheats", []).append({"index": idx, "code": st[1], "enabled": on})
    if g.get("jit_flush") and any(st[0] in ("patch", "scan") for st in steps):
        # recompiling cores (N64 dynarec) keep running the old code until their block cache is dropped: a save state +
        # immediate reload does that (verified live: OoT walls stayed solid until the reload)
        _flush_code_cache(ad)
        out["code_cache_flushed"] = True
    if held and on:
        stop = threading.Event()
        th = threading.Thread(target=_hold_loop, args=(m, held, stop), daemon=True)
        HOLDS[key] = (stop, th)
        th.start()
        out["held"] = True
    if not on and any(s[0] == "zero" for s in steps):
        out["note"] = "walls come back on the next screen/room load"
    out["note"] = out.get("note") or g.get("noclip_note", "")
    return out


# --- ops ----------------------------------------------------------------------------------------------------------------------

def _ready(m: Mem, g: dict):
    a, ok = g.get("ready", (None, ()))
    v = m.u8(a) if a is not None else None
    if a is not None and v not in ok:
        raise RuntimeError(f"{g['name']}: not in gameplay yet (state byte {hex(a)} = {v:#x}); load a save file and get Link "
                           "on screen first")
    if g.get("ready_fn"):
        g["ready_fn"](m, g)
    return True


def _listing(m, g):
    have = sorted(n for n, sp in g["items"].items() if not (sp.get("dx") and m.platform != "gbc") and _have(m, g, sp))
    out = {"game": g["name"], "items": have}
    btn = {}
    for b, (kind, a) in g["equip"].items():
        if kind == "slotidx":
            slot = m.u8(a[0])
            names = [n for n, sp in g["items"].items() if sp.get("slot") == slot and _have(m, g, sp)]
            btn[b] = names[0] if names else None
            continue
        v = m.u8(g["cbtn"] + a) if kind == "oot_c" else m.u8(a)
        if kind == "menu":
            names = [n for n, sp in g["items"].items() if sp.get("menu") == v and _have(m, g, sp)]
            btn[b] = names[0] if names else (None if not v else f"menu#{v}")
        else:
            names = [n for n, sp in g["items"].items() if sp["k"] in ("slot", "inv2", "set", "fn") and sp.get("v") == v
                     and (kind != "oot_c" or sp.get("c"))]
            if kind == "oot_b":
                names = [n for n, sp in g["items"].items() if sp.get("bitem") == v]
            btn[b] = (names[0] if names else hex(v)) if v not in (0, 0xFF) else None
    out["buttons"] = btn
    if "hearts" in g:
        out.update(_hearts(m, g, None))
    if "rupees" in g:
        out.update(_rupees(m, g, None))
    return out


def run(ad, title: str, platform: str, op: str = "list", item: str = "", count: int = 0, button: str = "",
        on: bool = True) -> dict:
    """Engine entry (also used by tests through a shim adapter)."""
    op = norm(op).replace(" ", "_") or "list"
    op = {"any_age": "unrestrict", "any_form": "unrestrict", "allow": "unrestrict", "use_anything": "unrestrict",
          "all": "all_items", "everything": "all_items", "give_all": "all_items", "inventory": "list", "state": "list",
          "take": "remove", "money": "rupees", "health": "hearts", "full": "max", "walk_through_walls": "noclip",
          "no_clip": "noclip", "ghost": "noclip"}.get(op, op)
    if op == "games":
        return {"games": {k: {"name": g["name"], "platforms": g["platforms"]} for k, g in GAMES.items()}}
    key, g = detect(title, platform)
    if g.get("delegate"):
        return g["delegate"](ad, g, op, item, count, button)
    m = Mem(ad, platform)
    m.base = g.get("base", 0)
    _ready(m, g)
    res = {"game": g["name"], "op": op}
    # 'give me hearts / rupees / everything' through give
    if op in ("give", "equip") and item:
        n = norm(item)
        if COMMON.get(n) in ("hearts", "rupees") or n in ("hearts", "rupees"):
            op = COMMON.get(n, n)
        elif n in ("everything", "all items", "all", "every item", "all the items", "full inventory"):
            op = "all_items"
    if op == "list":
        return {**res, **_listing(m, g)}
    if op == "noclip":
        res.update(_noclip(m, ad, g, on))
    if op == "give":
        name = resolve(g, item)
        _give(m, g, g["items"][name], int(count or 0), name)
        res.update(item=name, have=_have(m, g, g["items"][name]))
        if g.get("hud_refresh"):
            m.poke(g["hud_refresh"][0], bytes([m.u8(g["hud_refresh"][0]) | g["hud_refresh"][1]]))
    elif op == "equip":
        name = resolve(g, item)
        sp = g["items"][name]
        if not _have(m, g, sp):
            _give(m, g, sp, 0, name)
        if not g["equip"]:
            res.update(item=name, note=g.get("equip_note", "this game has no item buttons"))
            res["changes"], res["verified"] = m.changes(), m.verify()
            return res
        b = _button(g, button)
        if _equip(m, g, name, sp, b) == "worn":
            b = "worn"
        if sp.get("gear") or sp["k"] == "nib":
            b = "b" if sp.get("bitem") else "worn"
        res.update(item=name, button=b)
        if g.get("c_note") and b.startswith("c-"):
            res["note"] = g["c_note"]
        if g.get("refresh") and m.verify():
            res["hud_refreshed"] = _refresh_inputs(ad, g, m)
            if not res["hud_refreshed"]:
                res["note"] = "equipped; the HUD box redraws the next time the item menu opens/closes"
    elif op == "remove":
        name = resolve(g, item)
        _remove(m, g, g["items"][name])
        res.update(item=name, have=_have(m, g, g["items"][name]))
    elif op == "all_items":
        for w in g.get("max_writes", []):                  # capacities first: the game clamps counts to them
            _give(m, g, w)
        for name in g["all"]:
            sp = g["items"][name]
            if sp.get("dx") and platform != "gbc":
                continue
            _give(m, g, sp, g.get("max_counts", {}).get(name, 0), name)
        for w in g.get("max_writes", []):
            _give(m, g, w)
        if g.get("hud_refresh"):
            m.poke(g["hud_refresh"][0], bytes([m.u8(g["hud_refresh"][0]) | g["hud_refresh"][1]]))
        res["given"] = len(g["all"])
    elif op == "unrestrict":
        u = g.get("unrestrict") or {}
        if u.get("fn"):
            res.update(u["fn"](m, g, count))
        for name in u.get("give", []):
            _give(m, g, g["items"][name], 0, name)
        for w in u.get("writes", []):
            _give(m, g, w)
        res["note"] = u.get("note") or res.get("note") or "no restrictions to lift in this game"
    elif op == "hearts":
        res.update(_hearts(m, g, count or g["hearts"]["cap"]))
    elif op == "rupees":
        if "rupees" not in g:
            raise ValueError(f"{g['name']} has no rupees")
        res.update(_rupees(m, g, count or g["rupees"]["cap"]))
    elif op == "max":
        for w in g.get("max_writes", []):
            _give(m, g, w)
        res.update(_hearts(m, g, g["hearts"]["cap"]))
        if "rupees" in g:
            res.update(_rupees(m, g, g["rupees"]["cap"]))
        for name, n in g.get("max_counts", {}).items():
            if name in g["items"] and _have(m, g, g["items"][name]):
                _give(m, g, g["items"][name], n, name)
        for w in g.get("max_writes", []):
            _give(m, g, w)
    elif op != "noclip":
        raise ValueError("op: games | list | give | equip | remove | all_items | unrestrict | hearts | rupees | max | noclip")
    if g.get("hud_refresh") and m.log:
        m.poke(g["hud_refresh"][0], bytes([m.u8(g["hud_refresh"][0]) | g["hud_refresh"][1]]))
    res["changes"] = m.changes()
    res["verified"] = m.verify()
    return res


# --- gBox tool ------------------------------------------------------------------------------------------------------------------

class ZeldaIn(BaseModel):
    session_id: str
    op: str = "list"           # games | list | give | equip | remove | all_items | unrestrict | hearts | rupees | max | noclip
    item: str = ""             # by name: "hookshot", "hook shot", "master sword", "bombs", "bottle", "fire arrows"...
    count: int = 0             # give: ammo/amount; hearts: how many; rupees: how many
    button: str = ""           # equip: b | a | y | x | c-left | c-down | c-right (default: the game's main item button)
    on: bool = True            # noclip: true = walk through walls/doors, false = normal collision


class ZeldaOut(BaseModel):
    result: dict


@tool("zelda", "1.0", ZeldaIn, ZeldaOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=120)
def zelda(inp: ZeldaIn, ctx):
    """Zelda (every game, any system): give items by name, put an item on a button, give everything, lift item
    restrictions (OoT any age / MM any form), set hearts/rupees, list what Link has. Verified by read-back."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    return {"result": run(ad, g.get("title", ""), g.get("platform", ""), inp.op, inp.item, inp.count, inp.button, inp.on)}


# OoT / MM live in zelda_n64.py (registered into GAMES / FN on import)
from . import zelda_n64  # noqa: E402

FN.update(zelda_n64.FNS)
