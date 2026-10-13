The right-hand Assets sidebar is shared by the desktop shell and standalone browser. The desktop owns one sidebar across Library, Requests, Control, Tools and Extract; embedded webviews suppress their standalone copy.

Assets are grouped by their source title. All title groups start collapsed, retain the operator's expansion choices, and load their contents on expansion. Each group shows its filtered asset count and pages through every matching file without a fixed collection cutoff. Search, asset-type and source-game filters apply before pagination. Sort choices are newest, recently copied, oldest, name, game, type and size. Recent-copy order also determines the order of title groups.

The index combines character/vehicle/object and environment collections, their usable companion files, Universal Asset Packages and their supported images/audio/raw files, extracted model artifacts, and the asset clipboard. It excludes unrelated issue screenshots and model preview images used as thumbnails. Collection titles canonicalize case differences in extraction provenance. Entries without a known source remain under Unknown title.

Textures, raw data (`.bin`/`.anim`) and audio that belong to a character, environment or package are not listed as separate cards. The owner shows a collapsed **Textures (N) / Files (N)** tree (only populated categories appear), and companion rows are fetched only when the tree is expanded. The default top level shows characters, models and environments. Unowned textures, audio and data remain available through their type filters, explicit filename searches, and `nest=false`. Searches can show a texture directly when its owner does not match. Searching a model's name retains its complete companion tree even when its texture filenames differ. `GET /api/assets?owner=<id>` returns an owner's companion files. Texture and file counts update when extraction adds files, even when the number of model cards stays the same.

Index metadata is read through a separate read-only SQLite snapshot, so emulator/frame/job writes do not hold the asset list behind the shared store lock. The snapshot closes after each build.

The index lives in memory and is never rebuilt on the request path (on the Spark's NTFS HDD a full scan of every asset file took 34-42 s, and the old ten-second cache made almost every sidebar load time out). How it stays current:

- Each request compares a cheap signature with the snapshot's: artifact and asset-copy row counts in the metadata DB, the mtimes of the character, environment and UAP roots, the character library's in-process write counter, and explicit invalidations (copies, clipboard writes, accepted extraction and Blender-copy jobs). It also re-checks the mtimes of folders that had no `meta.json`/`manifest.json` yet or were still being written (modified within the last two seconds).
- On a change the request starts an incremental rebuild and waits up to one second for it, then answers with the newest snapshot it has. An incremental rebuild re-reads only the folders whose `meta.json` or directory mtimes changed. Artifact file stats are cached by SHA-256, because artifacts never change.
- In the background (stale-while-revalidate), every folder's mtimes are re-checked every 60 s, which finds files added inside an existing folder. If nothing changed, the snapshot is kept as it is. Every 30 minutes everything is rescanned, which also catches files rewritten in place. `fresh=1` on either list endpoint (the sidebar's ↻ button) starts that full rescan right away.
- The server builds the first snapshot in the background at startup. Set `GBOX_ASSET_WARM=0` to skip this. Until that first snapshot exists, the list endpoints answer `indexing: true` with no items, and the sidebar shows *Indexing assets…* and retries with backoff. It does the same when a request times out (the desktop allows asset listings 20 s), instead of showing an error.

A scan lists each directory once and stats each supported file once. The old scan called `rglob`, `is_file`, `resolve()` and `stat()` per file, about six syscalls each. On a synthetic store with 640 collections, about 31k files and 4k artifacts, a build fell from 41.9 s to 2.2 s. Repeat requests take about 3 ms, and an incremental rebuild after a new character or artifact takes about 0.8-1 s. Measured on Windows NTFS, where a cold 41.9 s build is comparable to the Spark's.

Existing preview renders are reused. glTF/GLB/UAP artifacts without a preview receive a cached CPU-rendered thumbnail on demand. Raster textures are displayed directly; formats without a supported preview use a labelled format tile. Preview failures are cached until the source changes. No LLM calls or extraction jobs are made by opening or refreshing the sidebar.

Copy places a self-contained glTF/GLB on the gBox clipboard for the Blender add-on (Ctrl+Shift+V), or preserves another file type on the asset clipboard. Copy history survives restarts and includes existing clipboard audit entries and successful native Blender-copy jobs. Downloads retain their file extensions. The sidebar polls for changes every ten seconds; while viewing a long list it offers a refresh notice to preserve the operator's position.

Authenticated API endpoints:

- GET /api/asset-groups — filtered title groups, counts and representative thumbnails (`fresh=1` rescans every file in the background).
- GET /api/assets — filtered, sorted pages; total and source/type facets; `indexing` (no snapshot yet) and `updating` (a rebuild is running).
- GET /api/assets/{id}/preview — cached preview or format tile.
- GET /api/assets/{id}/file — original file (UAP exports as GLB).
- POST /api/assets/{id}/copy — copy and record durable recency.

Identifiers resolve through the index rather than accepting filesystem paths. Model clipboard dependencies must stay inside the asset folder.
