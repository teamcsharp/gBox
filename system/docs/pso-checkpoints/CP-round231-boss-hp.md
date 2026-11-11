# Round 231: the CP18 observation tool is built - it records the boss's HP until it reaches zero

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (the app has not started a session), so this is tooling, not evidence.

## What CP18 needs and what now exists

Accept: **"the boss's HP reaches 0 from RAM, with both players alive."**

`boss_hp.py` does exactly that observation and nothing else:

* finds the boss entity by class fragment in the live entity table (`TBoss1Dragon`, `TBossDragon`, `TBoss`, ...);
* reads the actor's HP at **+0x32C** and its maximum at **+0x2B8** - the same offsets verified on the player actor, since enemies share the
  base actor class;
* writes a row per second **plus a row on every change** to `D:\gBox\pso-ds\boss-hp.jsonl`, so the decay series is captured with
  timestamps rather than sampled coarsely;
* stops the moment `hp == 0` and logs the player's HP at that instant as the "alive" check;
* logs when the boss entity disappears entirely (the other legitimate end signal).

If the boss actor's layout turns out to differ, `--scan` samples the struct twice a few seconds apart and lists every u16 offset whose value
**fell**, which locates the real HP field from behaviour instead of assumption:

```
python boss_hp.py TBoss1Dragon --scan      # find the field while the fight is happening
python boss_hp.py TBoss1Dragon 180         # record the series until HP is 0
```

## The gap this closes

Last round's honest finding was that the Dragon fight happened **without** the HP series, so CP18 could not be claimed. The failure was
procedural: the fight was observed through the entity table (which shows the boss is present) but not through the field that the accept test
names. This tool watches the named field.

## The remaining CP18 caveat

"Both players alive" means co-op, and every observation tool built this session watches **player slot 0 only**. The entity table does expose
more than one `TObjPlayer` when two are present, so the same script can enumerate them - that is a small extension, but it must be done
before the run that is offered as CP18 evidence, otherwise the second half of the accept condition is simply unmeasured.

## Files

* `boss_hp.py` - watch/scan the boss HP field, writing `boss-hp.jsonl`
