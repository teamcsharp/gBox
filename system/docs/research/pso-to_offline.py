"""From a cold boot to offline play, verifying every press on screen.

Shape of the flow, learned from watching it:

    title (logo)  --START-->  main menu (ONLINE / OFFLINE / OPTIONS / WEBSITE)
    main menu     --DOWN-->   OFFLINE GAME
    OFFLINE GAME  --A-->      offline play (card / character / continue)

Every press is verified: `tap_until_changed` looks at the screen and retries, because a single press is one job whose events the emulator may consume inside one
frame - the same A press activated a highlighted option once and did nothing the next time. A frame is saved after every step so the path can be checked.
"""
import time

from pso_pad import Pad

if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    print("\nwaiting for the boot to reach the title...")
    last = ""
    for index in range(20):
        time.sleep(4)
        last = pad.shot("boot_%02d" % index)
        print(f"  {index * 4:3d}s: {last}")
        if index == 3:                       # the logo is up by now; START reveals the menu
            changed, key, tries = pad.tap_until_changed(["start"], tries=4, settle=1.6)
            print(f"  START -> changed={changed} key={key!r} tries={tries}")
            break

    time.sleep(1.0)
    print("menu shot:", pad.shot("step_menu"))

    print("\nmoving to OFFLINE GAME (one DOWN from ONLINE)...")
    moved = pad.move("down", tries=3, settle=1.1)
    print("  moved:", moved, "| shot:", pad.shot("step_offline_selected"))

    print("\nentering offline play...")
    entered = pad.confirm(tries=5)
    time.sleep(3.0)
    print("  entered:", entered, "| shot:", pad.shot("step_offline_entered"))
    print("  status:", pad.status())
