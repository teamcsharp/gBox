"""Skeleton role maps shared by every writer (gBox retargets a donor onto a native skeleton through named body roles).

ROLES                the body-role vocabulary every role map uses (characters.py, sm64_swap, re4gc_enemies, ...)
ROLE_CHAINS          parent -> child order the roles must follow on any humanoid tree
role_of_joint        each joint -> the role of its nearest ancestor that has one (moved from gbox.re4gc_enemies)
check_role_map       what's wrong with a role map on a tree (generalised from gbox.pso_player.check_roles)
"""
from __future__ import annotations

ROLES = ("hip", "chest", "neck", "head",
         "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
         "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")
ROLE_CHAINS = [("hip", "chest", "head"), ("chest", "l_upper", "l_fore", "l_hand"), ("chest", "r_upper", "r_fore", "r_hand"),
               ("hip", "l_thigh", "l_shin", "l_foot"), ("hip", "r_thigh", "r_shin", "r_foot")]


def is_below(parents: list[int], a: int, b: int) -> bool:
    """Is node b a (strict) descendant of node a?"""
    k = parents[b]
    while k >= 0 and k != a:
        k = parents[k]
    return k == a


def check_role_map(parents: list[int], world: list, roles: dict[str, int], drawn: dict[int, int] | None = None,
                   chains=ROLE_CHAINS) -> list[str]:
    """What's wrong with a role map ([] = usable). parents: parent per node (-1 = root); world: bind-pose position per
    node (model faces +Z, left at +X); drawn: {node: drawn vertices} when known. Checks: every chained role is mapped
    to an existing node, chains run parent -> child, l_/r_ roles sit on their side, mapped nodes draw vertices, and
    head above chest above hip above the feet."""
    parents = [-1 if p is None else int(p) for p in parents]
    bad = [f"{r}: no node {j}" for r, j in roles.items() if not 0 <= j < len(parents)]
    missing = sorted({r for ch in chains for r in ch} - set(roles))
    if bad or missing:
        return bad + [f"no {r}" for r in missing]
    for ch in chains:
        for a, b in zip(ch, ch[1:]):
            if not is_below(parents, roles[a], roles[b]):
                bad.append(f"{b} (node {roles[b]}) isn't below {a} (node {roles[a]})")
    for r, j in roles.items():
        x = float(world[j][0])
        if r[:2] in ("l_", "r_") and (x > 0) != (r[0] == "l"):
            bad.append(f"{r} (node {j}) is on the {'left' if x > 0 else 'right'} (x {x:.2f})")
        if drawn is not None and not drawn.get(j):
            bad.append(f"{r} (node {j}) draws no vertices")
    y = {r: float(world[roles[r]][1]) for r in ("head", "chest", "hip", "l_foot", "r_foot")}
    if not y["head"] > y["chest"] > y["hip"] > max(y["l_foot"], y["r_foot"]):
        bad.append(f"heights out of order (head {y['head']:.2f}, chest {y['chest']:.2f}, hip {y['hip']:.2f})")
    return bad


def role_of_joint(rig: dict) -> list[str]:
    """Each source joint -> the body role of its nearest ancestor that has one (default: hip)."""
    roles = {j: r for r, j in rig["roles"].items()}
    out = []
    for j in range(len(rig["parent"])):
        k = j
        while k >= 0 and k not in roles:
            k = rig["parent"][k]
        out.append(roles.get(k, "hip"))
    return out
