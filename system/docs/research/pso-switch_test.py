"""Walk right up to the switch and press A from touching distance - the range A actually has.

The log shows the bot pressing A from 12 units five times with no effect. PSO's interact range is a couple of units, so a press at 12 is a swing at air.

This closes the distance first - several short approach attempts, reading the position each time so the distance achieved is on the record - and then
presses A from whatever it managed, logging the door state after each press. If the door opens, the range was the problem. If it stays 224 at touching
distance, the door genuinely needs a key and the bot must find one instead.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
LOG = r"D:\gBox\pso-ds\switch_test.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def nearest_switch():
    me = ME.read_pos()
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    best = None
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name or not any(word in name for word in ("Door", "Swtch", "Switch", "Key")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            state = struct.unpack(">i", blob[0x18C:0x18C + 4])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((me[0], me[1]), (x, z))
        if best is None or distance < best[0]:
            best = (round(distance, 1), name, state, (x, z))
    return best


target = nearest_switch()
if target is None:
    raise SystemExit("no switch found")
log(f"switch: {target[1]} state {target[2]} at {target[0]} units, position {target[3]}")

for attempt in range(5):
    distance, name, state, position = target
    if distance <= 3.0:
        break
    log(f"  approach {attempt + 1}: {distance} units -> walking")
    RUN.run_to(ME.read_pos, position, tolerance=2.0, budget=10.0)
    time.sleep(0.3)
    target = nearest_switch()
    log(f"    now {target[0]} units (state {target[2]})")

distance, name, state, position = target
log(f"at {distance} units from the switch - pressing A")
for attempt in range(6):
    pso_input.hold("a", 0.3)
    time.sleep(0.8)
    target = nearest_switch()
    log(f"  after A x{attempt + 1}: state {target[2]} at {target[0]} units")
    if target[2] == 2:
        log("OPENED")
        break
