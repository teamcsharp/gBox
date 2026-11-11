"""Closed-loop menu navigation: read which menu row is highlighted, then press the one key that moves toward the target.

Blind key sequences desync because the analog stick repeats. The highlighted row is unmistakable - it carries an orange bar - so this
samples each candidate row's pixels, picks the row with the strongest orange/blue contrast as the current selection, and steps the stick
until the wanted row is selected.

Row geometry comes from the 1030x579 captures. `SELECT_GAME_MODE`, `SELECT CHARACTER` and the title menu all use the same centred list,
so the same detector serves them (pass the row y-values measured from the screen).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_game as CG                                          # noqa: E402
import game_input as G                                             # noqa: E402

DEMO = Path(r"D:\gBox\pso-ds\demo")
XS = (455, 585)                                                    # horizontal band of the menu labels


def grab():
    CG.main()
    return sorted(DEMO.glob("*-game.png"), key=lambda p: p.stat().st_mtime)[-1]


def row_score(path, y, half=14):
    """Orange strength of the label band at row y: bright red with little blue, as the selection bar is orange."""
    from PIL import Image
    image = Image.open(path).convert("RGB")
    total = 0
    count = 0
    for yy in range(max(0, y - half), y + half):
        for xx in range(XS[0], XS[1], 2):
            r, g, b = image.getpixel((xx, yy))
            if r > 120 and r - b > 40:
                total += r - b
                count += 1
    return total / max(1, count) if count else 0.0


def highlighted(rows):
    """Index of the row that looks selected, and all scores."""
    path = grab()
    scores = [row_score(path, y) for y in rows]
    return scores.index(max(scores)), scores, path


def tap(key, hold=0.05, settle=0.9):
    G.send([{"key": key, "down": True}])
    time.sleep(hold)
    G.send([{"key": key, "down": False}])
    time.sleep(settle)


def navigate(target, rows, max_steps=8, label=""):
    """Step the stick until `target` row index is highlighted; returns True when selected."""
    for attempt in range(max_steps):
        index, scores, path = highlighted(rows)
        print(f"  [{label}] selected={index} scores={[round(s) for s in scores]} (want {target})", flush=True)
        if index == target:
            return True
        tap("ddown" if index < target else "dup", settle=0.75)
    return False


if __name__ == "__main__":
    # title menu rows measured from boot-b2-offline-selected.png / boot-b1-menu.png
    MENU_ROWS = (382, 420, 458, 496)                               # ONLINE, OFFLINE, OPTIONS, WEBSITE
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print("rows:", MENU_ROWS, "target:", target)
    ok = navigate(target, MENU_ROWS, label="title menu")
    print("reached target:", ok)
