"""Catch an enemy aggroing, and diff its struct to find the field that changes.

The operator's idea - an aggro switch - needs a field to flip, and the earlier dump could not find one because the sampled enemy was idle and its struct was static over two seconds. The missing
ingredient was **a state change to observe**. This creates one:

1. pick the nearest enemy and record its struct while it is far away and calm;
2. teleport the character next to it (same height - the learned relocation), which makes it notice;
3. re-dump its struct every 0.4 s for a few seconds while it closes in and attacks;
4. print every word that changes, with the calm and hot values side by side.

The aggro field is whichever of those words flips **at the moment the enemy starts moving toward the character** - a state word, a target pointer, or a timer. Anything that merely wiggles in
both states is animation and can be dismissed.
"""
import math
import struct
import time

from pso_pad import Pad, call


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def dump(pad, address, length=192):
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": int(address, 16), "length": length}}, "POST")
    try:
        return bytes.fromhex(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def esc(pad, x, y, z):
    player = (state(pad).get("player") or {})
    pointer = player.get("ptr")
    if not pointer:
        return False
    call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                       "input": {"session_id": pad.sid, "address": int(pointer, 16) + 0x38,
                                 "hex_bytes": struct.pack(">fff", x, y, z).hex()}}, "POST")
    return True


if __name__ == "__main__":
    pad = Pad()
    now = state(pad)
    player = now.get("player") or {}
    enemies = [e for e in (now.get("entities") or []) if str(e.get("kind")) == "enemy" and e.get("ptr")]
    print("session:", pad.sid, "| enemies with pointers:", len(enemies))
    if not enemies:
        raise SystemExit("no enemy with a pointer to watch")

    px, pz = float(player.get("x") or 0), float(player.get("z") or 0)
    target = min(enemies, key=lambda e: (float(e.get("x") or 0) - px) ** 2 + (float(e.get("z") or 0) - pz) ** 2)
    pointer = target.get("ptr")
    ex, ez = float(target.get("x") or 0), float(target.get("z") or 0)
    print(f"watching {target.get('class')} at ({ex:.0f},{ez:.0f}), player at ({px:.0f},{pz:.0f})")

    calm = dump(pad, pointer)
    if not calm:
        raise SystemExit("could not dump the enemy struct")
    print("calm dump taken")

    # put the character right next to it, at the enemy's own height so nothing ends up inside terrain
    ey = float(target.get("y") or player.get("y") or 0)
    print("teleporting next to it to make it notice...")
    esc(pad, ex - 6.0, ey, ez - 6.0)
    time.sleep(0.6)

    samples = []
    for index in range(14):
        time.sleep(0.4)
        blob = dump(pad, pointer)
        if not blob:
            continue
        samples.append(blob)
        here = state(pad).get("player") or {}
        distance = math.hypot(float(here.get("x") or 0) - ex, float(here.get("z") or 0) - ez)
        print(f"  sample {index:2d}: distance to enemy {distance:6.1f} | hp {here.get('hp')}")

    if not samples:
        raise SystemExit("no samples")

    print("\nwords that DIFFER between the calm state and the hot state:")
    for offset in range(0, len(calm) - 3, 4):
        baseline = calm[offset:offset + 4]
        hot_values = {sample[offset:offset + 4] for sample in samples}
        if baseline not in hot_values:
            hot = samples[0][offset:offset + 4]
            print(f"  +0x{offset:02X}: calm {baseline.hex()} ({int.from_bytes(baseline, 'big', signed=True)})"
                  f"  ->  hot {hot.hex()} ({int.from_bytes(hot, 'big', signed=True)})"
                  f"   [{len(hot_values)} distinct hot values]")
