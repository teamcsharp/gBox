"""This PC's fallback control plane; no Spark credentials or database required."""
import argparse
import logging
import re
import threading
import time
from pathlib import Path

from .config import HOST_OS, Config, Library, load

log = logging.getLogger(__name__)


def local_config(source: Config, data_dir: Path, port: int) -> Config:
    cfg = source.model_copy(deep=True)
    # Keep the installed runtime/cache even when the original uses default paths.
    cfg.cache_dir, cfg.runtime_dirs[HOST_OS] = source.cache, str(source.runtime)
    cfg.data_dir = data_dir
    cfg.api_host, cfg.api_port = "127.0.0.1", port
    cfg.public_url = f"http://127.0.0.1:{port}"
    cfg.cold_cache_dirs = {}
    cfg.showcase.enabled = False
    cfg.hermes.grunt.enabled = False
    cfg.libraries = [Library(id="offline-cache", kind="local-cache", paths={HOST_OS: str(cfg.cache)})] + cfg.libraries
    return cfg


def chd_platform(path: Path) -> str | None:
    """Read the first data sectors, without expanding a multi-GB disc."""
    from .chd import Chd
    from .catalog import sniff_head
    with path.open("rb") as f:
        version = int.from_bytes(f.read(16)[12:16], "big")
    if version == 4:
        from .psxdisc import CHD
        disc = CHD(path)
        try:
            first = disc.sector(0)
            platform = sniff_head(first, disc.logical)[0]
            if platform:
                return platform
            sectors = [disc.sector(i) for i in range(128)]
            cooked = b"".join(s[24:2072] if s[15] == 2 else s[16:2064] for s in sectors)
            return sniff_head(cooked, disc.logical)[0]
        finally:
            disc.f.close()
    chd = Chd(path)
    try:
        kind = (chd.tracks or [{}])[0].get("TYPE", "MODE1")
        sectors = []
        for i in range(128):
            frame = chd.frame(i)
            offset = 0 if kind == "MODE1" else 24 if kind == "MODE2_RAW" and frame[15] == 2 else 16
            sectors.append(frame[offset:offset + 2048])
        return sniff_head(b"".join(sectors), chd.h["logical_bytes"])[0]
    finally:
        chd.close()


def cache_entries(cfg: Config):
    from . import catalog, systems
    # Scan ordinary staged games, not extracted assets, incomplete copies or mod workspaces.
    roots = [p for p in cfg.cache.iterdir() if p.is_dir() and re.fullmatch(r"[0-9a-f]{16}", p.name)] if cfg.cache.is_dir() else []
    for root in roots:
        try:
            entries, _ = catalog.scan([root], {}, lib_id="offline-cache", do_hash=False)
            for entry in entries:
                if entry.platform == "unknown" and entry.format == "chd":
                    try:
                        entry.platform = chd_platform(Path(entry.source_paths[0])) or "unknown"
                    except Exception as exc:
                        log.warning("Cannot identify %s: %s", entry.title, exc)
                if entry.platform == "unknown":
                    continue
                if entry.platform == "ps1":
                    entry.platform = "psx"
                entry.system = entry.platform
                entry.game_id = entry.profile_id = root.name
                entry.rel_path = Path(entry.source_paths[0]).relative_to(cfg.cache).as_posix()
                entry.core = systems.core_for(entry.platform)[0]
                entry.launch.update(platform=entry.platform, core=entry.core)
                yield entry.model_dump(mode="json")
                break  # one original game per staging directory
        except Exception as exc:
            log.warning("Cannot index %s: %s", root, exc)


def index_local(cfg: Config, store):
    from . import catalog
    rows = list(cache_entries(cfg))
    store.upsert_catalog(rows)
    store.prune_catalog("offline-cache", {r["game_id"] for r in rows})
    print(f"Offline library: {len(rows)} cached games ready", flush=True)
    # Each library scans independently: an unavailable NAS never holds up the cache or local folders.
    def scan(lib):
        try:
            root = lib.root()
            if not root or not root.is_dir():
                return
            if lib.kind == "attract":
                entries, _, _ = catalog.scan_attract(root, lib.id)
            else:
                entries, _ = catalog.scan([root], {}, lib_id=lib.id, do_hash=False,
                    platform_hint=lib.platform, recursive=lib.recursive,
                    exclude_dirs=lib.exclude_dirs, exclude_files=lib.exclude_files)
            # Cached paths win over the original network location for the same game.
            cached = {r["game_id"] for r in rows}
            store.upsert_catalog([e.model_dump(mode="json") for e in entries if e.game_id not in cached])
            print(f"Offline library: indexed {lib.id} ({len(entries)} games)", flush=True)
        except Exception:
            log.exception("Cannot index library %s", lib.id)
    for lib in cfg.libraries:
        if lib.id != "offline-cache":
            threading.Thread(target=scan, args=(lib,), daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    cfg = local_config(load(args.config), Path(args.data_dir), args.port)
    import uvicorn
    from .server import create_app
    from . import worker
    app = create_app(cfg)
    threading.Thread(target=index_local, args=(cfg, app.state.store), daemon=True).start()
    threading.Thread(target=lambda: (time.sleep(1.5), worker.run(cfg.public_url, cfg.token(), cfg, args.name)), daemon=True).start()
    uvicorn.run(app, host=cfg.api_host, port=cfg.api_port, log_level="warning")


if __name__ == "__main__":
    main()
