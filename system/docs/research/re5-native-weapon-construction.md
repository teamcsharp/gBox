# RE5 native weapon construction: EBFFDB22

This is an implementation checkpoint for6104/6106, **not their completion**.
The viewer selector and primary-lock policy are implemented; full weapon-family
and combat-hit acceptance remain unfinished.
No inventory-window input is used by these native functions.

The game has24 physical cItem records in player+30F0, each56 bytes. Its9 visible
grid positions are independent of storage indices. The reader now covers24
records; a regression test places the held grid0 Hydra at physical record15.

Native cItemManager constructor91FAF0 initializes a private manager in the
controller's4096-byte allocation at+800. Native inventory add1C2EF0 has20
arguments; it creates the weapon through the game's type registry and resource
loader with the live player as owner. count=-2 requests the native full capacity.
The returned value is a cItem record, not a weapon unit.

stage refuses an occupied private manager. discard validates the player and unit
generations, owner and registration before invoking sItem virtual+70. 1C3D10 is
only a membership check. The player's manager and inline records are never freed.

commit rechecks living/idle player state, native vtables, unit readiness and
ownership, a unique grid0 target and a free physical record on the game thread.
It inserts the initialized unit into a spare record before clearing the old
grid0 record. Native7AB380 equips it; the old native unit is then removed.
Return0 means refusal; return2 means a published result requiring inspection,
not permission to retry. Duplicate calls cannot commit the cleared staging slot.
Python callers must inspect the resulting equipped object and actual firing.

## Evidence and limitations

Live stage/discard trial on Spark at1793345602.4292536:
session611d2fa684d545c1-9d058a82c73f4c90, PID1652982,
birth1793342773.07, Sheva Normal player generation13. A new Hydra uWp19,
unit generation10717, initialized successfully. All24 live inventory records
remained byte-identical. Native cleanup cleared the staging record, original
player dispatch was restored and autoplay resumed with job53713965a7b64ab4.
Receipt `re5-weapon-stage-trial-1793345602429259410.json` is in the Spark agent
scratch directory. This used the earlier stage-only image; it did not equip or
fire the Hydra.

The full transaction then passed in a fresh process after PR1602:
session911604520d1a415a-16930ffbb66a4d48, PID2240093,
birth1793347177.29, Wesker Cos2 generation2. A newly constructed Hydra,
unit generation476, replaced grid0 and became the held weapon in51.7ms.
It occupied physical record7. Protection flash completed in31.4ms using the
new code layout. Ordinary ZL/ZR input produced native firing motion29 in133
of137 samples over1.5seconds. The captured frame shows the equipped Hydra.
No enemy-health reduction was observed in that short sample: firing animation
is not proof of a hit. Original dispatch was restored, inputs released and
autoplay resumed. Receipt `re5-weapon-replace-trial-1793347511827312414.json`
and its equipped/firing JPEGs are in the Spark agent scratch directory.

The production queue now offers `equip_primary` with catalogue item IDs,
fences the originating player life through bot-input handover, and installs
the primary preference only after verified native equipment. The bot excludes
other equipment for120seconds and retains this gun preference for the match.
Queue, lifetime/expiry/takeover, native cleanup, policy and MCP roundtrip tests
pass. Browser tests exercise the shared viewer/PiP dropdown without changing
the stream source. Live production queue and120-second lock acceptance remain
to be measured after deployment.

Four native test programs pass, including all20 constructor arguments, refusal
without live-inventory mutation, grid/storage distinction, capacity, generation,
owner, resource and idle guards, native cleanup and duplicate rejection.
The110 targeted Python tests pass. Neither is a substitute for live firing.

## Code layout and rollout

The same verified bootstrap/dispatcher remains at118E600/118E740. To fit the
weapon helper entirely inside the exact executable's final zero padding, flash
spawn moves to118E820 and explode to118E9D0. The weapon image occupies
118EAC8..118EFEC; entries stage118EB70, discard118EC38, commit118EECC.
build.sh reproduces every checked-in byte and runs all four ABI tests.

**A fresh RE5 emulator process is required when moving from the earlier native
flash layout.** Existing nonzero code is never overwritten to force a migration.
Deployment must restart the owned session and verify native flashes again.
RE6 is unaffected. The all-title viewer, QTE, diversion and weapon tickets stay
open until their stated gameplay acceptance is met.
