"""`re_mods`: Resident Evil live mods, verified in the running game. Register with:  from . import re_mods_tool  # noqa: F401

Resident Evil 4 (GameCube NTSC-U, G4BE08) ops:
  status                         what is on, current room, money, HP, Mercenaries timer/combo, cave/hook state
  list                           the attache case (item ids, names, counts, loaded ammo)
  give item=<name|0xID> count=N  the game's own take-item routine: creates the item and auto-places it in the case
  replace target=<name|0xID|slot> item=<name|0xID>  remove that item, put the new one in its place (game placement;
                                 the old item is restored if the new one does not fit)
  mercenaries_unlock on=..       The Mercenaries + Assignment Ada + all 5 Merc characters + all 4 stages (title menu
                                 is built from these flags: they show the next time the title screen opens)
  infinite_ammo / combo_freeze / merc_timer_freeze / unlimited_health  on=true|false  (code patches, original bytes
                                 checked first, restored on off)
  merc_time seconds=N            set the Mercenaries clock
  equip item=<weapon>            give it if missing, then the game's weapon-change path (model + code reload)
  weapon_mod item=<weapon> fire_rate=<frames|auto> damage=<x> reset=..   per-class fire interval / firepower tables
  merc_loadout character=<name|any> items=[...] on=<replace default guns>  applied at the start of each Merc run
                                 (items "name:amount", e.g. "handgun ammo:200"); merc_loadout_list shows the records
  combo_time multiplier=N        Mercenaries combo window x N (300 frames = 10 s; 'triple the combo time' = 3)
  grenade_safe on=..             the hand grenade's blast is owned by the player: hurts enemies, never you
  punch                          why RE4 has no punch (context melee only) and what to use instead
  item_ids / addresses           the item id table / this release's address table (source, live_checked)
  spawn_multiplier count=2..8 on=..   every spawned enemy gets count-1 clones (Mercenaries and story rooms)
  flashbang / grenade target=player|aim   the game's own flash/hand-grenade detonation at the player or the last hit point
  flashbang_loop seconds=3 on=.. item=flash|grenade   one goes off at the player's feet every N seconds
  explosive_rounds items=[guns] on=..  every bullet impact of those guns also explodes (pistol -> rocket-like)
  warp target=r102 [items=[x,y,z]]    load any room (r1xx village, r2xx castle, r3xx island = disc 2, r4xx Merc/Ada)
  teleport items=[x,y,z]              move the player inside the current room
Data, addresses and evidence: gbox/re_games.py. Game routines run on the game thread through a small per-frame PPC
dispatcher (same idea as pso_mods_tool): code at 0x80002A00, the main loop's call to an empty function at 0x80122610
is pointed at it; requests go into a 5-entry queue {fn, r3..r10, f1, f2, result} and are run once at the end of the
next frame.
"""
import struct
import time

from pydantic import BaseModel

from . import re_games as R
from .models import Permission as P
from .registry import Unsupported, tool

DISPATCHER = bytes.fromhex(
    "9421ffa07c0802a690010064bf4100403fe0800063ff2e003bc00005819f00002c0c000041820040807f0004809f000880bf000c80df0010"
    "80ff0014811f0018813f001c815f0020c03f0024c05f00287d8903a64e800421907f002c38000000901f00003bff00303bdeffff2c1e0000"
    "4082ffac3fe0800063ff2f003bc00008819f00002c0c00004182000c7d8903a64e8004213bff00043bdeffff2c1e00004082ffe0bb410040"
    "800100647c0803a6382100604e800020")


def _bl(src: int, dst: int) -> bytes:
    return struct.pack(">I", (18 << 26) | ((dst - src) & 0x3FFFFFC) | 1)


class Mem:
    """Session memory with retries: Dolphin's GDB stub refuses (E00) an access that lands while the CPU is in an
    exception handler (address translation off); a moment later it works."""

    def __init__(self, ad):
        self.ad = ad

    def _retry(self, fn, *a):
        last = None
        for i in range(8):
            try:
                return fn(*a)
            except Exception as e:                       # noqa: BLE001 - stub hiccup, retried
                last = e
                time.sleep(0.05 * (i + 1))
        raise last

    def rd(self, a: int, n: int) -> bytes:
        return bytes(self._retry(self.ad.read_memory, a, n))

    def wr(self, a: int, data: bytes):
        self._retry(self.ad.write_memory, a, data)

    def u32(self, a):
        return struct.unpack(">I", self.rd(a, 4))[0]

    def u16(self, a):
        return struct.unpack(">H", self.rd(a, 2))[0]


class RE4:
    def __init__(self, ad):
        self.m = Mem(ad)
        self.V = R.GC
        try:
            gid = self.m.rd(0x80000000, 6)
        except Exception as e:                           # noqa: BLE001
            raise Unsupported("RE4 mods need game-memory access, which this session's emulator does not give gBox "
                              "(RetroArch's Dolphin core exposes no memory to RetroArch network commands). Relaunch "
                              f"the game on the Spark (Dolphin) to use RE4 mods. [{type(e).__name__}: {e}]") from e
        if gid not in R.VERSIONS:
            raise Unsupported(f"re_mods: Resident Evil 4 GameCube NTSC-U (G4BE08) or Wii PAL (RB4P08) so far; this disc "
                              f"is {gid!r}")
        self.V = R.VERSIONS[gid]

    # ---- dispatcher ------------------------------------------------------------------------------------------
    def hooked(self) -> bool:
        return self.m.rd(self.V.HOOK_SITE, 4) == _bl(self.V.HOOK_SITE, self.V.CAVE) and self.m.rd(self.V.CAVE, len(DISPATCHER)) == DISPATCHER  # 184 bytes: 0x80002A00-0x80002AB8

    def hook(self):
        if self.hooked():
            return
        cave = self.m.rd(self.V.CAVE, self.V.CAVE_END - self.V.CAVE)
        mine = cave[:len(DISPATCHER)] == DISPATCHER
        if not mine and any(cave):
            raise RuntimeError("the code-cave region 0x80002A00-0x80003000 is in use (Dolphin Gecko code handler?); "
                               "disable Gecko codes for this game and restart it")
        site = self.m.rd(self.V.HOOK_SITE, 4)
        if site not in (_bl(self.V.HOOK_SITE, self.V.HOOK_ORIG_TARGET), _bl(self.V.HOOK_SITE, self.V.CAVE)):
            raise RuntimeError(f"unexpected code at the hook site 0x{self.V.HOOK_SITE:08X}: {site.hex()}")
        if not mine:
            self.m.wr(self.V.QUEUE, bytes(self.V.QN * self.V.QSZ))
            self.m.wr(self.V.HOOKS, bytes(4 * self.V.HN))
            self.m.wr(self.V.CAVE, DISPATCHER)
        self.m.wr(self.V.HOOK_SITE, _bl(self.V.HOOK_SITE, self.V.CAVE))

    def in_room(self) -> bool | None:
        """GameCube: the game runs a room (pG+0x20 = 3) with Leon in it. None where it can't be told (Wii)."""
        if self.V is not R.GC:
            return None
        pg = self.pg()
        if not 0x80000000 <= pg < 0x81800000:
            return False
        return self.m.rd(pg + 0x20, 1)[0] == 3 and 0x80000000 <= self.m.u32(R.P_PLAYER) < 0x81800000

    def call(self, fn: int, *args: int, timeout: float = 6.0) -> int:
        """Run fn(r3..) on the game thread at the end of the next frame; returns r3. GameCube: only while a room runs.
        The dispatcher sits in the main loop, which runs every frame, room loads included, so a call queued then
        would run on a player and an attache case still being rebuilt (2026-10-20: RE4 froze in a room load,
        pG+0x20 = 2 with MEM1 static, right after `equip` was applied to the session)."""
        if self.in_room() is False:
            raise RuntimeError("the game is loading a room or showing a menu; this needs Leon in a running room "
                               "(try again in play)")
        self.hook()
        q = None
        for k in range(self.V.QN):
            a = self.V.QUEUE + k * self.V.QSZ
            if self.m.u32(a) == 0:
                q = a
                break
        if q is None:
            raise RuntimeError("dispatcher queue full (is the game paused or frozen?)")
        regs = list(args) + [0] * (8 - len(args))
        self.m.wr(q + 4, struct.pack(">8I", *[r & 0xFFFFFFFF for r in regs]) + bytes(12))
        self.m.wr(q, struct.pack(">I", fn))
        t = time.time()
        while self.m.u32(q) != 0:
            if time.time() - t > timeout:
                self.m.wr(q, bytes(4))
                raise RuntimeError("the game did not run the request (paused, loading or in a menu?) - try again in play")
            time.sleep(0.05)
        return self.m.u32(q + 44)

    # ---- state -------------------------------------------------------------------------------------------------
    def pg(self):
        return self.m.u32(self.V.P_GLOBAL)

    def items(self) -> list[dict]:
        arr, n = self.m.u32(self.V.ITEM_MGR + 0x14), self.m.u32(self.V.ITEM_MGR + 0x1C)
        if not (0x80000000 <= arr < 0x81800000) or not 0 < n <= 512:
            return []
        d = self.m.rd(arr, n * 14)
        out = []
        for k in range(n):
            e = d[k * 14:k * 14 + 14]
            if e[4] & 1:
                iid, cnt = struct.unpack_from(">HH", e)
                out.append({"slot": k, "addr": arr + k * 14, "id": iid, "name": R.item_name(iid), "count": cnt,
                            "loaded": struct.unpack_from(">H", e, 8)[0] & 0x1FFF, "in_case": bool(e[13]),
                            "x": e[10], "y": e[11], "raw": e.hex()})
        return out

    def patch_state(self, name):
        a, orig, new, _ = self.V.PATCHES[name]
        cur = self.m.rd(a, 4).hex()
        return "on" if cur == new else "off" if cur == orig else f"unknown ({cur})"

    def patch(self, name, on: bool) -> dict:
        a, orig, new, what = self.V.PATCHES[name]
        cur = self.m.rd(a, 4).hex()
        if cur not in (orig, new):
            raise RuntimeError(f"{name}: unexpected code at 0x{a:08X} ({cur}); not patching")
        self.m.wr(a, bytes.fromhex(new if on else orig))
        after = self.m.rd(a, 4).hex()
        return {name: "on" if on else "off", "address": f"0x{a:08X}", "before": cur, "after": after,
                "verified": after == (new if on else orig), "effect": what}

    def room(self) -> int:
        return self.m.u16(self.pg() + self.V.G_ROOM)

    def extras_addr(self) -> int:
        return self.m.u32(self.V.P_SYS) + self.V.EXTRAS_OFF          # pSys + 4: the unlock bits

    def status(self) -> dict:
        V = self.V
        pg = self.pg()
        room = self.m.u16(pg + V.G_ROOM)
        st = {"game": V.name, "room": f"r{room:03x}", "money": self.m.u32(pg + V.G_MONEY),
              "hp": struct.unpack(">h", self.m.rd(pg + V.G_HP, 2))[0],
              "unlock_flags": self.m.rd(self.extras_addr(), 4).hex(), "hooked": V.has("HOOK_SITE") and self.hooked(),
              **{k: self.patch_state(k) for k in V.PATCHES}}
        a, word, base = V.TIME_BONUS_MUL
        st["merc_time_bonus_x"] = round((self.m.u32(a) & 0xFFFF) / base, 2)
        if V.has("P_PLAYER"):
            pl = self.m.u32(V.P_PLAYER)
            if 0x80000000 <= pl < 0x81800000:
                st["player_pos"] = [round(v) for v in struct.unpack(">3f", self.m.rd(pl + 0x94, 12))]
        if V.has("COMBO_WINDOW"):
            st["merc_combo_window_x"] = round(self.m.u32(V.COMBO_WINDOW[0]) / V.COMBO_WINDOW[1], 2)
        if V.has("GRENADE_SAFE"):
            st["grenade_safe"] = grenade_safe_state(self)
        if room >> 8 == 4:
            st["merc_seconds_left"] = round(self.m.u32(V.MERC_TIMER) / V.FPS, 2)
            if V.has("MERC"):
                st["merc_combo"] = self.m.u32(V.MERC + 0x28)
        return st



# ---- weapons --------------------------------------------------------------------------------------------------------
def weapon_classes(g: "RE4") -> dict:
    """item id -> (class, variant) from the game's own weapon table."""
    d = g.m.rd(g.V.WEAPON_TBL, g.V.WEAPON_N * g.V.WEAPON_SZ)
    out = {}
    for k in range(g.V.WEAPON_N):
        e = d[k * g.V.WEAPON_SZ:(k + 1) * g.V.WEAPON_SZ]
        iid = struct.unpack_from(">H", e)[0]
        if iid < 0x100:
            out.setdefault(iid, (e[3], e[4]))
    return out


def install_weapon_code(g: "RE4"):
    """equip_now + pending-equip hook + Merc loadout wrapper + the effect-loop guard (all in the cave)."""
    g.hook()
    for a, code in ((g.V.EQUIP_NOW, g.V.EQUIP_NOW_CODE), (g.V.PEND_HOOK, g.V.PEND_HOOK_CODE), (g.V.LOAD_WRAP, g.V.LOAD_WRAP_CODE),
                    (g.V.GUARD_STUB, g.V.GUARD_CODE)):
        if g.m.rd(a, len(code)) != code:
            g.m.wr(a, code)
    if g.m.rd(g.V.RECS, 6) == bytes(6):
        g.m.wr(g.V.RECS, b"\xfe" + bytes(5))                       # empty record list
    if g.m.rd(g.V.HOOKS, 4) != struct.pack(">I", g.V.PEND_HOOK):
        g.m.wr(g.V.HOOKS, struct.pack(">I", g.V.PEND_HOOK))
    site = g.m.rd(g.V.GUARD_SITE, 4)
    if site not in (g.V.GUARD_ORIG, g.V.GUARD_BRANCH):
        raise RuntimeError(f"unexpected code at 0x{g.V.GUARD_SITE:08X}: {site.hex()}")
    g.m.wr(g.V.GUARD_SITE, g.V.GUARD_BRANCH)
    site = g.m.rd(g.V.LOAD_SITE, 4)
    if site not in (_bl(g.V.LOAD_SITE, g.V.LOAD_FN), _bl(g.V.LOAD_SITE, g.V.LOAD_WRAP)):
        raise RuntimeError(f"unexpected code at 0x{g.V.LOAD_SITE:08X}: {site.hex()}")
    g.m.wr(g.V.LOAD_SITE, _bl(g.V.LOAD_SITE, g.V.LOAD_WRAP))


def read_recs(g) -> list:
    d = g.m.rd(g.V.RECS, g.V.RECS_END - g.V.RECS)
    out = []
    for k in range(0, len(d) - 5, 6):
        if d[k] == 0xFE:
            break
        out.append(struct.unpack_from(">BBHH", d, k))
    return out


def write_recs(g, recs: list):
    if (len(recs) + 1) * 6 > g.V.RECS_END - g.V.RECS:
        raise ValueError(f"too many loadout entries ({len(recs)}); max {(g.V.RECS_END - g.V.RECS) // 6 - 1}")
    g.m.wr(g.V.RECS, b"".join(struct.pack(">BBHH", *r) for r in recs) + b"\xfe" + bytes(5))


def equip_item(g, iid: int) -> dict:
    wc = weapon_classes(g)
    if iid not in wc:
        raise ValueError(f"{R.item_name(iid)} is not a weapon the player can hold (not in the weapon table)")
    install_weapon_code(g)
    it = next((x for x in g.items() if x["id"] == iid), None)
    given = False
    if not it:
        if not g.call(g.V.F_TAKE_ITEM, iid, 0, 0):
            raise RuntimeError(f"no room in the attache case for {R.item_name(iid)}")
        given = True
        it = next((x for x in g.items() if x["id"] == iid), None)
    g.call(g.V.EQUIP_NOW, it["addr"])
    time.sleep(0.3)
    cls = g.m.rd(g.pg() + 0x4FBC, 1)[0]
    held = g.m.u16(g.V.ITEM_MGR + 0x10)
    return {"equipped": R.item_name(iid), "given": given, "weapon_class": f"0x{cls:02X}",
            "verified": held == iid and cls == wc[iid][0]}


def weapon_mod(g, iid: int, fire_rate=None, damage=None, reset=False) -> dict:
    wc = weapon_classes(g)
    if iid not in wc:
        raise ValueError(f"{R.item_name(iid)} is not a weapon")
    c = wc[iid][0]
    fr_a, fp_a = g.V.FIRE_RATE_TBL + c * 0x14, g.V.FIREPOWER_TBL + c * 0x1C
    fr_o = g.V.FIRE_RATE_ORIG[c * 0x14:(c + 1) * 0x14]
    fp_o = g.V.FIREPOWER_ORIG[c * 0x1C:(c + 1) * 0x1C]
    if reset:
        g.m.wr(fr_a, fr_o)
        g.m.wr(fp_a, fp_o)
    want_fr = None
    if fire_rate not in (None, ""):
        want_fr = 3.0 if str(fire_rate).lower() in ("auto", "machine gun", "machinegun", "tmp", "full auto") else float(fire_rate)
        want_fr = max(1.0, want_fr)
        g.m.wr(fr_a, struct.pack(">5f", *[want_fr] * 5))
    if damage not in (None, ""):
        orig = struct.unpack(">7f", fp_o)
        g.m.wr(fp_a, struct.pack(">7f", *[v * float(damage) for v in orig]))
    if g.V.has("HOOK_SITE"):
        install_weapon_code(g)                                   # the effect-loop guard keeps fast fire from freezing
    rate = struct.unpack(">5f", g.m.rd(fr_a, 20))
    power = struct.unpack(">7f", g.m.rd(fp_a, 28))
    ok = (want_fr is None or all(abs(x - want_fr) < 1e-3 for x in rate)) and \
         (damage in (None, "") or abs(power[0] - struct.unpack(">f", fp_o[:4])[0] * float(damage)) < 1e-2)
    return {"weapon": R.item_name(iid), "class": f"0x{c:02X}", "fire_interval_frames": [round(x, 2) for x in rate],
            "firepower_by_level": [round(x, 2) for x in power], "verified": ok,
            "note": "rows are per weapon class (all variants of that gun share them); 30 frames = 1 s. "
                    "The recoil animation itself is unchanged (it restarts every shot)."}


def spawn_multiplier(g, factor: int, on: bool = True, spread: int = 30) -> dict:
    factor = max(1, min(8, int(factor or 1)))
    if not on:
        factor = 1
    g.hook()
    code = g.V.SPAWN_HOOK_CODE
    cur = g.m.rd(g.V.SPAWN_HOOK, len(code))
    if cur != code:
        if any(cur) or any(g.m.rd(g.V.SPAWN_DONE, 32)):
            raise RuntimeError("0x80002800-0x800029E0 is in use (Dolphin Gecko code handler?); not installing")
        g.m.wr(g.V.SPAWN_DONE, bytes(32))
        g.m.wr(g.V.SPAWN_HOOK, code)
    site = g.m.rd(g.V.SPAWN_DUP_SITE, 4)
    if site not in (g.V.SPAWN_DUP_ORIG, g.V.SPAWN_DUP_PATCH):
        raise RuntimeError(f"unexpected code at 0x{g.V.SPAWN_DUP_SITE:08X}: {site.hex()}")
    g.m.wr(g.V.SPAWN_VARS, bytes([factor if factor > 1 else 0, max(1, min(120, int(spread)))]))
    g.m.wr(g.V.SPAWN_DUP_SITE, g.V.SPAWN_DUP_PATCH if factor > 1 else g.V.SPAWN_DUP_ORIG)
    if g.m.rd(g.V.HOOKS + 4, 4) != struct.pack(">I", g.V.SPAWN_HOOK):
        g.m.wr(g.V.HOOKS + 4, struct.pack(">I", g.V.SPAWN_HOOK))
    if factor > 1:
        g.m.wr(g.V.SPAWN_DONE, bytes(32))                         # clone what is already out, too
    time.sleep(1.5)
    base, n, stride = g.m.u32(0x8027DF20), g.m.u32(0x8027DF24), g.m.u32(0x8027DF28)
    alive = 0
    if 0x80000000 <= base < 0x81800000 and 0 < n <= 128:
        d = g.m.rd(base, n * stride)
        alive = sum(1 for k in range(1, n) if struct.unpack_from(">I", d, k * stride)[0] & 0x601
                    and d[k * stride + 0x398] != 0xFF)
    v = g.m.rd(g.V.SPAWN_VARS, 2)
    return {"factor": factor, "enemies_alive": alive, "verified": (v[0] or 1) == factor and
            g.m.rd(g.V.SPAWN_DUP_SITE, 4) == (g.V.SPAWN_DUP_PATCH if factor > 1 else g.V.SPAWN_DUP_ORIG),
            "note": "every enemy the room/Mercenaries spawns gets factor-1 extra copies next to it (clones of the same "
                    "enemy-set entry); limited by the game's 80 enemy slots"}


def install_blasts(g):
    g.hook()
    for a, code in ((g.V.GRENADE_AT, g.V.GRENADE_AT_CODE), (g.V.FLASH_AT, g.V.FLASH_AT_CODE), (g.V.PERIODIC, g.V.PERIODIC_CODE),
                    (g.V.IMPACT_WRAP, g.V.IMPACT_WRAP_CODE)):
        cur = g.m.rd(a, len(code))
        if cur != code:
            if any(cur):
                raise RuntimeError(f"0x{a:08X} is in use (Dolphin Gecko code handler?); not installing")
            g.m.wr(a, code)
    if g.m.rd(g.V.HOOKS + 8, 4) != struct.pack(">I", g.V.PERIODIC):
        g.m.wr(g.V.PVARS, bytes(8))
        g.m.wr(g.V.HOOKS + 8, struct.pack(">I", g.V.PERIODIC))


def blast(g, kind: str, at: str = "player") -> dict:
    install_blasts(g)
    pg = g.pg()
    if at in ("aim", "hit", "target", "last_hit"):
        pos = g.m.rd(pg + g.V.LAST_HIT, 12)
    else:
        pl = g.m.u32(g.V.P_PLAYER)
        if not 0x80000000 <= pl < 0x81800000:
            raise RuntimeError("no player in play")
        pos = g.m.rd(pl + 0x94, 12)
    g.m.wr(g.V.BLAST_POS, pos)
    fn = g.V.FLASH_AT if kind.startswith("flash") else g.V.GRENADE_AT
    ok = g.call(fn, g.V.BLAST_POS)
    return {"blast": "flashbang" if fn == g.V.FLASH_AT else "grenade", "at": [round(v, 1) for v in struct.unpack(">3f", pos)],
            "verified": ok == 1}


def blast_loop(g, kind: str, seconds: float, on: bool) -> dict:
    install_blasts(g)
    fn = g.V.FLASH_AT if kind.startswith("flash") else g.V.GRENADE_AT
    frames = max(10, int(round((seconds or 3) * 30))) if on else 0
    g.m.wr(g.V.PVARS, struct.pack(">HHI", frames, 0, fn))
    v = struct.unpack(">HHI", g.m.rd(g.V.PVARS, 8))
    return {"loop": "flashbang" if fn == g.V.FLASH_AT else "grenade", "every_seconds": round(frames / 30, 2) if frames else None,
            "on": bool(frames), "verified": v[0] == frames and v[2] == fn,
            "note": "goes off at the player's feet while in play (unlimited_health keeps the player alive for grenades)"}


def explosive_rounds(g, iids: list, on: bool) -> dict:
    install_blasts(g)
    wc = weapon_classes(g)
    mask = struct.unpack(">I", g.m.rd(g.V.BOOM_MASK, 4))[0]
    classes = sorted({wc[i][0] for i in iids if i in wc})
    for c in classes:
        mask = (mask | (1 << c)) if on else (mask & ~(1 << c))
    g.m.wr(g.V.BOOM_MASK, struct.pack(">I", mask))
    site = g.m.rd(g.V.IMPACT_SITE, 4)
    if site not in (g.V.IMPACT_ORIG, g.V.IMPACT_BRANCH):
        raise RuntimeError(f"unexpected code at 0x{g.V.IMPACT_SITE:08X}: {site.hex()}")
    g.m.wr(g.V.IMPACT_SITE, g.V.IMPACT_BRANCH if mask else g.V.IMPACT_ORIG)
    return {"explosive_rounds": [R.item_name(i) for i in iids], "classes": [f"0x{c:02X}" for c in classes], "on": on,
            "mask": f"0x{mask:08X}", "verified": struct.unpack(">I", g.m.rd(g.V.BOOM_MASK, 4))[0] == mask,
            "note": "every bullet impact of these guns also detonates a hand-grenade blast at the hit point"}


def unlock_all(g, on: bool = True, everything: bool = True) -> dict:
    """pSys+4 (u32, saved with the system data): byte 0 = every extra game (The Mercenaries, Assignment Ada, Separate
    Ways on Wii, movie browser) + the 4 extra Merc characters + all 4 Merc stages; the other bytes = Professional etc.
    RE4 Mercenaries has no costume choice (each Merc character has one outfit) and no weapon unlocks (fixed loadouts:
    merc_loadout changes them)."""
    a = g.extras_addr()
    before = g.m.rd(a, 4)
    want = (b"\xff\xff\xff\xff" if everything else b"\xff" + before[1:]) if on else bytes(4)
    g.m.wr(a, want)
    after = g.m.rd(a, 4)
    wii = g.V.name.startswith("Resident Evil 4: Wii")
    return {"before": before.hex(), "after": after.hex(), "verified": after == want, "address": f"0x{a:08X}",
            "unlocked": {"characters": ["Leon", "Ada", "HUNK", "Krauser", "Wesker"],
                         "stages": ["Village", "Castle", "Island", "Waterworld"],
                         "modes": ["The Mercenaries", "Assignment Ada"] + (["Separate Ways", "Movie Browser"] if wii else [])
                         + (["Professional difficulty"] if everything else []),
                         "costumes": "n/a: Mercenaries characters have one outfit each",
                         "weapons": "n/a: Mercenaries loadouts are fixed per character (merc_loadout changes them)"},
            "flags_this_release": R.UNLOCK_SCOPE.get(_gid(g)),
            "note": "The menus are built from these flags when the title menu opens (title screen; in game: Options > "
                    "Retry or Load > Game Reset). Saved with the next system save; on=false clears them."}


def merc_time_bonus(g, mult: float, melee_only: bool = True) -> dict:
    """Every Mercenaries time pickup goes through one mulli (seconds * 30 frames): scale its immediate."""
    a, word, base = g.V.TIME_BONUS_MUL
    cur = g.m.u32(a)
    if cur & 0xFFFF0000 != word:
        raise RuntimeError(f"unexpected code at 0x{a:08X}: {cur:08x}")
    k = max(1, min(0x7FFF, int(round(base * float(mult or 1)))))
    g.m.wr(a, struct.pack(">I", word | k))
    back = g.m.u32(a) & 0xFFFF
    return {"multiplier": round(back / base, 2), "address": f"0x{a:08X}", "verified": back == k,
            "applies_to": "every Mercenaries time bonus (hourglass pickups: +N s = the hourglass's value)",
            "note": ("RE4 gives Mercenaries time only through hourglass pickups - melee kills add score/combo, never "
                     "time - so there is no melee-only bonus to scale; every time pickup is multiplied.") if melee_only
            else "every time pickup multiplied"}


def _gid(g) -> str:
    return g.V.GAME_ID.decode() if isinstance(g.V.GAME_ID, bytes) else str(g.V.GAME_ID)


def _live_note(g, keys) -> dict:
    t = R.MERC_ADDRESS_TABLE.get(_gid(g), {})
    return {k: {"address": f"0x{t[k]['address']:08X}", "source": t[k]["source"], "live_checked": t[k]["live_checked"]}
            for k in keys if k in t}


def combo_time(g, factor: float) -> dict:
    """#512 'triple / quadruple the combo time': scale the Mercenaries combo window (the frames a combo stays alive
    after each kill; 300 = 10 s). The game reloads the combo timer from this one .sdata word on every kill."""
    a, orig = g.V.COMBO_WINDOW
    f = float(factor or 1)
    if not 0.25 <= f <= 20:
        raise ValueError("combo_time factor: 0.25 .. 20 (1 = the game's 10 seconds; 3 = triple, 4 = quadruple)")
    cur = g.m.u32(a)
    if not 1 <= cur <= orig * 20:                        # ours write 0.25x..20x; anything else is not the window
        raise RuntimeError(f"unexpected value at 0x{a:08X} ({cur}): not the combo window; not writing")
    want = max(1, int(round(orig * f)))
    g.m.wr(a, struct.pack(">I", want))
    back = g.m.u32(a)
    return {"combo_window_x": round(back / orig, 2), "combo_window_seconds": round(back / g.V.FPS, 1),
            "before_seconds": round(cur / g.V.FPS, 1), "verified": back == want, **_live_note(g, ["COMBO_WINDOW"]),
            "note": "how long a Mercenaries combo stays alive after each kill (melee kills included). RE4 gives no time "
                    "on the clock for melee or combos - only hourglass pickups add time (merc_time_bonus multiplier=N "
                    "scales those). factor=1 restores the game's 10 s."}


def grenade_safe_state(g) -> str:
    st = set()
    for a, orig, new, _ in g.V.GRENADE_SAFE:
        cur = g.m.rd(a, 4).hex()
        st.add("on" if cur == new else "off" if cur == orig else "unknown")
    return st.pop() if len(st) == 1 else "mixed"


def grenade_safe(g, on: bool) -> dict:
    """#512 'grenades don't hurt me': the hand grenade's own blast is made player-owned (owner = the player em), the
    rule the game uses for 'my attack never hurts me'. Enemies take the normal damage."""
    sites = g.V.GRENADE_SAFE
    cur = [g.m.rd(a, 4).hex() for a, *_ in sites]
    bad = [f"0x{a:08X}={c}" for (a, o, n, _), c in zip(sites, cur) if c not in (o, n)]
    if bad:
        raise RuntimeError(f"grenade_safe: unexpected code at {', '.join(bad)}; not patching")
    for a, o, n, _ in sites:
        g.m.wr(a, bytes.fromhex(n if on else o))
    after = [g.m.rd(a, 4).hex() for a, *_ in sites]
    return {"grenade_safe": on, "sites": {f"0x{a:08X}": {"before": c, "after": x, "what": w}
                                          for (a, o, n, w), c, x in zip(sites, cur, after)},
            "verified": all(x == (n if on else o) for (a, o, n, _), x in zip(sites, after)),
            **_live_note(g, ["GRENADE_OWNER_A", "GRENADE_OWNER_B"]),
            "note": "your hand grenades still blow enemies up but no longer hurt you (the blast is owned by the player, "
                    "like explosive_melee's). Enemy dynamite and the incendiary grenade's fire are unchanged; "
                    "unlimited_health covers everything."}


PUNCH_STATEMENT = (
    "Resident Evil 4 has no free punch: Leon's only melee you can use at any time is the knife (GameCube: hold L, "
    "then A). "
    "Kicks, roundhouses and suplexes (and Krauser's / Wesker's / HUNK's moves) are context actions: the game shows the "
    "prompt only after an enemy staggers (a shot to the head or knee, or a flash grenade), and those moves do not go "
    "through the hit routine gBox hooks (0x80143364; checked live: a flash-stunned Ganado + KICK logged no call). So "
    "gBox cannot add a punch button. What works now: knife hits that explode (explosive_melee, player-owned, never "
    "hurts you) or launch enemies (super_melee); for more kick prompts, stagger enemies with flashbangs "
    "(flashbang_loop) or headshots.")


# ---- melee / aiming mods (GameCube) -------------------------------------------------------------------------------
BLASTS = {"grenade": (0, 0x13, 6000.0), "flash": (1, 0x17, 15000.0), "flashbang": (1, 0x17, 15000.0),
          "rocket": (2, 0x0D, 9000.0), "rpg": (2, 0x0D, 9000.0)}


def install_melee(g):
    """Player-owned blasts + the melee impact wrapper + launch/spin hooks in the cave (idempotent)."""
    V = g.V
    g.hook()
    install_blasts(g)
    for name, (a, code) in V.MELEE_CODE.items():
        cur = g.m.rd(a, len(code))
        if cur != code:
            if any(cur) and name != "OWNED_GRENADE":
                pass                                             # an older build of ours: overwritten below
            g.m.wr(a, code)
    if g.m.rd(V.MELEE_VARS + 0x20, 4) != struct.pack(">f", 3.1415927410125732):   # first install: defaults
        v = bytearray(0x40)
        v[4:8] = bytes([0xFF, 0x13, 0, 0])
        struct.pack_into(">6f", v, 8, 6000.0, 819.0, 40.0, 11.0, 0.21, 0.0)
        v[0x1C] = 0
        struct.pack_into(">H", v, 0x1E, 0x0120)
        struct.pack_into(">4fI", v, 0x20, 3.1415927410125732, 6.2831854820251465, 1.0, 0.0, 600)
        g.m.wr(V.MELEE_VARS, bytes(v))
        g.m.wr(V.MELEE_VARS + 0x40, bytes(0x70))
    for slot, name in ((V.HOOK_SLOT_LAUNCH, "LAUNCH_HOOK"), (V.HOOK_SLOT_SPIN, "SPIN_HOOK")):
        want = struct.pack(">I", V.MELEE_CODE[name][0])
        if g.m.rd(V.HOOKS + 4 * slot, 4) != want:
            g.m.wr(V.HOOKS + 4 * slot, want)
    site = g.m.rd(V.IMPACT_SITE, 4)
    wrap = _bl(V.IMPACT_SITE, V.MELEE_CODE["MELEE_WRAP"][0])
    if site not in (V.IMPACT_ORIG, V.IMPACT_BRANCH, wrap):
        raise RuntimeError(f"unexpected code at 0x{V.IMPACT_SITE:08X}: {site.hex()}")
    g.m.wr(V.IMPACT_SITE, wrap)                                  # bullets (BOOM_MASK) keep the plain grenade


def _melee_mask(classes) -> int:
    m = 0
    for c in classes:
        m |= 1 << c
    return m


def explosive_melee(g, on: bool, kind: str = "grenade") -> dict:
    install_melee(g)
    V = g.V
    t, cls, radius = BLASTS.get((kind or "grenade").lower(), BLASTS["grenade"])
    vars_ = bytearray(g.m.rd(V.MELEE_VARS, 8))
    launch = vars_[6]
    if on:
        struct.pack_into(">I", vars_, 0, _melee_mask(V.MELEE_CLASSES.values()))
        vars_[4], vars_[5] = t, (cls if t != 1 else 0x13)
        vars_[7] = 1 if launch else 0
        g.m.wr(V.MELEE_VARS + 8, struct.pack(">f", radius))
    else:
        vars_[4], vars_[7] = 0xFF, 0
        if not launch:
            struct.pack_into(">I", vars_, 0, 0)
    g.m.wr(V.MELEE_VARS, bytes(vars_))
    back = g.m.rd(V.MELEE_VARS, 8)
    return {"explosive_melee": on, "type": kind if on else None, "melee_classes": {k: f"0x{c:02X}" for k, c in V.MELEE_CLASSES.items()},
            "verified": back == bytes(vars_) and g.m.rd(V.IMPACT_SITE, 4) == _bl(V.IMPACT_SITE, V.MELEE_CODE["MELEE_WRAP"][0]),
            "note": "every knife hit on an enemy sets off the game's own grenade / flash / rocket-strength blast at the "
                    "hit point, owned by the player (the attack routine's owner = Leon: the blast hurts enemies, never "
                    "Leon - checked: HP unchanged by a blast at his feet). Kicks/suplexes are context actions that do "
                    "not go through the impact path: not hooked yet (see docs/mercenaries.md)."}


def super_melee(g, on: bool, force: float = 100.0, direction: str = "both") -> dict:
    """force: feet of height (up/both) or of distance (away). 1 ft = 304.8 units; gravity 11 units/frame^2."""
    install_melee(g)
    V = g.V
    gacc = 11.0
    h = max(1.0, float(force or 100)) * 304.8
    v0 = (2 * gacc * h) ** 0.5
    d = (direction or "both").lower()
    up = v0 if d in ("up", "both", "air", "sky") else 120.0
    t_air = 2 * up / gacc
    away = (h / t_air) if d in ("away", "both", "back", "far") else 0.0
    vars_ = bytearray(g.m.rd(V.MELEE_VARS, 8))
    if on:
        struct.pack_into(">I", vars_, 0, _melee_mask(V.MELEE_CLASSES.values()))
        vars_[6] = 1
        vars_[7] = 1 if vars_[4] != 0xFF else 0
        g.m.wr(V.MELEE_VARS + 0x0C, struct.pack(">3f", up, away, gacc))
        g.m.wr(V.MELEE_VARS + 0x30, struct.pack(">I", int(t_air) + 60))
    else:
        vars_[6], vars_[7] = 0, 0
        if vars_[4] == 0xFF:
            struct.pack_into(">I", vars_, 0, 0)
    g.m.wr(V.MELEE_VARS, bytes(vars_))
    return {"super_melee": on, "force_feet": float(force or 100), "direction": d, "launch_speed_up": round(up, 1),
            "launch_speed_away": round(away, 1), "air_seconds": round(t_air / 30, 1),
            "verified": g.m.rd(V.MELEE_VARS, 8) == bytes(vars_),
            "combined_with_explosive_melee": bool(vars_[7]),
            "note": "a knife hit throws the nearest enemy (within ~5 m of the hit) up/away along a ballistic arc drawn "
                    "every frame by gBox's hook; with explosive_melee on, the blast goes off where it lands instead of at "
                    "the hit. Kicks are not hooked yet."}


def auto_spin(g, on: bool, speed: float = 360.0, mode: str = "fire") -> dict:
    install_melee(g)
    V = g.V
    m = {"fire": (1, 0x0120), "firing": (1, 0x0120), "aim": (1, 0x0020), "aiming": (1, 0x0020),
         "always": (2, 0), "on": (2, 0)}.get((mode or "fire").lower(), (1, 0x0120))
    rad = float(speed or 360.0) * 3.141592653589793 / 180.0 / V.FPS
    g.m.wr(V.MELEE_VARS + 0x18, struct.pack(">f", rad))
    g.m.wr(V.MELEE_VARS + 0x1E, struct.pack(">H", m[1]))
    g.m.wr(V.MELEE_VARS + 0x1C, bytes([m[0] if on else 0]))
    return {"auto_spin": on, "deg_per_second": float(speed or 360.0), "when": mode if on else None,
            "verified": g.m.rd(V.MELEE_VARS + 0x1C, 1)[0] == (m[0] if on else 0),
            "note": "Leon turns continuously (fire = while R+A are held, i.e. aiming and firing; aim = while R is held; "
                    "always). With a full-auto gun (weapon_mod fire_rate=auto) + infinite_ammo the burst sprays a circle."}


def aim_turn_speed(g, mult: float) -> dict:
    out = {}
    for a, orig in g.V.AIM_TURN:
        g.m.wr(a, struct.pack(">f", orig * float(mult or 1)))
        out[f"0x{a:08X}"] = round(struct.unpack(">f", g.m.rd(a, 4))[0], 5)
    ok = all(abs(v - o * float(mult or 1)) < 1e-4 * max(1.0, o * float(mult or 1)) for v, (a, o) in zip(out.values(), g.V.AIM_TURN))
    return {"aim_turn_speed_x": float(mult or 1), "constants": out, "verified": ok,
            "note": "scales how fast the stick turns Leon (and tilts the aim) while aiming; 1 = the game's speed"}


def _room(q) -> int:
    t = str(q).strip().lower().lstrip("r").replace("0x", "")
    v = int(t, 16)
    if v > 0xFFF or (v >> 8) not in (1, 2, 3, 4):
        raise ValueError("room: r1xx village, r2xx castle, r3xx island (disc 2), r4xx Mercenaries / Assignment Ada, e.g. r102")
    return v


def warp(g, room, pos=None, rot: float = 0.0) -> dict:
    """What a door does (0x8014CA4C): destination stage/room in pG+0x28/0x29, position+rotation in pG+0x2C..0x38,
    then the main routine pG+0x20 = 4 (room jump)."""
    r = _room(room)
    pg = g.pg()
    before = g.m.u16(pg + g.V.G_ROOM)
    if (r >> 8) == 3 and g.m.rd(0x80000000, 0x40)[0x20:0x40].split(b"\0")[0].endswith(b"disc1"):
        raise ValueError("r3xx (island) rooms are on disc 2; this is disc 1")
    x, y, z = (pos or (0.0, 0.0, 0.0))[:3]
    g.m.wr(pg + 0x28, bytes([r >> 8, r & 0xFF, 0]))
    g.m.wr(pg + 0x2C, struct.pack(">4f", x, y, z, rot))
    g.m.wr(pg + 0x21, bytes(3))
    g.m.wr(pg + 0x20, bytes([4]))
    t = time.time()
    while time.time() - t < 25:
        time.sleep(1)
        if g.m.u16(pg + g.V.G_ROOM) == r and g.m.rd(pg + 0x20, 1)[0] == 3:
            break
    now = g.m.u16(pg + g.V.G_ROOM)
    return {"from": f"r{before:03x}", "to": f"r{now:03x}", "verified": now == r and g.m.rd(pg + 0x20, 1)[0] == 3,
            "note": "the room loads with its own events/enemies for the current story flags; position defaults to the "
                    "room origin (pass x,y,z to choose)"}


def teleport(g, x: float, y: float, z: float) -> dict:
    pl = g.m.u32(g.V.P_PLAYER)
    if not 0x80000000 <= pl < 0x81800000:
        raise RuntimeError("no player in play")
    d = g.m.rd(pl, 0x300)
    px, py, pz = struct.unpack_from(">3f", d, 0x94)
    offs = [o for o in range(0, 0x2F4, 4) if abs(struct.unpack_from(">f", d, o)[0] - px) < 2
            and abs(struct.unpack_from(">f", d, o + 8)[0] - pz) < 2]
    for o in offs:                                       # the player keeps several copies (pos, old pos, collision)
        g.m.wr(pl + o, struct.pack(">3f", x, y, z))
    time.sleep(0.5)
    nx, ny, nz = struct.unpack(">3f", g.m.rd(pl + 0x94, 12))
    return {"from": [round(px), round(py), round(pz)], "to": [round(nx), round(ny), round(nz)],
            "verified": abs(nx - x) < 50 and abs(nz - z) < 50}


def _item_id(q) -> int:
    s = str(q).strip().lower()
    if s.startswith("0x"):
        return int(s, 16)
    if s.isdigit():
        return int(s)
    s = s.replace("’", "'")
    if s in R.NOT_ON_GC:
        raise ValueError(f"{q}: not in Resident Evil 4 GameCube - {R.NOT_ON_GC[s]}")
    if s in R.ALIASES:
        return R.ALIASES[s]
    names = {v.rstrip("*").lower(): k for k, v in R.ITEMS.items()}
    if s in names:
        return names[s]
    import difflib
    hit = difflib.get_close_matches(s, list(names) + list(R.ALIASES), n=1, cutoff=0.6)
    if hit:
        return names.get(hit[0], R.ALIASES.get(hit[0]))
    raise ValueError(f"unknown RE4 item {q!r}; names: {', '.join(sorted(n for n in names))}")


def _loadout_entry(q) -> tuple[int, int | None]:
    """'handgun ammo:200', 'handgun ammo x200', 'shotgun shells*50' or a plain name -> (item id, amount or None).
    The amount is what the game's take-item routine gives (rounds for ammo, count for grenades / herbs)."""
    import re
    s = str(q).strip()
    m = re.match(r"^(.*?)\s*(?::|\*|\bx)\s*(\d+)$", s, re.I)
    if m and m.group(1).strip():
        return _item_id(m.group(1)), int(m.group(2))
    return _item_id(s), None


def merc_loadout_list(g) -> dict:
    names = {v: k for k, v in g.V.CHARACTERS.items() if k != "all"}
    flags = {0: "give", 1: "give + equip", 2: "remove one", 4: "raw give"}
    recs = [{"character": names.get(c, c), "action": flags.get(f, f), "item": R.item_name(i), "id": f"0x{i:02X}",
             "amount": n or "game default"} for c, f, i, n in read_recs(g)]
    return {"records": recs, "game_defaults": {names[c]: [R.item_name(i) for i in v]
                                               for c, v in g.V.MERC_DEFAULT_WEAPONS.items()},
            "note": "records run right after the game's own Merc loadout routine (0x80018CC4) when a run starts"}


def run(ad, op: str, item: str = "", count: int = 0, target: str = "", on: bool = True, seconds: float = 0,
        character: str = "", items: list | None = None, fire_rate=None, damage=None, reset: bool = False,
        multiplier: float = 2.0, melee_only: bool = True, kind: str = "", force: float = 0, direction: str = "",
        speed: float = 0, g=None, **extra) -> dict:
    g = g or RE4(ad)
    op = op.strip().lower().replace(" ", "_").replace("-", "_")
    op = {"unlock": "mercenaries_unlock", "unlock_mercenaries": "mercenaries_unlock", "mercenaries": "mercenaries_unlock",
          "ammo": "infinite_ammo", "god": "unlimited_health", "god_mode": "unlimited_health", "invincible": "unlimited_health",
          "infinite_combo": "combo_freeze", "combo": "combo_freeze", "freeze_timer": "merc_timer_freeze",
          "timer_freeze": "merc_timer_freeze", "inventory": "list", "swap": "replace", "spawn": "spawn_multiplier",
          "enemy_multiplier": "spawn_multiplier", "more_enemies": "spawn_multiplier", "unlock_everything": "unlock_all",
          "time_bonus": "merc_time_bonus", "combo_bonus_time": "combo_time", "combo_window": "combo_time",
          "combo_bonus": "combo_time", "combo_timer": "combo_time", "safe_grenades": "grenade_safe",
          "grenades_safe": "grenade_safe", "grenade_immunity": "grenade_safe", "punch_enemies": "punch",
          "punches": "punch", "loadout": "merc_loadout", "loadouts": "merc_loadout_list",
          "merc_loadouts": "merc_loadout_list", "item_table": "item_ids", "items": "item_ids",
          "address_table": "addresses"}.get(op, op)
    res: dict = {"op": op}
    if op == "status":
        pass
    elif op == "punch":
        res.update(possible=False, statement=PUNCH_STATEMENT,
                   instead=["explosive_melee on=true kind=grenade", "super_melee on=true force=100 direction=both",
                            "flashbang_loop on=true seconds=3 (staggers enemies so the kick prompt shows)"])
    elif op == "combo_time":
        res.update(combo_time(g, (extra.get("factor") or multiplier) if on else 1.0))
    elif op == "grenade_safe":
        res.update(grenade_safe(g, on))
    elif op == "merc_loadout_list":
        res.update(merc_loadout_list(g))
    elif op == "item_ids":
        res.update(R.items_catalog("wii" if _gid(g) == "RB4P08" else "gamecube"))
    elif op == "addresses":
        res.update(game_id=_gid(g), addresses=R.address_table(_gid(g)), unlock_scope=R.UNLOCK_SCOPE.get(_gid(g)))
    elif op == "list":
        res["items"] = [{k: v for k, v in x.items() if k != "raw"} for x in g.items()]
    elif op in g.V.PATCHES:
        res.update(g.patch(op, on))
    elif op in R.PATCHES:
        raise Unsupported(f"re_mods: {op} is not located in {g.V.name} yet (GameCube only); see docs/mercenaries.md")
    elif op in ("mercenaries_unlock", "unlock_all"):
        res.update(unlock_all(g, on, op == "unlock_all"))
    elif op == "merc_time":
        if g.room() >> 8 != 4:
            raise ValueError("not in a Mercenaries stage")
        g.m.wr(g.V.MERC_TIMER, struct.pack(">I", int(max(0, seconds) * g.V.FPS)))
        res.update(seconds=round(g.m.u32(g.V.MERC_TIMER) / g.V.FPS, 2))
    elif op == "merc_time_bonus":
        res.update(merc_time_bonus(g, multiplier if on else 1.0, melee_only))
    elif op in ("explosive_melee", "exploding_melee", "melee_explode"):
        res.update(explosive_melee(g, on, kind or "grenade"))
    elif op in ("super_melee", "super_punch", "melee_launch"):
        res.update(super_melee(g, on, force or 100.0, direction or "both"))
    elif op in ("auto_spin", "spin"):
        res.update(auto_spin(g, on, speed or 360.0, target or "fire"))
    elif op in ("aim_turn_speed", "turn_speed", "aim_speed"):
        res.update(aim_turn_speed(g, multiplier if on else 1.0))
    elif op == "give":
        iid = _item_id(item)
        if iid in R.NOT_GIVABLE:
            raise ValueError(R.NOT_GIVABLE[iid])
        before = sum(x["count"] for x in g.items() if x["id"] == iid)
        ok = g.call(g.V.F_TAKE_ITEM, iid, max(0, int(count)), 0)
        after_items = [x for x in g.items() if x["id"] == iid]
        res.update(item=R.item_name(iid), id=f"0x{iid:02X}", placed=bool(ok), have=sum(x["count"] for x in after_items),
                   verified=bool(ok) and (len(after_items) > 0 and sum(x["count"] for x in after_items) >= before),
                   note=None if ok else "no room in the attache case for it")
    elif op == "replace":
        new = _item_id(item)
        if new in R.NOT_GIVABLE:
            raise ValueError(R.NOT_GIVABLE[new])
        inv = g.items()
        t = str(target).strip().lower()
        if t.isdigit() and int(t) < 512 and not t.startswith("0x"):
            old = next((x for x in inv if x["slot"] == int(t)), None)
        else:
            tid = _item_id(target)
            old = next((x for x in inv if x["id"] == tid and x["in_case"]), None)
        if not old:
            raise ValueError(f"no case item matches {target!r}")
        raw = bytes.fromhex(old["raw"])
        g.m.wr(old["addr"], raw[:4] + b"\x00" + raw[5:13] + b"\x00")       # free its slot and its case cells
        ok = g.call(g.V.F_TAKE_ITEM, new, max(0, int(count)), 0)
        if not ok:
            g.m.wr(old["addr"], raw)
        res.update(removed=old["name"], added=R.item_name(new) if ok else None, placed=bool(ok), verified=bool(ok) and
                   any(x["id"] == new for x in g.items()) and not any(x["addr"] == old["addr"] and x["id"] == old["id"]
                                                                        for x in g.items()),
                   note=None if ok else f"{R.item_name(new)} does not fit; {old['name']} put back")
    elif op in ("flashbang", "grenade", "explode", "blast"):
        res.update(blast(g, "flash" if op == "flashbang" or "flash" in (item or "").lower() else "grenade", target or "player"))
    elif op in ("flashbang_loop", "blast_loop", "grenade_loop"):
        res.update(blast_loop(g, "grenade" if op == "grenade_loop" or "grenade" in (item or "").lower() else "flash",
                              seconds or 3, on))
    elif op == "explosive_rounds":
        names = items or ([item] if item else ["handgun", "red9", "blacktail", "punisher"])
        res.update(explosive_rounds(g, [_item_id(x) for x in names], on))
    elif op in ("warp", "room", "goto"):
        res.update(warp(g, target or item, [float(v) for v in items[:3]] if items else None))
    elif op == "teleport":
        if not items or len(items) < 3:
            raise ValueError("teleport needs items=[x, y, z] (game units; status shows the current position)")
        res.update(teleport(g, *[float(v) for v in items[:3]]))
    elif op == "spawn_multiplier":
        res.update(spawn_multiplier(g, count or 2, on))
    elif op == "equip":
        res.update(equip_item(g, _item_id(item)))
    elif op == "weapon_mod":
        res.update(weapon_mod(g, _item_id(item), fire_rate, damage, reset))
    elif op == "merc_loadout":
        ch = g.V.CHARACTERS.get((character or "any").strip().lower())
        if ch is None:
            raise ValueError(f"character: {', '.join(g.V.CHARACTERS)}")
        install_weapon_code(g)
        recs = [r for r in read_recs(g) if r[0] != ch]
        if reset or not items:
            want = recs
            res.update(character=character or "any", loadout="game default")
        else:
            parsed = [_loadout_entry(x) for x in items]
            ids = [i for i, _ in parsed]
            amounts = {i: n for i, n in parsed if n is not None}
            bad = [i for i in ids if i in R.NOT_GIVABLE]
            if bad:
                raise ValueError(R.NOT_GIVABLE[bad[0]])
            wc = weapon_classes(g)
            new = [(ch, 2, 0x7C, 0), (ch, 4, 0x7F, 1)]                       # attache case XL for room
            if on:                                                          # on=true: drop the default guns
                for c in ([ch] if ch != 0xFF else list(g.V.MERC_DEFAULT_WEAPONS)):
                    new += [(c, 2, w, 0) for w in g.V.MERC_DEFAULT_WEAPONS.get(c, [])]
            first_gun = next((i for i in ids if i in wc), None)
            for iid in ids:
                n = amounts.get(iid, max(0, int(count)) if iid == first_gun else 0)
                new.append((ch, 1 if iid == first_gun else 0, iid, min(0xFFFF, max(0, int(n)))))
            want = recs + new
            res.update(character=character or "any", items=[R.item_name(i) for i in ids],
                       amounts={R.item_name(i): (amounts[i] if i in amounts else "game default") for i in ids},
                       equipped=R.item_name(first_gun) if first_gun is not None else None, replaced_defaults=on,
                       note="applied when a Mercenaries run starts (character select -> stage); the first weapon is "
                            "equipped about 5 seconds into the run")
        write_recs(g, want)
        res["records"] = len(want)
        res["verified"] = read_recs(g) == want
    else:
        raise ValueError("op: status | list | give | replace | equip | weapon_mod | merc_loadout | spawn_multiplier | warp | "
                         "teleport | flashbang | grenade | flashbang_loop | explosive_rounds | unlock_all | mercenaries_unlock | "
                         "infinite_ammo | combo_freeze | merc_timer_freeze | unlimited_health | merc_time | merc_time_bonus | "
                         "explosive_melee | super_melee | auto_spin | aim_turn_speed | combo_time | grenade_safe | punch | "
                         "merc_loadout_list | item_ids | addresses")
    res["status"] = g.status()
    return res


class REModsIn(BaseModel):
    session_id: str
    op: str = "status"      # status|list|give|replace|equip|weapon_mod|merc_loadout|spawn_multiplier|flashbang|grenade|
                            # flashbang_loop|explosive_rounds|warp|teleport|mercenaries_unlock|infinite_ammo|combo_freeze|
                            # merc_timer_freeze|unlimited_health|merc_time|combo_time|grenade_safe|punch|
                            # merc_loadout_list|item_ids|addresses
    item: str = ""          # give/replace: item name or id ("rocket launcher", "flash grenade", "0x37")
    count: int = 0          # give: amount (0 = the game's default); spawn_multiplier: factor 2..8
    target: str = ""        # replace: case item (name, id or slot); warp: room "r102"; flashbang/grenade: player|aim
    on: bool = True         # patches / unlock: on or off
    seconds: float = 0      # merc_time; flashbang_loop period
    character: str = ""     # merc_loadout: leon | ada | hunk | krauser | wesker | any
    items: list[str] = []   # merc_loadout: item names, "name:amount" for ammo/counts ("handgun ammo:200");
                            # explosive_rounds: item names; warp / teleport: [x, y, z]
    fire_rate: str | None = None   # weapon_mod: frames between shots (30 = 1 s) or "auto" (TMP speed, 3 frames)
    damage: float | None = None    # weapon_mod: firepower multiplier vs. the original table
    reset: bool = False     # weapon_mod / merc_loadout: back to the game's values first
    multiplier: float = 2.0 # merc_time_bonus / aim_turn_speed / combo_time: x N (1 = the game's own)
    melee_only: bool = True # merc_time_bonus: RE4 has no melee time bonus -> every time pickup is scaled
    kind: str = ""          # explosive_melee: grenade | flash | rocket
    force: float = 0        # super_melee: feet (height for up/both, distance for away); default 100
    direction: str = ""     # super_melee: up | away | both
    speed: float = 0        # auto_spin: degrees per second (default 360)


class REModsOut(BaseModel):
    result: dict


@tool("re_mods", "1.0", REModsIn, REModsOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=120)
def re_mods(inp: REModsIn, ctx):
    """Resident Evil 4 (GameCube; Wii Edition for unlock_all / merc_time / merc_time_bonus / timer freeze / unlimited
    health / weapon_mod) live mods, verified by read-back. unlock_all = every Mercenaries character + stage + extra mode
    (+ Professional); merc_time_bonus multiplier=N scales every Mercenaries time pickup; explosive_melee kind=grenade|
    flash|rocket = knife hits explode (player-owned blast, never hurts Leon); super_melee force=<feet> direction=up|away|
    both = knife hits throw the enemy (explodes where it lands with explosive_melee); auto_spin speed=<deg/s> target=
    fire|aim|always; aim_turn_speed multiplier=N. give items by name (auto-placed in the attache
    case by the game's own take-item routine), replace a case item, unlock The Mercenaries + all characters,
    infinite ammo, Mercenaries combo never ends, freeze/set the Mercenaries timer, unlimited health, equip any weapon
    now, per-character Mercenaries loadouts (items "name:amount" for ammo), weapon fire rate / damage (e.g. a full-auto
    Handcannon). GameCube also: combo_time multiplier=N (the Mercenaries combo window x N: 'triple the combo time' = 3),
    grenade_safe on= (your hand grenades never hurt you), punch (why RE4 has no punch + what to use), addresses (this
    release's address table with sources and live_checked)."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    if g.get("platform") not in ("gamecube", "wii"):
        hint = " Resident Evil 5: tool re5; Resident Evil 6: tool re6." if g.get("platform") in ("ps3", "xbox360") else ""
        raise Unsupported(f"re_mods: Resident Evil 4 on GameCube / Wii (Dolphin) so far; {g.get('title')} "
                          f"({g.get('platform')}): see docs/mercenaries.md for what each Mercenaries release has.{hint}")
    return {"result": run(ad, inp.op, inp.item, inp.count, inp.target, inp.on, inp.seconds, inp.character, inp.items,
                          inp.fire_rate, inp.damage, inp.reset, inp.multiplier, inp.melee_only, inp.kind, inp.force,
                          inp.direction, inp.speed)}
