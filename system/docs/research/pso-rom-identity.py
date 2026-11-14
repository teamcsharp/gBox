"""rom-identity - pin the running PSO build and read Pioneer 2's warp-pad record from the disc.

The campaign mandate's step A/B asks for the exact ROM build and for Pioneer 2's actual warp objects from the disc,
not from a guessed list of generic ``TObject`` coordinates. This tool answers both from the owned image:

    python pso-rom-identity.py identity        # game id, ISO sha256, PsoV3.dol sha256, catalog entry
    python pso-rom-identity.py city            # the city placement set, the pad record, and the warp families

Everything is read-only; the image is never modified. The placement set is decoded through the repo's own
``pso_map_write``/``pso_setdata`` readers (the same path CP14 used) and the pad is matched to the live entity the
bounded controller sees at ``(360, 26)``. The world transform ``(+228, +291)`` is CP's measured placement->world
offset; the tool prints both raw and world coordinates and refuses to claim a match outside a tolerance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox.gcdisc import GCDisc                            # noqa: E402
from gbox import pso_map_write as W                       # noqa: E402
from gbox import pso_setdata as P                         # noqa: E402
from gbox import pso_classes as C                         # noqa: E402

ISO = pathlib.Path(r"D:\gBox\pso-ds\disc\pso.iso")
GCZ = pathlib.Path(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
DOL_NAME = "PsoV3.dol"
DOL_SIZE = 5233088
DOL_SHA256 = "1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a"
SET = "map_city00_00o.dat"
COLLISION = "Scene/map_city00_00c.rel"
COLLISION_SIZE = 70144
COLLISION_SHA256 = "6d5f5d5d0ff9c18958d1ab577e5be9e6f83c66808537b085ca4c9d2cd97535ec"
PAD_RAW = (132.0, -265.0)          # (360,26) minus the measured world offset (228, 291)
WORLD_OFFSET = (228.0, 291.0)
PAD_TOLERANCE = 6.0


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity(args) -> int:
    receipt = {"iso": str(ISO), "gcz": str(GCZ)}
    disc = GCDisc(str(ISO))
    try:
        header = disc._r(0, 8)
        receipt["iso_header"] = header.hex()
        receipt["serial"] = header[:6].decode("ascii", "replace")
        receipt["iso_size"] = ISO.stat().st_size
        receipt["iso_sha256"] = sha256(ISO)
        dol = disc.read(DOL_NAME)
        receipt["dol"] = {"name": DOL_NAME, "size": len(dol), "sha256": hashlib.sha256(dol).hexdigest(),
                          "expected_size": DOL_SIZE, "expected_sha256": DOL_SHA256,
                          "matches_pinned_build": len(dol) == DOL_SIZE and
                                                 hashlib.sha256(dol).hexdigest() == DOL_SHA256}
        collision = disc.read(COLLISION)
        receipt["collision"] = {"name": COLLISION, "size": len(collision),
                                "sha256": hashlib.sha256(collision).hexdigest(),
                                "expected_size": COLLISION_SIZE,
                                "matches_pinned_build": len(collision) == COLLISION_SIZE and
                                                        hashlib.sha256(collision).hexdigest() == COLLISION_SHA256}
    finally:
        disc.f.close()
    if GCZ.exists():
        receipt["gcz_size"] = GCZ.stat().st_size
        receipt["gcz_sha256"] = sha256(GCZ)

    print(json.dumps(receipt, indent=1))
    return 0 if receipt["dol"]["matches_pinned_build"] else 1


def city(args) -> int:
    disc = GCDisc(str(ISO))
    try:
        if disc._r(0, 8) != b"GPOE8P\0\x02":
            raise SystemExit(f"{ISO} is not the GPOE8P/3OE2 image")
        data, where = W.read_set(disc, SET)
        dol = disc.read(DOL_NAME)
    finally:
        disc.f.close()
    recs = P.records(data)
    raw = {"name": SET, "archive": where, "records": len(recs), "sha256": hashlib.sha256(data).hexdigest()}
    pad_raw = min(recs, key=lambda rec: (rec["x"] - PAD_RAW[0]) ** 2 + (rec["z"] - PAD_RAW[1]) ** 2)
    pad_world = (pad_raw["x"] + WORLD_OFFSET[0], pad_raw["z"] + WORLD_OFFSET[1])
    pad_index = recs.index(pad_raw)
    pad = {"record_index": pad_index, "raw": {k: pad_raw[k] for k in ("kind", "x", "y", "z")},
           "kind_class": P.kind_class(pad_raw["kind"]), "kind_flags": P.kind_flags(pad_raw["kind"]),
           "world": {"x": round(pad_world[0], 2), "y": pad_raw["y"], "z": round(pad_world[1], 2)},
           "world_offset": WORLD_OFFSET,
           "expected_world": (360.0, 26.0),
           "distance_to_expected": round(((pad_world[0] - 360.0) ** 2 + (pad_world[1] - 26.0) ** 2) ** 0.5, 2),
           "matched": ((pad_world[0] - 360.0) ** 2 + (pad_world[1] - 26.0) ** 2) ** 0.5 <= PAD_TOLERANCE}
    by_class: dict[str, list] = {}
    for index, rec in enumerate(recs):
        cls = P.kind_class(rec["kind"])
        name = None
        try:
            name = C.name_of(dol, cls)
        except Exception:                                  # noqa: BLE001
            name = None
        key = f"0x{rec['kind']:08x} class={cls} name={name}"
        by_class.setdefault(key, []).append({"index": index, "x": round(rec["x"], 2), "y": round(rec["y"], 2),
                                             "z": round(rec["z"], 2)})
    interesting = {key: rows for key, rows in by_class.items()
                   if any(word in key for word in ("Warp", "warp", "Door", "door", "class=67", "class=87"))
                   or len(rows) <= 2}
    report = {"set": raw, "pad": pad, "families": interesting}
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "rom-city-receipt.json"
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"set": raw, "pad": pad}, indent=1))
    print(f"wrote {path}")
    return 0 if pad["matched"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="pin the PSO build and read the city warp-pad placement")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("identity")
    city_parser = sub.add_parser("city")
    city_parser.add_argument("--out", default=r"D:\gBox\pso-ds\mandate")
    args = parser.parse_args(argv)
    return identity(args) if args.mode == "identity" else city(args)


if __name__ == "__main__":
    raise SystemExit(main())


