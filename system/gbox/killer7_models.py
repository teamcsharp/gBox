"""Killer7 (GameCube) HSD character mesh reader.

Reuses gbox.melee_models (HAL sysdolphin): Killer7 .dat files hold scene_data -> ModelSet -> JObj tree with
standard HSD DObj(+8 MObj,+0xC PObj) / PObj(+8 vtxdesc,+0xC flags,+0xE dl blocks,+0x10 displist,+0x14 envelopes).
Geometry is decoded by Model.pobj_geometry (GX vtxdesc + displist); verified on AKI_M00 from the owned disc.
"""
from __future__ import annotations

import numpy as np

from gbox.melee_models import HSD, Model, write_gltf
from gbox.killer7_probe import modelsets


class Killer7Model(Model):
    def __init__(self, data: bytes, modelset: int = 0):
        self.h = h = HSD(data)
        sets = modelsets(h)
        if modelset >= len(sets):
            raise IndexError(f"modelset {modelset} of {len(sets)}")
        self.joints, self.jidx = [], {}
        self._walk(h.ptr(sets[modelset]), -1, np.eye(4))
        self.dobjs = []
        for ji, j in enumerate(self.joints):
            d = j["dobj"]
            while d is not None:
                self.dobjs.append((ji, d))
                d = h.ptr(d + 4)
        self.visible = set(range(len(self.dobjs)))
        self._tex_cache = {}

    def geometry(self):
        """[(dobj index, geometry dict)] for every DObj/PObj chain."""
        out = []
        for di, (ji, d) in enumerate(self.dobjs):
            p = self.h.ptr(d + 0xC)
            while p is not None:
                out.append((di, self.pobj_geometry(p, ji)))
                p = self.h.ptr(p + 4)
        return out


def export_gltf(model: Killer7Model, path, scale: float = 1.0):
    prims = []
    for di, g in model.geometry():
        n = len(g["pos"])
        J, W = np.zeros((n, 4), np.int64), np.zeros((n, 4))
        for k, ws in enumerate(g["env"]):
            for s, (j, w) in enumerate(sorted(ws, key=lambda t: -t[1])[:4]):
                J[k, s], W[k, s] = j, w
        W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
        prims.append({"pos": g["pos"], "nrm": g["nrm"], "uv": g["uv"], "tris": g["tris"], "J": J, "W": W,
                      "tex": None, "color": (200, 200, 200, 255), "dobj": di, "clr": g["clr"], "name": f"dobj{di:02d}"})
    return write_gltf(path, model.joints, prims, scale=scale, name="killer7")
