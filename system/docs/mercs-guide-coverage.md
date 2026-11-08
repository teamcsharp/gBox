# Mercs guide coverage ledger — sourced, per-cataloged-mode

Request #3113 (54ceec01e2ef47af) milestone run — 2026-11-07, spark-local (lilspark2, nvidia/Qwen3.8-27B-NVFP4).
Companion to `docs/mercs-research-findings.md` (2026-10-23.1). This ledger closes the gap
between the 13 cataloged modes in the meta doc and the sourced entries in
`gbox/mercs/research_profiles.py` (2026-10-23.1 covered: re5-basics/United, re5-original,
re5-reunion, re4-manual, re6-manual, mercs3d-manual — leaving 7 modes with no source
attribution and no RE5 per-character/equipment rows).

Access states: `full_access` (page body retrieved) | `indexed` (SERP snippet / search
result only, not fetched this run) | `source_gap` (no verified source accessed).

## 1. Per-mode coverage ledger (all 13 cataloged modes)

| # | mode | title | catalog state | source | access |
|---|------|-------|---------------|--------|--------|
| 1 | re3-mad-jackal | BLUS31485 (RE3 Nemesis) | native_driver_required | fandom RE3 "Operation: Mad Jackal" page; GameWith article 15537; TASVideos topic 8814; speedrun.com/re3m; residentevil.com.br (via reddit link) | indexed (rich SERP snippets) |
| 2 | re4-classic | G4BE08 | verified_driver | Capcom official RE4 manual ("Mercenaries" chapter) | full_access (2026-10-23.1) |
| 3 | re4-vr | — | native_driver_required | source_gap — no verified source accessed this run | source_gap |
| 4 | re4-remake | — | native_driver_required | reddit r/residentevil4 12jf8x4 (unlock mechanics: S on all 3 islands → Handcannon; A w/ Leon → Luis + Castle; 200k+ score ≈ S per island; special-ability L2+R2 clearing) | indexed snippet |
| 5 | re5-original | BLUS30491 | verified_driver | Capcom official RE5 manual; GamesRadar RE5 guide (2009); GameWith RE5 basics article 21447 | full_access (2026-10-23.1) |
| 6 | re5-reunion | BLUS30491 (mode reunion) | verified_driver | Capcom official RE5 manual (mode "reunion"); GamesRadar "RE5 Mercenaries: Reunion" (2013); GameWith article 45766 | full_access (2026-10-23.1) |
| 7 | re5-united | BLUS30491 (mode united) | verified_driver | IGN RE5 Mercenaries wiki (8 stages, B-rank unlock chain, 4 characters / 10 costumes); SuperCheats RE5 unlock tables (A-rank per stage → costume/character); Nintendo Switch store page (official description: United = "The Mercenaries and The Mercenaries Reunion ... combined"); residentevil.org RE5 Mercs Guide (per-character arsenals, scoring) | indexed (SN: 2026-11-07) |
| 8 | re5-no-mercy | BLUS30491 (mode no_mercy) | native_driver_required | IMfdb RE5 firearms wiki ("appear in all stages in Mercenaries No Mercy, probably to help the player deal with multiple bosses at a time"; incendiary M1014s on the Ruins stage); SuperCheats PC/PS3 unlock tables; residentevil.org scoring rules | indexed (SN: 2026-11-07) |
| 9 | re6-original | BH6 | verified_driver | Capcom official RE6 manual ("The Mercenaries" chapter) | full_access (2026-10-23.1) |
| 10 | re6-no-mercy | BH6 (mode no_mercy) | native_driver_required | source_gap — no verified source accessed this run | source_gap |
| 11 | mercs-3d | BLUS32327 | verified_driver | Capcom official Mercs 3D manual | full_access (2026-10-23.1; NOT yet wired into research_profiles.profile()) |
| 12 | village | BH7 | native_driver_required | source_gap — no verified source accessed this run; NOT yet wired into profile() | source_gap |
| 13 | village-additional-orders | BH7 (mode additional_orders) | native_driver_required | Capcom official RE Village manual ("Additional Orders" chapter) | full_access (2026-10-23.1) |

Coverage after this run: 10/13 sourced (2 `source_gap` rows: re4-vr, re6-no-mercy +
village base), 3 catalog-state caveats noted (merc3d/village not in profile() dispatch).

## 2. New sourced evidence this run

### 2.1 RE5 United (mode united) — reinforced
- Stage list (8): Public Assembly, Mines, Village, Ancient Ruins, Experimental Facility,
  Missile Area, Ship Deck, Prison. Unlock rule: B rank on a level unlocks the next
  (IGN wiki, indexed).
- Character/costome economy: 4 characters, 10 total costumes (Chris/Sheva 3 each,
  Wesker/Jill 2 each); start = Chris, Sheva + Public Assembly only (IGN, indexed).
- A-rank unlocks (SuperCheats PC, indexed): Village → Chris (Safari); Experimental
  Facility → Chris (STARS); Mines → Wesker (Midnight); Prison → Wesker (STARS);
  Jill (Battle Suit) row truncated in snippet. 2P A-rank threshold: 80,000 points
  (SuperCheats PS3, indexed).
- Official framing (Nintendo store, full_access earlier — re-cited from 2026-10-23.1):
  United "combines the two fan-favorite modes, The Mercenaries and The Mercenaries
  Reunion."

### 2.2 RE5 No Mercy (mode no_mercy) — new
- Multiple bosses appear simultaneously; weapons "appear in all stages in Mercenaries
  No Mercy, probably to help the player deal with multiple bosses at a time" (IMfdb,
  indexed).
- Incendiary M1014s scattered on the Ruins stage in No Mercy (PC) (IMfdb, indexed).
- Character unlock economy shared with base Mercenaries A-rank table (SuperCheats,
  indexed) — No Mercy entry itself not separately itemized in accessed snippets.
- Community challenge reference: "How Hard is No Mercy in RE5 Mercenaries? | SS+
  Challenge Run" (Danishi, youtube 8FFCA03nk-0) — SS+ difficulty exists; video-only
  source, not fetched (indexed).

### 2.3 RE5 scoring rules (applies to all RE5 merc modes) — new
- Base kill 300 pts; melee kill 300 + 5s clock; combo adds +10 × combo tier; combo
  time end awards 1000 × combo number (residentevil.org RE5 Mercs Guide, 2009 thread,
  indexed).
- 150 enemies per level; killing all ends the level with time-remaining bonus; a
  chicken on each level (residentevil.org, indexed — treat the chicken note as
  community lore, low confidence).
- Per-character arsenals (residentevil.org, indexed): Chris (BSAA) M92F + Ithaca M37
  (50 handgun / 30 shotgun rounds, 5 grenades, 1 FAS); Chris (Safari) SIG P229 + M3 +
  2 rocket launchers. Full per-character table truncated in snippet — fetch needed.

### 2.4 RE3 Operation Mad Jackal (BLUS31485) — new
- Unlock: completing the main game once (Fandom + GameWith, indexed).
- Route: Cable Car → Warehouse save room, 2:00 initial timer; kills grant time
  (Fandom, indexed).
- Characters (Fandom/GameWith, indexed):
  - Carlos — M4A1 + STI Eagle 6.0 (headshot-critical only), 90 handgun rounds, 3 mixed
    herbs. Moderate.
  - Mikhail — Benelli M3S + S&W M629C magnum + M66 rocket launcher, 21 shells / 18
    magnum, 1 mixed herb. Easiest.
  - Nicholai — SIG Pro SP2009 + combat knife (+24s per knife kill), 3 FAS, blue herb.
    Hardest.
- Grade table (TASVideos topic 8814, indexed): A=1000, B=800–999, C=500–799,
  D=300–499, E=100–299, F=0–99; A requires all 6 hostages saved, no FAS, ≥1:30:00 left.
  Penalties: rocket use −10, excessive damage −10, late hostage −10, <0:59:99 finish
  −50, FAS −50 each, death halves final score.
- Counter-example (region-dependent): censored regional builds give NO time bonus for
  killing human-type enemies (zombies/Nemesis) — EU PS1 players report scores
  ~1300 vs 2000+ uncensored (Fandom + GameFAQs, indexed).
- Community exploit (verify on native before relying): Nemesis-kill-zombie grants
  player time bonus → Nicholai knife loop "8x time score" (Fandom, indexed —
  unverified hypothesis).
- Speedrun category exists: speedrun.com/re3m, per-character boards (Mikhail ~2:37
  first place) (indexed).

## 3. Technique ledger (per-technique fields as required by #3113)

| technique | title/mode/character condition | observable native prerequisite | bounded action policy | risk | counter-example | eval metric |
|-----------|-------------------------------|-------------------------------|------------------------|------|-----------------|--------------|
| multi-boss deferral | RE5 No Mercy / any character | none — native_driver_required; no RE5 No Mercy driver verified | keep RPG-7/shotgun stock; do not commit to single-boss kill chains | over-stock drops primary | censored-region timing rules differ (RE3 analog) | bosses deflected per wave; clock remaining |
| knife-finish loop | RE3 MJ / Nicholai only | native driver for BLUS31485 (unverified) | wound with SP2009, finish with knife | death halves score | censored builds: no human-kill time bonus | +24s per knife kill observed on clock |
| shotgun up-aim (ceilings) | RE3 MJ / Mikhail | native driver for BLUS31485 (unverified) | hold aim up, single shell per ceiling cluster | rocket use −10 pts | — | seconds gained per shell |
| hostage sweep route | RE3 MJ / any | native driver for BLUS31485 (unverified) | save all 6 before killing sprees; -10 each if found dead | late hostage −10 | room 5 contains Hunter γ (non-zombie) — order changes | A-grade requires 6/6 + ≥1:30 left |
| combo-time stacking | RE5 all merc modes / any | verified RE5 driver exists for base/Reunion/United; No Mercy not | melee kills (+5s each) to extend combo window before burst-fire | long combos risk death (halved in some modes) | — | 1000 × combo number at window end |
| A-rank unlock chain | RE5 United / any | verified RE5 driver (united) | B-rank to advance stage; A-rank per stage for costume/character unlock | 2P threshold 80k differs from 1P | — | unlocked costume count |

All `native_driver_required` rows stay gated until a cast_swap plan is published for
that title; none may be used for unattended execution.

## 4. Checkpoint (2026-11-07, spark-local run)

- Change: this file (docs/mercs-guide-coverage.md) — first publish of the ledger.
  No code changes; no jobs started; no pending job IDs.
- Actual results: web evidence collected and attributed with access states above
  (2026-11-07 SERP pass; firecrawl backend errors, results served by free tier —
  snippets marked `indexed`, none treated as full-access).
- Receipt: commit + draft PR returned by publish_task_changes (this run).
- Next acceptance step (next run): extend `gbox/mercs/research_profiles.py` with the
  sourced rows above (re5-united reinforced, re5-no-mercy, re3-mad-jackal,
  re4-remake unlock mechanics), add `source_gap` rows for re4-vr / re6-no-mercy /
  village-base, wire `profile()` for BLUS32327 (Mercs 3D) and BH7 (Village), and add
  `tests/test_research_profile_coverage.py` asserting every cataloged mode has ≥1
  sourced row or an explicit source_gap row. Then full suite + publish.
- Operator safety: no session started, no test run, no operator-PC access this run.
