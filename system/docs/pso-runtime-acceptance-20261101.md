# i9 PSO runtime acceptance, 2026-11-01

The owned Plus US revision-2 GCZ launched as session
`deaab18c708942d3-1f770f790d4645c9`, Dolphin PID 3808. Its buddy setup reported
two controllers and the isolated persistent card under
`gbox-data/pso-buddies/i9-NUC/436e0bb84d5337d1/dolphin/A.USA.raw`.
The previous agent-owned Mercenaries 3D session was stopped through the normal
local MercMode API before this launch. No personal card was selected.

The two-character campaign started but did not reach character creation or
verified gameplay. Native controller mapping remains unverified. The random
RAmarl and FOmar preferences in its telemetry are requested identities, not
evidence that the game has created them. No room, boss, episode, difficulty or
achieved-speed completion is claimed.

The actual stopped result was `gBox or the emulator must be active to send
emulator input safely`. The configured vision model was available. With explicit
user approval, one diagnostic request sent the captured license-screen frame to
the user's Spark at `10.89.1.246:11434/v1/chat/completions`; `qwen2.5vl:7b`
returned valid menu JSON in 4.17 seconds. The pictured highlight was on Disagree,
while that response proposed A to agree. This is not reliable cursor evidence.

The repair restores the existing idle-only foreground setup before the PSO
campaign branch returns, and preserves input wrapper signatures so both pads
retain their existing polite focus handling. It does not bypass foreground,
idle, operator-lease or per-player checks. Existing desktop input leases need a
fresh worker/adapter lifecycle to receive the signature metadata fix.

The controller now reports plan request/response/failure counts, latency,
requested inputs and acknowledged delivery. A failed planner future is cleared
before its result is read, allowing a fresh observation rather than rereading
the same error. Five failed observations end the attempt. Menu confirmation
requires named selected/intended options and visible-highlight evidence; the
labels must match, and navigation cannot be combined with confirmation. Six
unchanged menu attempts stop with an inspection reason. These remain model
observations, not verified native cursor values.

Local regression coverage exercises the attached desktop wrapper on both pads,
PSO idle-focus setup, selected-option rejection, repeated-menu bounds, and
recovery from separate failed planner observations. These checks do not prove
live character creation, gameplay or campaign completion after the repair.
