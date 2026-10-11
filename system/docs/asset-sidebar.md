The right-hand Assets sidebar is shared by the desktop shell and standalone browser. The desktop owns one sidebar across Library, Requests, Control, Tools and Extract; embedded webviews suppress their standalone copy.

Assets are grouped by their source title. All title groups start collapsed, retain the operator's expansion choices, and load their contents on expansion. Each group shows its filtered asset count and pages through every matching file without a fixed collection cutoff. Search, asset-type and source-game filters apply before pagination. Sort choices are newest, recently copied, oldest, name, game, type and size. Recent-copy order also determines the order of title groups.

The index combines character/vehicle/object and environment collections, their usable companion files, Universal Asset Packages and their images/audio, extracted model artifacts, and the asset clipboard. It excludes unrelated issue screenshots and model preview images used as thumbnails. Collection titles canonicalize case differences in extraction provenance. Entries without a known source remain under Unknown title.

Textures that belong to a character, environment or package are not listed as separate cards. The owner shows a collapsed **Textures (N)** tree, and the texture rows are fetched only when the tree is expanded, so the top level shows characters, models and environments. Textures without an owner, or whose owner is excluded by the current search, stay at the top level. The **texture** type filter lists textures directly. `GET /api/assets?owner=<id>` returns an owner's textures; `nest=false` returns the flat list.

Existing preview renders are reused. glTF/GLB/UAP artifacts without a preview receive a cached CPU-rendered thumbnail on demand. Raster textures are displayed directly; formats without a supported preview use a labelled format tile. Preview failures are cached until the source changes. No LLM calls or extraction jobs are made by opening or refreshing the sidebar.

Copy places a self-contained glTF/GLB on the gBox clipboard for the Blender add-on (Ctrl+Shift+V), or preserves another file type on the asset clipboard. Copy history survives restarts and includes existing clipboard audit entries and successful native Blender-copy jobs. Downloads retain their file extensions. The sidebar polls for changes every ten seconds; while viewing a long list it offers a refresh notice to preserve the operator's position.

Authenticated API endpoints:

- GET /api/asset-groups — filtered title groups, counts and representative thumbnails.
- GET /api/assets — filtered, sorted pages; total and source/type facets.
- GET /api/assets/{id}/preview — cached preview or format tile.
- GET /api/assets/{id}/file — original file (UAP exports as GLB).
- POST /api/assets/{id}/copy — copy and record durable recency.

Identifiers resolve through the index rather than accepting filesystem paths. Model clipboard dependencies must stay inside the asset folder. Metadata enumeration is cached for ten seconds and invalidated on accepted extraction/copy operations.
