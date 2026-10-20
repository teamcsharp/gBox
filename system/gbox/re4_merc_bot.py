"""Resident Evil 4 (GameCube G4BE08) Mercenaries autoplay playbook: an "any means necessary" run.

setup() applies the hack package through re_mods (Mercenaries unlocked, Leon's loadout = a full-auto Hand Cannon with
explosive rounds, infinite ammo, unlimited health, time pickups x3, combo window x3 and frozen, every Ganado cloned
twice more). play() then drives Leon from RAM at ~20 Hz:
  * reads Leon (player em: *0x802B3044, +0x94 position, +0xA4 facing) and every live Ganado (EmMgr 0x8027DF20 slots:
    flags & 0x601 and +0x398 != 0xFF, +0x94 position);
  * snaps Leon's facing onto the nearest one (tank controls: facing + stick forward walks there), sprints in and holds
    aim + fire inside FIRE_RANGE;
  * teleports next to the target when it is far away or Leon is stuck on scenery (every copy of his position,
    like re_mods teleport);
  * a target that soaks 6 s of fire without the combo moving (on a roof, behind a wall) is skipped for 10 s;
  * the Mercenaries clock stops while a prompt is up ("Take the Handgun Ammo?", a time pillar): answer Yes (A);
  * between rounds (results, the Mercenaries title, character / stage select, the briefing) it presses A until the
    next round starts: GAME START, Leon, the first stage, go - the hack package stays in RAM, so every round is
    played the same way and no menu stays on screen (operator 2026-10-20: "I want to see Leon destroying
    Mercenaries mode", and earlier "I don't like seeing it sit on menus forever").
Measured 2026-10-20 on the Spark (Dolphin, real frames): 18 kills, 13,370 points, 18 in a row, two stars, from a
stage-select save state (no menus); unmodded rooftop spinning had made 8 kills / 2,840.

Memory comes from Dolphin's shared RAM view (/proc/<pid>/mem on Linux, a whole EmMgr table per read) when available,
else the adapter's read_memory/write_memory. Input goes through the adapter's send_input with gBox pad names.
"""
from __future__ import annotations

import math
import os
import struct
import time

GAME_IDS = {"G4BE08"}
EMMGR, P_PLAYER, P_GLOBAL = 0x8027DF20, 0x802B9780 - 0x673C, 0x802B2280
G_ROOM, MERC_TIMER, MERC = 0x4FA8, 0x80279308, 0x8021392C
FIRE_RANGE, HOP_FAR, HOP_SHORT = 2600.0, 5500.0, 1400.0
MENU_AFTER, MENU_EVERY = 2.0, 1.5                 # out of a stage this long: press A this often (next round)
PACKAGE = [("mercenaries_unlock", {"on": True}),
           ("merc_loadout", {"character": "leon", "items": ["handcannon", "handcannon ammo:200"], "on": True}),
           ("weapon_mod", {"item": "handcannon", "fire_rate": "auto", "damage": "99.9"}),
           ("infinite_ammo", {"on": True}), ("unlimited_health", {"on": True}),
           ("explosive_rounds", {"items": ["handcannon"], "on": True}),
           ("merc_time_bonus", {"multiplier": 3}), ("combo_time", {"multiplier": 3}),
           ("combo_freeze", {"on": True}), ("spawn_multiplier", {"count": 3, "on": True})]


def ptr_ok(p: int) -> bool:
    return 0x80000000 <= p < 0x81800000


class ShmMem:
    """Dolphin's 32 MiB MEM1 view in /dev/shm, read through /proc/<pid>/mem (Linux, same user): whole tables per read."""

    def __init__(self, game_id: bytes = b"G4BE08"):
        for pid in (p for p in os.listdir("/proc") if p.isdigit()):
            try:
                maps = open(f"/proc/{pid}/maps").read()
            except OSError:
                continue
            for line in maps.splitlines():
                if "/dev/shm/dolphin-emu" not in line:
                    continue
                a, b = (int(x, 16) for x in line.split()[0].split("-"))
                if b - a != 0x2000000:
                    continue
                try:
                    f = open(f"/proc/{pid}/mem", "r+b", 0)
                    f.seek(a)
                    if f.read(6) == game_id:
                        self.f, self.base = f, a
                        return
                except OSError:
                    continue
        raise OSError("no Dolphin MEM1 view for this game")

    def rd(self, addr: int, n: int) -> bytes:
        self.f.seek(self.base + (addr & 0x1FFFFFF))
        return self.f.read(n)

    def wr(self, addr: int, data: bytes) -> None:
        self.f.seek(self.base + (addr & 0x1FFFFFF))
        self.f.write(data)


class AdMem:
    def __init__(self, ad):
        self.ad = ad

    def rd(self, addr: int, n: int) -> bytes:
        return bytes(self.ad.read_memory(addr, n))

    def wr(self, addr: int, data: bytes) -> None:
        self.ad.write_memory(addr, data)


def memory(ad):
    try:
        return ShmMem()
    except OSError:
        return AdMem(ad)


def u32(m, a):
    return struct.unpack(">I", m.rd(a, 4))[0]


def snapshot(m) -> dict:
    """room, Merc clock (s), combo, Leon {ptr, pos, rot}, live Ganados [{slot, pos}]."""
    pg = u32(m, P_GLOBAL)
    room = struct.unpack(">H", m.rd(pg + G_ROOM, 2))[0] if ptr_ok(pg) else None
    pl = u32(m, P_PLAYER)
    player = None
    if ptr_ok(pl):
        player = {"ptr": pl, "pos": struct.unpack(">3f", m.rd(pl + 0x94, 12)),
                  "rot": struct.unpack(">f", m.rd(pl + 0xA4, 4))[0]}
    base, n, stride = u32(m, EMMGR), u32(m, EMMGR + 4), u32(m, EMMGR + 8)
    enemies = []
    if ptr_ok(base) and 0 < n <= 128 and 0x100 < stride < 0x2000:
        d = m.rd(base, n * stride)
        for k in range(1, n):
            o = k * stride
            if not (struct.unpack_from(">I", d, o)[0] & 0x601) or d[o + 0x398] == 0xFF:
                continue
            enemies.append({"slot": k, "pos": struct.unpack_from(">3f", d, o + 0x94)})
    return {"room": room, "timer": round(u32(m, MERC_TIMER) / 30.0, 1), "combo": u32(m, MERC + 0x28),
            "player": player, "enemies": enemies}


def in_mercenaries(snap: dict) -> bool:
    return snap["room"] is not None and (snap["room"] >> 8) == 4 and snap["player"] is not None


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def teleport(m, pl: int, x: float, y: float, z: float) -> int:
    """Every copy of Leon's position (pos, old pos, collision) moves; returns how many were written."""
    d = m.rd(pl, 0x300)
    pos = struct.unpack_from(">3f", d, 0x94)
    n = 0
    for o in range(0, 0x2F4, 4):                     # all three coordinates must match: zeros are everywhere
        if all(abs(a - b) < 2 for a, b in zip(struct.unpack_from(">3f", d, o), pos)):
            m.wr(pl + o, struct.pack(">3f", x, y, z))
            n += 1
    return n


class Bot:
    """One decision per tick; the caller sends what it returns ({'hold': keys} / {'tap': key}) and sleeps."""

    def __init__(self, m, clock=time.time):
        self.m, self.clock = m, clock
        self.hist: list = []
        self.last_hop = 0.0
        self.last_timer, self.timer_since = None, clock()
        self.skip: dict[int, float] = {}
        self.aim = {"slot": None, "since": 0.0, "combo": 0}
        self.stats = {"hops": 0, "prompts": 0, "max_combo": 0}

    def tick(self, s: dict) -> dict:
        now, p = self.clock(), s["player"]
        self.stats["max_combo"] = max(self.stats["max_combo"], s["combo"])
        if not p:
            return {"hold": set()}
        if s["timer"] != self.last_timer:
            self.last_timer, self.timer_since = s["timer"], now
        elif now - self.timer_since > 1.2 and s["timer"] > 0:           # the clock stopped: a prompt is up
            self.stats["prompts"] += 1
            return {"tap": "b" if now - self.timer_since > 6 else "a"}
        if not s["enemies"]:
            return {"hold": {"up", "b"}}
        px, _, pz = p["pos"]
        self.hist = [h for h in self.hist if now - h[0] < 1.5] + [(now, px, pz)]
        moved = math.hypot(self.hist[-1][1] - self.hist[0][1], self.hist[-1][2] - self.hist[0][2])
        pool = [e for e in s["enemies"] if self.skip.get(e["slot"], 0) < now] or s["enemies"]
        tgt = min(pool, key=lambda e: (e["pos"][0] - px) ** 2 + (e["pos"][2] - pz) ** 2)
        if tgt["slot"] != self.aim["slot"] or s["combo"] != self.aim["combo"]:
            self.aim = {"slot": tgt["slot"], "since": now, "combo": s["combo"]}
        elif now - self.aim["since"] > 6:                              # soaked 6 s of fire: out of reach
            self.skip[tgt["slot"]] = now + 10
            self.aim = {"slot": None, "since": now, "combo": s["combo"]}
            return {"hold": set()}
        tx, ty, tz = tgt["pos"]
        dx, dz = tx - px, tz - pz
        dist = math.hypot(dx, dz)
        stuck = dist >= FIRE_RANGE and now - self.hist[0][0] > 1.2 and moved < 150
        if (dist > HOP_FAR or stuck) and now - self.last_hop > 2.5:
            k = max(0.0, (dist - HOP_SHORT) / dist)
            teleport(self.m, p["ptr"], px + dx * k, ty, pz + dz * k)
            self.last_hop, self.hist = now, []
            self.stats["hops"] += 1
            return {"hold": set()}
        self.m.wr(p["ptr"] + 0xA4, struct.pack(">f", heading(dx, dz)))
        return {"hold": {"r", "a"} if dist < FIRE_RANGE else {"up", "b"}}


def setup(ad) -> list[str]:
    """Apply the hack package (re_mods); returns the ops that failed."""
    from . import re_mods_tool as RM
    g = RM.RE4(ad)
    failed = []
    for op, kw in PACKAGE:
        try:
            RM.run(ad, op, g=g, **kw)
        except Exception as e:                       # noqa: BLE001 - one failed mod never stops the run
            failed.append(f"{op}: {e}")
    return failed


def play(ad, send, stopped, sleep=time.sleep, m=None, tick_s: float = 0.05, stats: dict | None = None,
         clock=time.time) -> dict:
    """Drive Leon until stopped(); send(rows) presses keys. Returns the run's stats (stats, when given, is filled live:
    the watch panel shows it): hops, prompts, max_combo, combo, timer, rounds, menu_presses."""
    m = m or memory(ad)
    bot, held = Bot(m, clock=clock), set()
    if stats is not None:
        stats.update(bot.stats)
        bot.stats = stats
    bot.stats.update(rounds=1, menu_presses=0)
    out_since, last_press, was_in = None, 0.0, True

    def hold(keys):
        nonlocal held
        rows = [{"key": k, "down": False} for k in sorted(held - keys)] + [{"key": k, "down": True} for k in sorted(keys - held)]
        if rows:
            send(rows)
        held = set(keys)
    while not stopped():
        s = snapshot(m)
        now = clock()
        if not in_mercenaries(s) or s["timer"] <= 0:   # the Result screen (same room, clock at 0), the title, select
            hold(set())
            out_since = out_since or now
            if now - out_since > MENU_AFTER and now - last_press > MENU_EVERY:
                send([{"key": "a", "down": True}])
                sleep(0.2)
                send([{"key": "a", "down": False}])
                last_press = clock()
                bot.stats["menu_presses"] += 1
            was_in = False
            sleep(0.25)
            continue
        if not was_in:
            bot.stats["rounds"] += 1
            was_in = True
        out_since = None
        bot.stats.update(combo=s["combo"], timer=s["timer"])
        act = bot.tick(s)
        if "tap" in act:
            hold(set())
            sleep(0.15)
            send([{"key": act["tap"], "down": True}])
            sleep(0.25)
            send([{"key": act["tap"], "down": False}])
            sleep(0.4)
            continue
        hold(act["hold"])
        sleep(tick_s)
    hold(set())
    return bot.stats


def matches(ad, g: dict) -> bool:
    """This playbook plays this session: RE4 GameCube NTSC-U in a Mercenaries stage."""
    if g.get("platform") != "gamecube":
        return False
    try:
        m = memory(ad)
        return m.rd(0x80000000, 6).decode("ascii", "replace") in GAME_IDS and in_mercenaries(snapshot(m))
    except Exception:                                # noqa: BLE001
        return False
