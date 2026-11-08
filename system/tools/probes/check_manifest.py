"""What does the title's asset manifest say about the RomFS, and is imagepackhd complete?

Round 118 needs one fact: whether the extracted tree is the whole RomFS (in which case the player's texture ids genuinely have no archive)
or a partial extraction (in which case they exist in the container and were skipped).
"""
import json
import os


def main() -> int:
    path = os.path.join(os.path.expanduser("~"), "gBox_alt", "switch", "assets", "010099A00BC1E000.json")
    if not os.path.isfile(path):
        print(f"{path} is missing")
        return 1
    data = json.load(open(path, encoding="utf-8"))
    print("keys:", list(data.keys())[:16])
    for key in ("title_id", "name", "files", "romfs", "size", "sections", "nca"):
        if key in data:
            value = data[key]
            text = json.dumps(value)[:300] if not isinstance(value, str) else value[:300]
            print(f"  {key}: {text}")

    root = os.path.join(os.path.expanduser("~"), "gBox_alt", "switch", "romfs", "010099A00BC1E000")
    packdir = os.path.join(root, "bio4", "imagepackhd")
    names = [n for n in os.listdir(packdir) if n.endswith(".pack.fen")]
    ids = sorted(int(n[:8], 16) for n in names if len(n) == 17)
    print(f"\nextracted imagepackhd: {len(names)} archives, ids {ids[0]}..{ids[-1]}")
    missing_low = [i for i in range(0, ids[0]) if i not in set(ids)]
    print(f"ids below the first present one: {missing_low}")
    gaps = [i for i in range(ids[0], ids[-1] + 1) if i not in set(ids)]
    print(f"gaps inside the range: {len(gaps)} (first few {gaps[:10]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
