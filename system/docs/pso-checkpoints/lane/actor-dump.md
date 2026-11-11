# Lane-log text of `ds-pso-actor-dump-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `92ee3e4d`.

----

## Round 59 (2026-11-10, later session) — A7's data route is empty too; the live discriminator is now one call

Working locally; no lilspark, no live session.

**The city has no event set.** `gsl_set_event.gsl` holds 143 entries (`map_forest01_00.evt`, `..._off.evt`, `..._gj.evt`,
the caves, ...) and **not one for the city**, and there is no loose `map_city00*.evt` on the disc either. Combined with
the earlier findings, the static routes for the city pad are now all exhausted:

* no vtable (none of the named `TObj*` placement classes is a C++ object - the 38-class census is all engine classes);
* no name-comparison dispatch (no code anywhere materialises a placement class-name address);
* no event set for the city.

So the pad's behaviour is either a hard-coded position/class special case somewhere in the executable, or - much more
likely - **the pad is inert in offline play and the surface is the Hunter's Guild quest flow**, which is what the lane's
nine approaches and the operator's own route have been telling us all along.

**The remaining discriminator is a live object, and it is now one call away:** `gbox/pso_actor_dump.py` dumps an actor's
first bytes as labelled `u32` fields and classifies each pointer - `class-name` (points at printable text),
`executable` (points into the `0x8000C000`-`0x80600000` image), `ram`, `small` or `raw` - with `handlers()` returning
the image-pointing fields (candidate handler/update slots) and `actor_dump()` picking an actor by class from
`pso_entities.entities()`. It needs only a `pso_ram.Reader`, so a live window or a savestate answers "which field is the
pad's handler" in a single call.

Tests (`tests/test_pso_actor_dump.py`, 4): the field labels (class name, room, a float bit pattern, an image pointer), the
handler filter (aligned image pointers only, an unaligned one rejected, a RAM pointer rejected), a dump that stops at the
end of mapped memory instead of raising, and `actor_dump` picking the class from the entity list and returning None for
an absent one.

**What A7 needs now, in one live window:** load the city, `pso_entities.entities()`, `pso_actor_dump.actor_dump(reader,
items, cls="TObjCity")` (and the same for a door and the pedestal), and read the image-pointing fields. That is a
5-minute live step for whoever has the window - and the one thing that cannot be done statically.
