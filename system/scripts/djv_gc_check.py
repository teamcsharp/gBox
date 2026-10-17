"""Check the Def Jam Vendetta (GameCube) entries after the reader v2 refresh: every djv_* entry of game
8b37766f557e1f5f must be made by djv_gc_reader 2, carry the 18 body roles, pass cast_swap's donor gate (verified model
+ preview, roles with the hip) and be replacement-ready.

    python scripts/djv_gc_check.py [library root]      (default: characters.library_root(), GBOX_CHARACTERS honoured)

Prints one line per failing entry and a summary; exits 1 unless every entry passes.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import cast_swap as CS, characters as C  # noqa: E402

GAME_ID = "8b37766f557e1f5f"


def check(root: Path) -> dict:
    rows = []
    for p in sorted(Path(root).glob("*/meta.json")):
        meta = json.loads(p.read_text("utf-8"))
        if (meta.get("source") or {}).get("game_id") != GAME_ID:
            continue
        rs = C.reader_status(meta) or {}
        roles = (meta.get("rig") or {}).get("roles") or {}
        why = CS.retarget_check(meta, root)
        rd = meta.get("readiness") or {}
        problems = ([f"reader v{rs.get('entry')} (current v{rs.get('current')})"] if rs.get("stale") else []) + \
                   ([f"{len(roles)} roles"] if len(roles) != 18 else []) + ([why] if why else []) + \
                   ([f"readiness {rd.get('status')}: {rd.get('missing')}"] if rd.get("status") != "ready" else [])
        rows.append({"slug": meta["slug"], "reader": rs.get("entry"), "roles": len(roles),
                     "joints": (meta.get("rig") or {}).get("joints"), "readiness": rd.get("status"),
                     "ok": not problems, "problems": problems})
    ok = sum(r["ok"] for r in rows)
    return {"game_id": GAME_ID, "entries": len(rows), "retargetable": ok, "complete": bool(rows) and ok == len(rows),
            "failing": [r for r in rows if not r["ok"]]}


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else C.library_root()
    r = check(root)
    for f in r["failing"]:
        print(f"FAIL {f['slug']}: {'; '.join(f['problems'])}")
    print(f"{r['retargetable']}/{r['entries']} Def Jam Vendetta GC entries retargetable "
          f"({'complete' if r['complete'] else 'INCOMPLETE'})")
    sys.exit(0 if r["complete"] else 1)
