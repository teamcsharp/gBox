"""Add a two-key hold to pso_input, and a diagonal escape to the route driver.

A character pressed against a wall cannot turn: the camera follows the character's travel, so with no travel there is no rotation and turn
taps do nothing (34 turns in 11 s produced 16 units). Holding a diagonal - left+up or right+up - forces travel in some direction, which
both escapes the corner and re-establishes the heading.
"""
import pathlib

INPUT = pathlib.Path(r"C:\_tools\gBox\.tmp\pso_input.py")
text = INPUT.read_text(encoding="utf-8")

if "def hold2(" not in text:
    text = text.replace('''def tap(key, gap=0.3, log=None, wait_for_operator=False):''',
                        '''def hold2(keys, seconds, log=None):
    """Hold two keys at once (diagonals), under the same operator lock."""
    if not allowed():
        if log is not None:
            log("  (operator has the controller: holding off)")
        return False
    OP.note_bot_input(seconds + 0.25)
    G.send([{"key": key, "down": True} for key in keys])
    time.sleep(seconds)
    G.send([{"key": key, "down": False} for key in keys])
    time.sleep(0.05)
    return True


def tap(key, gap=0.3, log=None, wait_for_operator=False):''')
    INPUT.write_text(text, encoding="utf-8")
print("pso_input.hold2:", "def hold2(" in INPUT.read_text(encoding="utf-8"))

DRIVER = pathlib.Path(r"C:\_tools\gBox\.tmp\drive_route.py")
driver = DRIVER.read_text(encoding="utf-8")

OLD = '''    blocked = 0
    while time.time() - started < budget:'''
NEW = '''    blocked = 0
    escapes = 0
    while time.time() - started < budget:'''
driver = driver.replace(OLD, NEW)

OLD_BLOCK = '''        if moved > 1.5:
            heading = heading_of(vector)
            blocked = 0
        else:
            blocked += 1
            side = "right" if blocked % 2 else "left"
            pso_input.hold(side, 0.45)
            turns += 1'''
NEW_BLOCK = '''        if moved > 1.5:
            heading = heading_of(vector)
            blocked = 0
        else:
            blocked += 1
            if blocked >= 2:
                # pressing against a wall: a diagonal forces travel, which also turns the camera and gives a new heading
                side = "right" if escapes % 2 else "left"
                pso_input.hold2([side, "up"], 1.0)
                escapes += 1
                vector, after = forward(read_pos, 0.3)
                if vector is not None and math.hypot(*vector) > 1.5:
                    heading = heading_of(vector)
                blocked = 0
            else:
                side = "right" if blocked % 2 else "left"
                pso_input.hold(side, 0.45)
                turns += 1'''
driver = driver.replace(OLD_BLOCK, NEW_BLOCK)
DRIVER.write_text(driver, encoding="utf-8")
print("drive_route diagonal escape:", "hold2([side, \"up\"], 1.0)" in driver)
