"""Build an experimental high-em1000 import and its complete uEm11 class-rebind overlay.

Run from any checkout with --archive uEm10.arc --source character.glb --output imported.arc.
--overlay DIR additionally writes the two LayeredFS files (uEm11.arc and main.ips). It does not install or launch them.
Geometry and skin acceptance still require a live round and visual evidence; this builder proves only structural safety.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gbox import mt_arc, mt_model, mtf_author, re5_ips


def source_mesh(path: Path) -> tuple[list[dict], list[tuple[int, int, int]]]:
    """Read the source's posed world-space triangles, including node and skin transforms."""
    import numpy as np
    from gbox import characters
    vertices, triangles, lookup = [], [], {}
    for points, uvs, _texture, _colour in characters._triangles(path):
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        length = float(np.linalg.norm(normal))
        if not length:
            continue
        normal = tuple(float(v) for v in normal / length)
        triangle = []
        for point, uv in zip(points, uvs):
            position = tuple(float(v) for v in point)
            uv = tuple(float(v) for v in uv)
            key = position, normal, uv
            if key not in lookup:
                lookup[key] = len(vertices)
                vertices.append({"position": position, "normal": normal, "uv": uv})
            triangle.append(lookup[key])
        triangles.append(tuple(triangle))
    if not triangles:
        raise mtf_author.AuthorError("the source contains no nondegenerate triangles")
    return vertices, triangles


def fit_vertices(vertices: list[dict], bounds: dict) -> list[dict]:
    """Uniformly fit all three axes; centre horizontally and place the feet on the floor."""
    low = [min(v["position"][i] for v in vertices) for i in range(3)]
    high = [max(v["position"][i] for v in vertices) for i in range(3)]
    target_low = [bounds["min"][a] for a in "xyz"]
    target_high = [bounds["max"][a] for a in "xyz"]
    scale = min((target_high[i] - target_low[i]) / (high[i] - low[i])
                for i in range(3) if high[i] > low[i])
    if scale <= 0:
        raise mtf_author.AuthorError("the target bounds have no room for the source")
    source_origin = [(low[i] + high[i]) / 2 for i in range(3)]
    target_origin = [(target_low[i] + target_high[i]) / 2 for i in range(3)]
    source_origin[1], target_origin[1] = low[1], target_low[1]
    return [v | {"position": tuple(max(target_low[i], min(target_high[i],
                    target_origin[i] + (v["position"][i] - source_origin[i]) * scale)) for i in range(3))}
            for v in vertices]


def build_archive(archive: bytes, vertices: list[dict], triangles: list[tuple[int, int, int]],
                  *, model_name: str = "em1000") -> tuple[bytes, bytes, dict]:
    """Replace exactly the named MOD, preserving its paired MRL and every other entry."""
    parsed = mt_arc.parse(archive)
    matches = []
    for index, entry in enumerate(parsed.entries):
        if entry.name.replace("\\", "/").rsplit("/", 1)[-1] != model_name:
            continue
        for window in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                raw = zlib.decompress(entry.data, window)
                break
            except zlib.error:
                raw = b""
        if raw.startswith(mt_model.MOD_MAGIC):
            matches.append((index, raw))
    if len(matches) != 1:
        raise mtf_author.AuthorError(f"expected exactly one MOD named {model_name!r}; found {len(matches)}")
    index, raw = matches[0]
    model = mt_model.parse_mod(raw)
    imported, report = mtf_author.replace_topology(model, fit_vertices(vertices, model.bounds()), triangles)
    built = mtf_author.replace_archive_model(archive, index, imported)
    check = mt_arc.parse(built)
    payload = check.entries[index].data
    try:
        decoded = zlib.decompress(payload)
    except zlib.error:
        decoded = zlib.decompress(payload, -zlib.MAX_WBITS)
    if decoded != imported:
        raise mtf_author.AuthorError("the archive did not round-trip the imported model")
    return built, imported, report | {"entry": parsed.entries[index].name, "model_bytes": len(imported),
                                    "archive_bytes": len(built), "textures": "original target materials"}


def main(argv=None) -> int:
    root = Path.home() / "gBox_alt"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=root / "switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive/uEm10.arc")
    parser.add_argument("--source", type=Path, default=root / "gbox-cache/characters/sonic/sa2_sonic_0.glb")
    parser.add_argument("--model", default="em1000", help="exact MOD basename; em1000_low is a separate model")
    parser.add_argument("--output", type=Path, default=Path("/tmp/em10_high_sonic.arc"))
    parser.add_argument("--overlay", type=Path, help="write a complete test overlay here, without installing it")
    parser.add_argument("--main", type=Path, help="optional extracted main image for IPS instruction preflight")
    args = parser.parse_args(argv)
    try:
        vertices, triangles = source_mesh(args.source)
        archive, model, report = build_archive(args.archive.read_bytes(), vertices, triangles, model_name=args.model)
        changes = re5_ips.rebind_changes(archive, main=args.main.read_bytes() if args.main else None)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(archive)
        args.output.with_suffix(".bin").write_bytes(model)
        if args.overlay:
            for name, change in changes.items():
                path = args.overlay / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(change["bytes"])
        report |= {"source": str(args.source), "output": str(args.output),
                   "overlay": str(args.overlay) if args.overlay else None, "files": list(changes),
                   "target_revision_verified": args.main is not None}
        args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
