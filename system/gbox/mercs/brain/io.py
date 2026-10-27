"""What the combat core reads from a title beyond its snapshot: the title IO.

The RE5 PS3 combat layer (gbox/mercs/titles/re5_combat.py, Combat) takes io=: every RAM read it makes goes through it.
re5_combat.PS3IO is the PS3's (its original reads); another title passes its own, built on NullIO, which answers from the
snapshot alone and reads nothing:

    player_index()        0: the solo / first player's view (1: a second player's; None: unknown)
    player_ptr()          the scoped player's id (0: none)
    action(pl)            (kind, frames) of the player's current action object (the PS3's weapon-fire / ready / reload
                          action and its frame counter), or None when the title has no such reader
    in_hand(pl)           (weapon id, rounds, an item in hand) when the snapshot carried no inventory; None
    fire_command(pl)      the title's per-frame fire signal: 4 on a frame a shot leaves, else 0
    second_player()       another player could have damaged the enemies (shots are then not attributed)
    character(pl)         the character's name (the calibration and the tunables are kept per character)
    read_laser(now)       (origin, dot) read directly when the snapshot has no "laser" key; None
    rapid_fire(wid)       the fire-rate mod is on for this weapon (True / False)
    read_pitch(pl), write_pitch(pl, value)   the aim pitch (only with the combat layer's PITCH_WRITE)
    laser, writer         objects with read(now) / ok + write(addr, data) (the PS3's Laser and Writer)
"""
from __future__ import annotations


class NullLaser:
    def read(self, now):
        return None


class NullWriter:
    ok = False

    def write(self, addr, data) -> bool:
        return False


class NullIO:
    """A title whose snapshot carries everything: no RAM reads. bind(snap) each tick gives the player's id."""

    def __init__(self):
        self.laser, self.writer = NullLaser(), NullWriter()
        self.snap: dict = {}

    def bind(self, snap: dict) -> None:
        self.snap = snap or {}

    def player_index(self):
        return 0

    def player_ptr(self) -> int:
        p = self.snap.get("player") or {}
        return p.get("ptr") or 0

    def action(self, pl):
        return None

    def in_hand(self, pl):
        return None

    def fire_command(self, pl) -> int:
        return 0

    def second_player(self) -> bool:
        return False

    def character(self, pl) -> str:
        return "?"

    def read_laser(self, now):
        return None

    def rapid_fire(self, wid) -> bool:
        return False

    def read_pitch(self, pl):
        return None

    def write_pitch(self, pl, value) -> bool:
        return False
