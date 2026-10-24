"""Arcade-build inventory for Dead or Alive 2 (Sega NAOMI cart).

The owned arcade set is a MAME zip (``doa2.zip``) holding one 4 MiB NAOMI cart
program, ``epr-22207.ic22``.  This module reads that member read-only and
writes a JSON manifest with the facts a character-replacement run needs:

* source identity - the owning archive hash and the member hash, both streamed
  from the bytes on disk, never copied from a reference manifest;
* the NAOMI cart header - magic, vendor, game title and the per-region title
  table (USA / EXPORT / KOREA / AUSTRALIA) decoded from fixed offsets;
* the load address, *pinned* by counting absolute 32-bit references to those
  header offsets instead of assuming a Dreamcast 1ST_READ.BIN offset;
* the Ghidra function catalog for the same source, when a catalog directory is
  supplied (function count plus the first/last code range);
* the asset inventory, kept honest: counted archive members with their real
  sizes and CRCs, and the number of NaomiLib models actually decoded out of
  the cart program - no filenames guessed from a sibling build.

    python -m gbox.doa2_arcade_inventory --set doa2.zip --out manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

GAME_ID = "d04e50a8f2d99251"
TITLE = "Dead or Alive 2 (arcade)"
CART_MAGIC = b"NAOMI"
VENDOR_OFF = 0x10
TITLE_OFF = 0x30
REGION_OFF = 0x50
REGION_STRIDE = 0x20
REGION_NAME_LEN = 16
REGION_COUNT = 4
# NAOMI cart program base and the Dreamcast 1ST_READ.BIN base, as candidates.
LOAD_BASE_CANDIDATES = (0x8C000000, 0x8C010000)
# cart-header offsets whose absolute address the program refers to
HEADER_DELTAS = (0x00, 0x10, 0x30, 0x50, 0x70, 0x90, 0xB0)


def sha256_file(path: str | Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def _dec(raw: bytes) -> str:
    return raw.decode("latin-1").strip()


def parse_cart_header(data: bytes) -> dict:
    """Decode the NAOMI cart header: magic, vendor, title, per-region table."""
    if data[:5] != CART_MAGIC:
        raise ValueError("not a NAOMI cart image: no 'NAOMI' magic")
    regions = []
    for i in range(REGION_COUNT):
        off = REGION_OFF + REGION_STRIDE * i
        name = _dec(data[off:off + REGION_NAME_LEN])
        region = _dec(data[off + REGION_NAME_LEN:off + REGION_STRIDE]).rstrip("-").strip()
        regions.append({"index": i, "title": name, "region": region})
    return {"magic": "NAOMI",
            "vendor": _dec(data[VENDOR_OFF:VENDOR_OFF + 16]),
            "title": _dec(data[TITLE_OFF:TITLE_OFF + 16]),
            "regions": regions}


def pin_load_base(data: bytes, candidates=LOAD_BASE_CANDIDATES,
                  deltas=HEADER_DELTAS) -> dict:
    """Pin the load address by counting absolute references to the header.

    The candidate with strictly more 32-bit little-endian references to the
    cart-header offsets wins; a tie is a failure, not a guess.
    """
    scores = {}
    for base in candidates:
        scores[base] = sum(data.count(struct.pack("<I", base + d)) for d in deltas)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0
    if best_score == 0 or best_score <= runner:
        raise ValueError(f"load base not pinned by reference count: {scores}")
    return {"load_base": f"0x{best:08x}",
            "method": "absolute 32-bit references to cart-header offsets",
            "scores": {f"0x{k:08x}": v for k, v in scores.items()},
            "margin": best_score - runner}


def count_models(data: bytes) -> dict:
    """How many NaomiLib models actually decode out of `data`."""
    try:
        from .naomilib import scan
    except Exception as e:  # noqa: BLE001 - reported, never silently faked
        return {"decoded": False, "count": None, "error": f"{type(e).__name__}: {e}"}
    try:
        models = scan(bytes(data))
    except Exception as e:  # noqa: BLE001
        return {"decoded": False, "count": None, "error": f"{type(e).__name__}: {e}"}
    return {"decoded": True, "count": len(models),
            "triangles": sum(m.get("triangle_count", 0) for m in models)}


def read_members(path: str | Path) -> list[dict]:
    """Counted members of a MAME zip: name, real size, real CRC."""
    with zipfile.ZipFile(path) as zf:
        return [{"name": zi.filename, "bytes": zi.file_size, "crc32": f"{zi.CRC:08x}"}
                for zi in zf.infolist()]


def load_catalog(catalog_dir: str | Path | None) -> dict | None:
    """Ghidra catalog facts for the same source, when the directory exists."""
    if not catalog_dir:
        return None
    d = Path(catalog_dir)
    out: dict = {"dir": str(d)}
    cat = d / "state" / "catalog.json"
    if cat.exists():
        try:
            c = json.loads(cat.read_text())
            fns = c.get("functions", [])
            out["functions"] = len(fns)
            if fns:
                out["first_function"] = fns[0].get("addr")
        except Exception as e:  # noqa: BLE001
            out["catalog_error"] = f"{type(e).__name__}: {e}"
    rng = d / "state" / "code_ranges.txt"
    if rng.exists():
        rows = [r.split() for r in rng.read_text().split("\n") if r.strip()]
        if rows:
            out["code_range_first"] = rows[0][0]
            out["code_range_last"] = rows[-1][-1]
    return out


def build(set_path: str | Path, *, member: str = "epr-22207.ic22",
          catalog_dir: str | Path | None = None,
          data_archive: str | Path | None = None,
          scan_model: bool = True, progress=None) -> dict:
    """Inventory manifest for the owned arcade set (read-only)."""
    set_path = Path(set_path)
    say = progress or (lambda *_: None)
    say(f"reading {set_path}")
    with zipfile.ZipFile(set_path) as zf:
        names = zf.namelist()
        if member not in names:
            raise ValueError(f"{member} not in {set_path}; members={names}")
        data = zf.read(member)
        members = [{"name": zi.filename, "bytes": zi.file_size, "crc32": f"{zi.CRC:08x}"}
                   for zi in zf.infolist()]
    say(f"hashing {set_path}")
    manifest = {
        "schema": "gbox.doa2_arcade_inventory/1",
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": "arcade (Sega NAOMI SH-4 cart)",
        "byte_order": "little-endian (SH-4)",
        "source": {
            "archive": str(set_path),
            "archive_bytes": set_path.stat().st_size,
            "archive_sha256": sha256_file(set_path),
            "container": "MAME zip, NAOMI cart program member",
            "member": member,
            "member_bytes": len(data),
            "member_sha256": hashlib.sha256(data).hexdigest(),
        },
        "cart_header": parse_cart_header(data),
        "load_base": pin_load_base(data),
        "catalog": load_catalog(catalog_dir),
        "assets": {
            "cart_models": count_models(data) if scan_model else None,
            "members": members,
            "data_chips": read_members(data_archive) if data_archive else None,
        },
        "notes": [
            "Hashes are streamed from the owned files; no reference hash is copied.",
            "Load address is pinned from absolute references, not assumed from the "
            "Dreamcast 1ST_READ.BIN base.",
            "The arcade set is not the Dreamcast disc: DOA2/*.CHR archives and the "
            "Dreamcast 1ST_READ.BIN addresses do not apply here.",
            "Sibling owned sets are distinct builds: doa2.zip (this one), "
            "doa2a.zip (epr-22121a.ic22) and doa2m.zip (mpr-* data chips); their "
            "offsets must not be reused for this member.",
            "Asset counts are decoded or counted from the bytes; filenames are never "
            "inferred from a catalog label.",
        ],
    }
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DOA2 (arcade) NAOMI cart inventory")
    ap.add_argument("--set", dest="set_path", required=True, help="owned MAME zip")
    ap.add_argument("--member", default="epr-22207.ic22")
    ap.add_argument("--catalog", help="decomp_pipeline work dir with state/catalog.json")
    ap.add_argument("--data-archive", help="sibling set holding the data chips")
    ap.add_argument("--no-scan-models", action="store_true")
    ap.add_argument("--out", default="doa2arcade_manifest.json")
    args = ap.parse_args(argv)
    manifest = build(args.set_path, member=args.member, catalog_dir=args.catalog,
                     data_archive=args.data_archive, scan_model=not args.no_scan_models,
                     progress=lambda *a: print(*a, file=sys.stderr))
    with open(args.out, "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
