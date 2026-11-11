"""Find the switches in the current room, walk to each, flip it, and prove the flip by watching what it moves.

How it works:
  1. scan the entity table for switch classes (TLazerFenceSw today; the pattern list covers TOSwitchAttackSub and other names too);
  2. snapshot the switch's struct AND its laser fence's animation floats (measured this round: flipping a fence switch moves the
     TObjLazerFenceNorm floats at +0x190 / +0x198 / +0xB8);
  3. steer to within reach of the switch with the empirical controller;
  4. press A (a switch is an interactable); if nothing changes, attack it - TLazerFenceSw is a "sw attack" panel;
  5. compare the snapshot: any moved field is the proof of the flip, printed and recorded.

Every input goes through the v2 operator lock, so the run pauses the moment the operator takes the controller and resumes 3 s after they
stop.
"""
import json
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import pso_operator2 as OP                                         # noqa: E402
import session as S                                                # noqa: E402
import steer2 as STEER                                             # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
SWITCH_PREFIXES = ("TLazerFenceSw", "TOSwitchAttackSub", "TOSwitch", "TObjSwitch")
FENCE_PREFIXES = ("TObjLazerFenceNorm", "TObjLazerFenceSw")
REACH = 7.0                                                        # how close to a switch A needs the character
LOG = r"D:\gBox\pso-ds\switch_flips.log"
RECORD = r"D:\gBox\pso-ds\switch_flips.jsonl"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def read_pos():
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    if not pointer:
        return None
    blob = S.read_memory(pointer + POS, 12)
    if len(blob) != 12:
        return None
    x, _y, z = struct.unpack(">fff", blob)
    return (x, z)


def hold(key, seconds):
    OP.note_bot_input(seconds + 0.25)
    G.send([{"key": key, "down": True}])
    time.sleep(seconds)
    G.send([{"key": key, "down": False}])
    time.sleep(0.05)


def tap(key, gap=0.35):
    OP.note_bot_input(0.3)
    G.send([{"key": key, "down": True}, {"key": key, "down": False}])
    time.sleep(gap)


def entities(prefixes):
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    found = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
        if not any(name.startswith(prefix) for prefix in prefixes):
            continue
        blob = S.read_memory(pointer, 0x340)
        if len(blob) < 0x340:
            continue
        x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
        found.append({"index": index, "class": name, "pointer": pointer, "x": x, "y": y, "z": z, "blob": blob})
    return found


def snapshot(entity):
    """Everything a flip could change: small integers and the animation floats."""
    fields = {}
    blob = entity["blob"]
    for offset in range(0, 0x340 - 3, 4):
        (word,) = struct.unpack(">i", blob[offset:offset + 4])
        if -1 <= word <= 64:
            fields[offset] = word
        (as_float,) = struct.unpack(">f", blob[offset:offset + 4])
        if 0.0 < as_float < 1000.0:
            fields[offset] = round(as_float, 2)
    return fields


def changed_fields(entity, before):
    blob = S.read_memory(entity["pointer"], 0x340)
    after = snapshot({"blob": blob})
    return {offset: (before.get(offset), after.get(offset)) for offset in after
            if offset in before and abs(float(after[offset]) - float(before[offset])) > 0.05}


def flip(entity, fences):
    x, z = entity["x"], entity["z"]
    here = read_pos()
    if here is None:
        return False, "lost position"
    distance = math.dist(here, (x, z))
    log(f"switch {entity['index']} {entity['class']} at ({x:.0f},{z:.0f}), {distance:.0f} units away")
    if distance > REACH:
        arrived, steps, final, reason = STEER.step_toward(
            hold, read_pos, (x, z), tolerance=REACH, max_steps=18, log=log,
            on_stuck=lambda stalls: (tap("b"), True)[1])
        here = read_pos()
        distance = math.dist(here, (x, z)) if here else 999
        log(f"  approach: arrived={arrived} steps={steps} now {distance:.0f} units ({reason})")
        if distance > REACH + 4:
            return False, f"could not reach ({distance:.0f} units)"
    before_switch = snapshot(entity)
    before_fences = [snapshot(fence) for fence in fences]
    tap("a")
    time.sleep(0.6)
    diff = changed_fields(entity, before_switch)
    fence_diffs = []
    for fence, snapshot_before in zip(fences, before_fences):
        fence_diff = changed_fields(fence, snapshot_before)
        if fence_diff:
            fence_diffs.append({"fence": fence["index"], "class": fence["class"],
                                "changes": {hex(k): v for k, v in list(fence_diff.items())[:6]}})
    if not diff and not fence_diffs:
        log("  nothing changed on A; attacking the panel")
        for _ in range(3):
            tap("a", 0.32)
        time.sleep(0.5)
        diff = changed_fields(entity, before_switch)
        for fence, snapshot_before in zip(fences, before_fences):
            fence_diff = changed_fields(fence, snapshot_before)
            if fence_diff:
                fence_diffs.append({"fence": fence["index"], "class": fence["class"],
                                    "changes": {hex(k): v for k, v in list(fence_diff.items())[:6]}})
    proof = {"switch": entity["index"], "class": entity["class"], "x": round(x, 1), "z": round(z, 1),
             "switch_changes": {hex(k): v for k, v in list(diff.items())[:6]}, "fence_changes": fence_diffs,
             "t": time.time()}
    with open(RECORD, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(proof) + "\n")
    if diff or fence_diffs:
        log(f"  FLIPPED: switch changes {proof['switch_changes']}, fences {len(fence_diffs)} moved")
        return True, proof
    return False, "no state change observed"


def main(max_switches=4):
    log("=== switch scan and flip")
    while OP.operator_active():
        time.sleep(0.3)
    switches = entities(SWITCH_PREFIXES)
    fences = entities(FENCE_PREFIXES)
    log(f"switches found: {[(s['class'], round(s['x']), round(s['z'])) for s in switches]}")
    log(f"fences found: {[(f['class'], round(f['x']), round(f['z'])) for f in fences]}")
    if not switches:
        log("no switches in the loaded room")
        return 2
    flips = 0
    for entity in sorted(switches, key=lambda s: math.dist(read_pos(), (s["x"], s["z"])))[:max_switches]:
        while OP.operator_active():
            time.sleep(0.3)
        ok, detail = flip(entity, fences)
        log(f"  -> {'flipped' if ok else 'not flipped'}: {str(detail)[:160]}")
        flips += 1 if ok else 0
    log(f"done: {flips}/{min(max_switches, len(switches))} switches flipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 4))
