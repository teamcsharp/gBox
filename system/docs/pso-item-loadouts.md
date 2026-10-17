# PSO item families and researched loadouts

The item panel groups repeated item names behind a disclosure triangle. The
on-disc item code remains available for every variant. A GameCube S-Rank Axe is
shown as **S-Rank Axe**, with its seventeen variants identified by their actual
special: No special, Jellen, Zalure, HP Revival, TP Revival, Burning, Tempest,
Blizzard, Arrest, Chaos, Hell, Spirit, Berserk, Demon's, Gush, Geist and King's.
The AXE rows were genuine records with different special-selector bytes, rather
than seventeen unrelated weapons. No catalog entries are removed to hide them.

Weapon cards link to the PSO wiki and load reference thumbnails lazily. Missing
external images are omitted while the text, native statistics and selections
remain usable. Ephinea's wiki is an image/identity reference; its server balance
and exclusive skins do not establish GameCube or Dreamcast availability.

After a verified manual ground drop, the items in that command are unchecked.
An error, unverified result or unknown timeout retains the checks. Clearing the
manual selection does not disable an already configured enemy-drop policy.

## Lists and builds

**Researched weapon lists and builds** provides community, Hunter, Ranger and
Force shortlists, plus a separate computed maximum-grind ATP list. Preview shows
the resolved names/codes, exclusions, rationale and source links before **Drop
list** creates one of each item on the ground. Count limits the number of items;
Class filters actual disc eligibility. A list that has fewer compatible entries
reports the shortfall instead of inventing unavailable items or duplicates.

ATP ordering uses the owned PMT's maximum ATP plus twice maximum grind. It is
explicitly not a DPS order: animation, targets, specials and technique bonuses
change practical effectiveness. Community selections are contextual shortlists,
not an official universal tier list.

An imported researched list accepts one exact name or code per line, up to twenty,
and an HTTPS source URL. A family name resolves its base/no-special variant;
the full special name or exact code chooses another variant. Unknown names and
ambiguous unrelated identities are excluded with diagnostics. Source URLs are
provenance and are never executed or fetched by the item planner.

`pso_loadout` exposes the same operation to the local agent:

```json
{"session_id":"worker-session","op":"plan","preset":"hunter","character_class":"HUmar","count":10}
```

The agent can first use `web_search` for the exact running PSO version, then pass
the resulting `names` and `source_urls` to `pso_loadout`, with `op: "drop"` when
the user requests a drop. The tool determines the actual session version and
uses the existing session-pinned `pso_controls` / `floor_spawn` RPC. Native
revision, offline-session, permissions and read-back checks still apply. It
never retries a timed-out drop and does not directly write a web-provided code
or address into memory. The planner endpoint itself performs no game mutation.

Catalog schema 3 adds family/display/special labels, native ATA/special fields,
maximum-grind ATP and wiki references. The old schema cache is not reused.

## Sources and verification

Research snapshot: 2026-10-15.

- [Sitka's weapons worth hunting](https://www.pso-world.com/sections.php?artid=2350&op=viewarticle)
  supplies a contextual melee/ranged/Force shortlist.
- [Tycho's extended optimum equipment](https://www.pso-world.com/sections.php?artid=2307&op=viewarticle)
  provides class/role context, including utility and technique equipment.
- [PSO-World GameCube S-Rank availability](https://www.pso-world.com/sections.php?artid=2434&op=viewarticle)
  identifies the Axe as an Episode II Challenge reward.
- [ES weapon reference](https://wiki.pioneer2.net/w/ES_weapons) and
  [ES Axe](https://wiki.pioneer2.net/w/ES_Axe) identify the weapon family and
  reference image. Only the owned disc supplies native availability/statistics.
- The independently maintained
  [newserv item-name implementation](https://github.com/fuzziqersoftware/newserv/blob/master/src/ItemNameIndex.cc)
  and [item identity implementation](https://github.com/fuzziqersoftware/newserv/blob/master/src/ItemData.cc)
  document S-Rank special selectors and code ranges.

Read-only validation against the owned discs retained all 1,257 GameCube and
545 Dreamcast records. Every GameCube class and every Dreamcast class resolved
ten distinct ATP-ranked weapons. The mixed community list resolved ten GC
items and eight DC items; Black King Bar and Sange & Yasha were correctly
reported absent from the owned Dreamcast catalog. Existing verified native
floor spawning is reused; this change does not claim a new in-game validation
of every weapon or special.
