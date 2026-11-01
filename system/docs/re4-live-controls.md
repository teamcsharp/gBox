# RE4 GameCube live Mercenaries controls

The G4BE08 facade in `gbox/mercs/titles/re4_gc_native.py` uses the existing
owned-disc hooks in `re_mods_tool.py` and `re_games.py`. Its picker enumerates
the live weapon table even when the inventory is empty. A direct operator pick
keeps that exact weapon, including a sniper or rocket launcher. Automatic
loadout policy replaces sniper rifles with the rapid-fire Handcannon and rocket
choices with a random verified shotgun. Explicit snipers receive 30x native
class intervals; Handcannon retains 40x. Intervals cannot be below one game
frame, and recoil animation and actual shots per second remain game-controlled.

The shared operator selection expires after 180 seconds. Loadout repair and
automatic round arming respect that lease. A known empty gun can use another
loaded inventory gun. An unreadable/empty inventory list keeps the verified gun
in hand rather than inventing an empty-ammo observation.

Ordinary TAKE prompts are rejected even while navigating to a time bonus.
Only a live enabled item AEV of type 3 with bonus item ID 0x73 or 0x75 can
authorize that bonus's press. A recent matching bonus press is required before
answering a stopped-clock pickup dialog Yes. The prompt source clears its
previous action/AEV evidence before every read. Unknown or nearby ammo pickups
are not authorized by the route's goal alone.

The controller exposes verified infinite-ammo readback and toggling, timer
readback/set (1–3600 seconds), an immediate native flash, and bounded six-blast
rings. Only `flash` and `hand` are implemented. Injected hand-grenade blasts use
the existing owner-zero wrapper, so the facade requires verified unlimited
health before each hand-grenade blast. The ordinary `grenade_safe` patch does
not protect this wrapper; it is not used as proof of immunity. Other grenade
types remain unavailable.

Relevant existing evidence:

- `ItemMgr` 0x802138E0: held item at +0x10; inventory at +0x14, count +0x1C.
- Weapon table 0x801DF47C; class fire intervals 0x801ED248.
- Mercenaries timer 0x80279308 (30 frames/second).
- Infinite-ammo instruction 0x8001BD14: original/patched bytes are checked
  and the write is read back.
- `take_item` 0x80147E6C and the existing `EQUIP_NOW` wrapper 0x80002C00.
- Existing flash/grenade wrappers 0x80002600/0x80002500, using the verified
  native effects and area attack documented in `re_games.py`.

Every intervention requires the owned Dolphin process, exact disc ID, living
player, running native room phase, a supported Mercenaries room, and a valid
clock. Both bot loops publish the same **host-observed context epoch** and
release inputs before equipment handover. This is not a native allocation
generation: it invalidates on observed pointer, room, phase, process, adapter
restore-epoch, or VI rewind changes. A load that restores exactly the same
state entirely between observations cannot be proven absent.

An adapter transaction lock serializes equipment, mods, and the shared native
mailbox/scratch buffer. Context is checked before native publication and after
completion. Unknown publication/completion latches the controller or dispatcher.
Mailbox publication uses one debugger write and completion readback, because
the game can consume the function before ordinary same-byte verification.
It does not clear and reuse a request that might still execute. Relaunch is
required before retrying an uncertain native request. Read-only preparation
does not install hooks. Existing tests exercise receipts, context transitions,
failed operations, serialization, pickup filtering, weapon policy, and inventory
fallback. These are local regression checks; no new live-game success or
measured shot-rate claim is made here.
