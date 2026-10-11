The right-hand Assets sidebar is shared by the desktop shell and standalone browser. The desktop owns one sidebar across Library, Requests, Control, Tools and Extract; embedded webviews suppress their standalone copy.

Assets are grouped by their source title. All title groups start collapsed, retain the operator's expansion choices, and load their contents on expansion. Each group shows its filtered asset count and pages through every matching file without a fixed collection cutoff. Search, asset-type and source-game filters apply before pagination. Sort choices are newest, recently copied, oldest, name, game, type and size. Recent-copy order also determines the order of title groups.

The index combines character/vehicle/object and environment collections, their usable companion files, Universal Asset Packages and their supported images/audio/raw files, extracted model artifacts, and the asset clipboard. It excludes unrelated issue screenshots and model preview images used as thumbnails. Collection titles canonicalize case differences in extraction provenance. Entries without a known source remain under Unknown title.

Textures, raw data (`.bin`/`.anim`) and audio that belong to a character, environment or package are not listed as separate cards. The owner shows a collapsed **Textures (N) / Files (N)** tree (only populated categories appear), and companion rows are fetched only when the tree is expanded. The default top level shows characters, models and environments. Unowned textures, audio and data remain available through their type filters, explicit filename searches, and `nest=false`. Searches can show a texture directly when its owner does not match. Searching a model's name retains its complete companion tree even when its texture filenames differ. `GET /api/assets?owner=<id>` returns an owner's companion files. Texture and file counts update when extraction adds files, even when the number of model cards stays the same.

Index metadata is read through a separate read-only SQLite snapshot, so emulator/frame/job writes do not hold the asset list behind the shared store lock. The snapshot closes after each build; the existing ten-second cache and API response shape remain unchanged.

Existing preview renders are reused. glTF/GLB/UAP artifacts without a preview receive a cached CPU-rendered thumbnail on demand. Raster textures are displayed directly; formats without a supported preview use a labelled format tile. Preview failures are cached until the source changes. No LLM calls or extraction jobs are made by opening or refreshing the sidebar.

Copy places a self-contained glTF/GLB on the gBox clipboard for the Blender add-on (Ctrl+Shift+V), or preserves another file type on the asset clipboard. Copy history survives restarts and includes existing clipboard audit entries and successful native Blender-copy jobs. Downloads retain their file extensions. The sidebar polls for changes every ten seconds; while viewing a long list it offers a refresh notice to preserve the operator's position.

Authenticated API endpoints:

- GET /api/asset-groups — filtered title groups, counts and representative thumbnails.
- GET /api/assets — filtered, sorted pages; total and source/type facets.
- GET /api/assets/{id}/preview — cached preview or format tile.
- GET /api/assets/{id}/file — original file (UAP exports as GLB).
- POST /api/assets/{id}/copy — copy and record durable recency.

Identifiers resolve through the index rather than accepting filesystem paths. Model clipboard dependencies must stay inside the asset folder. Metadata enumeration is cached for ten seconds and invalidated on accepted extraction/copy operations.
