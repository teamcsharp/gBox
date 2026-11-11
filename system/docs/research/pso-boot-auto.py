"""Boot PSO by FINDING the menu rows instead of assuming their coordinates.

The fixed-coordinate boot failed because the standalone window is 1280x960 while the docked one is 1030x579. This locates the menu itself:
the four entries are bright text bands in the middle of the frame, and the selected one is drawn in warm red/orange rather than white. Rows
are found by scanning for bright horizontal bands, then the highlight is identified by colour, so it works at any window size or scaling.

Steps: press START if the title is showing, D-pad until the warm band is the OFFLINE GAME entry (the second band), press A, then advance
the offline flow with captures until capabilities.supported is true.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_game as CG                                          # noqa: E402
import game_input as G                                             # noqa: E402
import session as S                                                # noqa: E402

LOG = r"D:\gBox\pso-ds\boot_auto.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def capture():
    CG.main()
    return sorted(Path(r"D:\gBox\pso-ds\demo").glob("*-game.png"), key=lambda p: p.stat().st_mtime)[-1]


def rows_and_highlight():
    """Find bright text bands in the central area and mark which is warm (selected)."""
    from PIL import Image
    image = Image.open(capture()).convert("RGB")
    width, height = image.size
    x0, x1 = int(width * 0.28), int(width * 0.78)
    bands = []
    current = None
    for y in range(int(height * 0.45), int(height * 0.95)):
        bright = warm = 0
        for x in range(x0, x1, 2):
            r, g, b = image.getpixel((x, y))
            if r > 200 and g > 200 and b > 200:
                bright += 1
            elif r > 140 and g < 120 and b < 120:
                warm += 1
        if bright + warm > 12:
            if current is None:
                current = {"y0": y, "y1": y, "bright": bright, "warm": warm}
            else:
                current["y1"] = y
                current["bright"] += bright
                current["warm"] += warm
        elif current is not None:
            bands.append(current)
            current = None
    if current is not None:
        bands.append(current)
    for band in bands:
        band["y"] = (band["y0"] + band["y1"]) // 2
        band["warm_ratio"] = band["warm"] / max(1, band["warm"] + band["bright"])
    return bands


def press(key, settle=0.7):
    G.send([{"key": key, "down": True}, {"key": key, "down": False}])
    time.sleep(settle)


def main():
    log("=== dynamic boot")
    G.raise_window()
    time.sleep(0.6)
    for attempt in range(3):
        bands = rows_and_highlight()
        if not bands:
            log(f"  attempt {attempt}: no menu bands - pressing START")
            press("start", settle=1.8)
            continue
        log(f"  bands: {[(b['y'], round(b['warm_ratio'], 2)) for b in bands]}")
        if len(bands) >= 4:
            break
        press("start", settle=1.8)
    bands = rows_and_highlight()
    if len(bands) < 4:
        log("could not find the four title entries")
        return 2
    # the four entries in order: ONLINE, OFFLINE, OPTIONS, WEBSITE
    offline = bands[1]
    for attempt in range(8):
        bands = rows_and_highlight()
        if len(bands) < 4:
            break
        selected = max(bands, key=lambda b: b["warm_ratio"])
        log(f"  selected y={selected['y']} warm={selected['warm_ratio']:.2f} (want y~{offline['y']})")
        if abs(selected["y"] - offline["y"]) <= 12 and selected["warm_ratio"] > 0.4:
            log("  OFFLINE GAME is selected")
            press("a", settle=2.0)
            break
        press("ddown" if selected["y"] < offline["y"] else "dup")
    for step in range(8):
        try:
            caps = S.controls("capabilities", {})
        except Exception as exc:                                    # noqa: BLE001
            log(f"  step {step}: {str(exc)[:60]}")
            caps = {}
        if isinstance(caps, dict) and caps.get("supported") is True:
            log("  PLAYABLE")
            return 0
        log(f"  step {step}: advancing")
        press("a", settle=1.7)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
