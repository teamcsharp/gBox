"""Static unlock-evidence census for Madden NFL 2005 (USA, GNQE69) main.dol (#2155).

Read-only. Verifies the exact main.dol SHA-256, then locates lock/unlock
related strings. This is string-level evidence only: no lock-check function,
save flag or unlock patch has been traced, so every category stays 'unknown'
and ``unlock_supported`` is False. Do not register in profile_for until a
runtime-verified routine exists.

Usage: python -m gbox.madden2005_unlock_research main.dol [--out f.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

BUILD_ID = "GNQE69"
MAIN_DOL_SHA256 = "06d962171ca5db73db1dc6b6e209faf85231540d7ac43d43655efd8567860cb5"

CATEGORIES = ("characters", "hidden_characters", "modes", "levels",
              "stages", "costumes", "items", "extras")

# category -> exact strings observed in main.dol (candidate evidence only)
EVIDENCE_STRINGS = {
    "modes": ["Owner Mode", "Mini-Camp", "Mini Camp Mode"],
    "items": ["Madden Cards", "MADDEN CARDS", "Card Locked", "Tickets", "Cheat"],
    "extras": [
        "Additional Madden Moments have now been unlocked.",
        "The next Madden Moment has now been unlocked.",
        "madgamer.rel",
        "unlocked", "locked",
    ],
    "hidden_characters": [],
    "characters": [], "levels": [], "stages": [], "costumes": [],
}


def find_string(data: bytes, text: str) -> list[int]:
    return [m.start() for m in re.finditer(re.escape(text.encode()), data)][:8]


def research(path: str) -> dict:
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    ok = sha == MAIN_DOL_SHA256
    cats = {}
    for cat in CATEGORIES:
        entries = []
        for s in EVIDENCE_STRINGS[cat]:
            offs = find_string(data, s) if ok else []
            entries.append({"name": s, "status": "unknown" if offs else "not_present",
                            "file_offsets": offs,
                            "note": "string present; lock logic not traced" if offs else "string absent"})
        cats[cat] = entries
    return {"build_id": BUILD_ID, "main_dol_sha256": sha, "revision_match": ok,
            "unlock_supported": False, "categories": cats}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dol")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = json.dumps(research(a.dol), indent=2)
    if a.out:
        Path(a.out).write_text(out)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
