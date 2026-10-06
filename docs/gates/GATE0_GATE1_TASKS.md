# Gate 0 and Gate 1: engineering-track task specs (P1, P2)

Submitted to `labs/robolab` with `autolab task` in this order (each depends on the
previous). Specs are ENGINEERING_DECISIONs under the mandate (docs/MANDATE.md). Every
task is reviewed by the verifier with hermetic independent tests. `src/contracts/*` and
`src/safety/*` merges also need a review-gate decision.

## G0-1 Contracts: message envelope and message classes
**Refs:** Gate 0, REQ-LOG, REQ-STATE, ADR-001
**Spec:** In `src/contracts/`, implement versioned message contracts as frozen dataclasses
with JSON (de)serialisation and validation:
- an `Envelope` with message_id, timestamp (float seconds, simulation clock), source,
  destination, schema_version (a `SCHEMA_VERSION` string constant), cycle_id,
  correlation_id and payload;
- payload classes for Observation, StateUpdate, PredictionRequest, PredictionResult,
  ActionProposal, PlanProposal, AwarenessDecision, SafetyDecision, Outcome, LearningEvent,
  MemoryQuery, MemoryResult and ExperimentEvent;
- uncertainty kept as separate typed fields (measurement, estimation, model, policy,
  outcome) where a message carries uncertainty;
- `to_json` / `from_json` round-trip; `validate()` rejects missing fields, wrong types,
  non-finite numbers, unknown message types and schema-version mismatches with a
  `ContractError`.

**Acceptance:**
1. A round-trip test for every message class.
2. Malformed-message tests (missing field, wrong type, NaN, unknown type, wrong version)
   each raise `ContractError`.
3. `docs/contracts.md` documents every class and field.

## G0-2 Telemetry: per-cycle structured log
**Refs:** Gate 0, REQ-LOG
**Spec:** In `src/state/telemetry.py` (or `src/contracts/telemetry.py`), implement
`TelemetryLog`: an append-only JSONL writer. Each record has timestamp, component, level,
cycle_id, event_id, model_version, decision, reason and latency_ms; extra fields go under
`data`. The writer refuses writes after `close()`, enforces a configurable size cap
(raising `TelemetryCapExceeded`), and offers `summary()` with per-component latency
p50/p95.

**Acceptance:**
1. Records round-trip and keep their order.
2. The size cap is enforced.
3. Writes after close are refused.
4. p50/p95 are correct on a known sample.

## G0-3 Safety Kernel v1
**Refs:** Gate 0, REQ-SAFE, ADR-003
**Spec:** In `src/safety/kernel.py`, implement a deterministic `SafetyKernel` that every
actuator command must pass:
- configured per-axis action limits (out-of-limit commands are clamped *or* rejected, per
  config) and workspace bounds (a command predicted to leave the workspace is rejected);
- stale-command rejection (command timestamp older than `max_command_age_s`);
- malformed-command rejection (via the contracts validator);
- a watchdog: if no valid command arrives within `watchdog_timeout_s`, output the
  configured safe action (zero force);
- an emergency-stop latch that forces the safe action until explicitly reset by the
  operator API, independent of every learned module;
- every decision returned as a `SafetyDecision` with a reason, and logged.

The kernel exposes no API for learned modules to change its limits.

**Acceptance (fault-injection tests, each asserting the expected safe behaviour):**
1. An out-of-limit command is clamped or rejected per config.
2. A workspace exit is rejected.
3. A stale command is rejected.
4. A malformed command is rejected.
5. Command silence makes the watchdog output the safe action.
6. With the e-stop latched, every command yields the safe action until reset.
7. Limits are immutable after construction.

## G0-4 Cycle runner skeleton
**Refs:** Gate 0, ADR-001, ADR-002, REQ-STATE, REQ-S1
**Spec:** In `src/robot/runner.py`, implement a deterministic synchronous control loop:
observe → state estimate → world-model predict → System 1 propose → (System 2 plan) →
Awareness arbitrate → **Safety Kernel** → actuate → outcome → telemetry. Each module sits
behind a `typing.Protocol` interface (StateEstimator, WorldModel, System1, System2,
Awareness, Environment), with null or pass-through default implementations, so any
module can be swapped by configuration. Per-module latency is measured with
`time.perf_counter`. All randomness comes from a `numpy.random.Generator` passed in.
The runner never lets an action bypass the Safety Kernel.

**Acceptance:**
1. With a stub environment, two runs with the same seed give identical telemetry
   decision sequences.
2. A test proves every actuated command passed through the kernel (a kernel spy).
3. Swapping a module implementation needs no runner changes.
4. Per-module latency appears in the telemetry summary.

## G1-1 Puck2D simulator (EnvA)
**Refs:** Gate 1, REQ-SIM
**Spec:** In `src/simulation/puck2d.py`, implement a deterministic 2D point-mass
environment implementing the runner's Environment protocol:
- state: position, velocity; parameters: mass, viscous damping, Coulomb friction,
  dt = 0.02 s, semi-implicit Euler integration;
- action: a 2D force with configured limits;
- task: reach a goal disc (radius configurable) within a step limit; optional circular
  obstacles (collision terminates the episode as failure);
- observation: position and velocity with configurable Gaussian sensor noise; optional
  actuator lag (first-order);
- disturbances, scheduled by config: impulses, friction patches (regions with different
  friction) and mass change at a step;
- `reset(seed)`, `step(action) -> (obs, reward, terminated, truncated, info)`, with `info`
  carrying ground-truth state and the active disturbances;
- every random draw from the seeded Generator.

**Acceptance:**
1. Same seed + same actions give bit-identical trajectories.
2. Physics sanity: with no force and no friction, momentum is conserved; with damping,
   speed decays monotonically; at the force limit, acceleration = F/m.
3. Each disturbance type has the configured effect at the configured step or region.
4. Goal and collision termination are correct.
5. A step costs < 1 ms (benchmark test with a generous bound).

## G1-2 Episode harness and scripted baselines
**Refs:** Gate 1, REQ-SIM, REQ-LOG
**Spec:** In `src/simulation/harness.py`, run N episodes of an environment with a policy
through the cycle runner, writing telemetry and returning per-episode metrics: success,
steps, time-to-goal, path length, collisions, safety interventions. Add two reference
policies in `src/simulation/policies.py`: `RandomPolicy` (uniform force) and
`PDController` (gains in config). Add an evaluation-set builder: a frozen list of task
instances (start, goal, obstacles, disturbance schedule) generated from a seed and saved
as JSON.

**Acceptance:**
1. Determinism of the episode metrics given seeds.
2. The PD controller reaches the goal in the no-disturbance, no-obstacle case.
3. The random policy mostly fails (sanity of the instrument).
4. Evaluation sets round-trip through JSON unchanged.

## G1-3 Safety Kernel v1.1: stopping-distance workspace check
**Refs:** Gate 1, REQ-SAFE, ADR-003. Added 2026-10-05 from the G0-3 safety review (APR-0002).
**Why:** v1 checks only the next control step and its safe action is zero force, so a fast
body is approved two steps from a wall and then coasts through it (reproduced in review:
x = 9, v = 50 m/s, wall at 10, dt = 0.01 -> approved).
**Spec:** In `src/safety/kernel.py`, reject (or, in clamp mode, replace with a braking
action) any command after which the body could not stop inside the workspace: per axis,
with the predicted next position p' and velocity v', require that the stopping distance
v'^2 / (2 * a_brake) in the direction of motion fits between p' and the workspace bound,
where a_brake = max |action| on that axis / mass_kg (configured; conservative: ignore
friction and damping). Replace "zero force" as the only safe action with a braking safe
action (opposing velocity, at the action limit, clamped to zero once stopped). Bump
KERNEL_VERSION. Keep every G0-3 behaviour and test.
**Acceptance:**
1. The review case (x = 9, v = 50, wall 10) is rejected or braked.
2. In Puck2D (G1-1), random high-speed commands through the kernel never leave the
   workspace over many seeded episodes (property test).
3. Commands that can still stop in time are approved unchanged.
4. All G0-3 tests still pass.

## G1-4 Ground-truth isolation (the brain learns physics only from consequences)
**Refs:** Gate 1, REQ-SIM, REQ-STATE, ADR-001, ADR-004. Added 2026-10-05 (D27).
**Why:** Puck2D's `info` carries the true state, parameters and active disturbances. If any
brain module can read them, "learned physics" results are invalid.
**Spec:** The cycle runner passes brain modules (StateEstimator, WorldModel, System1, System2,
Awareness) only the noisy observation, their own past actions and telemetry they produced.
Ground truth (`info`) goes only to the harness metrics and telemetry under a `ground_truth`
key that brain modules never receive. Brain packages (`src/world_model`, `src/system1`,
`src/system2`, `src/awareness`, `src/memory`, `src/skills`, `src/learning`) must not import
`src/simulation`.
**Acceptance:**
1. A spy module asserts it never receives ground-truth fields over seeded episodes.
2. A static test fails if any brain package imports `simulation`.
3. Harness metrics still use ground truth correctly (G1-2 tests pass).

## G1-5 Model Hardware Standard (MHS) v0
**Refs:** Gate 1, H5, ADR-001, ADR-003, ADR-005, REQ-SAFE, REQ-ROS. Added 2026-10-05 (D28).
**Why:** the brain must be the same code for every body; what differs is a declared,
machine-readable description of the body. The brain reads it; it never hard-codes a body.
**Spec:** In `src/contracts/mhs.py` (+ `docs/mhs.md`), define `MHS` (frozen, versioned
`MHS_VERSION`, JSON round-trip, `validate()` raising `ContractError`) with:
- identity: body name, body class (e.g. point_mass, wheeled, legged), MHS version;
- actuators: name, kind (force, torque, velocity, steering, ...), units, min/max, rate limit,
  latency; the action vector layout the brain must produce;
- sensors: name, kind, units, shape, rate, noise model, frame; the observation layout;
- body: mass and inertia if known (or "unknown"), geometry/footprint, frames;
- control: control period, timing requirements, which low-level reflexes the body provides
  itself (below the adapter, e.g. balance or motor current loops);
- safety envelope: workspace or operating domain, speed limits, braking capability, safe
  action, e-stop semantics. The Safety Kernel is configured FROM the MHS (no per-body code).
Puck2D publishes its MHS; the runner hands the MHS to brain modules at construction.
**Acceptance:**
1. Round-trip and malformed-MHS tests (missing actuator limits, unknown units, inconsistent
   layouts) raise `ContractError`.
2. A `SafetyKernel` built from Puck2D's MHS behaves identically to the hand-configured one
   (all G0-3/G1-3 tests pass).
3. Brain-side code reads action/observation layouts only from the MHS (static test: no
   Puck2D constants in brain packages).

## G1-6 Car2D: a second body (RC-car-like) behind the same MHS
**Refs:** Gate 1, H5, REQ-SIM. Added 2026-10-05 (D28).
**Why:** a brain designed against one body silently overfits to it. A non-holonomic car
(it cannot move sideways) differs from the puck in exactly the way that exposes that.
**Spec:** In `src/simulation/car2d.py`, a deterministic kinematic-bicycle car (wheelbase,
max steering angle and rate, throttle/brake force, speed limit, rolling resistance) in the
same 2D world and task format as Puck2D (goals, obstacles, disturbances: slippery patches,
impulses, payload change), implementing the Environment protocol and publishing an MHS.
**Acceptance:** G1-1-style determinism and physics-sanity tests (turning radius matches
wheelbase/steering; no sideways motion without slip); the G1-2 harness runs it unchanged;
the Safety Kernel built from its MHS keeps it inside the workspace (property test).
