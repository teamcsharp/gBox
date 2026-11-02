# Game Analysis

Right-click a running game or a catalog title and choose **Analysis**. The overlay collects existing session reports, visual observations, exact-linked job console lines, and receipt artifacts. It shows measured counts, job states, source timestamps, and an elapsed collection window. These measurements are not a percentage of reverse engineering completed.

A live run stays bound to its original session, process details when reported, title, and selected build. It ends if that identity changes; it never adopts a replacement game. Catalog Analysis does not launch a game and has no native telemetry. Missing disc or derived-build hashes remain explicitly unverified.

Collection defaults to 300 seconds, with a 600-second maximum and four simultaneous runs. **Hide** toggles the overlay while bounded collection continues. **Stop analysis** ends this run and cancels only its own local-model job. It never stops the game or its autoplay controller. Console scrolling stays where the operator left it; it follows new lines only when already at the bottom.

Opening live Analysis automatically requests one bounded evidence review on that exact session worker when its local Ollama assistance policy is enabled and the selected model is installed. A per-title preference can turn automatic reviews off. The worker chooser permits an explicit alternate selection. There are no model downloads or cloud fallbacks. An unavailable model or resource wait is shown in the overlay.

The existing CPU, RAM, GPU admission budget, excluded-PC policy, and fresh resource telemetry remain mandatory. Explicit gameplay coexistence applies only to the exact Analysis run/job/worker, expires with the run, and does not cover another human session on that PC. Running inference rechecks permission and the free-memory reserve. This is bounded, cooperative admission, not an OS hard throttle. Ollama output reports model/token usage; it does not attest actual GPU placement.

Each run writes immutable, content-addressed `gbox.analysis.crystal.v1` checkpoints with title/build provenance, session identity, timestamped sources, linked jobs/artifacts, measured sample counts, and model hypotheses. Export links retain artifact hashes. PSO native review blocks also link their exact run crystal and source sequence. Reusing a finding requires matching build evidence and fresh validation; session-specific addresses and recorded paths are not portable authority.

Generic mapping, mission, inventory, mods, extraction, and replacement rows show installed hooks separately from verified support. Requested feature preferences do not enable execution. Analysis never sends controls, writes native memory, pauses/restarts a game, or dispatches arbitrary model tools. Extraction/replacement operations remain disabled until a verified adapter and explicit operation are integrated.

API: `POST /api/analysis`, `GET /api/analysis/{id}`, `POST /api/analysis/{id}/stop`, `POST /api/analysis/{id}/model`, `PUT /api/analysis-preferences/{game_id}`, and `GET /api/analysis-crystals/{game_id}`. Session job lookup uses the session index; catalog lookup considers up to 30 matching jobs among the latest 200 jobs.
