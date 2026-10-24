"""RE5 proximity bombs through game-created loadouts and ordinary pad input.

The spawn-template schema is the existing, verified BLUS30491 inventory constructor.
Existing inventory identities are never relabelled. Placement requires both item
consumption and a new game-created ground mine, not merely a button press.
"""
import json
import math
import struct
from pathlib import Path

from ..deployables import Cadence
from . import re5_weapons as W

DEFAULT = {"enabled": True, "interval_s": 60., "only": False}


def settings_path():
    from .. import lessons
    return lessons.ROOT.parent / "re5-mine-settings.json"


def settings():
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        test = Cadence(data["interval_s"], data["only"], data["enabled"])
        return {"enabled": test.enabled, "interval_s": test.interval, "only": test.only}
    except (OSError, ValueError, TypeError, KeyError):
        return dict(DEFAULT)


def configure(interval=60., only=False, enabled=True):
    c = Cadence(interval, only, enabled)
    data = {"enabled": c.enabled, "interval_s": c.interval, "only": c.only}
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)
    return data


ORIGINAL_BANKS = (0x0172C790, 0x0172DC30)
ORIGINAL_KNIVES = {address:0x101 for address in ORIGINAL_BANKS}
ORIGINAL_DESCRIPTORS = {0x0172C790:0x0175488C,0x0172DC30:0x017548DC}


def verify_original_presets(g):
    from ... import re5_mods_tool as M
    for address in ORIGINAL_BANKS:
        M.verify_preset_descriptors(g,address,tuple(ORIGINAL_DESCRIPTORS[address]+8*i for i in range(10)))
        if g.u32(address+9*M.TEMPLATE_REC)!=ORIGINAL_KNIVES[address] or g.u32(address+11*M.TEMPLATE_REC)!=0x100:
            raise ValueError('original preset knife/EMPTY signature differs')

# Exact BLUS30491 getDTI / Ghidra uWpMine::update, verified by live placement.
MINE_VTABLES = frozenset({0x0162E5F8, 0x01629DB0})
PLACED, DETONATING, ARMING = 0x1CF9, 0x1DE5, 0x1DB4


def ground_mines(memory):
    """Read deployed weapons on sUnit line 10; held/spare weapons have PLACED=0."""
    from . import re5_ps3 as R
    result, seen = {}, set()
    if not callable(getattr(memory, 'rd', None)):
        return result
    try:
        manager = R.u32(memory, R.S_UNIT)
        if not R.ptr_ok(manager):
            return result
        unit = R.u32(memory, manager + R.UNIT_LINES + 10*R.LINE_STRIDE + R.LINE_FIRST)
        while R.ptr_ok(unit) and unit not in seen and len(seen) < 300:
            seen.add(unit)
            if R.u32(memory, unit) in MINE_VTABLES and memory.rd(unit+PLACED, 1) == b'\x01':
                pos = struct.unpack('>3f', memory.rd(unit+0x30, 12))
                remaining = struct.unpack('>f', memory.rd(unit+ARMING, 4))[0]
                if all(math.isfinite(v) for v in (*pos, remaining)):
                    result[unit] = {'pos': pos, 'arming_s': remaining,
                                    'detonating': memory.rd(unit+DETONATING, 1) == b'\x01'}
            unit = R.u32(memory, unit+R.UNIT_NEXT)
    except (ValueError, OSError, struct.error, IndexError):
        pass
    return result


def _bank(g, address, blocks, key):
    from ... import re5_mods_tool as M
    current = g.rd(address, blocks * M.TEMPLATE_BLOCK)
    g.keep(key, lambda: current)
    data = bytearray(current)
    changed = 0
    for block in range(blocks):
        base = block * M.TEMPLATE_BLOCK
        rows = [struct.unpack_from(">11I", current, base + i*M.TEMPLATE_REC) for i in range(12)]
        # A zero-ID record is an unused, game-owned grid slot, not an arbitrary empty memory region.
        mines = [i for i,r in enumerate(rows) if r[0] == 0x10A and r[5] < 9]
        target = mines[0] if mines else next((i for i,r in enumerate(rows) if r[5] == 7), None)
        if target is None:
            # Some costumes omit grid 7 entirely and duplicate other empty grid numbers.
            # The constructor accepts an unused record assigned to the vacant quick slot.
            target = next((i for i,r in enumerate(rows) if r[0] == 0 and r[5] < 9), None)
        if target is None: continue
        updated = [list(row) for row in rows]
        if updated[target][0] not in (0, 0x10A):
            vacant = next((i for i,r in enumerate(updated) if i!=target and r[0] == 0 and r[5] < 9), None)
            occupied = {r[5] for r in updated if r[0] and r[5] < 9}
            free_grid = next((x for x in range(9) if x != 7 and x not in occupied), None)
            if vacant is None or free_grid is None: continue
            updated[vacant] = list(updated[target]); updated[vacant][5] = free_grid
        # Sheva Tribal has an empty grid-seven stub AND a shotgun at grid
        # seven in another record. Preserve the gun and normalize the grid
        # before the constructor sees the inserted mine.
        conflict = False
        for index,row in enumerate(updated):
            if index == target or not row[0] or row[5] != 7:
                continue
            occupied = {r[5] for i,r in enumerate(updated) if i!=target and r[0] and r[5]<9}
            free_grid = next((x for x in range(9) if x!=7 and x not in occupied),None)
            if free_grid is None:
                conflict = True; break
            row[5] = free_grid
        if conflict: continue
        updated[target] = [0x10A,5,0xffffffff,0xffffffff,0xffffffff,7,0,0,0,0,0]
        for index,row in enumerate(updated):
            struct.pack_into(">11I",data,base+index*M.TEMPLATE_REC,*row)
        changed += 1
    return g.wr(address, bytes(data)), changed


def templates(g):
    from ... import re5_mods_tool as M
    M.verify_main_presets(g)
    verify_original_presets(g)
    ok, changed = _bank(g, M.TEMPLATE, M.TEMPLATE_BLOCKS, "template")
    for address in ORIGINAL_BANKS:
        good, count = _bank(g, address, 10, f"mine_bank_{address:x}")
        ok &= good
        changed += count
    # Keep the game's own item identity and stack. A new placed weapon is the
    # acknowledgement when the verified ordinary no-consumption flag is active.
    ok &= g.wr(M.DEF_TABLE + 0x0A*M.DEF_STRIDE + M.DEF_NOAMMO, struct.pack(">I", 1))
    return {"verified": ok, "mine_loadout_blocks": changed, "effective_next_round": True}


class Controller:
    def __init__(self, memory, stats, switch):
        self.m, self.stats, self.switch = memory, stats, switch
        self.cadence = Cadence()
        self.pending = None
        self.config_at = -math.inf
        self.retry_at = 0.
        self.equip_until = 0.
        self.restore = None
        self.prepare_at = None
        self.restore_after = 0.
        self.detonating = set()
        self.escape = None
        self.events = []
        self.owned = {}
        self.scope_player = None
        self.learning = self.mesh = None
        self.blast_windows = []
        self.last_blast_snapshot = None
        self.last_blast_at = -math.inf

    def bind_learning(self, learning, mesh):
        if self.mesh is not None and (mesh is None or mesh.learning_sig != self.mesh.learning_sig):
            self.blast_windows.clear()
            self.last_blast_snapshot = None
        self.learning, self.mesh = learning, mesh

    def learn(self, pos, counter, count=1):
        if self.learning is not None:
            # The bot flushes this shared Learning every 20 seconds and at
            # shutdown. Never serialize the complete navigation history once
            # per nearby death or damage observation on the control tick.
            self.learning.note_mine(self.mesh,pos,counter,count)

    def observe_blasts(self, snap, now):
        living = {e['ptr']:e for e in snap.get('enemies',()) if e.get('ptr') is not None}
        hp = (snap.get('player') or {}).get('hp')
        for window in list(self.blast_windows):
            if now-window['at'] > 2.:
                self.blast_windows.remove(window)
                continue
            # A disappearing actor is not a death; require positive->zero HP.
            dead = [ptr for ptr in window['enemies'] if ptr in living and living[ptr].get('hp') == 0]
            for ptr in dead:
                window['enemies'].remove(ptr)
            if dead:
                self.learn(window['pos'],'candidate_deaths',len(dead))
                self.event('mine_death_candidates',now,actor=window['actor'],pos=window['pos'],
                           enemies=dead,count=len(dead),attribution='unconfirmed: nearby HP deaths in explosion window')
            if not window['damage'] and hp is not None and hp < window['hp']:
                window['damage'] = True
                self.learn(window['pos'],'damage_windows')
                self.event('mine_damage_window',now,actor=window['actor'],pos=window['pos'],
                           hp_before=window['hp'],hp_after=hp,attribution='unconfirmed: damage during owned explosion window')
            if now-window['at'] >= 2.:
                self.blast_windows.remove(window)

    def reset_round(self, now, player=None, reason="new round"):
        """Discard pad/inventory/actor ownership from a completed player scope."""
        if self.pending is not None or self.restore is not None or self.escape is not None or self.owned:
            self.event('scope_reset', now, reason=reason, old_player=self.scope_player,
                       new_player=player, abandoned_escape=self.escape is not None)
        self.pending = self.restore = self.escape = self.prepare_at = None
        self.retry_at = self.equip_until = self.restore_after = 0.
        self.detonating.clear()
        self.owned.clear()
        self.blast_windows.clear()
        self.last_blast_snapshot = None
        self.cadence = Cadence(self.cadence.interval,self.cadence.only,self.cadence.enabled)
        self.scope_player = player

    def event(self, kind, now, **fields):
        self.events.append({'kind': kind, 'at': now, **fields})
        del self.events[:-128]

    def clear_escape(self, now, position):
        """Completion requires measured separation, never a movement button alone."""
        if self.escape is None:
            return True
        distance = math.dist(position, self.escape['pos'])
        self.stats['mine_retreat_distance'] = round(distance, 1)
        if distance < 600:
            return False
        self.event('retreat_complete', now, actor=self.escape['actor'], distance=distance,
                   elapsed_s=now-self.escape['at'])
        self.learn(self.escape['pos'],'retreats')
        self.stats['mine_retreats_completed'] = self.stats.get('mine_retreats_completed', 0)+1
        self.escape = None
        return True

    def tick(self, snap, now):
        scope = snap.get('player') or {}
        if scope.get('ptr') is not None and (scope.get('hp') or 0) > 0:
            if self.scope_player is not None and scope['ptr'] != self.scope_player:
                self.reset_round(now,scope['ptr'],'player changed')
            self.scope_player = scope['ptr']
        self.observe_blasts(snap,now)
        prior = self.last_blast_snapshot if self.last_blast_snapshot and 0 <= now-self.last_blast_at <= 1. else snap
        self.last_blast_snapshot = {'player':dict(scope), 'enemies':[dict(e) for e in snap.get('enemies',())]}
        self.last_blast_at = now
        ground = ground_mines(self.m)
        snap['ground_mines'] = ground
        exploding = {ptr for ptr, row in ground.items() if row['detonating']}
        if self.escape is not None:
            actor = self.escape['actor']
            witnessed = actor in exploding or actor in self.detonating or any(
                event.get('kind') == 'detonation_observed' and event.get('actor') == actor for event in self.events)
            if witnessed:
                self.escape['detonation_observed'] = True
            player = snap.get('player') or {}
            position = player.get('pos')
            nearby = position is not None and any(math.dist(position,row['pos'])<600. for row in ground.values())
            if actor not in ground and self.escape.get('detonation_observed') and position is not None and not nearby:
                self.event('retreat_hazard_removed',now,actor=actor,pos=position,
                           reason='exact actor detonation witnessed then actor removed; no nearby mine remains',
                           escape_completed=False,distance=math.dist(position,self.escape['pos']))
                self.stats['mine_escapes_unachieved'] = self.stats.get('mine_escapes_unachieved',0)+1
                self.escape = None
        for ptr in exploding-self.detonating:
            self.event('detonation_observed', now, actor=ptr, pos=ground[ptr]['pos'],
                       owned=ptr in self.owned, combo=snap.get('combo'), score=snap.get('score'))
            if ptr in self.owned:
                position = ground[ptr]['pos']
                self.learn(position,'detonations')
                p = snap.get('player') or {}
                self.blast_windows.append({'actor':ptr,'pos':position,'at':now,
                    'hp':(prior.get('player') or p).get('hp',0),
                    'damage':False,'enemies':{e['ptr'] for e in prior.get('enemies',()) if e.get('ptr') is not None
                        and (e.get('hp') or 0)>0 and math.dist(position,e['pos']) <= 1000.}})
                del self.blast_windows[:-32]
        self.observe_blasts(snap,now)
        for ptr in set(self.owned)-set(ground):
            old = self.owned.pop(ptr)
            self.event('actor_disappeared', now, actor=ptr, pos=old['pos'],
                       cause='unknown; disappearance alone does not prove explosion or kill')
        self.stats['mine_detonations_observed'] = self.stats.get('mine_detonations_observed', 0) + len(exploding-self.detonating)
        self.detonating = exploding
        self.stats['mine_ground_count'] = len(ground)
        self.stats['mine_armed_count'] = sum(row['arming_s'] <= 0 and not row['detonating'] for row in ground.values())
        if now-self.config_at >= 2:
            cfg = settings(); self.cadence.configure(cfg["interval_s"], cfg["only"], cfg["enabled"])
            self.config_at = now
        self.stats.update(mine_interval_s=self.cadence.interval, mines_only=self.cadence.only,
                          mines_enabled=self.cadence.enabled)
        if not self.cadence.enabled:
            self.pending = None
            self.restore = None
            return None
        p = snap.get("player")
        busy = not p or snap.get("recovery_active") or snap.get("prompt") or snap.get("stage_prompt") \
            or p.get("action") in (4,5) or (p.get("hp") or 0) <= 0
        if busy:
            self.prepare_at = None
            return None
        if self.restore is not None:
            gun = next((w for w in snap.get("inventory", ())
                        if W.inventory_key(w) == self.restore), None)
            if gun is None or gun.get("hand"):
                self.restore = None
            else:
                if now < self.restore_after or p.get("action") not in (0, 1):
                    return {"hold":set()}
                return self.switch(gun, now, "restore gun after mine") or {"hold":set()}
        choices = [w for w in snap.get("inventory", ()) if w.get("id") == 0x10A and W.quick_key(w)]
        # A costume can carry several storage records: the equipped stack owns consumption.
        mine = next((w for w in choices if self.pending and w['slot'] == self.pending['slot']), None) \
            or next((w for w in choices if w.get('hand')), None) or next(iter(choices), None)
        if mine is None:
            self.stats["mine_status"] = "Waiting for the next game-created mine loadout"
            return None
        if self.pending:
            pen = self.pending
            if mine["slot"] != pen["slot"] or p["ptr"] != pen["player"]:
                self.pending = None
                return None
            deployed = {ptr: row for ptr, row in ground.items() if ptr not in pen['before']
                        and math.dist(row['pos'], pen['pos']) < 250}
            pen['deployed'].update(deployed)
            infinite = False
            ad = getattr(self.m,'adapter',None)
            if ad is not None and pen['deployed']:
                from ... import re5_mods_tool as mods
                verified = mods.RE5(ad)
                infinite = verified.u32(mods.DEF_TABLE+0x0A*mods.DEF_STRIDE+mods.DEF_NOAMMO) == 1
            if (mine["rounds"] < pen["count"] or infinite) and pen['deployed']:
                self.stats["mines_placed"] = self.stats.get("mines_placed",0)+len(pen['deployed'])
                self.stats['mine_infinite_supply_verified'] = infinite
                self.stats["mine_status"] = "Ground Proximity Bomb verified; returning to gunplay"
                self.stats['mine_last_ground_actor'] = hex(next(iter(pen['deployed'])))
                for ptr in pen['deployed']:
                    self.owned[ptr] = dict(ground.get(ptr, {'pos':pen['pos']}))
                actor = next(iter(pen['deployed']))
                self.escape = {'pos': tuple(pen['pos']), 'actor': actor, 'at': now}
                self.event('placement_verified', now, actor=actor, pos=pen['pos'],
                           hp=p.get('hp'), combo=snap.get('combo'), score=snap.get('score'))
                self.learn(pen['pos'],'placements')
                self.cadence.acknowledge(now,p["pos"])
                if ad is not None and not infinite and not getattr(self.m, 'mercs_no_modifications', False):
                    from ...re5_mods_tool import RE5, INV_OFS, SLOT
                    g=RE5(ad); addr=p["ptr"]+INV_OFS+mine["slot"]*SLOT+0xC
                    if g.u32(addr) == mine["rounds"]:
                        self.stats["mine_refill_verified"] = g.wr(addr,struct.pack(">I",5))
                self.pending = None
                gun = next((w for w in snap.get("inventory",()) if W.quick_key(w) and w.get("type")==1
                            and w.get("item") in W.WEAPONS and W.WEAPONS[w["item"]].family in W.DIRECT), None)
                if gun and not self.cadence.only:
                    self.restore = W.inventory_key(gun)
                    self.restore_after = now + 1.2
                    return {"hold":set()}
                return {"hold":set()}
            if now-pen["at"] > 5:
                self.event('placement_unconfirmed', now, pos=pen['pos'])
                self.stats["mine_status"] = "Placement unconfirmed; retry deferred"
                self.pending=None; self.retry_at=now+5
                return {"hold":set()}
            age=now-pen["at"]
            # Type D's displayed "L1 Place" is the whole command. R1 can cancel it.
            # Release as soon as consumption starts so holding L1 cannot plant a second mine.
            return {"hold": {'l1'} if mine['rounds'] == pen['count'] and age < 1.2 else set()}
        if self.escape is not None:
            self.clear_escape(now, p['pos'])
            if self.escape is not None:
                self.stats['mine_status'] = 'Leaving planted mine; further placement deferred'
                return None
        if now < self.retry_at or not self.cadence.due(now,p["pos"]):
            return None
        if self.learning is not None and self.mesh is not None:
            site = self.learning.mine_site(self.mesh,p['pos'])
            self.stats['mine_site_evidence'] = site
            if site['defer']:
                self.stats['mine_status'] = 'Moving past a deployment site with repeated observed damage'
                return None
        # Bot supplies a current measured floor-route preflight before equipping.
        # Legacy standalone callers can omit it; an explicit negative never plants.
        if snap.get('mine_placement_safe') is False:
            self.stats['mine_status'] = 'Placement deferred: no measured floor escape route'
            self.prepare_at = None
            return None
        # Leave room to retreat; a nearby explosion can stagger even a modified character.
        if any((e.get("hp") or 0)>0 and math.dist(p["pos"],e["pos"])<350 for e in snap.get("enemies",())):
            self.stats["mine_status"] = "Waiting for deployment space"
            return None
        if not mine.get("hand"):
            self.stats["mine_status"] = "Equipping proximity bomb"
            if now < self.equip_until:
                return {"hold":set()}
            if self.prepare_at is None:
                self.prepare_at = now
                return {"hold":set()}
            # Aiming/fire recovery can outlive P_ACTION=stand. A full neutral second
            # was verified live to make the same D-pad tap equip reliably.
            if now-self.prepare_at < 1.0 or p.get("action") not in (0, 1):
                if now-self.prepare_at > 2:
                    self.prepare_at = None
                    self.retry_at = now + 2
                    return None
                return {"hold":set()}
            action = self.switch(mine,now,"scheduled proximity bomb")
            self.prepare_at = None
            if action is not None:
                self.equip_until = now + 3
            else:
                # The weapon switcher may be backing off a failed change. Do not
                # repeatedly freeze navigation while its cooldown is still running.
                self.retry_at = now + 5
            return action
        self.pending={"at":now,"count":mine["rounds"],"slot":mine["slot"],"player":p["ptr"],
                      'pos':p['pos'], 'before':set(ground), 'deployed':set()}
        self.stats["mine_attempts"]=self.stats.get("mine_attempts",0)+1
        self.event('placement_attempt', now, pos=p['pos'], hp=p.get('hp'),
                   combo=snap.get('combo'), score=snap.get('score'))
        return {"hold":{"l1"}}
