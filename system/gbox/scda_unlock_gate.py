"""Tom Clancy's Splinter Cell: Double Agent (GameCube, gwye41) -- unlock-gate token discovery.

Build under test: SCDA (USA) Disc 1, catalog game id 3ee1e44d0f1ebf5e, disc GCEX41 "gwye41".
The ticket gate is `UnlockCondition`.  This module pins the owned-build artifact digests and
locates the gate strings in the shipped executable, so a later stage can bind `UnlockCondition`
to a real call site instead of to a guessed offset.

The gate vocabulary is not a decompiler guess: it is the exact ASCII literals present in the
shipped `main.dol` string table, cross-checked against the Ghidra analysis artifact for the
same build (which independently lists all three tokens).

Nothing here mutates the operator's ROM, saves or installation; the module only reads bytes
that were already extracted from the owned disc image.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

GAME_ID = "3ee1e44d0f1ebf5e"
BUILD = "gwye41"
DISC_ID = "GCEX41"

# The gate vocabulary, in the order the executable's string table emits it.
GATE_TOKENS = ("UnlockCondition", "UnLocked", "BashUnLocked")

# sha256 of the extracted, owned-build artifacts (verified byte-for-byte on every run).
EXPECTED_DIGESTS = {
    "main.dol": "f5bdb8a357ce86a2bf654e8ed431b7d7e0d7cc26631133b084d27417bdcad05c",
    "main.elf": "cbc39326297a17084aab756d3684ffed8aea6f04da752abc2019d0deea24a62e",
    "SplinterCell4.ini": "7bfff844fa6017c9d37902585c2b28271a54679e5094d5e1f646d47342a09bc8",
    "Default.ini": "1a5c07c5d22b9261baff0f72090eed017902b6690383136326afeb3108e7b0dd",
}

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "scda_gc_gwye41"


def sha256_file(path) -> str:
    """Stream the bytes of a real file; never report a reference hash."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def scan_gate_tokens(blob: bytes) -> dict:
    """Byte offsets of every occurrence of every gate token inside `blob`.

    Every GATE_TOKENS member is always a key, so an absent token is an empty list rather
    than a missing key.  Overlapping hits are reported: "UnLocked" is a suffix of
    "BashUnLocked", so both offsets appear.
    """
    out = {}
    for token in GATE_TOKENS:
        needle = token.encode("ascii")
        offsets, start = [], blob.find(needle)
        while start != -1:
            offsets.append(start)
            start = blob.find(needle, start + 1)
        out[token] = offsets
    return out


def verify_artifacts(root=None, expected=None) -> dict:
    """Compare the on-disk artifacts against the pinned digests for this build."""
    root = Path(root) if root is not None else ARTIFACT_DIR
    expected = EXPECTED_DIGESTS if expected is None else expected
    report = {}
    for name, want in expected.items():
        path = root / name
        present = path.is_file()
        got = sha256_file(path) if present else None
        report[name] = {
            "present": present,
            "sha256": got,
            "matches": bool(present and got == want),
            "size": path.stat().st_size if present else None,
        }
    return report


def gate_report(root=None) -> dict:
    """One reviewable summary: artifact integrity plus gate token offsets."""
    root = Path(root) if root is not None else ARTIFACT_DIR
    artifacts = verify_artifacts(root)
    dol = root / "main.dol"
    tokens = scan_gate_tokens(dol.read_bytes()) if dol.is_file() else {t: [] for t in GATE_TOKENS}
    return {
        "game_id": GAME_ID,
        "build": BUILD,
        "disc_id": DISC_ID,
        "artifacts": artifacts,
        "all_artifacts_match": all(a["matches"] for a in artifacts.values()),
        "gate_tokens": tokens,
        "gate_tokens_present": {t: bool(o) for t, o in tokens.items()},
    }


def _main() -> int:
    report = gate_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_artifacts_match"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
