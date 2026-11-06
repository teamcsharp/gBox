"""Joint roles for a rig that has no anatomical names, derived from where the joints are.

Many of the collection's models come out of an extractor with names like `b000` or `node_17`, so nothing can be looked up by
name. The retargeter (`gbox.re4gc_enemies.retarget`) does not care about names - it wants to know which joint plays hip,
chest, neck, head, each upper arm / forearm / hand and each thigh / shin / foot. Those can be read off the rest pose:

* the highest joint is the **head**; its parent chain gives **neck**, **chest** and the joint below (the **hip**)
* from the chest, the two children that are not the neck lead to the arms - the one with the larger X is the character's left
* from the hip, the two children lead to the legs, by the same rule
* a three-joint chain from chest or hip is upper / middle / end (forearm, hand / shin, foot)

Facing and up are taken as the caller states them (+Y up, left = +X by default, matching the retargeter's own convention), so
a rig that faces -Z only needs `left_sign=-1`.
"""
from __future__ import annotations

import math

ROLES = ("hip", "chest", "neck", "head",
         "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
         "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")


def _dist(a, b) -> float:
    return math.dist(a, b)


def derive(joints, parent, *, left_sign: float = 1.0) -> dict[str, int]:
    """`{role: joint index}` for a humanoid rest pose.

    joints: [(x, y, z)] in any unit, +Y up. parent: [int], -1 for a root. Missing roles are simply absent from the result, so
    a rig without fingers or toes still returns the joints it has.
    """
    if not joints:
        return {}
    count = len(joints)
    parent = list(parent) + [-1] * (count - len(parent))
    children: list[list[int]] = [[] for _ in range(count)]
    for index, par in enumerate(parent):
        if 0 <= par < count and par != index:
            children[par].append(index)

    def up(i):
        return float(joints[i][1])

    def x(i):
        return float(joints[i][0])

    head = max(range(count), key=up)
    chain = [head]
    seen = {head}
    while parent[chain[-1]] >= 0 and parent[chain[-1]] not in seen:
        chain.append(parent[chain[-1]])
        seen.add(chain[-1])
    roles: dict[str, int] = {"head": head}
    if len(chain) > 1:
        roles["neck"] = chain[1]
    if len(chain) > 2:
        roles["chest"] = chain[2]
    # the hip is the ROOT of the spine chain, not the joint just above it: rigs differ in how many spine joints they carry
    # (the test skeleton has one between chest and hip), and the root is always the pelvis.
    roles["hip"] = chain[-1] if len(chain) > 1 else head
    spine = set(chain)                     # every joint on the head-to-hip chain: never a limb root, never a limb step

    def two_children(node, purpose):
        """The left and right limb roots under `node`: its children that are not on the spine chain."""
        kids = [k for k in children[node] if k not in spine]
        if len(kids) < 2:
            return None
        if purpose == "arms":
            # arms leave the chest sideways: the pair with the widest X span
            score = lambda k: (abs(x(k)), -abs(up(k) - up(node)))          # noqa: E731
        else:
            # legs leave the hip downwards: the pair that drops furthest
            score = lambda k: (abs(up(node) - up(k)), abs(x(k)))           # noqa: E731
        ranked = sorted(kids, key=score, reverse=True)[:2]
        if len(ranked) < 2:
            return None
        a, b = ranked
        left, right = (a, b) if x(a) * left_sign >= x(b) * left_sign else (b, a)
        return left, right

    def chain_three(start, prefix, names):
        node = start
        out = []
        for _ in range(3):
            out.append(node)
            kids = [k for k in children[node] if k not in spine]
            if not kids:
                break
            node = max(kids, key=lambda k: _dist(joints[k], joints[node]))       # follow the longest step
        for role, joint in zip(names, out):
            roles[f"{prefix}{role}"] = joint

    pair = two_children(roles.get("chest", head), "arms") if "chest" in roles else None
    if pair:
        for prefix, start in (("l_", pair[0]), ("r_", pair[1])):
            chain_three(start, prefix, ("upper", "fore", "hand"))
    pair = two_children(roles.get("hip", head), "legs") if "hip" in roles else None
    if pair:
        for prefix, start in (("l_", pair[0]), ("r_", pair[1])):
            chain_three(start, prefix, ("thigh", "shin", "foot"))
    return roles


def named(joints, parent, names, **kw) -> dict[str, str]:
    """`{role: joint name}` for callers that need names rather than indices (e.g. characters.rig_from_gltf)."""
    roles = derive(joints, parent, **kw)
    return {role: names[index] for role, index in roles.items() if 0 <= index < len(names)}
