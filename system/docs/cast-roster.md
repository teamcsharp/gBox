# Read-only visual cast roster

`GET /api/cast_swap/roster?game_id=<exact target ID>&source=<named group or exact source ID>&slots=all` returns the target game, selected source, target rows, donor rows and writer capability. It does not submit jobs, collect assets, refresh stale readers, plan a build or launch a game.

Native target IDs are actual writer slot names. Independently registered or extracted target characters use stable `roster:<slug>` IDs with `slot:null` and `buildable:false`. A single `player` slot does not absorb a title's other characters. Native rows receive collection images/models only when the writer explicitly names their exact collection identity from the target game.

Source title IDs are matched exactly; equal display titles across platforms or editions do not share collection metadata. Existing collection files receive their authenticated character-file URLs only when the files exist within the correct entry. Missing assets have null URLs. An exact catalog source with no exports still returns its known registered roster as pending donors, or an empty pending donor list when no roster is registered.

Donor `ready` uses the existing cast-swap readiness gate without automatic re-extraction and additionally requires available model/preview files and exact source provenance. Registered-but-missing, stale and refused donors carry a reason. Named source groups retain existing costume and preferred-pack selection. Readiness does not establish that a particular target can accept the donor.

`slots` filters actual native rows with the existing native slot filter. Roster-only rows can match their known kinds/groups, main-cast kind, slug or stable ID. Unknown scopes yield no invented rows and expose the pending coverage reason. `requested_scope` records the selection.

Capability reports `ready`, `partial` or `unsupported`, the registered writer, a boolean `combined_writer`, visible native slot count, and blocking reasons. A single-replacement writer remains partial and cannot imply whole-cast support. Existing `/api/cast_swap/plan` and build gates are unchanged, including `unsupported_cast`; the visual inventory is not permission to bypass them.
