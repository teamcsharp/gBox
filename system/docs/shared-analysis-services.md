# Shared analysis sources and archive tools

`prepare_task_workspace` returns `shared_sources.manifest`, an inventory of Python modules installed on the
prime Spark and hashed reference copies of modules missing from or different in the task checkout. References
live outside Git; task patches and shared runtime files are preserved. Copy a required implementation into the
task checkout, test it, and publish through the normal delivery path. A runtime copy is evidence, not proof of
review or deployment. A name absent from both locations still needs investigation; do not invent that module.

Authenticated clients can GET `/api/analysis/sources` and `/api/analysis/sources/file?path=gbox/module.py`.
Verify the response's `x-content-sha256` against the manifest before staging code for a kiosk. These endpoints
share Python source only; they do not share tokens, configuration, ROMs, saves or system binaries. Deploy
reviewed changes with the existing platform bootstrap/deployment scripts, preserving local changes and waiting
for an idle worker before restarting. Source access alone does not install a service or restart a kiosk.

Each worker needs its own platform's archive executable. `provision_archives` installs
or verifies 7-Zip without installing emulators or changing library mounts. Select `require_worker` for the target
kiosk. The normal `gbox setup` also checks this dependency and records its receipt. Existing INSTALL permissions
apply. Ghidra and other analysis services remain available through the full provisioning operation.
The dedicated tool name prevents an old worker from silently ignoring a new option and running full setup.
Workers must load the updated registry before advertising this tool; busy kiosks can defer that refresh.

Catalog inspection, launch extraction, fingerprinting and ROM executable reads use `rom_archives`.
ZIP and TAR/TAR.GZ/TAR.BZ2/TAR.XZ have Python readers. 7-Zip handles 7z, RAR and its supported CAB, WIM,
ARJ, LZH, CPIO, DEB, RPM, XAR, split and compressed-stream formats. Actual codec support depends on the installed
7-Zip build. Encrypted archives require credentials; damaged, missing-volume and unsupported proprietary archives
must report their error. No extractor can guarantee every arbitrary archive. Unsafe paths and links are rejected.

The Requests **Export history** button downloads all retained operator prompts and follow-ups plus chat turns,
ordered by individual UTC timestamp. Explicit chat/request links remove duplicate copies of the same event;
repeated independent prompts are retained. The export ignores inbox filters and pagination. It redacts credentials
and cannot reconstruct deleted or never-imported external history. `/api/requests/export` without
`prompts_only=true` retains the full request/response transcript export.
