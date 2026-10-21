"""The world as the engines see it (docs/mercenaries_engine.md, section 2): one RAM read of a title's map through
ram_map, put into the shared vocabulary, with each enemy's signature tags.

    from gbox.mercs import vocab, world
    prof = vocab.profile("G4BE08")
    w = world.read(prof, reader, driver=None, now=time.time())
    w.screen, w.timer, w.player.pos, [e.sig for e in w.enemies]

Positions stay in the title's world units; headings become radians in the atan2(dx, dz) convention (0 = +z, + toward
+x) from the map's mercs.heading; times are seconds. A name the title leaves unknown is None.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import vocab as V


@dataclass
class Player:
    pos: tuple
    facing: float = 0.0
    hp: int | None = None
    hp_max: int | None = None
    state: int | None = None
    tags: frozenset = frozenset()
    aim_pitch: float | None = None
    weapon: int | None = None
    ammo: int | None = None
    aim_offset: float | None = None        # the aim's own horizontal offset from the facing (counts while aiming)

    @property
    def aim_facing(self) -> float:
        """Where the gun points: the facing plus the aim's offset while aiming (a stale offset after, ignored)."""
        if "aiming" in self.tags and self.aim_offset is not None and abs(self.aim_offset) < 0.5:
            return self.facing + self.aim_offset
        return self.facing


@dataclass
class Enemy:
    id: int
    pos: tuple
    facing: float | None = None
    hp: int | None = None
    hp_max: int | None = None
    type: int | None = None
    state: int | None = None
    act: int | None = None
    motion: int | None = None
    frame: float | None = None
    frames: int | None = None
    speed: float | None = None
    events: int = 0
    target: int | None = None
    tags: frozenset = frozenset()
    sig: dict | None = None                    # the attack signature of its state / act right now
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def dying(self) -> bool:
        return (self.hp is not None and self.hp <= 0) or bool(self.tags & {"dying", "gone"})


@dataclass
class Projectile:
    id: int
    pos: tuple
    kind: str | None = None
    owner: int | None = None
    state: int | None = None


@dataclass
class Prompt:
    kind: int
    button: str | None = None
    tags: dict = field(default_factory=dict)


@dataclass
class Bonus:
    id: int
    pos: tuple
    kind: str | None = None
    taken: bool = False


@dataclass
class World:
    t: float
    screen: str
    player: Player | None
    enemies: list = field(default_factory=list)
    projectiles: list = field(default_factory=list)
    prompt: Prompt | None = None
    bonuses: list = field(default_factory=list)
    drops: list = field(default_factory=list)
    stage: object = None
    timer: float | None = None
    combo: int | None = None
    combo_timer: float | None = None
    score: int | None = None
    kills: int | None = None
    partner: Player | None = None
    values: object = None


def heading_fn(mercs: dict):
    """The title's facing -> radians atan2(dx, dz). mercs.heading: {"zero": "+z"|"+x"|"-z"|"-x", "positive":
    "toward +x"|"toward -x"|..., "units": "rad"|"deg"|"bam16"}."""
    h = mercs.get("heading") or {}
    zero = {"+z": 0.0, "+x": math.pi / 2, "-z": math.pi, "-x": -math.pi / 2}.get(h.get("zero", "+z"), 0.0)
    pos = h.get("positive", "toward +x")
    sign = 1.0
    if zero in (0.0, math.pi):
        sign = 1.0 if ("+x" in pos) == (zero == 0.0) else -1.0
    else:
        sign = 1.0 if ("-z" in pos) == (zero > 0) else -1.0
    units = h.get("units", "rad")
    scale = {"rad": 1.0, "deg": math.pi / 180.0, "bam16": math.pi / 32768.0}.get(units, 1.0)

    def f(v):
        if v is None:
            return None
        return (zero + sign * float(v) * scale + math.pi) % (2 * math.pi) - math.pi
    return f


def _sig_of(fdef, value):
    sigs = getattr(fdef, "signatures", None) or {}
    try:
        return sigs.get(int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _tags(sig: dict | None) -> set:
    return {k for k, v in (sig or {}).items() if v is True}


def read(prof: V.Profile, reader, driver=None, now: float = 0.0, values=None) -> World:
    """One read of the title's map -> World. driver: fills the names the vocab leaves to it (screen, prompt.button)."""
    vals = values if values is not None else prof.rmap.read(reader)
    fields = prof.rmap.fields
    hfn = heading_fn(prof.mercs)

    def top(name):
        f = prof.field(name)
        return vals.get(f) if f not in (None, "driver") else None

    pf = prof.field("player.pos")
    player = None
    if pf and vals.get(pf):
        state = top("player.state")
        sdef = fields.get(prof.field("player.state") or "")
        ptags = _tags(_sig_of(sdef, state))
        player = Player(pos=tuple(vals[pf]), facing=hfn(top("player.facing")) or 0.0, hp=top("player.hp"),
                        hp_max=top("player.hp_max"), state=state, tags=frozenset(ptags),
                        aim_pitch=top("player.aim_pitch"), weapon=top("player.weapon"), ammo=top("player.ammo"),
                        aim_offset=top("player.aim_offset"))
    enemies = []
    arr = prof.field("enemies")
    edef = fields.get(arr) if arr not in (None, "driver") else None
    for row in (vals.get(arr) or []) if edef else []:
        def sub(name):
            s = prof.field("enemies." + name)
            return row.get(s) if s not in (None, "driver") else None
        st, act = sub("state"), sub("act")
        ssig = _sig_of(edef.fields.get(prof.field("enemies.state") or ""), st)
        asig = _sig_of(edef.fields.get(prof.field("enemies.act") or ""), act) if (ssig or {}).get("acting", True) else None
        tags = _tags(ssig) | _tags(asig)
        attack = asig if asig and asig.get("attack") else (ssig if ssig and ssig.get("attack") else None)
        pos = sub("pos")
        if pos is None:
            continue
        enemies.append(Enemy(id=row.get("index"), pos=tuple(pos), facing=hfn(sub("facing")), hp=sub("hp"),
                             hp_max=sub("hp_max"), type=sub("type"), state=st, act=act, motion=sub("motion"),
                             frame=sub("motion_frame"), frames=sub("motion_frames"), speed=sub("motion_speed"),
                             events=int(sub("motion_events") or 0), target=sub("target"), tags=frozenset(tags),
                             sig=attack, raw=row))
    projectiles = []
    parr = prof.field("projectiles")
    for row in (vals.get(parr) or []) if parr not in (None, "driver") else []:
        ps = prof.field("projectiles.pos")
        if row.get(ps) is None:
            continue
        projectiles.append(Projectile(id=row.get("index"), pos=tuple(row[ps]),
                                      kind=row.get(prof.field("projectiles.kind") or ""),
                                      owner=row.get(prof.field("projectiles.owner") or ""),
                                      state=row.get("state")))
    prompt = None
    pk = top("prompt.kind")
    if pk:
        kdef = fields.get(prof.field("prompt.kind") or "")
        sig = _sig_of(kdef, pk) or {}
        button = top("prompt.button")
        if button is None and driver is not None and prof.field("prompt.button") == "driver":
            button = driver.prompt_button(pk, vals)
        prompt = Prompt(kind=pk, button=button, tags=sig)
    screen = top("screen")
    if prof.field("screen") == "driver" and driver is not None:
        screen = driver.screen(reader, None)
    elif screen is not None:
        sdef = fields.get(prof.field("screen"))
        screen = sdef.label(vals.raw.get(prof.field("screen"))) if sdef else str(screen)
    return World(t=now, screen=screen or "playing", player=player, enemies=enemies, projectiles=projectiles,
                 prompt=prompt, stage=top("merc.stage"), timer=top("merc.timer"), combo=top("merc.combo"),
                 combo_timer=top("merc.combo_timer"), score=top("merc.score"), kills=top("merc.kills"),
                 values=vals)
