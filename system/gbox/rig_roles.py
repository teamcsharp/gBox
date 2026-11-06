"""Joint roles for a rig that has no anatomical names, derived from where the joints are.

Many of the collection's models come out of an extractor with names like `b000` or `node_17`, so nothing can be looked up by
name. The retargeter (`gbox.re4gc_enemies.retarget`) does not care about names - it wants to know which joint plays hip,
chest, neck, head, each upper arm / forearm / hand and each thigh / shin / foot.

The roles are read from the rest pose, and the **limb pairs are found first**, because they are the least ambiguous thing a
humanoid rig has: two joints that are siblings and mirror each other across the centre line. Arms are the pair with the
widest sideways span, legs the other mirrored pair; where they hang then tells us the spine:

```
chest = parent of the arm pair        hip = parent of the leg pair
head  = the highest joint that still has children (ears and hats are leaves above it)
neck  = parent of the head
```

Doing it this way survives rigs whose spine runs head-first, where the head's parent chain descends through the chest to the
root - a shape that defeats a rule that starts from the highest joint and walks down.
"""
from __future__ import annotations

import math

ROLES = ("hip", "chest", "neck", "head",
         "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
         "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")


def _dist(a, b) -> float:
    return math.dist(a, b)


def derive(joints, parent, *, left_sign: float = 1.0) -> dict[str, int]:
    """`{role: joint index}` for a humanoid rest pose, by geometry.

    joints: [(x, y, z)] in any unit, +Y up. parent: [int], -1 for a root. left_sign: the sign of X that points to the
    character's left. Roles the rig does not have are simply absent.
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

    # ---- mirrored sibling pairs: the two best ones are the arms and the legs
    pairs = []
    for node in range(count):
        kids = children[node]
        if len(kids) < 2:
            continue
        for first in range(len(kids)):
            for second in range(first + 1, len(kids)):
                a, b = kids[first], kids[second]
                if x(a) * x(b) >= 0:                       # both on the same side: not a mirrored pair
                    if abs(x(a)) < 1e-9 or abs(x(b)) < 1e-9:
                        continue
                    continue
                span = abs(x(a) - x(b))
                pairs.append((span, node, a, b))
    pairs.sort(key=lambda row: (-row[0], -up(row[2])))
    roles: dict[str, int] = {}
    arms = pairs[0] if pairs else None
    legs = next((p for p in pairs[1:] if p[1] != arms[1]), None) if arms else None
    # arms are the higher pair when both have a similar span; the span decides first, the height breaks ties
    if arms and legs and up(arms[2]) < up(legs[2]) and abs(arms[0] - legs[0]) < 0.35 * max(arms[0], 1e-9):
        arms, legs = legs, arms

    if arms:
        _, chest, a, b = arms
        roles["chest"] = chest
    if legs:
        _, hip, a, b = legs
        roles["hip"] = hip

    # ---- head and neck. A single highest joint IS the head; several joints at the same height are ears, horns or
    # antennae above it, and then the head is their deepest common ancestor.
    if joints:
        highest = max(up(i) for i in range(count))
        near = [i for i in range(count) if up(i) >= highest - max(abs(highest) * 0.02, 1e-9)]
        if len(near) == 1:
            head = near[0]
        else:
            def ancestor_of(candidate, joint):
                walker = joint
                for _ in range(count + 1):
                    if walker == candidate:
                        return True
                    if parent[walker] < 0:
                        return False
                    walker = parent[walker]
                return False

            head = parent[near[0]]
            while head >= 0 and not all(ancestor_of(head, joint) for joint in near):
                head = parent[head]
            if head < 0:
                head = near[0]
        roles["head"] = head
        if parent[head] >= 0:
            roles["neck"] = parent[head]
    if "hip" not in roles:                              # a rig with no legs: the spine root is the hip
        root = next((i for i, par in enumerate(parent) if par < 0), 0)
        roles["hip"] = root

    def lateral(pair):
        _, node, a, b = pair
        left, right = (a, b) if x(a) * left_sign >= x(b) * left_sign else (b, a)
        return left, right

    def chain_three(start, prefix, names):
        node = start
        out = []
        for _ in range(3):
            out.append(node)
            kids = children[node]
            if not kids:
                break
            node = max(kids, key=lambda k: _dist(joints[k], joints[node]))
        for role, joint in zip(names, out):
            roles[f"{prefix}{role}"] = joint

    if arms:
        for prefix, start in zip(("l_", "r_"), lateral(arms)):
            chain_three(start, prefix, ("upper", "fore", "hand"))
    if legs:
        for prefix, start in zip(("l_", "r_"), lateral(legs)):
            chain_three(start, prefix, ("thigh", "shin", "foot"))
    return roles


def named(joints, parent, names, **kw) -> dict[str, str]:
    """`{role: joint name}` for callers that need names rather than indices (e.g. characters.rig_from_gltf)."""
    roles = derive(joints, parent, **kw)
    return {role: names[index] for role, index in roles.items() if 0 <= index < len(names)}
