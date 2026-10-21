"""One frame of a fight, in the engine's terms: World(frame, screen, p1, p2) from one batched RAM read."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import vocab


@dataclass
class Attack:
    """An attack that is out (the attacker's move / class / attack record says so)."""
    kind: str = "strike"                      # strike / throw / hold / special
    height: str | None = None                 # high / mid / low
    limb: str | None = None                   # punch / kick
    phase: str | None = None                  # startup / active / recovery
    start: int | None = None                  # first active frame (move-relative)
    end: int | None = None                    # last active frame
    frame: int | None = None                  # the move's frame now
    lead: int | None = None                   # frames from onset to the first active frame (signature lead_f)
    move: int | None = None
    tags: dict = field(default_factory=dict)

    def to_active(self, since_onset: int = 0) -> int | None:
        """Frames until the first active frame: exact from start / frame, else lead minus the frames since onset."""
        if self.start is not None and self.frame is not None:
            return self.start - self.frame
        if self.lead is not None:
            return self.lead - since_onset
        return None

    def cls(self) -> str:
        """The attack class the book learns per when a move is new: 'strike:mid:kick', 'throw:high' ..."""
        return ":".join(p for p in (self.kind, self.height, self.limb) if p)


@dataclass
class Fighter:
    hp: int | None = None
    hp_max: int | None = None
    chara: int | None = None
    pos: tuple | None = None
    side: int | None = None                   # +1 left (facing right), -1 right
    state: int | None = None
    move: int | None = None
    move_class: int | None = None
    move_frame: int | None = None
    hit: int | None = None
    input: int | None = None
    warn: int | None = None
    tags: dict = field(default_factory=dict)  # merged state / move / class / hit tags
    attack: Attack | None = None

    def has(self, *names) -> bool:
        st = self.tags.get("state")
        st = [st] if isinstance(st, str) else (st or [])
        return any(n in st or self.tags.get(n) for n in names)

    def can_act(self) -> bool:
        """Free to start an answer: not hit, held, thrown, down or KO (unknown counts as free)."""
        return not self.has("hitstun", "held", "thrown", "down", "ko", "stagger") or self.has("can_act")


@dataclass
class World:
    frame: int | None
    t: float
    screen: str
    p1: Fighter
    p2: Fighter
    values: object = None

    @property
    def distance(self) -> float | None:
        a, b = self.p1.pos, self.p2.pos
        if not a or not b:
            return None
        return sum((x - y) ** 2 for x, y in ((a[0], b[0]), (a[-1], b[-1]))) ** 0.5   # floor plane (x, z)


def _tagged(values, rmap, name):
    """(value, raw, tags) of a map field (None when unmapped / unreadable)."""
    if not name or name not in rmap.fields:
        return None, None, {}
    v = values.get(name)
    raw = values.raw.get(name)
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    return v, raw, vocab.tags(rmap.fields[name], raw if raw is not None else (v if isinstance(v, int) else None))


def fighter(values, rmap, mapping: dict, who: str) -> Fighter:
    """A Fighter from one map read through the fight block's vocab (p1.* / p2.*)."""
    get = lambda n: mapping.get(f"{who}.{n}")                       # noqa: E731
    f = Fighter()
    tags: dict = {}
    for n in ("hp", "hp_max", "chara", "side", "move_frame", "input", "warn"):
        v, _, t = _tagged(values, rmap, get(n))
        setattr(f, n, v)
        tags.update(t)
    pos, _, _ = _tagged(values, rmap, get("pos"))
    f.pos = tuple(pos) if isinstance(pos, list) else None
    for n in ("state", "move", "move_class", "hit"):
        v, raw, t = _tagged(values, rmap, get(n))
        setattr(f, n, raw if raw is not None else v)
        if t:
            st = t.get("state")
            if st:
                cur = tags.get("state")
                cur = [cur] if isinstance(cur, str) else list(cur or [])
                t = {**t, "state": cur + ([st] if isinstance(st, str) else list(st))}
            tags.update(t)
    rec, _, _ = _tagged(values, rmap, get("attack"))
    height, _, htags = _tagged(values, rmap, get("attack_height"))
    start, _, _ = _tagged(values, rmap, get("attack_start"))
    end, _, _ = _tagged(values, rmap, get("attack_end"))
    f.tags = tags
    if rec or tags.get("attack"):                                   # an attack record, or an attack-tagged move
        merged = {**tags, **htags}
        act = merged.get("active") if isinstance(merged.get("active"), list) else None
        f.attack = Attack(kind=merged.get("attack") or "strike", height=merged.get("height"), limb=merged.get("limb"),
                          phase=merged.get("phase"), start=start if rec else (act[0] if act else None),
                          end=end if rec else (act[1] if act else None), frame=f.move_frame,
                          lead=merged.get("lead_f"), move=f.move, tags=merged)
    return f


def read(rmap, values, frame, t, screen: str) -> World:
    mapping = (rmap.spec.get("fight") or {}).get("vocab") or {}
    return World(frame=frame, t=t, screen=screen, p1=fighter(values, rmap, mapping, "p1"),
                 p2=fighter(values, rmap, mapping, "p2"), values=values)
