"""A synthetic RE4 stage for the room-collision mesh tests: built by gbox.re4_switch_nav.build_mesh from a hand-made
GameCube-navmap grid (re4_navmap.NavGrid), so the tests run the real builder, mesh and walker on known geometry.

    6 m x 4 m of floor at y 0, 200 mm cells (30 x 20), x to the right, z up:
    * a wall down column ix 15 (x 3000-3200) with a 600 mm door at iz 8-10 (z 1600-2200): two rooms;
    * a fence (VAULT cells) along iz 4 (z 800-1000) across the left room: its bottom strip (z 0-800) is reached only
      by jumping the fence;
    * a platform at y 3000 over ix 20-24, iz 14-18 (x 4000-5000, z 2800-3800), reached only by a ladder whose stand
      is the cell below it (x 4500, z 2700, facing +z).
"""
from __future__ import annotations

import base64
import zlib

import numpy as np

from gbox import re4_navmap as N
from gbox import re4_switch_nav as B
from gbox.mercs.titles import re4_nav

CELL, NX, NZ = 200.0, 30, 20
WALL_X, DOOR, FENCE_Z = 15, (8, 9, 10), 4
PLATFORM_X, PLATFORM_Z, PLATFORM_Y = range(20, 25), range(14, 19), 3000.0
LADDER = {"kind": "ladder", "pos": [4500.0, 0.0, 2700.0], "top": [4500.0, 3000.0, 2700.0], "facing": 0.0,
          "rungs": 3, "source": "AEV[0]"}


def grid() -> N.NavGrid:
    lc, lh, ls, lr = [], [], [], []
    for iz in range(NZ):
        for ix in range(NX):
            c = iz * NX + ix
            if ix == WALL_X and iz not in DOOR:
                state = N.WALL
            elif iz == FENCE_Z and ix < WALL_X:
                state = N.VAULT
            else:
                state = N.FREE
            lc.append(c)
            lh.append(0.0)
            ls.append(state)
            lr.append(2)
            if ix in PLATFORM_X and iz in PLATFORM_Z:
                lc.append(c)
                lh.append(PLATFORM_Y)
                ls.append(N.FREE)
                lr.append(2)
    return N.NavGrid(0.0, 0.0, NX, NZ, lc, lh, ls, lr, CELL)


def collision() -> dict:
    """The floor the vertex heights are sampled from: the ground and the platform's top."""
    V = np.array([[-1000, 0, -1000], [7000, 0, -1000], [7000, 0, 5000], [-1000, 0, 5000],
                  [4000, PLATFORM_Y, 2800], [5000, PLATFORM_Y, 2800], [5000, PLATFORM_Y, 3800], [4000, PLATFORM_Y, 3800]],
                 np.float64)
    T = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], np.int64)
    return {"verts": V, "tris": T, "normals": np.tile([0.0, 1.0, 0.0], (4, 1)), "attr": np.zeros(4, np.uint32)}


def mesh_dict() -> dict:
    return B.build_mesh(grid(), collision(), [LADDER])


WALLS = [[3000, 0, 3000, 1600, 0, 2600, 0], [3000, 2200, 3000, 4000, 0, 2600, 0],    # the dividing wall, both sides of
         [3200, 0, 3200, 1600, 0, 2600, 0], [3200, 2200, 3200, 4000, 0, 2600, 0],    # the door
         [0, 900, 3000, 900, 0, 1000, 0x20]]                                         # the fence (a VAULT_BITS wall)


def stage_json(room: str = "r400", shift: float = 0.0) -> dict:
    """The fixture as a stage file (re4_nav.from_json), its x shifted by `shift` mm."""
    m = mesh_dict()
    P = np.round(np.array(m["points"]) + [shift, 0.0, 0.0]).astype(np.int64)

    def pack(a):
        return base64.b64encode(zlib.compress(np.asarray(a, "<i4").tobytes(), 9)).decode()
    crossings = []
    for c in m["crossings"]:
        row = dict(c)
        for k in ("approach", "portal", "landing"):
            row[k] = [round(c[k][0] + shift), round(c[k][1]), round(c[k][2])]
        crossings.append(row)
    return {"format": B.FORMAT, "room": room, "stage": re4_nav.ROOMS.get(room, room), "units": "mm",
            "points": pack(P.ravel()), "tris": pack(np.asarray(m["tris"]).ravel()), "crossings": crossings,
            "walls": [[w[0] + shift, w[1], w[2] + shift, *w[3:]] for w in WALLS],
            "ladders": [LADDER | {"pos": [LADDER["pos"][0] + shift, *LADDER["pos"][1:]],
                                  "top": [LADDER["top"][0] + shift, *LADDER["top"][1:]]}],
            "bounds": {"x": [int(P[:, 0].min()), int(P[:, 0].max())], "z": [int(P[:, 2].min()), int(P[:, 2].max())],
                       "y": [int(P[:, 1].min()), int(P[:, 1].max())]}}


def mesh(room: str = "r400", shift: float = 0.0) -> re4_nav.Mesh:
    return re4_nav.from_json(stage_json(room, shift))
