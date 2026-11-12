"""Walk the remaining start-up menus with A, one confirmed press at a time, until the player exists.

The flow so far, each step verified on screen:

    title --START--> menu --DOWN--> OFFLINE GAME --A--> SELECT GAME MODE --A--> SELECT CHARACTER
          --A--> Confirm/Recreate --A--> SELECT EPISODE (EPISODE 1 / EPISODE 2)

The rest are "A to confirm" screens, so this presses A, captures the frame, saves it, and stops when the player pointer at `0x8050EA10` becomes valid - the
single unambiguous sign that a character is standing in the world.
"""
import time

from pso_pad import Pad

if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    for index in range(10):
        pointer = pad.player_pointer()
        if pointer:
            print(f"player already in the world: {hex(pointer)}")
            break

        state = pad.send([{"key": "a", "down": True}, {"key": "a", "down": False}])
        time.sleep(2.8)
        shot = pad.shot("walk_%02d" % index)
        pointer = pad.player_pointer()
        floor = pad.floor()
        print(f"  {index + 1:2d} press A -> {state:10s} | floor {floor} | "
              f"player {hex(pointer) if pointer else None} | {shot}")
        if pointer:
            print("\nTHE CHARACTER IS IN THE FIELD")
            break
    else:
        print("\nstill not in the field - the next screen needs something other than A")
