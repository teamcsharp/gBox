"""The GoldenEye 007 PC port's gBox bridge, Python side: the shared-memory block gbox_bridge.c creates.

The port (built with system/adapters/ge007_port/gbox_bridge.c, see gbox/native_ports.py) creates the block named by
GE_GBOX_BRIDGE and writes the game state every frame; gBox maps it, reads the state and writes buttons + stick for
the seats it drives (bots on seats 1-3, player 1 when gBox plays or forwards streamed input).

Layout, little endian, GBX_VERSION 1 (keep in step with gbox_bridge.c; the sizes are asserted below):

    0      header (64 B): magic "GBX1", version, size, frame, stage, nplayers, in_match, nav_serial,
                          num_nodes, num_edges, num_items, num_chrs, pid, reserved[3]
    64     players[4]  x 80 B: pos xyz, theta, verta, health, armour, dead, weapon, room, near_node, visible,
                               kills, deaths, points, flags, ammo, mag, pad[2]
    384    seats[4]    x 16 B: seq, enabled, buttons (u16), sx, sy (s8), live
    448    items[64]   x 16 B: pos xyz, item
    1472   chrs[32]    x 32 B: pos xyz, alive, visible, health, pad[2]
    2496   nodes[1024] x 24 B: pos xyz, first, count, kind (0 pad, 1 bound pad, 2 floor tile)
    27072  edges[16384] x i32
    92608  end

World units are about a centimetre; theta is the player's yaw in degrees as the game keeps it (vv_theta).
"""
import math
import mmap
import os
import struct
import sys
import time
from dataclasses import dataclass, field

MAGIC = 0x31584247            # b"GBX1"
VERSION = 1
SIZE = 92608
PLAYERS = 4

HEADER = struct.Struct("<4I3iI4iI3I")
PLAYER = struct.Struct("<7f4iI3iI4i")
SEAT = struct.Struct("<IIHbbI")
ITEM = struct.Struct("<3fi")
CHR = struct.Struct("<3fiIf2i")
NODE = struct.Struct("<3f3i")
OFF_PLAYERS, OFF_SEATS, OFF_ITEMS, OFF_CHRS, OFF_NODES, OFF_EDGES = 64, 384, 448, 1472, 2496, 27072
MAX_ITEMS, MAX_CHRS, MAX_NODES, MAX_EDGES = 64, 32, 1024, 16384
assert HEADER.size == 64 and PLAYER.size == 80 and SEAT.size == 16 and ITEM.size == 16
assert CHR.size == 32 and NODE.size == 24
assert OFF_SEATS == OFF_PLAYERS + 4 * PLAYER.size and OFF_ITEMS == OFF_SEATS + 4 * SEAT.size
assert OFF_CHRS == OFF_ITEMS + MAX_ITEMS * ITEM.size and OFF_NODES == OFF_CHRS + MAX_CHRS * CHR.size
assert OFF_EDGES == OFF_NODES + MAX_NODES * NODE.size and SIZE == OFF_EDGES + 4 * MAX_EDGES

# N64 controller buttons (libultra CONT_*), as the bridge seats take them
A, B, Z, START = 0x8000, 0x4000, 0x2000, 0x1000
DU, DD, DL, DR = 0x0800, 0x0400, 0x0200, 0x0100
L, R = 0x0020, 0x0010
CU, CD, CL, CR = 0x0008, 0x0004, 0x0002, 0x0001
STICK_MAX = 80

# ITEM_IDS (src/bondconstants.h) that a multiplayer bot can hold
ITEMS = {0: "unarmed", 1: "fist", 2: "knife", 3: "throwing knife", 4: "PP7", 5: "PP7 silenced", 6: "DD44",
         7: "Klobb", 8: "KF7 Soviet", 9: "ZMG", 10: "D5K", 11: "D5K silenced", 12: "Phantom", 13: "AR33",
         14: "RC-P90", 15: "shotgun", 16: "automatic shotgun", 17: "sniper rifle", 18: "Cougar Magnum",
         19: "Golden Gun", 20: "silver PP7", 21: "gold PP7", 22: "Moonraker laser", 23: "watch laser",
         24: "grenade launcher", 25: "rocket launcher", 26: "hand grenade", 27: "timed mine",
         28: "proximity mine", 29: "remote mine", 31: "taser"}


@dataclass
class Player:
    index: int
    present: bool
    pos: tuple = (0.0, 0.0, 0.0)
    theta: float = 0.0
    verta: float = 0.0
    health: float = 0.0
    armour: float = 0.0
    dead: bool = False
    weapon: int = -1
    room: int = -1
    near_node: int = -1
    visible: int = 0                 # bit j: player j is in line of sight
    kills: int = 0
    deaths: int = 0
    points: int = 0
    on_floor: bool = False
    ammo: int = -1                   # rounds for the weapon in hand; -1 = it needs none
    mag: int = 0

    def sees(self, j: int) -> bool:
        return bool(self.visible >> j & 1)


@dataclass
class Item:
    pos: tuple
    item: int


@dataclass
class Chr:
    pos: tuple
    alive: bool
    visible: int
    health: float


@dataclass
class Snapshot:
    frame: int
    stage: int
    nplayers: int
    in_match: bool
    nav_serial: int
    players: list
    items: list = field(default_factory=list)
    chrs: list = field(default_factory=list)
    seats_live: tuple = (False, False, False, False)
    pid: int = 0


@dataclass
class Nav:
    """The bridge's navigation graph: pads linked where a straight walk is clear (multiplayer has no waypoints)."""
    serial: int
    nodes: list                      # (x, y, z)
    adj: list                        # adj[i] = [j, ...]
    kinds: list = field(default_factory=list)


def heading_deg(theta: float) -> float:
    """The game's facing as a bearing in the atan2(dx, dz) convention the AI uses (yaw = 360 - vv_theta)."""
    return (360.0 - theta) % 360.0


def bearing_deg(frm, to) -> float:
    """Bearing from one position to another, atan2(dx, dz) in degrees 0..360 (chraction.c's convention)."""
    return math.degrees(math.atan2(to[0] - frm[0], to[2] - frm[2])) % 360.0


def parse_header(buf) -> tuple:
    return HEADER.unpack_from(buf, 0)


def parse_snapshot(buf) -> Snapshot:
    (magic, version, size, frame, stage, nplayers, in_match, nav_serial, num_nodes, num_edges, num_items, num_chrs,
     pid, *_rest) = HEADER.unpack_from(buf, 0)
    if magic != MAGIC or version != VERSION or size != SIZE:
        raise ValueError(f"not a version {VERSION} gBox bridge block (magic {magic:#x}, version {version}, size {size})")
    players = []
    for i in range(PLAYERS):
        (x, y, z, theta, verta, health, armour, dead, weapon, room, near, visible, kills, deaths, points,
         flags, ammo, mag, _p0, _p1) = PLAYER.unpack_from(buf, OFF_PLAYERS + i * PLAYER.size)
        players.append(Player(i, bool(flags & 1), (x, y, z), theta, verta, health, armour, bool(dead), weapon, room,
                              near, visible, kills, deaths, points, bool(flags & 2), ammo, mag))
    items = [Item(tuple(v[:3]), v[3]) for v in
             (ITEM.unpack_from(buf, OFF_ITEMS + k * ITEM.size) for k in range(max(0, min(num_items, MAX_ITEMS))))]
    chrs = [Chr(tuple(v[:3]), bool(v[3]), v[4], v[5]) for v in
            (CHR.unpack_from(buf, OFF_CHRS + k * CHR.size) for k in range(max(0, min(num_chrs, MAX_CHRS))))]
    live = tuple(bool(SEAT.unpack_from(buf, OFF_SEATS + s * SEAT.size)[5]) for s in range(PLAYERS))
    return Snapshot(frame, stage, nplayers, bool(in_match), nav_serial, players, items, chrs, live, pid)


def parse_nav(buf) -> Nav:
    head = HEADER.unpack_from(buf, 0)
    serial, num_nodes, num_edges = head[7], max(0, min(head[8], MAX_NODES)), max(0, min(head[9], MAX_EDGES))
    edges = struct.unpack_from(f"<{num_edges}i", buf, OFF_EDGES) if num_edges else ()
    nodes, adj, kinds = [], [], []
    for i in range(num_nodes):
        x, y, z, first, count, kind = NODE.unpack_from(buf, OFF_NODES + i * NODE.size)
        nodes.append((x, y, z))
        kinds.append(kind)
        adj.append([j for j in edges[first:first + count] if 0 <= j < num_nodes] if 0 <= first <= num_edges else [])
    return Nav(serial, nodes, adj, kinds)


class Bridge:
    """A mapped bridge block. `where` is a file path on Linux (the port creates it), a mapping name on Windows."""

    def __init__(self, where: str):
        self.where = where
        self.mm = None
        self._seq = [0] * PLAYERS
        self._nav = None

    def open(self, timeout: float = 60.0, stopped=lambda: False, sleep=time.sleep) -> bool:
        """Map the block once the port has created it and stamped the magic; False on timeout."""
        end = time.monotonic() + timeout
        while time.monotonic() < end and not stopped():
            try:
                if self.mm is None:
                    self.mm = self._map()
                if self.mm is not None and struct.unpack_from("<I", self.mm, 0)[0] == MAGIC:
                    return True
            except (OSError, ValueError):
                self.mm = None
            sleep(0.25)
        return False

    def _map(self):
        if sys.platform == "win32":
            return mmap.mmap(-1, SIZE, tagname=self.where)
        if not os.path.exists(self.where) or os.path.getsize(self.where) < SIZE:
            return None
        fd = os.open(self.where, os.O_RDWR)
        try:
            return mmap.mmap(fd, SIZE)
        finally:
            os.close(fd)

    def snapshot(self) -> Snapshot:
        if self.mm is None:
            raise ValueError("the bridge is closed")
        return parse_snapshot(self.mm)

    def nav(self, serial: int | None = None) -> Nav | None:
        """The current navigation graph (re-read only when the port published a new one)."""
        if self.mm is None:
            return self._nav
        serial = HEADER.unpack_from(self.mm, 0)[7] if serial is None else serial
        if not serial:
            return None
        if self._nav is None or self._nav.serial != serial:
            nav = parse_nav(self.mm)
            if nav.serial != serial:                 # published while we read: take it next time
                return self._nav
            self._nav = nav
        return self._nav

    def drive(self, seat: int, buttons: int = 0, sx: int = 0, sy: int = 0):
        """Give seat `seat` these buttons and stick (until the next call); the port takes them while seq moves."""
        if self.mm is None:
            return
        sx = max(-STICK_MAX, min(STICK_MAX, int(sx)))
        sy = max(-STICK_MAX, min(STICK_MAX, int(sy)))
        base = OFF_SEATS + seat * SEAT.size
        struct.pack_into("<IHbb", self.mm, base + 4, 1, buttons & 0xFFFF, sx, sy)
        self._seq[seat] = (self._seq[seat] + 1) & 0xFFFFFFFF
        struct.pack_into("<I", self.mm, base, self._seq[seat])

    def release(self, seat: int):
        """Hand the seat back to its pad (player 1) or leave it idle (a bot seat)."""
        if self.mm is None:
            return
        base = OFF_SEATS + seat * SEAT.size
        struct.pack_into("<IHbb", self.mm, base + 4, 0, 0, 0, 0)
        self._seq[seat] = (self._seq[seat] + 1) & 0xFFFFFFFF
        struct.pack_into("<I", self.mm, base, self._seq[seat])

    def close(self):
        if self.mm is not None:
            try:
                for s in range(PLAYERS):
                    self.release(s)
                self.mm.close()
            except (ValueError, OSError):
                pass
            self.mm = None
