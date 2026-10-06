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

## Software requirements (D33)

Status today: Python 3.13 + NumPy 2.5 only (`requirements.lock`), src-layout packages imported
by bare names (`from contracts import ...`), pytest, Windows only, no packaging, no type or
lint checks, no remote backup.

### Language, platform and runtime

| ID | Requirement | Now |
|---|---|---|
| SW-LANG | Brain, kernel, harness and simulators: Python ≥ 3.11 + NumPy. Body reflex loops (≥ 200 Hz: balance, motor current, ABS) live in the body's firmware or a C/C++ adapter, never in the Python brain. | met |
| SW-OS | Develop on Windows; the target is Linux (Raspberry Pi OS / Ubuntu, Jetson L4T). Tests must pass on both. | Windows only |
| SW-RUNTIME | The fast-loop runtime has minimal dependencies (NumPy; ONNX Runtime when learned models need it). Training dependencies (e.g. PyTorch) are separate and never imported by the fast loop. Learned models ship as versioned, hash-checked files. | met (NumPy only) |
| SW-RT | The fast loop does no unbounded work per cycle: no network, disk sync or allocation-heavy calls on the cycle path; System 2 and logging I/O run off the cycle path. | partly (sync runner) |
| SW-ROS | Core logic is testable without ROS 2; ROS 2 (Jazzy) appears only in adapters at Gate 7. | met |

### Structure and interfaces

| ID | Requirement | Now |
|---|---|---|
| SW-PKG | One installable package (`pyproject.toml`) with a namespace (`robobrain.contracts`, `robobrain.safety`, ...) so names cannot collide with third-party packages and the brain installs on an edge board with `pip install`. | not met |
| SW-IFACE | Modules talk only through versioned contracts (SCHEMA_VERSION, MHS_VERSION, KERNEL_VERSION); a breaking change bumps the version and updates `docs/contracts.md`. | met |
| SW-CONFIG | All configuration (modules, seeds, MHS, limits, evaluation sets) in validated files (TOML/JSON); no magic constants in brain code. | partly |
| SW-DEP | The brain packages may not import `simulation` (REQ-ISO) and `safety` may not import any learned module. Enforced by an import test. | not yet (G1-4) |

### Quality

| ID | Requirement | Now |
|---|---|---|
| SW-TEST | The mandate's test levels: unit, contract, component, integration, simulation, fault injection, regression, research benchmark. A fast subset runs in < 1 min. | unit to fault injection; no fast marker |
| SW-SAFETY-CODE | `src/safety`: 100% branch coverage, no dynamic code, no third-party dependency beyond NumPy, every change through the safety review gate. | review gate met; coverage not measured |
| SW-STATIC | Type hints on public APIs, checked by a type checker (pyright or mypy); a linter (ruff) runs in CI. | not met |
| SW-DET | Same seed gives bit-identical results on the same platform; across platforms, results agree within a stated tolerance (floating-point differences are expected). | same-platform met |
| SW-PERF | Benchmarks for per-module latency and memory, tracked across commits (REQ-RT, REQ-COMPUTE). | telemetry only |

### Process, versioning and delivery

| ID | Requirement | Now |
|---|---|---|
| SW-VCS | All code in git with provenance trailers; changes only through autolab tasks (engineer → tests → verifier → gated merge). | met |
| SW-BACKUP | Both repositories (LAB1 and labs/robolab/repo) are pushed to a private remote. Today they exist only on this PC. | **not met** |
| SW-CI | CI runs the test suite on Windows and Linux for every merge. | not met (local controller tests only) |
| SW-LOCK | Every dependency pinned in `requirements.lock`, recorded per run (L9). | met |
| SW-RELEASE | Brain releases are semantic-versioned; each records the contract, MHS and kernel versions and the model hashes it contains; rollback is one version back. | not yet |
| SW-DOCS | Every public module documented; architecture and requirements docs updated with every design change. | met |

## Open-source stack, mapped to the schematic layers (D34)

Selection rules: fits the lab PC (4 cores, 8 GB, no GPU) or the edge-board target; keeps
the brain body-agnostic (ROS/vendor code only below the adapter); permissive licence
preferred. Licences are as understood on 2026-10-05; re-check each one when adopting it.

### Licence policy

| ID | Requirement |
|---|---|
| SW-LICENSE | robolab code is released under one permissive licence (recommended: Apache-2.0; the human decides). |
| SW-LICENSE-DEP | Inside the brain process: only permissive (MIT, BSD, Apache-2.0) or weak-copyleft (LGPL, MPL) dependencies. GPL components (e.g. ArduPilot, ORB-SLAM3, VESC firmware) are allowed only as separate processes or firmware behind a protocol (MAVLink, ROS 2 topics). AGPL is excluded (e.g. Ultralytics YOLO). Every dependency's licence is recorded in the lock file review. |
| SW-MODEL-LICENSE | Open-weight models (System 2) are checked individually; some popular ones are not OSI-open (e.g. the Llama licence). |

### By layer

| Schematic layer | Need | Recommended | Licence | When |
|---|---|---|---|---|
| 1 User interfaces | voice in / out (offline) | whisper.cpp or Vosk; Piper TTS | MIT; Apache-2.0; MIT | after Gate 5 |
| 1 | dashboard | Lichtblick (open fork of Foxglove Studio) | MPL-2.0 | Gate 7 |
| 2 AI & decision | local LLM for System 2 | llama.cpp (or Ollama) with a small open-weight model | MIT | Gate 5 |
| 2 | task planner / mission sequencing | py_trees (behaviour trees); Unified Planning (PDDL) | BSD; Apache-2.0 | Gate 5 |
| 2 | World Model, Awareness, Safety | our own (NumPy) | - | Gates 0-4 |
| 3 Perception | image processing, detection | OpenCV; YOLOX or NanoDet (not Ultralytics: AGPL) | Apache-2.0 | before Gate 7 |
| 3 | sensor fusion / state estimation | FilterPy (Python); robot_localization (ROS 2) | MIT; BSD | Gate 3 / Gate 7 |
| 3 | SLAM, maps | RTAB-Map or slam_toolbox; OctoMap; Open3D | BSD; LGPL-2.1; BSD; MIT | before Gate 7 |
| 4 Control & planning | MPC / trajectory optimisation | acados or CasADi; OSQP | BSD-2; LGPL-3.0; Apache-2.0 | Gate 5 (S2 planner) |
| 4 | motion / manipulation planning | OMPL; MoveIt 2; Nav2 (also as the "tuned body-specific baseline" for REQ-GEN) | BSD; BSD; Apache-2.0 | baselines from Gate 3 |
| 4 | RL training | Gymnasium API for our environments; Stable-Baselines3 or CleanRL (training only) | MIT | Gate 3 |
| 5 Hardware abstraction | middleware | ROS 2 Jazzy, ros2_control, micro-ROS (microcontrollers) | Apache-2.0 | Gate 7 |
| 5 | communication | python-can, pyserial, pymavlink | LGPL-3.0; BSD; LGPL-3.0 | Gate 7 |
| 6 Physical (RC car) | low-level firmware / reflexes below the adapter | ArduPilot Rover or PX4 (via MAVLink); VESC motor firmware | GPL-3.0; BSD-3; GPL-3.0 | Gate 7 |
| 6 | reference RC-car platforms | Donkey Car; F1TENTH | MIT; open | Gate 7 |
| Data & infra | datasets, logs | MCAP (also ROS 2 bags); Apache Parquet via pyarrow; DVC for dataset versions | MIT; Apache-2.0; Apache-2.0 | Gate 2 |
| | model training / deployment | PyTorch (training only); ONNX + ONNX Runtime (edge inference) | BSD; MIT | Gate 2-3 |
| | simulation | own NumPy sims now; MuJoCo for contact, arms, humanoids (the mandate's choice); Gazebo with ROS 2 for hardware rehearsal; CARLA for road cars (needs a GPU). Isaac Sim is not open source and needs an RTX GPU: excluded | Apache-2.0; Apache-2.0; MIT | MuJoCo when a gate needs contact |
| | CI | pre-commit; nox; GitHub Actions (service) | MIT; Apache-2.0 | G1-7 |
| Monitoring & tools | visualisation | Rerun (Python, no ROS needed; fits the episode visualiser); matplotlib; RViz2 with ROS 2 | MIT/Apache-2.0; PSF-based; BSD | Rerun after G1-2 |
| | system health, resources | psutil; ROS 2 diagnostics | BSD | G1-7 / Gate 7 |
| | parameter tuning | Optuna (with the same tuning budget for baseline and intervention); pydantic for config validation | MIT | Gate 3 |
| Quality (SW-*) | lint, types, coverage, property tests, benchmarks | ruff; pyright or mypy; coverage.py; Hypothesis (safety property tests); pytest-benchmark | MIT; MIT; Apache-2.0; MPL-2.0; BSD | G1-7 |

### Deliberately not adopted

- **Isaac Sim / Isaac Lab:** proprietary simulator, RTX GPU required.
- **Ultralytics YOLO:** AGPL-3.0.
- **Full Nav2 / MoveIt 2 as the brain:** they would replace the components we are testing; they are used as conventional baselines instead.
