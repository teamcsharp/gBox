"""Census of BND3 entry names across every BHD5 record of the owned Armored Core V ISO.

Read-only; streams the ISO. Bounded: payloads over max_size are skipped and counted.
"""
from __future__ import annotations

import collections
import hashlib
import os

from gbox import acv_bnd3 as B
from gbox import acv_dcx as D
from gbox import acv_inventory as acv


def census(iso_path: str, max_size: int = 8 << 20, limit: int | None = None,
           stride: int = 1) -> dict:
    ext = collections.Counter()
    prefixes = collections.Counter()
    magics = collections.Counter()
    examples: dict = {}
    flv_by_prefix = collections.Counter()
    flv_samples: list = []
    stats = collections.Counter()
    with open(iso_path, "rb") as h:
        def rd(lba, n):
            h.seek(lba * 2048)
            return h.read(n)
        r, s = acv.xiso_root(rd)
        bp = {e["path"]: e for e in acv.parse_xiso_directory(rd, r, s)}
        b, d = bp["bind/dvdbnd5.bhd"], bp["bind/dvdbnd.bdt"]
        recs = sorted(acv.parse_bhd5_buckets(rd(b["lba"], b["size"]), d["size"]),
                      key=lambda x: x["offset"])[::stride]
        if limit:
            recs = recs[:limit]
        stats["records"] = len(recs)
        for x in recs:
            if x["size"] > max_size:
                stats["skipped_large"] += 1
                continue
            h.seek(d["lba"] * 2048 + x["offset"])
            raw = h.read(x["size"])
            magics[raw[:4]] += 1
            try:
                if raw[:4] == b"DCX\0":
                    raw = D.decompress_dcx(raw)
                if raw[:4] != b"BND3":
                    stats["not_bnd3"] += 1
                    continue
                t = B.parse_bnd3(raw)
            except Exception:
                stats["parse_fail"] += 1
                continue
            stats["bnd3"] += 1
            nflv = [en for en in t["entries"] if (en.get("name") or "").lower().endswith(".flv")]
            if nflv and len(flv_samples) < 60:
                flv_samples.append({"offset": x["offset"], "size": x["size"], "names": [en["name"] for en in t["entries"]][:12]})
            for en in t["entries"]:
                name = (en.get("name") or "").replace("\\", "/")
                base = os.path.basename(name)
                e = os.path.splitext(base)[1].lower()
                ext[e] += 1
                if e == ".flv":
                    flv_by_prefix[base.split("_")[0][:4].lower()] += 1
                pre = base.split("_")[0][:4].lower()
                prefixes[pre] += 1
                examples.setdefault(e, []).append(name) if len(examples.get(e, [])) < 5 else None
    return {"stats": dict(stats), "ext": ext.most_common(40),
            "prefix": prefixes.most_common(60),
            "magics": [(m.hex(), c) for m, c in magics.most_common(15)],
            "examples": examples,
            "flv_by_prefix": flv_by_prefix.most_common(60), "flv_samples": flv_samples}
