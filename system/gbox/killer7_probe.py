"""Killer7 (GK7E08) analysis probe: HSD scene_data -> ModelSet -> JObj/DObj/PObj tree (read-only).

SceneData(+0 ModelSet*[], null-terminated); ModelSet(+0 JObj, +4 AnimJoint*, +8 MatAnim*, +C ShapeAnim*).
JObj: +4 flags, +8 child, +C next, +0x10 DObj, +0x14.. rot/scale/trans. DObj: +4 next, +8 MObj, +0xC PObj.
PObj: +4 next, +8 VtxDesc*, +0xC flags(u16), +0xE ndisplist blocks(u16), +0x10 displist.
"""
from .melee_models import HSD


def _chain(h, o, nxt):
    while o is not None:
        yield o
        o = h.ptr(o + nxt)


def modelsets(h: HSD):
    sd = h.root("scene_data")
    arr = h.ptr(sd)
    out, i = [], 0
    while arr is not None:
        p = h.ptr(arr + 4 * i)
        if p is None:
            break
        out.append(p)
        i += 1
    return out


def walk_jobj(h, o, depth=0, acc=None):
    acc = [] if acc is None else acc
    for j in _chain(h, o, 0xC):
        d = h.ptr(j + 0x10)
        dobjs = list(_chain(h, d, 4)) if d is not None else []
        acc.append({"off": j, "depth": depth, "flags": h.u32(j + 4), "dobjs": len(dobjs),
                    "pobjs": sum(len(list(_chain(h, h.ptr(x + 0xC), 4))) for x in dobjs if h.ptr(x + 0xC) is not None)})
        c = h.ptr(j + 8)
        if c is not None:
            walk_jobj(h, c, depth + 1, acc)
    return acc


def probe(data: bytes) -> dict:
    h = HSD(data)
    sets = modelsets(h)
    res = []
    for ms in sets:
        jo = h.ptr(ms)
        joints = walk_jobj(h, jo) if jo is not None else []
        res.append({"modelset": ms, "jobj_root": jo, "animjoint": h.ptr(ms + 4), "joints": len(joints),
                    "dobjs": sum(j["dobjs"] for j in joints), "pobjs": sum(j["pobjs"] for j in joints)})
    return {"roots": list(h.roots), "modelsets": res}
