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
