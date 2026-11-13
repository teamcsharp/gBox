# RE4 Switch defense after traversal

`mercs/titles/re4_traversal.py` observes a completed native traversal and requests five hand-grenade blasts through the existing RE4 native ring. It does not create mines, use a nitrogen alias, alter health, or own movement input. The ring is an immediate explosive defense; it does not leave a persistent mine behind.

## Native state evidence

The analyzed ELF is `/home/ehm_eckx/gBox_alt/gbox-cache/exefs/010099A00BC1E000/main.elf`, SHA-256 `c8e8f22f9996b7d6de8913133c791579dc0e6df43d32ef9478dd13781c303433`, image base zero. Existing full decompilation: `/home/ehm_eckx/gBox_alt/analysis/merc-full/re4-c8e8f22f-20261113`. The local reference `gBox_alt/reference/re4-gc-decomp/src/game/player.cpp` names the routines; the Switch executable independently verifies their table entries and completion instructions. GameCube addresses are not used as Switch anchors.

At Switch `0x30D430`, the movement dispatcher reads the actual routine index at player `+0x115`, loads the table pointer through GOT `0xB27D68`, then calls `table[index]`. The relocated table is `main+0xB067C0`, 21 entries. Routine 0 at player `+0x114` must be zero for this dispatcher; damage, death, scenario and object-action routines are excluded. Runtime reads verify the complete dispatch instruction sequence and all 21 table entries before using these meanings.

| Routine 1 | Handler | Native meaning and completion |
| --- | --- | --- |
| 7 | `0x30E2C0` | Ledge climb up. `0x30E3B4` calls motion advancement, `0x30E3B8` rejects incomplete motion, then `0x30E3D0` clears the routine to ordinary movement. |
| 8 | `0x30E3F0` | Ledge climb down. Motion result gate at `0x30E4C8`; optional Y adjustment at `0x30E4E8`; routine reset at `0x30E500`. |
| 12 | `0x30E870` | Fence/window vault. Motion/character exit predicate gates collision restoration and routine reset at `0x30EE18`. |
| 14 | `0x30EE80` | Fall/drop. Native world collision at `0x30F1C0`, collision-hit Y written at `0x30F1CC`, landing state 4 at `0x30F29C`; motion completion gate at `0x30F2AC`, routine reset at `0x30F2D0`. |
| 16 | `0x30F380` | Ladder up/down. Steps 0..3 / 10..13. Native motion completion at `0x310624..28`, collision/shadow restoration and routine reset at `0x310660`. |
| 19 | `0x310A00` | Jump/fall. Native collision query snaps Y to `player+0x538`, sets landing step 2 and restores collision. Step 2 waits until motion frame ≥20 before writing ordinary movement `(0,0,2,0)`. |

Ordinary movement entries 0..6 are footwork, walk, back, run, turn, turn180 and weapon control. A change in an animation byte is never sufficient. The observer requires a recognized traversal handler followed by ordinary movement, at least 0.2 seconds of stable height (150mm tolerance), and at least 600mm displacement from the observed traversal start. A traversal chain such as vault → fall produces one event after its final landing.

The native reader revalidates the current player pointer, native ID, vtable, all four routine bytes, and game phase/stage/mode after reading position. Dead, unknown, foreign or changed actors and reads exceeding 150ms are unavailable. Damage/unknown reads, round changes, operator control, gaps over one second, clock reversal and episodes over 60 seconds cancel the active traversal. Native phase `held` can be observed during traversal, but completion and ring submission require `playing`.

## Integration and explosive clearance

`RE4Switch.snapshot()` observes every snapshot after its existing watch hook, so an input-prompt branch skipping the combat decision does not erase a traversal. The event contains the round/player/native ID, completion time, landing position in **millimetres**, traversal routine and handler. It remains eligible for five seconds. `grenade_ring.control().step()` gives new hit/grab reactions priority; otherwise it can consume one fresh landing event while the ring policy permits it. A fresh ordinary-movement observation is also required, so a queued event cannot dispatch during a new jump.

The request is **hand**, five blasts, zero ripple delay. Existing title-native radius and per-blast player-clearance checks remain intact: the hand blast's area radius is 6000mm; the native ring clamps its minimum placement radius to at least 7010mm, reanchors to the current player before each blast, and independently checks each point is at least 7000mm away. This provides the existing clearance margin; it is not a new proof that every possible scene has zero self-damage. Native receipts retain observed HP before/after and `self_damage`. No health or invulnerability writes are added.

`traversal_ring_requested` counts consumed requests; `traversal_rings_confirmed` counts native rings returning `state: confirmed`; `traversal_ring_receipt` preserves actual `verified`, requested/detonated counts, reason, self-damage and the triggering event. Refused input release has zero native detonations. Partial/uncertain submissions are consumed and never replayed. `verified: false` is not upgraded by this feature: a returned native call is not independent visual or damage proof.

Native RE4 mine-dart detonation is available, but radial mine creation remains explicitly unsupported in `re4_switch_native.grenade_ring('mine')`. This implementation does not bypass that boundary. A persistent explosive left precisely at a landing requires a separately verified mine/projectile spawn and safe retreat, or a later title-specific implementation.

## Validation and remaining live check

Focused tests exercise the actual player/game-state readers against a native-layout fixture, exact dispatch/table verification, lifetime/routine/vtable/phase races, all six traversal handlers, interruption and stable landing, prompt-independent snapshot observation, fresh event deduplication, airborne exclusion, hit/grab priority, disabled policy and truthful confirmed/uncertain/refused receipts.

No live traversal-to-ring effect is claimed by this change. At the read-only validation query on 2026-11-13 the active rotation was RE5 (session `b445b3e9a1404bd5-2e22c1bbe764447c`), so RE4 landing and native explosive-effect evidence remain to be captured after activation.
