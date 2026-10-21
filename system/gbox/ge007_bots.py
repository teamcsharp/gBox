"""Bots for the GoldenEye 007 PC port: gBox's bot brain driving multiplayer seats through the port's bridge.

The port (built by gbox/native_ports.py with the gBox bridge) shares its game state and takes buttons + stick per
seat (gbox/ge007_bridge.py). This module turns each bot's Intent (gbox/bot_brain.py) into an N64 pad. Which N64
control style a seat runs depends on the port's settings (a seat without a physical pad follows Input.NaturalPitch:
1.2 "Solitare" by default, 1.1 "Honey" when it is off), so each bot measures it when it first spawns:

    stick X   turn (both styles)          Z   fire        A   next weapon / respawn        B   use (doors)
    1.1 Honey     stick Y walks, C-left/right strafe, C-up/down look
    1.2 Solitare  stick Y looks up/down, C-up/down walk, C-left/right strafe

Auto-aim (on by default in multiplayer) handles the vertical aim, so the bot only has to face its target and keep
its view level.

Also an autoplay playbook (matches / setup / play) for player 1 of a port session: the same brain plays seat 0.

    python -m gbox.ge007_bots --bridge /dev/shm/gbox-ge007-test --seats 1,2,3 --difficulty 00 --seconds 120
"""
import argparse
import json
import random
import threading
import time

from . import bot_brain
from . import ge007_bridge as gb

# How much a bot wants to hold each weapon (ITEM_IDS); 0 = switch away at once.
WEAPON_SCORE = {0: 0.0, 1: 0.05, 2: 0.1, 3: 0.15, 4: 0.35, 5: 0.35, 6: 0.4, 7: 0.5, 8: 0.7, 9: 0.75, 10: 0.75,
                11: 0.72, 12: 0.7, 13: 0.9, 14: 0.95, 15: 0.65, 16: 0.8, 17: 0.5, 18: 0.75, 19: 1.0, 20: 0.5,
                21: 1.0, 22: 0.85, 23: 0.6, 24: 0.6, 25: 0.8, 26: 0.3, 27: 0.1, 28: 0.1, 29: 0.1, 31: 0.3}
AUTOMATIC = {7, 8, 9, 10, 11, 12, 13, 14, 16, 22}          # hold Z; everything else is pulsed
EXPLOSIVE = {24, 25, 26, 27, 28, 29}                       # never at close range (splash damage)
CLOSE = 600.0                                              # ~6 m


def weapon_score(item: int, enemy_close: bool = False, ammo: int = -1) -> float:
    """0..1; an empty gun (ammo 0) and an explosive with an enemy close by rate as useless."""
    if ammo == 0:
        return 0.0
    s = WEAPON_SCORE.get(item, 0.3)
    if enemy_close and item in EXPLOSIVE:
        return 0.05
    return s


class WeaponPicker:
    """Cycles with A until it holds the best weapon it has seen in its hands since the last respawn."""

    def __init__(self):
        self.seen: dict[int, float] = {}
        self.next_at = 0.0
        self.presses = 0
        self.pause_until = 0.0

    def reset(self):
        self.seen.clear()
        self.presses = 0

    def want_cycle(self, item: int, now: float, enemy_close: bool, ammo: int = -1) -> bool:
        score = weapon_score(item, enemy_close, ammo)
        self.seen[item] = score                    # current value: ammo runs out, explosives turn risky
        if now < self.pause_until or now < self.next_at:
            return False
        best = max(self.seen.values())
        if score >= 0.3 and score >= best - 1e-6:
            self.presses = 0
            return False
        if self.presses >= 12:                    # went round without finding better: stop for a while
            self.presses, self.pause_until = 0, now + 10.0
            return False
        self.presses += 1
        self.next_at = now + 0.7
        return True


class Seat:
    """One bot seat: brain, weapon picker, control-style measurement and button pulses."""

    TEST_S = 0.35                                 # how long each measuring push is held

    def __init__(self, index: int, diff, rng):
        self.index = index
        self.brain = bot_brain.Brain(diff, rng=rng)
        self.picker = WeaponPicker()
        self.turn_sign = 0                        # +1: positive stick X raises the heading; 0 until measured
        self.style = ""                           # "honey" | "solitare", "" until measured
        self.pitch_sign = 1                       # solitare: sign of the pitch change for a positive stick Y
        self.cal_phase = ""
        self.cal_until = 0.0
        self.cal_from = None
        self.pulse: dict[int, int] = {}           # button -> ticks left
        self.was_dead = False
        self.fire_flip = False
        self.intent = bot_brain.Intent()

    @property
    def ready(self) -> bool:
        return bool(self.turn_sign and self.style)

    def press(self, button: int, ticks: int = 2):
        self.pulse[button] = max(self.pulse.get(button, 0), ticks)

    def calibrate(self, p: gb.Player, now: float) -> tuple[int, int]:
        """Measure the seat's controls on its first life: hold stick X briefly and watch the heading (turn sign),
        then hold stick Y and watch the pitch (Solitare looks) or the position (Honey walks). Returns (sx, sy)."""
        if not self.cal_phase:
            self.cal_phase = "turn" if not self.turn_sign else "style"
            self.cal_from = (gb.heading_deg(p.theta), p.verta, p.pos)
            self.cal_until = now + self.TEST_S
        push = (50, 0) if self.cal_phase == "turn" else (0, 50)
        if now < self.cal_until:
            return push
        heading0, verta0, pos0 = self.cal_from
        if self.cal_phase == "turn":
            delta = bot_brain.wrap180(gb.heading_deg(p.theta) - heading0)
            if abs(delta) >= 3.0:
                self.turn_sign = 1 if delta > 0 else -1
        else:
            dpitch, moved = p.verta - verta0, bot_brain.dist2d(p.pos, pos0)
            if abs(dpitch) >= 2.0:
                self.style, self.pitch_sign = "solitare", (1 if dpitch > 0 else -1)
            elif moved >= 15.0:
                self.style = "honey"
        self.cal_phase = ""
        return 0, 0

    def pad(self, intent: bot_brain.Intent, weapon: int, verta: float = 0.0) -> tuple[int, int, int]:
        buttons = 0
        if intent.fire:
            if weapon in AUTOMATIC:
                buttons |= gb.Z
            else:
                self.fire_flip = not self.fire_flip   # semi-automatic: one press per shot
                buttons |= gb.Z if self.fire_flip else 0
        if intent.strafe > 0.3:
            buttons |= gb.CR
        elif intent.strafe < -0.3:
            buttons |= gb.CL
        if intent.use:
            self.press(gb.B)
        if intent.cycle_weapon or intent.respawn:
            self.press(gb.A)
        for b in list(self.pulse):
            buttons |= b
            self.pulse[b] -= 1
            if self.pulse[b] <= 0:
                del self.pulse[b]
        sx = round(intent.turn * gb.STICK_MAX * (self.turn_sign or 1))
        if self.style == "solitare":
            if intent.forward > 0.3:
                buttons |= gb.CU
            elif intent.forward < -0.3:
                buttons |= gb.CD
            # stick Y is the look: keep the view level (auto-aim takes care of targets above or below)
            sy = 0 if abs(verta) < 2.0 else round(max(-1.0, min(1.0, -verta / 20.0)) * 60 * self.pitch_sign)
        else:
            sy = round(intent.forward * gb.STICK_MAX)
        return buttons, sx, sy


class GoldenEyeBots:
    """Drives `seats` of a running port session through its bridge, one brain per seat."""

    MENU_PULSE_S = 1.5

    def __init__(self, bridge: gb.Bridge, seats=(1, 2, 3), difficulty="00", rng=None, log=None, menus=False):
        self.bridge = bridge
        self.seats = {s: Seat(s, difficulty, rng or random.Random(1000 + s)) for s in seats}
        self.log = log
        self.menus = menus                        # press Start through end-of-match screens (autoplay of player 1)
        self._menu_at = 0.0
        self._nav_serial = None
        self._nav = None
        self.stats = {"ticks": 0, "frames": 0, "in_match": False, "seats": {}}

    def _navgraph(self, snap: gb.Snapshot):
        if snap.nav_serial != self._nav_serial:
            nav = self.bridge.nav(snap.nav_serial)
            self._nav = bot_brain.NavGraph(nav.nodes, nav.adj) if nav else None
            self._nav_serial = nav.serial if nav else None
            if nav and self.log:
                self.log({"event": "nav", "stage": snap.stage, "nodes": len(nav.nodes),
                          "links": sum(len(a) for a in nav.adj)})
        return self._nav

    def world_for(self, seat: int, snap: gb.Snapshot, nav, now: float) -> bot_brain.World:
        me = snap.players[seat]
        contacts = [bot_brain.Contact(q.index, q.pos, alive=not q.dead, visible=me.sees(q.index), hostile=True,
                                      node=q.near_node)
                    for q in snap.players if q.present and q.index != seat]
        close = any(c.alive and bot_brain.dist3d(c.pos, me.pos) < CLOSE for c in contacts)
        items = [(it.pos, WEAPON_SCORE.get(it.item, 0.3)) for it in snap.items if WEAPON_SCORE.get(it.item, 0.3) > 0.3]
        body = bot_brain.Body(me.pos, gb.heading_deg(me.theta), alive=not me.dead, node=me.near_node,
                              weapon_score=weapon_score(me.weapon, close, me.ammo))
        return bot_brain.World(now, body, contacts, items, nav)

    def step(self, now: float | None = None) -> gb.Snapshot | None:
        now = time.monotonic() if now is None else now
        snap = self.bridge.snapshot()
        self.stats["ticks"] += 1
        self.stats["frames"] = snap.frame
        self.stats["in_match"] = snap.in_match
        if not snap.in_match:
            pulse = self.menus and now - self._menu_at >= self.MENU_PULSE_S
            if pulse:
                self._menu_at = now
            for s in self.seats:                     # keep the seats ours but idle through menus and loads
                self.bridge.drive(s, gb.START if pulse else 0, 0, 0)
            return snap
        nav = self._navgraph(snap)
        for s, seat in self.seats.items():
            p = snap.players[s] if s < len(snap.players) else None
            if p is None or not p.present or s >= snap.nplayers:
                self.bridge.drive(s, 0, 0, 0)
                continue
            if p.dead and not seat.was_dead:
                seat.picker.reset()
                seat.cal_phase = ""                  # a test cut short by a death starts over
            seat.was_dead = p.dead
            st = self.stats["seats"].setdefault(s, {})
            if not p.dead and not seat.ready:
                sx, sy = seat.calibrate(p, now)
                self.bridge.drive(s, 0, sx, sy)
                st.update(goal="measuring controls", turn_sign=seat.turn_sign, style=seat.style)
                continue
            w = self.world_for(s, snap, nav, now)
            intent = seat.brain.tick(w)
            close = any(c.alive and bot_brain.dist3d(c.pos, p.pos) < CLOSE for c in w.contacts)
            if not p.dead and seat.picker.want_cycle(p.weapon, now, close, p.ammo):
                intent.cycle_weapon = True
            seat.intent = intent
            buttons, sx, sy = seat.pad(intent, p.weapon, p.verta)
            self.bridge.drive(s, buttons, sx, sy)
            st.update(goal=intent.goal, target=intent.target, kills=p.kills, deaths=p.deaths, points=p.points,
                      weapon=gb.ITEMS.get(p.weapon, p.weapon), ammo=p.ammo, node=p.near_node, turn_sign=seat.turn_sign,
                      style=seat.style, replans=seat.brain.stats["replans"], stuck=seat.brain.stats["stuck"],
                      shots=seat.brain.stats["shots"], pos=[round(v) for v in p.pos],
                      sees=[j for j in range(gb.PLAYERS) if p.sees(j)], route=len(seat.brain.route))
        return snap

    def run(self, stopped=lambda: False, hz: float = 30.0, seconds: float | None = None, sleep=time.sleep):
        end = None if seconds is None else time.monotonic() + seconds
        period = 1.0 / hz
        try:
            while not stopped() and (end is None or time.monotonic() < end):
                t0 = time.monotonic()
                try:
                    self.step(t0)
                except (ValueError, OSError) as e:      # the port went away or restarted its block
                    if self.log:
                        self.log({"event": "bridge_error", "error": str(e)})
                    sleep(1.0)
                    continue
                sleep(max(0.0, period - (time.monotonic() - t0)))
        finally:
            for s in self.seats:
                try:
                    self.bridge.release(s)
                except (ValueError, OSError):
                    pass
        return self.stats


def start_thread(bridge: gb.Bridge, seats=(1, 2, 3), difficulty="00", log=None):
    """Bots in the background for a session; returns (bots, stop_event)."""
    stop = threading.Event()
    bots = GoldenEyeBots(bridge, seats, difficulty, log=log)
    threading.Thread(target=bots.run, kwargs={"stopped": stop.is_set}, daemon=True, name="ge007-bots").start()
    return bots, stop


# ---------------------------------------------------------------------------------------------- autoplay playbook

def matches(ad, g: dict) -> bool:
    """Autoplay for player 1 of a GoldenEye PC port session (the adapter owns the bridge)."""
    return getattr(ad, "port_id", "") == "ge007" and getattr(ad, "bridge", None) is not None


def setup(ad) -> list[str]:
    return []


def play(ad, send, stopped, stats=None, difficulty="00", **_kw) -> dict:
    """Player 1 plays itself: the brain drives seat 0 through the bridge (send is not needed: the bridge takes
    the analog stick). The seat goes back to the operator's pad when autoplay stops."""
    bots = GoldenEyeBots(ad.bridge, seats=(0,), difficulty=difficulty, menus=True)
    if stats is not None:                         # the watch panel reads it while the bot plays
        stats.update(bots.stats)
        bots.stats = stats
    return bots.run(stopped=stopped)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bridge", required=True, help="GE_GBOX_BRIDGE of the running port")
    ap.add_argument("--seats", default="1,2,3")
    ap.add_argument("--difficulty", default="00", choices=sorted(bot_brain.PRESETS))
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--hz", type=float, default=30.0)
    ap.add_argument("--log", default="", help="write stats lines (JSON) here every 2 s")
    a = ap.parse_args(argv)
    bridge = gb.Bridge(a.bridge)
    if not bridge.open(timeout=120):
        print("bridge not found or never initialised:", a.bridge)
        return 1
    out = open(a.log, "a") if a.log else None

    def log(ev):
        line = json.dumps({"t": round(time.time(), 2), **ev})
        print(line, flush=True)
        if out:
            out.write(line + "\n")
            out.flush()
    bots = GoldenEyeBots(bridge, tuple(int(s) for s in a.seats.split(",") if s.strip()), a.difficulty, log=log)
    stop = threading.Event()

    def report():
        while not stop.wait(2.0):
            log({"event": "stats", "frame": bots.stats["frames"], "in_match": bots.stats["in_match"],
                 "seats": bots.stats["seats"]})
    threading.Thread(target=report, daemon=True).start()
    try:
        bots.run(seconds=a.seconds, hz=a.hz)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        log({"event": "end", "seats": bots.stats["seats"]})
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
