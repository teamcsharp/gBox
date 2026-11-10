# DeepSeek hand-off, 2026-11-10 evening: the i9 as a service node, then bot work

> **Hard rule: hands off lilspark.**
> - No ssh, sudo, systemctl, kill or curl on the Spark (10.89.1.246).
> - No launches, stops or restarts there.
> - Work on the i9.
> - Every gBox API call carries `x-gbox-actor: agent`.
> - Branches only: never push to main.
> - Never print or commit keys or tokens.

The Claude session that coordinated today is going offline (usage). lilspark2's Hermes now holds tickets #9525-#9529 at the top of its priority list:

| Ticket | Work |
|---|---|
| #9525 | death lessons |
| #9526 | proactive crowds |
| #9527 | no wall hugging / straight runs |
| #9528 | one map format for every stage |
| #9529 | RE5 / RE6 never fire at nothing |

Don't duplicate those. This doc is the i9's share of the work.

## 1. The i9 as a gBox service node (the operator, 2026-11-10)

> "Now that the I9 NUC has been turned into a kiosk that's able to use decryption services externally, I want the ability to also have Hermes able to use the I9 NUC to handle services if the EGPU is detected to be attached and G Box is running ... if the I9 has its GPU disconnected or G Box is closed or isn't enabled for being used for service work, then it's just a general G Box client. But if it's enabled for it like it is right now, then I want G Box able to dispatch tasks to it from the central server that's able to be completed via the installed services and clients that are running on that computer locally. So it's able to handle decryption and analysis work as its own system."

Build it on a branch, `i9-service-node-20261110`, from main. The design to implement and test on the i9:

- **Service-work switch.** A local setting on the i9 (`service_work` in its gbox.toml, plus a toggle in its UI). Off means a plain client.
- **Readiness.** Checked every heartbeat:
  - the eGPU is present (`nvidia-smi -L` lists the 3090);
  - gBox is running;
  - the service is enabled;
  - each installed service answers its own health check. List what is installed: the decryption tools, Ghidra / headless analysis, the local LLM / vision services, and anything else on the i9.
- **Registration.** The i9 reports to the central server at http://10.89.1.246:8765 as a service node, with its services and readiness, in its worker heartbeat or a new `/api/service-nodes` registration. When it is not ready it is removed from routing within one heartbeat.
- **Routing on the central server.** An inbox task that needs a service the i9 offers (decrypt, analyse a binary, extract assets, GPU vision / LLM) is sent to the i9's service as a job, in addition to Hermes, and its result is attached to the request. When the i9 is not ready, the task falls back to Hermes alone.
  - Add the task-to-service mapping in one table.
  - Pass the task kind in `context`.
- **Tests.** Readiness transitions (GPU unplugged, gBox closed, toggle off), routing and fallback, result attachment.
- **Deliverable.** The branch plus `system/docs/i9-service-node.md`. That doc covers: the services found, the config lines, the central-server change, and whether gBox.service on the Spark needs a restart. The PM merges and restarts; you don't.

## 2. Bot work that runs on the i9 (no lilspark)

- The Mercs bots are `system/gbox/mercs/core/*` and `system/gbox/mercs/titles/re{4,5,6}_switch.py`.
- Replay and test locally with recorded data. Shot logs and telemetry are under gbox-data/mercs. Ask the PM for copies; never pull multi-GB over JAYBUILTFINALE's Wi-Fi.
- Where a live check is needed, write the exact probe for the PM to run instead of running it.
- Continue your PSO lane (`DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md`).
- Continue the grenade lane (`DEEPSEEK-GRENADE-RING-CHECKPOINTS-2026-11-10.md`, checkpoint 0 first).
- Use the 3090 for vision and analysis.

## 3. Where things stand (for context)

- **On main today:**
  - the RE4 doorway / detour fix (live 15:00);
  - menu pace (bots start the tick a game is up);
  - the ComfyUI render-only freeze;
  - the RE4 aim book (RAM aim line, sway zeroed, fire only on the game's sight, every shot learned; pushed at 7abe1a30).
- **Not yet on main:** the RE6 one-flash-a-minute and tight-situation gate, fire-first, the RE5 flash on the crowd, and the RE5 / RE6 aim books. They are on branch `mercs-aim-book` (858dd780) and were being tested for merge when the session paused.
- **The Spark now keeps only Switch RE builds.** 414 other builds were archived to `gbox-data/patch-library` and deleted. Do no Xbox or PS3 work there.
