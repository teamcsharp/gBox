"""Where does the round timer live, and can it tell a round from a briefing?

The harness called the Mercenaries briefing `playing` (round 109), so a capture could photograph the announcement and look like a
negative result. The timer sits in the top-left corner in gameplay and is absent from the briefing, the menus and the title screen. This
measures the near-white pixel count in that box across frames whose content is known, so the threshold is chosen from data.
"""
import pathlib
import sys

from PIL import Image

FRAMES = {
    "round (van1_05)": r"C:\_tools\gBox\.work\re4-probe\vn_05.jpg",
    "round (sf_06)": r"C:\_tools\gBox\.work\re4-probe\sf_06.jpg",
    "round (ga_07)": r"C:\_tools\gBox\.work\re4-probe\ga_07.jpg",
    "briefing (bisS1_03)": r"C:\_tools\gBox\.work\re4-probe\bs_03.jpg",
    "briefing (bisS1_06)": r"C:\_tools\gBox\.work\re4-probe\bs_06.jpg",
    "menu (freshmenu)": r"C:\_tools\gBox\.work\re4-probe\fm_b.jpg",
    "prompt (cancel loading)": r"C:\_tools\gBox\.work\re4-probe\p19.jpg",
}


def measure(path: pathlib.Path, w_frac: float = 0.30, h_frac: float = 0.14) -> dict:
    image = Image.open(path).convert("L")
    w, h = image.size
    box = image.crop((0, 0, int(w * w_frac), int(h * h_frac)))
    values = list(box.getdata())
    bright = sum(1 for v in values if v > 200)
    very = sum(1 for v in values if v > 240)
    return {"box": box.size, "pixels": len(values), "bright": bright, "very": very,
            "fraction": round(bright / max(1, len(values)), 5)}


def main() -> int:
    print(f"{'frame':24s} {'box':>10} {'bright>200':>11} {'>240':>6} {'fraction':>9}")
    rows = []
    for label, path in FRAMES.items():
        p = pathlib.Path(path)
        if not p.is_file():
            print(f"{label:24s} (missing)")
            continue
        m = measure(p)
        rows.append((label, m))
        print(f"{label:24s} {str(m['box']):>10} {m['bright']:>11} {m['very']:>6} {m['fraction']:>9}")
    highs = [m["bright"] for label, m in rows if label.startswith("round")]
    lows = [m["bright"] for label, m in rows if not label.startswith("round")]
    if highs and lows:
        print(f"\nround frames: min bright {min(highs)} | other frames: max bright {max(lows)}")
        print("a threshold between them separates the two" if min(highs) > max(lows) else
              "OVERLAP: the timer count alone does not separate them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
