# RE2 GameCube inventory and equipment transactions

This implementation is for library title `c6adbfa00c20aaf9`, GHAE08, with the exact
owned main DOL and Leon/Claire REL hashes in `re2gc_state.py`. It is a runtime
inventory writer, not an all-unlocks profile or a claim of gameplay acceptance.
No live game was changed during implementation. Native acceptance remains required.

## Sidebar behavior

The existing session sidebar exposes carried slots, the 64-entry item box, item
IDs/reference names, quantities, equip and unequip. Jobs are pinned to the current
session worker. Before any job, the panel checks that exact worker is online,
runs Windows and advertises the tool; unsupported sessions show the reason without
submitting a doomed job. Open the native inventory, select an item, and close action popups
before editing. A successful edit closes that menu through the native game routine.
The panel requires a fresh read after reopening the menu. Unknown completion blocks
repeat mutations until refresh, and the backend never retries a close request.

The ten carried records contain at most eight or ten active slots. The reserved
lighter/lockpick record is never edited. Items 0x0e through 0x12 occupy paired carried
slots (markers 1/2, matching ID/count); their boxed record uses marker 3. Existing
boxed marker 1 is accepted because the owned initialization uses it. Replacing the
second half replaces the complete pair. A larger replacement requires the adjacent
slot to be empty, and slot capacity cannot be extended through this tool. Unknown
fourth bytes, inactive slots and unrelated storage are preserved.

IDs below 0x68 follow the bound in the owned code. Quantities are unsigned bytes;
non-weapon items require a positive count, and an empty record requires zero.
Reference names in `re2gc_item_labels.json` come from the existing PSX label catalog
only. No PSX addresses, capacity claims or unlock flags are used. GameCube labels
and actual item effects still need native screen confirmation.

## Owned native evidence

The analyzed images use synthetic REL base 0x80400000 only for cross-references.
Runtime module/BSS addresses always come from the linked OS module list and section
table, followed by whole executable-section comparison against relocated owned code.
Only the two existing exact Dolphin audio NOP exceptions are accepted.

| Operation | Leon REL offset | Claire REL offset |
|---|---:|---:|
| Inventory main callback | 0x73d6c | 0x73b78 |
| Inventory close/equipment reload | 0x741e8 | 0x73fc0 |
| PLW resource loading | 0x3cac4 | 0x3cb3c |
| Weapon model/animation setup | 0x3cd3c | 0x3cdb4 |
| Task spawn | 0x3a7f8 | 0x3a870 |

Both scenarios use BSS-relative task table 0x10748, stride 0x24 (eight records),
inventory task 1 at 0x1076c, current-task pointer 0x10868 and inventory control 0x1352c.
The owned scheduler at Leon REL+0x3a520 initializes a newly spawned status-2 task,
sets status 0x7f while executing its callback, and returns an ordinary yielded task
to status 1 with wait count 1. Writes require yielded inventory status/wait 1/1,
init/fade bytes 1/0, exact callback pointer, a current-task pointer in the eight-record table but outside
the inventory callback, active inventory
phase 1/submenu 3/action 0/subphase 0, normal mode 0 and ready flag 1. Pending native
equipment edits must first be closed/reopened. The loaded weapon word must agree.

Writing phase 2 requests the existing close callback. That callback compares prior
and current equipment, updates loaded weapon word 0x80163f36 (preserving upper flag
bits), removes old model geometry and runs native PLW/model/animation/sound loading.
After it finishes, the tool checks task completion, equipment, loaded weapon and
both storage arrays. It does not substitute a raw equipped-item byte change for
native resource loading and does not overwrite saved-equipment fields.

`re2gc_weapons.json` records the exact owned path, size and SHA-256 for original
Leon/Claire weapon streams with 15-bone EMR animation data. Several other nominal
weapon files are placeholders with only four EMR bytes. They are not equip choices.
Each selected resource is reread and hash-checked from the actual launched image.
Only original character IDs 0/1 are currently mapped; other characters fail closed.
This is source-resource evidence, not a proof that every weapon fires correctly.

## Transaction and concurrency

Windows Dolphin direct process memory is required. The cached `DolphinProcMem`
instance now owns a reentrant lock used by reads, writes, close, and adapter
pause/resume. Lock acquisition has a two-second bound; an internal 60-second pre-dispatch budget
and cancellation checkpoint prevent delayed preparation from writing after the
90-second tool timeout. The registry captures an absolute deadline before executor
submission in execution-local context; RE2 requires at least 15 seconds remaining
immediately before its first write. A queued tool that starts after its outer
timeout therefore cannot mutate, even when its context object is reused. The inventory operation holds the lock from its native-progress gate through
completion, preventing existing gBox memory/cheat writes and pause/resume commands
from interleaving. It never acquires a cheat ownership lock while holding this lock.

Each short memory snapshot/write context suspends every enumerated emulator thread
through retained Win32 thread handles, verifies PID/start time and stable thread
membership, and balances each successful suspension on exit. Failed partial holds
are unwound. Resume API failure is retried once, all other held handles are still
released, and unrecoverable failures are reported explicitly. No window or GDB
requests occur while emulator threads are held. The prior suspension count is
preserved; this is verified on a newly created hidden Windows child, never a user's
emulator. Known operator pause is rejected before mutation. Bounded observation of two advances in the owned main-loop counter (BSS+0x7e78,
Leon REL+0x3169c / Claire REL+0x316d8) rejects a Dolphin UI pause without resuming it.
The active-game flag and native pause byte are also checked. Linux mutation remains disabled because the existing GDB halt helper
can report halted without proving a stop acknowledgement.

The actual launched ISO/GCZ is opened read-only. Bounded reads enforce known DOL/REL
sizes before allocation and exact SHA-256 before interpreting layouts. Source
file identity/size/mtime is checked on both path and open descriptor. Sidebar tokens
bind relevant inventory/control/module data to the exact process PID/start time.

Before writing, the tool fsyncs a new JSON backup under
`cache/re2gc-inventory-backups/` and adds the same bytes as a job artifact. It then
rechecks process, code, module, menu gates and stale-view token under the strict
hold. Every staged range has expected original bytes and exact readback. Failed or
partial writes restore all touched ranges in reverse order and verify restoration
before releasing the emulator. The close phase is written last.

Once the emulator resumes, native model/animation state may change. A byte-only
rollback at that point would be unsafe. Timeout, changed process, failed native
completion or post-staging resume failure returns an explicit unknown outcome,
backup location/hash and `retry_allowed=false`. No late byte rollback is attempted.

## Required native acceptance

Use a disposable copy of an authorized save on the local PC, not another machine.
Verify Leon and Claire separately: ordinary count/item change, two-slot creation
and removal, equip/unequip, real native weapon reload, placeholder rejection,
item-box persistence, known pause and Dolphin UI pause rejection, and failure
cleanup. Capture before/after native inventory and gameplay frames and exact source
and process identity. Confirm save/load, clean boot and second launch. Full HUNK,
Tofu, Extreme Battle and other unlock eligibility remains separate until persistent
save/menu flags are traced and verified. Unit/fake-memory evidence cannot close
those gameplay or all-unlocks tasks.
