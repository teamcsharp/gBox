"""GoldenEye AI lists as behaviour graphs: the game-neutral form of its bot logic (#2410, gBrain milestone 3, part 1).

An AI list (gbox.bond_ai.ailists) is a small state machine written as bytecode: ``Label(ID)`` marks a state, the
commands after it are its actions, an ``IF...(..., GOTOLABEL)`` command is a conditional transition to another
label, ``GotoNext`` / ``GotoFirst`` an unconditional one, ``Yield`` ends the frame, and ``SetChrAiList`` /
``SetReturnAiList`` hand the character to another list. ``graph(list)`` turns one list into
``{states: {label: {actions, yields}}, edges: [{from, to, when, args}], handoffs: [{from, list, chr}]}``, which a
driver in another game can run with its own movement, aiming and senses: the conditions are names
(IFICouldSeeBond, IFMyDistanceToBondLessThanDecimeter, ...) with their numeric arguments, not GoldenEye code.

    python -m gbox.bond_ai.behaviour <GoldenEye ROM> [--level UsetupdamZ] [--out graphs.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ENTRY = "entry"                    # the state before the list's first Label
JUMPS = {"GotoNext": "always", "GotoFirst": "always"}
HANDOFF = {"SetChrAiList", "SetReturnAiList"}


def _target(cmd: dict) -> int | None:
    a = cmd["args"]
    for key in ("GOTOLABEL", "LABEL"):
        if key in a:
            return a[key]
    return None


def graph(lst: dict) -> dict:
    """One decoded AI list -> its behaviour graph (labels are states; jumps and IFs are edges)."""
    states: dict = {ENTRY: {"actions": [], "yields": 0}}
    edges, handoffs, unresolved = [], [], []
    cur = ENTRY
    labels = {c["args"]["ID"] for c in lst["commands"] if c["name"] == "Label"}
    for c in lst["commands"]:
        name = c["name"]
        if name == "Label":
            nxt = c["args"]["ID"]
            if cur is not None:                              # falling through into the label
                edges.append({"from": cur, "to": nxt, "when": "fallthrough", "args": {}})
            cur = nxt
            states.setdefault(cur, {"actions": [], "yields": 0})
            continue
        if cur is None:                                      # unreachable code after an unconditional jump
            cur = f"after_0x{c['at'] - lst['offset']:x}"
            states.setdefault(cur, {"actions": [], "yields": 0})
        tgt = _target(c)
        if name in JUMPS or (name.startswith("IF") and tgt is not None):
            if tgt not in labels:
                unresolved.append({"at": c["at"] - lst["offset"], "command": name, "label": tgt})
            edges.append({"from": cur, "to": tgt, "when": JUMPS.get(name, name),
                          "args": {k: v for k, v in c["args"].items() if k not in ("GOTOLABEL", "LABEL")}})
            if name in JUMPS:
                cur = None
            continue
        if name == "Yield":
            states[cur]["yields"] += 1
        elif name in HANDOFF:
            handoffs.append({"from": cur, "list": c["args"].get("AI_LIST_ID"), "chr": c["args"].get("CHR_NUM")})
        elif name != "EndList":
            states[cur]["actions"].append({"do": name, "args": c["args"]})
    return {"id": lst["id"], "kind": lst["kind"], "states": {str(k): v for k, v in states.items()},
            "edges": [{**e, "from": str(e["from"]), "to": str(e["to"])} for e in edges],
            "handoffs": [{**h, "from": str(h["from"])} for h in handoffs], "unresolved": unresolved}


def level_graphs(lists: list[dict]) -> dict:
    """All lists of one level -> {lists: {id: graph}, calls: [(from list, to list)]} (the list-to-list hand-offs)."""
    gs: dict = {}
    for lst in lists:                                       # a level may define one id twice: keep both (#2 suffix)
        key, n = f"0x{lst['id']:04x}", 2
        while key in gs:
            key, n = f"0x{lst['id']:04x}#{n}", n + 1
        gs[key] = graph(lst)
    calls = sorted({(k.split("#")[0], f"0x{h['list']:04x}") for k, g in gs.items() for h in g["handoffs"]
                    if h["list"] is not None})
    return {"lists": gs, "calls": [list(c) for c in calls]}


def main(argv=None) -> int:
    from .ailists import rom_levels
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("--level", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    levels = rom_levels(a.rom)
    if a.level:
        levels = {a.level: levels[a.level]}
    out = {name: level_graphs(lists) for name, lists in levels.items()}
    if not a.level:                                         # the 18 shared lists every level calls into
        from ..goldeneye_files import GoldenEyeROM
        from .ailists import global_lists
        out["global"] = level_graphs(global_lists(GoldenEyeROM.load(a.rom)))
    n = sum(len(v["lists"]) for v in out.values())
    e = sum(len(g["edges"]) for v in out.values() for g in v["lists"].values())
    bad = sum(len(g["unresolved"]) for v in out.values() for g in v["lists"].values())
    print(f"{len(out)} levels, {n} behaviour graphs, {e} edges, {bad} jumps to a missing label")
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
