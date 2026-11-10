"""Twin Snakes no-op writer roundtrip proof on an owned disc 1 image (read-only).

For every stage of stage.dat: parse, then rebuild with nothing changed (stock zlib streams kept) and compare with the
disc bytes; also rebuild with every page recompressed and compare the decoded pages. Run:
    python3 -m gbox.ts_roundtrip <disc1.iso>
"""
from __future__ import annotations

import hashlib
import json
import sys
import zlib
from pathlib import Path

from . import ts_stage as S


def _strip(b: bytes) -> bytes:
    return b.rstrip(b"\0")


def roundtrip(iso, limit: int | None = None) -> dict:
    from .gcdisc import GCDisc
    d = GCDisc(str(iso))
    try:
        sd = S.StageDat.from_disc(d)
        rep = {"game_id": d.game_id, "stages": 0, "identical": 0, "repack_equal": 0, "mismatch": [], "skipped": []}
        for i, (name, _sec) in enumerate(sd.entries[:limit]):
            off, span = sd.span(i)
            if span <= 0:
                rep["skipped"].append(name)
                continue
            raw = sd._read(off, span)
            st = S.parse_stage(raw, name, _sec, span)
            rep["stages"] += 1
            out = S.build_stage(st)
            if _strip(out) == _strip(raw):
                rep["identical"] += 1
            else:
                rep["mismatch"].append(name)
            allp = {p.number for p in st.pages}
            re = S.parse_stage(S.build_stage(st, allp), name, _sec, len(raw) * 2)
            if [(p.number, p.data) for p in re.pages] == [(p.number, p.data) for p in st.pages]:
                rep["repack_equal"] += 1
            else:
                rep["mismatch"].append(name + ":repack")
        rep["ok"] = not rep["mismatch"] and rep["stages"] == rep["identical"] == rep["repack_equal"]
        return rep
    finally:
        d.f.close()


def main(argv=None) -> int:
    a = (argv if argv is not None else sys.argv)[1:]
    if not a:
        print(__doc__)
        return 2
    rep = roundtrip(Path(a[0]))
    print(json.dumps(rep, indent=1))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
