# Robot Brain Requirements (robolab)

_v0.1, 2026-10-05 (D32). Sources: mandate REQ-* (`docs/MANDATE.md`), D27, D28, D30.
Defaults chosen by claude-code under delegation (human: "no preference"); the human may
change any of them. Every change after adoption is recorded as an amendment with a reason,
never silently._

## Requirements versus hypotheses

**Requirements** are properties the system must guarantee; they are tested pass/fail and a
failure is a defect. **Hypotheses** (H1-H5, the north star in D28) are what the research
tries to find out; they are tested by pre-registered experiments and a negative result is a
valid result. A hypothesis is never turned into a requirement, because a target that must
be met invites tuning until it is (metric manipulation, forbidden by the mandate).

## Scope decisions (D32)

| Decision | Choice |
|---|---|
| Target compute for the fast loop | Edge-board class (Raspberry Pi 5 / Jetson Orin Nano). Development and simulation run on the lab PC (4 cores, 8 GB RAM, CPU only). System 2 may use more compute (local or cloud, decided by Gate 5). |
| Meaning of "figured out a new body" | Fast adaptation: a fixed experience budget, compared with a tuned body-specific controller, with zero safety violations. |
| First task family | Navigation: reach goals, avoid obstacles, handle disturbances. Manipulation and language-specified goals come later. |

## Functional requirements

| ID | Requirement | Verification | Gate |
|---|---|---|---|
| REQ-STATE | State and belief representation in four layers (physical, belief, task, meta) with uncertainty kept separate by kind. | contract tests | 0 |
| REQ-WM | The World Model predicts the next k states with uncertainty and exposes prediction error as a surprise signal. | component tests | 2 |
| REQ-WM+ | Prediction error and calibration are reported: k-step position RMSE, and the share of outcomes inside the predicted 90% interval (target 85-95%). | evaluation on held-out trajectories | 2 |
| REQ-S1 | System 1 outputs an action and a confidence every cycle, within the latency budget, with a safe fallback. | component + latency tests | 3 |
| REQ-S2 | System 2 produces plans or skill choices, runs asynchronously, and never commands actuators. | integration tests (kernel spy) | 5 |
| REQ-AH | The Awareness Harness selects one of accept, request S2, request prediction, replan, abstain, escalate, with a logged reason. | component tests | 4 |
| REQ-MEM | Episodic memory with retrieval and replay; skills versioned; provenance observable. | component tests | 6 |
| REQ-CL | Continual learning with held-out regression checks, replay, versioning and rollback. | regression suite | 6 |
| REQ-MHS | Any body describable in MHS v0 is added with only an MHS file and an adapter; zero brain code changes. Brain packages contain no body constants. | static test + adding Car2D (G1-6) with no brain diff | 1 |
| REQ-ISO | Brain modules never receive simulator ground truth. | spy test + import test (G1-4) | 1 |
| REQ-NAV | The task interface supports navigation tasks (goal region, obstacles, deadline, disturbances) for every body class. | harness tests | 1 |

## Safety requirements

| ID | Requirement | Verification | Gate |
|---|---|---|---|
| REQ-SAFE | Per-axis limits, workspace / operating domain, stale and malformed command rejection, watchdog, e-stop latch reset only by the operator, immutable limits. | fault-injection tests | 0 |
| REQ-SAFE+ | 0 workspace exits and 0 limit violations over ≥ 10,000 seeded episodes with random commands and injected faults, per body; e-stop yields the safe action within 1 cycle; the kernel reads position/velocity from raw observations via the MHS, never from the brain's state estimate (D30). | property tests per body | 1 |
| REQ-SAFE-H | A human safety review of the Safety Kernel before any hardware run. | recorded human approval | 7 |

## Performance and resource requirements

| ID | Requirement | Verification | Gate |
|---|---|---|---|
| REQ-RT | Fast loop p95 latency ≤ 20% of the MHS control period, measured on the target compute class. | telemetry p95 on the target device (simulated budget on the lab PC until then) | 3 |
| REQ-COMPUTE | Fast-loop modules fit the edge-board class: CPU-only inference, ≤ 1 GB resident memory for the brain process. | resource metering | 3 |
| REQ-COST | Every result reports compute used (CPU time, memory; System 2 tokens/calls when used). | telemetry + run records | 2 |

## Reproducibility and records

| ID | Requirement | Verification | Gate |
|---|---|---|---|
| REQ-SIM | Deterministic simulation: same seed and actions give bit-identical trajectories. | determinism tests | 1 |
| REQ-REPRO | Same seed gives identical telemetry decision sequences end to end (simulation clock injected). | harness determinism test | 1 |
| REQ-LOG | Per-cycle telemetry; every result traceable to commit, frozen protocol, environment and raw data. | autolab trace + ledger verify | 0 |

## Research measures (for hypotheses, not pass/fail)

| Measure | Used by |
|---|---|
| Adaptation: success relative to a tuned body-specific controller after a fixed experience budget (draft: 200 episodes; target of interest ≥ 80%), with zero safety violations | north star (D28), E6 |
| S2 invocations, correct/unnecessary escalations, abstentions | H1, H2 (E2, E3) |
| Surprise as a predictor of S1 failure (e.g. AUROC) | H3 (E4) |
| Forgetting and forward transfer | H4 (E5) |
| Samples to threshold, transfer vs retraining | H5 (E6) |

Exact thresholds for each experiment are fixed at its pre-registration.

## Deferred

| ID | Requirement | When |
|---|---|---|
| REQ-PER | Perception from raw sensors (camera, LiDAR): estimation, mapping | before Gate 7 |
| REQ-ROS | ROS 2 integration below the embodiment adapter | Gate 7 |
| REQ-UI | Operator interface, language goals | after Gate 5 |
