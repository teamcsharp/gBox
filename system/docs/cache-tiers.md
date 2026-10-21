# Two-tier game cache (Spark)

The Spark caches staged titles, base copies, built mods and the character library on its own disks. The internal
NVMe is fast but shared with everything else; the Elements HDD (spinning disk, NTFS through ntfs-3g, USB 5 Gbps, about
90 MB/s sequential, very slow small-file metadata) is big. A single cache on the HDD was too slow:

| operation (on the HDD)                | measured     |
|---------------------------------------|--------------|
| character list re-read                | 35-82 s      |
| asset index                           | 35-42 s      |
| hashing a 1.4 GB build                | 34 s         |
| DOA2 roster manifest                  | 156 s        |
| DOA2 roster build                     | 33+ min (about 7 min on a PC SSD) |

So the cache has two tiers. The NVMe is a hot tier capped at 100 GB. The HDD is the cold tier. Old data moves to the
HDD only while the Spark is idle, and moves back when it is used. The rest of gBox does not know about the tiers.
Code: `gbox/cache_tiers.py`. Tests: `tests/test_cache_tiers.py`, `tests/test_cache_tiers_card.cjs`.

## Configuration

`gbox.toml` on the Spark:

```toml
cache_dirs = { linux = "/home/ehm_eckx/gBox_alt/gbox-cache", windows = "D:/gBox/cache" }   # hot tier (NVMe) on the Spark
cache_limits_gb = { linux = 150, windows = 250 }                                    # staged-copy eviction ceiling
cold_cache_dirs = { linux = "/home/ehm_eckx/samples/gbox-cache" }                   # cold tier (Elements HDD)
hot_cache_limit_gb = { linux = 100 }                                                # demotion keeps the NVMe under this
cache_tier_idle_minutes = 30                                                        # idle time before anything is demoted
```

Other settings, with their defaults: `cache_tier_warm_fraction = 0.5` (after the migration, recently used games are
promoted up to half of the cap) and `cache_tier_promote_wait_s = 60` (a launch waits for its game to move up only when
that takes less than this).

Tiering is turned on per OS by a `cold_cache_dirs` entry. The Windows PCs have none, so they keep their single
`D:/gBox/cache` and nothing changes there. `GET /api/cache/tiers` answers `enabled: false` on such a node.

The cold dir must already exist. gBox never creates it, so a drive that is not mounted cannot make gBox write onto the
NVMe under the empty mount point. If it is missing, gBox moves nothing and the status shows a warning.

`cache_limits_gb` keeps its meaning: it is the size at which LRU eviction deletes staged copies of library files after
a staging copy (`catalog.evict`). Eviction now counts only real files on the hot tier and never follows a symlink, so
data demoted to the HDD is never deleted. It also never touches `mods/`, `modbase/` (mods hard-link onto it),
`characters/`, `environments/`, `characters_mirror/` or `.gbox-tiers/`. This also applies on Windows: eviction used to
be able to delete base copies and the character library. Because demotion keeps the NVMe near 100 GB, the 150 GB
eviction is only a safety net for a long busy period with no idle window.

## What moves, and what stays

A **unit** is everything that belongs to one game and hard-links together. These folders move together:

- `<gid>/` (staged discs)
- `dc/<gid>/` and `gc/<gid>/` (extracted discs)
- `modbase/<gid>/` (the base copy)
- `mods/<gid>/` (every built mod: a hard-link tree onto the base, with its `.gbox-mod.json` marker and
  `.<mod>.sha256.json` hash sidecar)
- `romexport_base/<gid>/`

Hard links are kept on the HDD too (ntfs-3g supports them), so a mod never duplicates its base when it moves.

Other top-level folders (RE workspaces such as `lcs_re`, `sprite_captures`, `fitting-jobs`, `n64-rom`, ...) are one
unit each. Each child of `characters_build/` is a unit of its own: `characters_build/cast`, `characters_build/<slug>`,
and so on.

**Pinned on the NVMe, never demoted:**

- the character library `characters/`
- the environment library `environments/`
- `characters_mirror/`
- every top-level file: `.gbox-staged.json` (the stage db) and other indexes
- anything hidden

The built mods index (`data_dir/built_mods_index.json`) and the asset index (`data_dir/gbox.sqlite3`) were already
in the data dir, which is on the NVMe.

Markers and hash sidecars are not split off from their mod folder. gBox checks that a mod folder is one real tree with
no symlinks inside (`filemods._matches`, `_file_path`), and the sidecar must stay next to its folder. A cold game's
markers are read only when that game is used, and using it moves it back up.

The status shows the pinned size. If pinned data alone reaches 80% of the cap, it shows a warning.

## How a move works

- **Demotion (NVMe to HDD)** happens only in idle time. All of these must hold:
  - no game session on the Spark
  - no job running on the Spark's worker
  - no launch copy in flight
  - none of the above for `cache_tier_idle_minutes`
  - nothing touched the game for that long either: a job input or an API path or query that names the game counts
    as a touch

  The least recently used games go first. Last use is recorded in `<hot>/.gbox-tiers/state.json`, because atime is
  unreliable on ntfs-3g. Demotion runs until the NVMe is under 90% of the cap.

  A game with a file open in any process (`/proc/*/fd`, `maps`, `cwd`) is skipped. The copy runs at idle I/O
  priority and nice 10. It is verified: the file list and sizes are compared, and every file's SHA-256 is re-read
  from the HDD after `fsync` and dropping the page cache. The copy gives way as soon as the Spark gets busy or the game
  is asked for.

  At the end, the real folder and a symlink to the HDD copy are swapped atomically with
  `renameat2(RENAME_EXCHANGE)`. Every `Path(cfg.cache) / ...` path still works afterwards, just slower.

  The HDD stores times in 100 ns steps. After a demotion, the hash sidecars and the stage db get the new mtimes for
  files whose content was verified, so nothing is re-hashed.

  A move needs its size plus 2 GB free on the target disk. A background move can fail, for example on a file name
  that the NTFS side refuses. The game is then left alone for 6 hours (10 minutes for a pinned library) instead of
  being re-read on every pass, and the status shows the error on its row.

- **Promotion (HDD to NVMe)** happens on access. Every tool run on the Spark goes through `registry.execute`. When the
  run's input names a game (its id in any field, or a path under either cache root), that game moves up before the
  tool runs, and the job shows "Moving <gid> to the fast drive". This covers builds, writers, collect, file mods and
  romexport.

  There are two exceptions. A launch waits only when the move fits in `cache_tier_promote_wait_s`. Otherwise the game
  plays from the HDD (as it did before), and it moves up once the Spark is idle again. It may push out an older game.
  A job that names more than four games (a sweep) only marks them used.

  The central mod collection works like this:
  - `GET /api/modfiles/<gid>/<mod>` answers from wherever the game is. The sidecar makes that cheap. The game is
    queued to move up when idle.
  - Uploads (`PUT .../file/...`) move the game up first, so new writes land on the NVMe.

  New folders that a writer creates are always created on the NVMe. A game can be split for a while, with some folders
  on each drive. The next move takes all of it.

- **Crash safety.** Every move is journaled under `<hot>/.gbox-tiers/journal/`. At every step, either the NVMe copy or
  the HDD copy is complete and reachable at the cache path, never neither:
  1. Copy into a staging folder on the target drive.
  2. Verify the copy.
  3. Switch atomically.
  4. Carry over writes that arrived during the switch.
  5. Put the old copy in a trash folder. It is deleted later, when nothing holds it open.

  At start-up, gBox rolls back every interrupted move from before the switch. It finishes every interrupted move from
  after it. `tests/test_cache_tiers.py` cuts power in the copy, in the middle of a multi-folder switch, and between
  the unlink and the rename of the non-atomic fallback.

## Migration (first start with this code)

Start-up (`cache_tiers.install`, called first in `create_app` and in `worker.run`) is idempotent:

1. It finishes or undoes any journaled move.
2. **It links everything on the HDD.** Every top-level folder on the HDD, and every child of `dc`, `gc`, `modbase`,
   `mods`, `romexport_base` and `characters_build`, gets a symlink in the hot dir if the hot dir has no entry for it.
   This only creates links, so it takes seconds.
3. **It copies the top-level files.** Each one is copied and verified. The HDD original is renamed
   `<name>.migrated-to-hot`. The keys of `.gbox-staged.json` are moved from the HDD path to the hot path, so known
   hashes survive.
4. **It points the built mods index at the hot dir.** `built_mods_index.json` has a `root` field. If it names the HDD's
   `mods/`, it is changed to the hot dir's `mods/`, so the index is not rebuilt with a walk of the HDD.
5. **It handles leftovers in the hot dir.** `/home/ehm_eckx/gBox_alt/gbox-cache` still holds about 1.5 GB written by the old
   service just before the HDD cutover: modbase, n64-rom, and one game folder.
   - On the first migration, a leftover that also exists on the HDD is moved to
     `/home/ehm_eckx/gBox_alt/gbox-cache/.gbox-tiers/conflicts/<stamp>/`. The HDD copy is what the service has used since the
     cutover. Nothing is deleted.
   - A leftover that exists only in the hot dir stays there as a hot game.
   - On later starts, the hot copy wins. A duplicate on the HDD is only reported in the status.

   Using `/home/ehm_eckx/gBox_alt/gbox-cache` as the hot dir also brings back the hard-coded `~/gBox_alt/gbox-cache/...` paths
   (`n64_rom`, `nfl2k2_inventory`, the PSO disc paths in `server.py`). They resolve through the hot view again.
6. **It copies the pinned libraries in the background, right away.** This starts with the character library and is
   not idle-gated, because those libraries are what made the HDD slow to use. Until the copy finishes, the library
   is read through the symlink, just as before. Writes made during the copy are caught by delta passes. After the
   switch, the HDD original is renamed `characters.migrated-to-hot`. It is the operator's to delete.
7. **It warms the NVMe.** When idle, it promotes the most recently used games, newest folder mtime first, up to 50%
   of the cap (50 GB).

## Status and controls

`GET /api/cache/tiers` returns:

- NVMe used, cap and pinned bytes, and free space on both disks
- game counts on each tier
- the 60 most recently used games, with tier, size, last use and pin
- moves in progress and the last 15 moves
- the queue
- whether pinned copies are still pending
- migration facts and conflicts
- the idle state and warnings

`POST /api/cache/tiers/pin {"unit": "<gid>", "pin": true}` keeps a game on the NVMe. A pinned game is never demoted,
and it is promoted when the Spark is idle.

The desktop app's **Settings** tab has a "Game cache drives" card with the same facts and a "Keep on NVMe" box per
game.

## Deploy notes

1. **PR #181 (`spark-cache-on-hdd`) merges first.** It moves `cache_dirs.linux` to the HDD and matches what the share
   has run since the cutover on 2026-10-13. This branch is built on top of it.
2. After this PR merges, the deploy cron (`scripts/deploy_main.sh`, every 15 min) copies it to the share and restarts
   `gbox.service` when the Spark is idle. That restart runs the migration above.
3. No manual step is needed. After the restart:
   - check the status: `curl -s -H "authorization: Bearer $(cat gbox-data/api_token)" localhost:8765/api/cache/tiers | jq .hot,.pinned_pending,.conflicts`
   - check the log: `journalctl -u gbox | grep "cache tiers"`
   - expect `pinned_pending: ["characters"]` until the library copy finishes
4. What the operator may want to delete later, when it suits them:
   - `~/gbox-cache.migrated-to-hdd-20261012` (the old NVMe cache, 360 GB)
   - `/home/ehm_eckx/samples/gbox-cache/characters.migrated-to-hot`
   - `~/gBox_alt/gbox-cache/.gbox-tiers/conflicts/`

**Going back to one tier.** Stop `gbox.service`. Then copy the real data from the hot dir to the HDD, without the
links (which point there already):

```sh
rsync -aH --no-links --exclude .gbox-tiers /home/ehm_eckx/gBox_alt/gbox-cache/ /home/ehm_eckx/samples/gbox-cache/
```

Then set `cache_dirs.linux` back to the HDD and remove `cold_cache_dirs`. The stage db keys will name the hot dir,
so the first launches re-hash.
