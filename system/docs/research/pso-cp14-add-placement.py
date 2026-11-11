"""CP14 (P6c) offline half: add one placement to a real room, checked against CP8's room footprint.

CP14's fallback is explicit: "first expand by adding records (objects and enemies), which the writer already does, and record it as
'expansion by placements only'". This does exactly that, with the position validated against the room's measured footprint (the
`r.rel` opening quad from CP8) instead of a guessed coordinate:

  1. read the set, take an existing record's `kind` (so the game has a constructor for it) and its `y`;
  2. choose a target inside the room's footprint - the quad's centre, which CP8 measured;
  3. run the editor's `add` op through `pso_editor.preview` (no image build needed to validate the edit);
  4. verify the preview reports the edit, the set's record count grew by one, and the new record lands inside the footprint.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\cp14wt\system")

from gbox import gcdisc, pso_editor as E, pso_map_write as W, pso_rooms as R, pso_setdata as P  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
SET = "map_ancient01_00_00o.dat"
ROOM = "Scene/map_aancient01_00r.rel"


def main():
    d = gcdisc.GCDisc(DISC)
    quad = R.room_quad(d.read(ROOM))
    data, where = W.read_set(d, SET)
    recs = P.records(data)
    template = recs[0]
    kind, y = template["kind"], template["y"]
    x, z = quad["origin"][0], quad["origin"][2]          # the room's centre
    print(f"room {ROOM}: footprint {quad['size']} at {quad['origin']}")
    print(f"set {SET}: {len(recs)} records; template kind {kind:#x} at y={y:.2f}")
    print(f"adding one record at ({x:.1f}, {y:.2f}, {z:.1f})")

    op = E.edit("add", SET, kind=kind, x=float(x), y=float(y), z=float(z))
    preview = E.preview(d, [op])
    print("preview:", json.dumps(preview, default=str)[:400])
    ok_preview = preview.get("ok") is True

    # apply the same change to the bytes and read the records back
    changed = W.add_placement_change(data, kind, float(x), float(y), float(z))["bytes"]
    after = P.records(changed)
    added = len(after) == len(recs) + 1
    last = after[-1] if after else {}
    inside = R.contains(quad, last.get("x", 0.0), last.get("z", 0.0))
    print(f"records {len(recs)} -> {len(after)} (grew: {added}); new record at "
          f"({last.get('x', 0):.2f}, {last.get('z', 0):.2f}); inside the footprint: {inside}")

    # the unchanged records must be untouched
    same_prefix = all(a == b for a, b in zip(recs, after[: len(recs)]))
    print(f"original records unchanged: {same_prefix}")
    result = {"set": SET, "room": ROOM, "records_before": len(recs), "records_after": len(after),
              "added": added, "inside_footprint": inside, "prefix_unchanged": same_prefix,
              "preview_ok": ok_preview, "kind": kind, "position": [x, y, z]}
    Path(r"D:\gBox\pso-ds\cp14").mkdir(parents=True, exist_ok=True)
    Path(r"D:\gBox\pso-ds\cp14\expansion.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0 if (added and inside and same_prefix and ok_preview) else 1


if __name__ == "__main__":
    sys.exit(main())
