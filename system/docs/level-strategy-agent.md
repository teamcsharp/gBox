# Level strategy research

Run the `level_strategy` worker tool against a running session:

```json
{"session_id":"<current-session>","op":"research","goal":"Complete this mission and verify the next level unlock."}
```

`status` returns the scoped plan and execution limitations. `enable` permits
automatic research when a Merc3D plan is missing or objective progress stalls;
`disable` stops consumption and new research. The tool requires read, stage and
network permissions. The runtime rechecks network permission before refreshes.
Neither command starts a game or sends a controller input by itself.

The agent uses the configured SearXNG and language model. It fetches at most four
public sources, prefers the publisher manual, stores fetched-source hashes and
URLs, and rejects invented citations. PDF extraction needs `pypdf`. A provider
whose `/api/version` identifies Ollama uses its native chat endpoint; other
providers use their configured OpenAI-compatible endpoint. Provider errors stay
visible and do not become a plan or a completion receipt.
For Ollama, bounded optional metadata reads preserve an exact matching resident
model's observed context size from [`/api/ps`](https://docs.ollama.com/api/ps)
and request `think:false` only when
[`/api/show`](https://docs.ollama.com/capabilities/thinking) explicitly advertises
the boolean `false`. Missing metadata retains provider defaults; permission
revocation or the shared elapsed-time budget stops the request. The model is
never changed, and a context size is never guessed or resized by this logic.
Source fetches and every redirect are restricted to the fixed publisher/guide
host set in `level_strategy_web.SOURCE_HOSTS` (Capcom, Nintendo, PlayStation,
Sega, GameFAQs, StrategyWiki, IGN and TASVideos), plus a public-address check.
Unlisted hosts are refused even if search returns them; this avoids accepting
arbitrary DNS owners under a preflight-only public-network claim. Additional
publishers require a reviewed allowlist change.

Workers use the existing authenticated control-plane connection to
`POST /api/level-strategy/research`. A desktop authority forwards to its existing
connected paired server; the central server uses its own configured providers.
The request includes bounded game/level labels, capabilities and progress only.
Screenshots, saves, coordinates and RAM addresses are excluded. The service
checks network permission and the same running session/game/mod/worker before
returning; the worker rechecks the current native level before activating a plan.
`install(app, config, auth)` in `level_strategy_service` registers this route.
The central `agent.strategy_timeout_seconds` setting is clamped to 15–120 seconds
and shared across network phases; transport timeouts are 150/160 seconds inside
the tool's 180-second budget. Late results are rejected. Network/DNS and PDF
parsing are synchronous provider work, so this is not a hard process deadline.

Plans live under `data_dir/level-strategy`, separately keyed by game, observed
build, modification and native level. Each contains objectives, named route
landmarks, citations, unsupported actions and uncertainties. Schema/source
validation means the structure and provenance passed checks; it does not mean a
guide's strategy has been proven in the running game. Web text never becomes
buttons, memory writes, executable code or invented world coordinates.

Merc3D consumes enemy/boss objectives through the existing native enemy census,
aim checks and crowd avoidance. A boss instruction must bind to an enemy class
currently observed in RAM. A stalled target may be deprioritized while the
agent researches a revised plan. Health decreases on the same actor, score
changes and native objective events provide progress evidence. Timer expiration,
an empty enemy list and remaining alive do not prove completion. Requests are
limited to one pending call per bot and at least 60 seconds between attempts.
Results from a previous mission are discarded. Research does not block the
combat tick.

The current executor consumes the first semantic objective and stops consuming
it on a native objective-end/failure event. Later steps and named routes are
explicitly advisory until a title adapter supplies step-completion evidence.
It never advances a plan because enemies disappeared from the reader.

Other games can use the same research tool when their verified semantic profile
exposes a current level/area. They receive a cited advisory plan until a title
adapter implements and grounds the semantic actions. This is not universal
automatic completion.

## Mercenaries 3D findings and remaining hooks

The [Capcom manual](https://static.capcom.com/manuals/retm/RETM_3DS_DMNL_EN.pdf),
printed pages 9 and 15, distinguishes mission objectives from a successful clear:
B rank or better is required, and clearing a Rank-Up mission opens a new level.
The current native `cMerceStageEndState` proves objective end, not a decoded rank
or new unlock. The rank-byte encoding and unlock flags still need verification;
research does not fabricate them or write saves.

The menu selector previously clamped a locked next level to the highest open
level, then selected its first mission and lost the pending unlock goal. It now
retains that goal and retries an available final/Rank-Up tab. The
[firsthand TAS route](https://tasvideos.org/Forum/Topics/23732) identifies 1-3,
2-3 and 3-5 as level unlocks; its LV4 route makes 4-5 a guide-inferred candidate,
which is labeled as such. Native tab counts constrain every selection. Only an
increase in the observed native open-level count proves a newly opened level;
objective end alone never does. The existing pass counter describes traversal
of LV1–5, not proven B ranks or EX completion.

[Berserker's walkthrough](https://gamefaqs.gamespot.com/3ds/609524-resident-evil-the-mercenaries-3d/faqs/62693)
identifies different early objectives: mission 1-1 follows active movement
markers, 1-2 destroys red barrels, and 2-2 eliminates twenty Town Majini. The
existing enemy-only reader cannot ground markers or barrels. Those plans report
missing targets instead of labeling survival a completed tutorial. Required
marker/barrel objectives cannot be replaced by a model's combat-only proposal.
Named guide routes also remain advisory until observed geometry binds them.

The 2026-11-01 read-only control-plane check found only three retired/offline i9
Merc3D records, with stale frames. PSO was preserved. The last local native audit
documents repeated failure on mission `0x0101` (human 2-2) before the October 30
enemy-list and trigger corrections; it does not establish today's live cause.
No new live mission clear, rank, unlock or route acceptance is claimed.

A read-only provider check on 2026-11-01 returned valid JSON in 0.61 seconds
with the already resident model, its observed 16384-token context, and supported
thinking disabled. The earlier request using provider defaults timed out; this
comparison does not isolate which option caused the difference. The official
manual fetch returned HTTP 503 during that check, so this is a model transport
receipt, not acceptance of a complete research run or an activated game plan.
After the request fix, the actual `model_plan` function passed the same JSON
transport check in 0.86 seconds while retaining its 1800-token output budget.
A subsequent complete research smoke passed in 11.45 seconds using the verified
mission-ID mapping and historical mission 2-2 context. The TAS guide was fetched
and supplied the cited twenty-enemy objective; configured local search refused
the connection, the manual returned 503, and GameFAQs returned 403. TAS is now
the third default Merc3D source, within the four-source limit. This audit saved
no live plan and sent no input. It proves the fallback research pipeline, not
current session admission, route execution, rank or unlock completion.

The existing gameplay Crystal stores observations/replay evidence, and the
Mercenaries notebook stores round outcomes. Cited web plans are kept separately
so downloaded prose cannot masquerade as recorded play or a verified route.
