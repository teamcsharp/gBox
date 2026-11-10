#!/usr/bin/env python3
"""Turok: Evolution (GameCube, GTKE51) -- owned-build probe.

Reads the owned GCZ container read-only, hashes the real source bytes, walks
the GCFST and dumps the head of supertree0.tre plus main.dol strings.  Nothing
here writes to the owned disc; every output goes to a scratch directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.gcz import GCZ                      # noqa: E402
from gbox.formats import gcfst                 # noqa: E402


def sha256_range(z: GCZ, off: int, size: int, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    left = size
    pos = off
    while left > 0:
        n = min(chunk, left)
        h.update(z.read(pos, n))
        pos += n
        left -= n
    return h.hexdigest()


def head_strings(blob: bytes, min_len: int = 4, limit: int = 400) -> list[str]:
    out = []
    for m in re.finditer(rb"[ -~]{%d,}" % min_len, blob):
        out.append(m.group().decode("ascii"))
        if len(out) >= limit:
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gcz", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tre-head", type=int, default=1 << 20)
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"gcz": args.gcz}

    with GCZ(args.gcz) as z:
        report["gcz_data_size"] = z.data_size
        report["gcz_block_size"] = z.block_size
        report["gcz_num_blocks"] = z.num_blocks

        hdr = z.read(0, 0x440)
        dh = gcfst.disc_header(hdr)
        report["disc_header"] = dh

        ents = gcfst.parse_fst(z.read(dh["fst_offset"], dh["fst_size"]), dh["fst_offset"])
        files = []
        for path, off, size, ent in ents:
            files.append({"path": path, "offset": off, "size": size, "fst_entry": ent})
        report["files"] = files
        report["file_count"] = len(files)

        # hash the authoritative source: main.dol (the executable) by streaming
        main = next((f for f in files if f["path"] == "main.dol"), None)
        if main:
            report["main_dol_sha256"] = sha256_range(z, main["offset"], main["size"])
            report["main_dol_offset"] = main["offset"]
            report["main_dol_size"] = main["size"]
            dol = z.read(main["offset"], main["size"])
            (out / "main.dol").write_bytes(dol)
            report["main_dol_strings_head"] = head_strings(dol[: 1 << 20], 5, 500)
            report["main_dol_strings_all"] = [s for s in head_strings(dol, 5, 20000)]
            report["main_dol_tre_mentions"] = [s for s in report["main_dol_strings_all"]
                                              if ".tre" in s or "supertree" in s.lower()
                                              or "Turok" in s or "tre" in s.lower()][:200]

        tre = next((f for f in files if f["path"] == "supertree0.tre"), None)
        if tre:
            report["supertree_offset"] = tre["offset"]
            report["supertree_size"] = tre["size"]
            n = min(args.tre_head, tre["size"])
            head = z.read(tre["offset"], n)
            (out / "supertree_head.bin").write_bytes(head)
            report["supertree_head_sha256"] = hashlib.sha256(head).hexdigest()
            report["supertree_head_first64"] = head[:64].hex()
            report["supertree_head_u32_be"] = [f"{v:08x}" for v in struct.unpack_from(">16I", head, 0)]
            report["supertree_head_u32_le"] = [f"{v:08x}" for v in struct.unpack_from("<16I", head, 0)]
            report["supertree_head_strings"] = head_strings(head, 4, 200)
            # entropy of the first 64 KiB
            import collections
            c = collections.Counter(head[: 1 << 16])
            report["supertree_head_entropy_bytes"] = len(c)
            report["supertree_head_zero_run"] = next((i for i, b in enumerate(head) if b != 0), len(head))

    (out / "probe_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("main_dol_strings_all", "main_dol_strings_head",
                                   "main_dol_tre_mentions")}, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
