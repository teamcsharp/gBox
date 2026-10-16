# Read-only visual cast roster

The cast menu opens a two-roster mapping window in the web and desktop clients. Search for an owned source title, click or drag a replacement onto an original, or shuffle a selected donor pool. Available thumbnails and GLB/glTF models open for inspection. Manual connections can be locked before shuffling. A session draft retains connections, locks, donor pool and the visible shuffle seed when the window is reopened.

Review checks the diagram against the native planner. Native build submission requires a combined writer, ready donors, actual native target slots and an exact match between the reviewed diagram and the returned plan. Pending characters remain selectable for planning, but cannot be passed off as writable native slots. The engineering request preserves the exact diagram, including unchanged targets and roster-only references, for extraction and writer work. Controls stay frozen while that request is being saved; retries reuse the same request identity.

Opening the window performs read-only roster lookups. Closing it releases viewers, timers and polling without cancelling a submitted request or job. Choosing an arbitrary source title creates a mapping plan; it does not establish that the target supports a playable conversion.

`GET /api/cast_swap/roster?game_id=<exact target ID>&source=<named group or exact source ID>&slots=all` returns the target game, selected source, target rows, donor rows and writer capability. It does not submit jobs, collect assets, refresh stale readers, plan a build or launch a game.

Native target IDs are actual writer slot names. Independently registered or extracted target characters use stable `roster:<slug>` IDs with `slot:null` and `buildable:false`. A single `player` slot does not absorb a title's other characters. Native rows receive collection images/models only from a unique exact registered identity: a declared collection slug or reader slot, shared native ID (JGR), Twin Snakes' reader-key-to-slot function, AUF's context body key, or SA2's explicit `SONIC` player resource. An ambiguous match receives no enrichment. Only the matched original is removed from the separate roster list; the remaining cast stays visible and non-writable.

Source title IDs are matched exactly; equal display titles across platforms or editions do not share collection metadata. Existing collection files receive their authenticated character-file URLs only when the files exist within the correct entry. Missing assets have null URLs. An exact catalog source with no exports still returns its known registered roster as pending donors, or an empty pending donor list when no roster is registered.

Donor `ready` uses the existing cast-swap readiness gate without automatic re-extraction and additionally requires available model/preview files and exact source provenance. Registered-but-missing, stale and refused donors carry a reason. Named source groups retain existing costume and preferred-pack selection. Readiness does not establish that a particular target can accept the donor.

`slots` filters actual native rows with the existing native slot filter. Roster-only rows can match their known kinds/groups, main-cast kind, slug or stable ID. Unknown scopes yield no invented rows and expose the pending coverage reason. `requested_scope` records the selection.

Capability reports `ready`, `partial` or `unsupported`, the registered writer, a boolean `combined_writer`, visible native slot count, and blocking reasons. A single-replacement writer remains partial and cannot imply whole-cast support. Existing `/api/cast_swap/plan` and build gates are unchanged, including `unsupported_cast`; the visual inventory is not permission to bypass them.
