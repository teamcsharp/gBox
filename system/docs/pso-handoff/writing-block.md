# PSO — Continuous Operator Training and Combat Assimilation Mandate

**Priority: Critical. Implement before further unattended exploration.**

Every time I touch the controller and take over PSO, treat that as a training demonstration.

You must automatically capture, study, classify, retain, and attempt to reproduce the gameplay behaviors I demonstrate. This is a permanent operating requirement, not a one-time recording task.

## 1. Capture every demonstration without exception

Implement a persistent recording service that runs independently of the autoplay worker.

On the first detected operator input:

- Immediately revoke the bot's controller ownership.
- Mark the beginning of a demonstration.
- Record the controller's exact effective input stream, including keyboard, gamepad, and gBox virtual-pad inputs.
- Capture input changes at emulator-frame resolution, not by sampling buttons every 200 milliseconds.
- Record the corresponding game state with emulator frame identifiers and synchronized timestamps.
- Continue recording until the operator relinquishes control.
- Preserve the raw recording even if the analysis process crashes.

The capture service must survive bot restarts and reconnect to replacement Dolphin sessions. Detect and report any gaps in capture coverage. Do not claim to have recorded inputs that the input bridge did not expose.

## 2. Make the game's 2D map the reference coordinate system

Reverse-engineer the ROM's minimap implementation and corresponding RAM structures.

For every recorded frame or state change, associate the operator's actions with:

- Biome, floor, room, and map-layout identifier.
- Player world coordinates and projected 2D map coordinates.
- Player heading and movement vector.
- Enemy coordinates, orientation, HP, and state.
- Doors, exits, switches, barriers, and teleporters.
- Nearby collision boundaries.
- Current progression flags.

Persist the coordinate transformations between world space, room-local space, and minimap space.

Never rely on camera orientation to determine which exit to approach.

## 3. Reverse-engineer target acquisition

Use Ghidra and controlled RAM experiments to locate the routines and memory fields responsible for the targeting indicator.

Identify:

- Target candidate enumeration.
- Target selection and validity.
- Weapon-specific range and angle checks.
- Obstruction and height checks.
- Player facing requirements.
- Attack eligibility and animation state.
- Target-indicator visibility or equivalent game state.

Do not assume a reticle's memory representation is known until it has been verified experimentally.

During my demonstrations, correlate changes in heading and position with target acquisition.

Produce a reusable function that determines whether a specific enemy is attackable, and explain why when it is not.

## 4. Learn my combat positioning

For each demonstrated encounter, reconstruct:

1. My initial position relative to the enemy.
2. How I approach or circle the enemy.
3. How I orient the character.
4. When the target indicator becomes available.
5. Which attack button I press.
6. When the attack animation begins.
7. When I press the second and third combo inputs.
8. How much enemy HP changes.
9. How I reposition afterward.

Train a weapon-specific combat controller using these recorded examples.

Do not merely count button presses. Learn the relationship between game state, input timing, and successful damage.

## 5. Learn navigation and interaction in the same way

When I demonstrate a doorway, switch, teleporter, or route:

- Identify the relevant objects.
- Record the 2D trajectory.
- Determine the preconditions for success.
- Observe the resulting RAM state transition.
- Convert the demonstration into a reusable, map-relative skill.
- Test it from different valid starting positions.

Maintain a persistent knowledge database keyed by game version, map variant, room, object type, and skill.

## 6. Build a demonstration-to-skill compiler

Every completed demonstration must pass through this pipeline:

**Raw recording → synchronized state trace → action segmentation → causal analysis → skill candidate → controlled recreation → verification → permanent knowledge.**

Use a skill representation containing:

- Preconditions.
- Target object or enemy class.
- Map-relative approach strategy.
- Controller policy and timing.
- Expected state changes.
- Failure and recovery behavior.
- Source demonstration ID.
- Confidence and validation count.

Failed recreations must generate diagnostic evidence and refine the skill. Never overwrite a successful demonstration with an unsuccessful guess.

## 7. Verify that learning is actually occurring

After every operator demonstration, display:

- Recording duration and number of captured frames.
- Number of controller events.
- Rooms, doors, and enemies encountered.
- New skills extracted.
- Existing skills improved.
- Behaviors awaiting verification.
- Successful and failed recreations.

I must be able to inspect what you learned from each training session.

If no usable skill was extracted, explain precisely why, using the recording and RAM evidence.

## 8. Mandatory tests

**Test A — Automatic capture:** I take control without warning. You record all effective controller inputs and synchronized game states without interrupting me.

**Test B — Target acquisition:** I approach an enemy, adjust facing until the targeting indicator becomes available, and attack. You identify the target and reconstruct the positioning conditions.

**Test C — Three-hit combo:** I perform a complete combo. You recover the input frames and animation timing, then reproduce a successful combo against an appropriate enemy.

**Test D — Navigation:** I demonstrate a doorway traversal. You reproduce it from another starting position using the 2D map.

**Test E — Persistence:** Restart the worker and verify that the previously learned skills remain available and executable.

**Test F — Continuous learning:** I demonstrate a correction to a failed maneuver. The bot incorporates the correction and measurably improves its next attempt.

Do not mark a test passed because code exists. Supply captured traces and independently verified outcomes.

## 9. Protect my live gameplay

Do not interrupt operator control to perform experiments.

Do not allow multiple workers to issue controller inputs simultaneously.

Do not write experimental memory values during my demonstration unless I explicitly enable that testing mode.

Analyze recordings asynchronously and recreate actions only after operator control has ended and the environment is safe for testing.

## Immediate deliverable

Audit the existing `pso-autoplay-loop.py`, demonstration recorder, `pso-learn-routes.py`, combat model, and gBox controller bridge.

Determine which inputs are actually captured, whether frame-accurate capture exists, which learned skills are persisted, and which skills have been successfully recreated.

Then implement the missing components and demonstrate the full training pipeline on one enemy encounter and one doorway.

**The definition of success is not that you watched me play. It is that you learned a reproducible behavior from my gameplay and proved that you can perform it yourself.**