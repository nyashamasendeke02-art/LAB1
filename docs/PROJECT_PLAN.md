# Project Plan: AI Robotics Lab on autolab

**Status:** DRAFT for human approval (2026-10-04). Nothing in this plan has been run.
**Authority:** the mandate ([MANDATE.md](MANDATE.md) / the PDF) sets *what*; CLAUDE.md sets *how*;
the human researcher approves this plan, every pre-registration and every safety change.
**Labels:** plan choices are ENGINEERING_DECISION (proposed) unless marked; effort and risk
estimates are INFERENCE; unresolved items are OPEN_QUESTION.

---

## 1. Programme objective and definition of success

**Objective (Phase 1 of the mandate roadmap, "foundation").** Build, in simulation only, the
smallest version of the modular robot brain that lets us test H1-H4 with controlled
experiments. Every component is earned by beating its ablation (D20). H5 (transfer) follows.

**Phase 1 is complete when:**
1. Gates 0-6 have passed with the mandate's evidence (implementation, tests,
   observability, documentation, reproducibility).
2. Each of E1-E5 has a *recorded conclusion* (supported, unsupported, inconclusive, or an
   invalid instrument), each traceable from the conclusion to commit, frozen protocol and raw data.
3. Negative results are kept, and components that failed their ablation are recorded as such.
4. A Gate 8 synthesis report states what the evidence supports, with labels, alternative
   explanations and limitations.

Success means **answered questions**, not "the full architecture works". A rigorous result
that H2 is unsupported is a success for the programme.

## 2. Strategy: five principles

1. **Instrument before intervention.** No mechanism is tested until the environment, telemetry
   and baseline are validated and reproducible (Gates 0-1, then E1).
2. **One new mechanism per experiment**, always against the previous frozen baseline plus its
   ablation. The architecture grows only along a chain of evidence.
3. **Fair comparisons by construction:** the same tuning budget for baseline and intervention,
   comparisons at matched compute where compute differs, and held-out evaluation sets frozen
   in the protocol.
4. **Pilot, then confirm.** Every hypothesis gets a small exploratory pilot (to estimate
   variance and validate the instrument), then *one* pre-registered confirmatory study on fresh
   seeds, sized by power analysis. No re-tries of a failed confirmatory study.
5. **Small, cheap, deterministic.** Pure Python/NumPy simulation sized for this machine
   (4 cores, 8 GB RAM, CPU only). Heavier tools (MuJoCo, PyTorch) come in only when a gate
   needs them, as a recorded decision.

## 3. Operating model: how the lab runs the programme

### 3.1 One lab, one research codebase
- Create one autolab lab, **`labs/robolab/`**. Its `repo/` *is* the robot-brain codebase,
  initialised with the mandate layout (`src/contracts, state, world_model, system1, system2,
  awareness, memory, skills, learning, safety, simulation, robot`, `tests`, `experiments`,
  `configs`, `docs`).
- Every experiment is an autolab **project** in that lab. Every component change is a
  controller-merged commit on `main`. So one provenance chain links code, protocols, runs and
  conclusions (decision needed, section 10).

### 3.2 Two tracks
| Track | Used for | Flow (autolab) |
|---|---|---|
| **Engineering track** (new, L1) | gate work with no hypothesis: contracts, simulator, Safety Kernel, telemetry, components before they are tested | spec traced to REQ-* and ADR-* → engineer implements → controller tests → verifier review + hermetic tests → merge (+ human gate for safety/contract paths) |
| **Research track** (exists) | every hypothesis (WM-1, E1-E6) | question → hypothesis → requirements → design → review → **pre-registration gate** → engineering → validation → run → analysis → challenge → evaluate → report |

### 3.3 Mandate roles → lab roles
| Mandate role | Who in autolab |
|---|---|
| Project Lead | human (final authority) + Claude Code (planning, lab maintenance) |
| Research Governor | scientist agent (design, scientific review, validation) + human pre-registration gate |
| Contracts, Simulation, World Model, S1, S2, Awareness, Memory & Skills, Continual Learning, DevOps | engineer agent, scoped by task spec, allowed paths and REQ IDs |
| Testing & Evaluation | verifier agent (adversarial review, independent tests, challenge) + controller-run tests |
| Safety | human review gate on `src/safety/**` + verifier fault-injection tests |

### 3.4 Traceability (mandate section 01-04)
Every task and protocol carries `mandate_refs` (e.g. `REQ-WM`, `ADR-004`, `H3`, `E4`,
`Gate 2`). The gate-status report is generated from the ledger, not written by hand.

### 3.5 Human decision points
1. approve this plan;
2. approve every confirmatory pre-registration (gate on);
3. approve merges touching `src/safety/**` or `src/contracts/**` (new gates, L2);
4. approve passing each mandate gate (a short evidence review);
5. approve any new heavy dependency or compute above budget.

## 4. Phase overview

| Phase | Gate | Track | Deliverable | Experiment | Exit criterion |
|---|---|---|---|---|---|
| P0 | none | lab maintenance | lab upgrades L1-L10 + one live validation run | lab validation (toy, exploratory) | the lab reaches COMMUNICATE live with no integrity or protocol failures |
| P1 | 0 | engineering | contracts, cycle runner, telemetry, Safety Kernel v1 | none | contract tests + fault-injection tests pass; human safety review |
| P2 | 1 | engineering | EnvA simulator (+ disturbance and fault injection) | instrument checks (not a hypothesis) | determinism, reset and logging validated; physics sanity tests |
| P3 | 2 | research | World Model v1 | **WM-1**: does the learned residual improve prediction over the integrator alone? | WM-1 concluded |
| P4 | 3 | research | System 1 v1 | **E1**: S1 baseline vs conventional and random | frozen reproducible baseline with known variance |
| P5 | none | research | (uses WM + S1) | **E4 / H3**: does WM surprise predict S1 failure? | concluded |
| P6 | 4 | eng + research | Awareness v1 (rules: accept / fallback / abstain) | E3a: rule-based abstention vs none | concluded |
| P7 | 5 | eng + research | System 2 v1 (planner over the WM) | **E2 / H1**: does S1+S2 broaden capability at acceptable compute? | concluded |
| P8 | none | research | Awareness v1 with escalation to S2 | **E3 / H2**: does Awareness cut S2 use without hurting hard cases? | concluded |
| P9 | 6 | eng + research | episodic memory, replay, continual learning | **E5 / H4**: continual learning vs frozen, with forgetting control | concluded |
| P10 | none | eng + research | EnvB (second body) + embodiment adapter | **E6 / H5**: transfer vs retraining | concluded |
| P11 | 8 | research | synthesis report | none | human accepts the conclusions |
| deferred | 7 | none | hardware / HIL | none | only by explicit human decision |

Gate order follows the mandate (2 World Model before 3 System 1). E1 is CLAUDE.md's first
milestone: the minimal predictive agent (S1 acting, WM predictions logged) with a
reproducible baseline.

## 5. Phase details

### P0: Lab readiness (lab maintenance by Claude Code; no research experiments)
The lab has never completed a live cycle; trusting it with the mandate first needs:

| ID | Upgrade | Why |
|---|---|---|
| L1 | Engineering track: ENG tasks without a hypothesis, spec traced to REQ/ADR/Gate, same review/merge machinery | gate work is not hypothesis-driven |
| L2 | Path-based merge gates (`src/safety/**`, `src/contracts/**` need a human) | mandate: safety and contract changes need review |
| L3 | Controller-measured resources per trial (wall time, CPU time, peak RAM) recorded in the manifest, not self-reported | mandate metric: compute/latency; prevents reporting bias |
| L4 | Decision rules: non-inferiority, co-primary endpoints, Holm correction for multiple contrasts | E3/H2 is "fewer S2 calls AND not worse on hard cases" |
| L5 | Power / sample-size check at scientific review, from pilot variance | principle 4 |
| L6 | Pilot → confirmatory policy: a confirmatory study after a registered pilot is allowed (fresh seeds, one attempt), refining D18 | D18 currently blocks legitimate replication |
| L7 | `mandate_refs` on tasks, protocols and conclusions; generated gate-status report | traceability requirement |
| L8 | Telemetry artifact policy: per-trial size cap, compressed JSONL/NPZ, summary metrics in metrics.json | REQ-LOG without filling the disk |
| L9 | Dependency lock (`requirements.lock`) checked into the research repo and recorded per run | reproducibility (mandate 08-04) |
| L10 | Citation verification for background research (verified/unverified + method) | robotics literature will be cited |

Then one **lab validation run** (needs your go-ahead): a fresh toy objective, exploratory and
unprotected, run to COMMUNICATE. Exit: a complete cycle with a report, no integrity
violations, and protocol retries under 2 per stage. **Effort (INFERENCE):** L1-L10 is roughly
2-4 sessions of my work, with tests; the validation run is about 1 hour plus agent quota.

### P1: Gate 0, contracts and runtime skeleton (engineering track)
- **Contracts (REQ-LOG, mandate 02-04):** versioned JSON schemas plus dataclasses for the 11
  message classes and their required metadata (message/cycle/correlation ID, timestamp,
  source, destination, schema version). Uncertainty types kept separate (mandate 02-03).
  Contract tests, including rejection of malformed messages.
- **Cycle runner:** a deterministic synchronous tick (observe → state → predict → propose →
  arbitrate → **safety** → act → outcome → log). Modules sit behind interfaces with null
  implementations, so every later component is a swap (ADR-001).
- **Telemetry:** per-cycle records with module latency (p50/p95), decisions and reasons.
- **Safety Kernel v1 (REQ-SAFE, ADR-003):** action limits, workspace limits, stale-command and
  malformed-command rejection, a watchdog timeout to a safe state, e-stop independent of
  learned modules, and fault telemetry. Fault-injection tests per mandate 05-04, each with
  expected safe behaviour. **Your review is required.**
- **Exit:** all contract and fault tests pass in the hermetic run; latency overhead of the
  runner measured; your safety sign-off.

### P2: Gate 1, simulation (engineering track)
**EnvA "Puck2D"** (proposed; OPEN_QUESTION 8): a 2D point mass with mass *m*, viscous plus
Coulomb friction, a goal-reaching task, optional obstacles, and disturbances (impulses,
friction patches, mass changes). Why this one: cheap (≪1 ms/step), physics a World Model can
learn (integrator + residual, as the mandate prescribes), and natural "surprise" events where
a fast controller fails.
- Deterministic seeding; reset/termination; sensor noise and actuator lag models; domain
  randomisation ranges in config; reproducible logs.
- **Instrument checks** (tests, not hypotheses): energy/physics sanity, determinism across runs,
  and disturbance injection doing what its config says.
- **Exit:** the Gate 1 evidence pack. EnvB (a different body) is deliberately postponed to P10.

### P3: Gate 2, World Model v1, experiment WM-1 (research track)
- **WM v1:** a hand-written integrator over object-centric physical variables + a small
  learned residual for friction (ADR-004, mandate 03-02), with predictive uncertainty.
- **WM-1 question:** does the learned residual reduce k-step prediction error versus the
  integrator alone on held-out trajectories, including friction regimes unseen in training?
- **Conditions:** constant-velocity (null), integrator only (baseline), integrator +
  residual (intervention), residual only (ablation).
- **Primary metric:** held-out k-step position RMSE. **Secondary:** uncertainty calibration
  (coverage of predicted intervals), inference latency, training compute.
- **Validity checks:** the integrator beats the constant-velocity model; the data split has no
  leakage (trajectory-level split).
- **Data:** logged trajectories from scripted and random policies, frozen as a versioned
  dataset; experiences immutable.

### P4: Gate 3, System 1 v1, experiment E1 (research track)
- **S1 v1:** a small learned controller (NumPy MLP or linear policy, trained by evolution
  strategies or CEM; no GPU) with an explicit action space and a **confidence output**
  (required by H2/H3), plus a safe fallback (mandate 03-03).
- **E1 conditions:** random (null), a tuned PD controller (conventional baseline, as the
  mandate asks), S1 (intervention). The same tuning budget for PD gains and S1 training.
- **Primary metric:** task success rate on a frozen held-out task set. **Secondary:** time to
  goal, control latency p95, confidence calibration (ECE of confidence vs success), training
  compute.
- **Decision:** S1 vs random (validity, must clearly beat it); S1 vs PD (the scientific
  contrast, either direction is informative). The pilot gives the variance; the confirmatory
  study is sized from it.
- **Output:** a **frozen, reproducible baseline** (commit + config + seeds + variance) that every
  later experiment compares against. This is the first milestone of CLAUDE.md.

### P5: E4 / H3, prediction error as a reconsideration signal (research track)
- **Question:** in episodes with unseen disturbances, does WM surprise (prediction error,
  normalised by predicted uncertainty) predict S1 failure within the next *k* steps better
  than S1 confidence alone?
- **Conditions (signals):** random flag (null), S1 confidence (baseline), WM surprise
  (intervention), confidence + surprise (combination); surprise without uncertainty
  normalisation (ablation).
- **Primary metric:** AUROC of failure prediction, paired by seed. Events are defined in the
  protocol before data (OPEN_QUESTION 10).
- **Alternative explanations to rule out:** surprise merely tracking speed or proximity to
  obstacles (control: a speed-only predictor); disturbance-size leakage.

### P6: Gate 4, Awareness v1 (engineering + E3a)
- Interpretable rules (mandate 03-05) with inputs confidence, surprise, novelty, stakes and
  budget, operationalised in config. Actions available before S2 exists: accept, fall back to
  safe controller, abstain. Every decision is logged with its reason.
- **E3a:** Awareness (accept/fallback) vs no Awareness on disturbance episodes. Primary metric:
  failure rate; co-primary: the cost of unnecessary fallbacks. Ablations: drop each input.

### P7: Gate 5, System 2 v1, E2 / H1
- **S2 v1:** a sampling-based planner (CEM-MPC) over the WM. It proposes plans and never
  actuates (mandate 03-04).
- **Task set:** EnvA tasks that need planning (obstacles, traps), frozen as "hard" vs "easy".
- **E2 conditions:** S1 only (baseline), S1+S2 with S2 always on (intervention), S2 with a
  ground-truth model (upper bound), S1+S2 at matched compute (control).
- **Primary metric:** success on hard tasks. **Co-reported:** compute per decision and latency.
  H1 says "acceptable compute", so the acceptable bound is fixed in the protocol (OPEN_QUESTION 9).

### P8: E3 / H2, awareness-guided escalation
- **Conditions:** S1+S2 always (reference), S1+S2 with Awareness escalation (intervention),
  random escalation at the same rate (control for "any reduction"), and Awareness minus each
  input (ablations).
- **Decision rule (needs L4):** co-primary: S2 invocations reduced by ≥ a pre-set fraction
  **and** hard-case success non-inferior within margin δ; Holm-corrected secondary contrasts.

### P9: Gate 6, memory, skills and continual learning, E5 / H4
- Episodic memory with retrieval provenance; replay; versioned updates with held-out
  regression and rollback (mandate 03-07).
- **E5:** a sequence of regimes A→B→C (friction/mass). Conditions: frozen train-then-deploy
  (baseline), online updates without replay (ablation), online updates with replay
  (intervention). Metrics: average performance across the sequence (primary), backward
  forgetting on A after C, forward transfer.

### P10: E6 / H5, embodiment transfer
- **EnvB:** a unicycle (differential-drive) body in the same 2D world, behind an embodiment
  adapter.
- **Conditions:** train-from-scratch on EnvB (baseline) vs shared representation + new adapter
  (intervention); adapter-only training (control). Metric: samples to reach the success
  threshold; transfer kept distinct from retraining (mandate 03-08).

### P11: Gate 8, research evaluation
A synthesis report over all conclusions, with evidence labels, effect sizes and intervals,
failed ablations, threats to validity, and the next questions (Phase 2 of the roadmap: online
continual learning at scale). For your acceptance.

## 6. Experimental design standards (all research projects)

- **Unit of replication = seed** (one seed fixes environment sampling, initialisation and
  training). Evaluation episodes are averaged *within* a seed. Seeds are shared across
  conditions, so analysis is paired.
- **Frozen evaluation sets** (task instances, disturbance schedules) live in
  `protocol.fixed_params` and are never used in training or tuning.
- **Equal tuning budget** for baseline and intervention, recorded in the protocol.
- **Compute matching** wherever an intervention uses more compute (S2, Awareness).
- **Validity checks first:** the baseline must work (D12) and the null must behave as null.
- **Pilot → confirmatory:** a pilot with at least 5 seeds (exploratory), then power analysis,
  then one confirmatory study on fresh seeds behind your gate.
- **Multiplicity:** one primary contrast per study; secondary contrasts Holm-corrected and
  labelled exploratory.
- **Failure analysis** for every result (mandate 06-06): cause hypothesis, evidence,
  reproduction, impact on the hypothesis.
- **Alternative explanations** must be named in the design and attacked at CHALLENGE.

## 7. Engineering standards

- **Stack:** Python 3.13, NumPy, jsonschema. No PyTorch or MuJoCo until a gate justifies it
  (recorded decision). A lock file is pinned per run (L9).
- **Determinism:** NumPy `Generator` objects passed explicitly; no global RNG; seeds recorded.
- **Contracts first:** contract → tests → implementation → integration → ADR → report (mandate
  08-01). The Contracts and Safety paths are protected by gates (L2).
- **Testing matrix:** unit, contract, component, integration (cycle runner), simulation
  determinism, fault injection, regression (frozen baselines must reproduce), research
  benchmark (the experiments themselves).
- **Performance:** per-module latency budget in config; telemetry p95 checked in tests.
- **Data:** experiences immutable; raw vs derived versioned; no silent discarding (mandate 09).
- **Docker:** deferred to Gate 7 (single Windows machine). The venv + lock file is the
  reproducible environment for now.

## 8. Budget (INFERENCE)

| Resource | Estimate | Control |
|---|---|---|
| CPU per trial | under 60 s target, under 5 min hard timeout | protocol budget.timeout_s |
| Trials per study | pilot ~5 seeds × 3-5 conditions; confirmatory sized by power (≤ 200 = budget gate) | compute_budget gate |
| RAM | under 2 GB per trial; one trial at a time | L3 measurement |
| Agent quota | about 20-30 agent calls per research cycle, 6-15 per engineering task | the usage limit already halted a run once (F5); plan about 1 research cycle per day |
| Disk | under 20 MB telemetry per trial | L8 cap |

## 9. Risk register

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| 1 | The lab is still unproven live (no cycle has reached COMMUNICATE) | high / high | P0 validation run before any mandate work |
| 2 | Implementation overtakes research (mandate risk) | medium / high | gate order; each component earned by an experiment |
| 3 | Under-specified Awareness/surprise definitions invite post-hoc choices | high / high | operational definitions frozen in protocols (OPEN_QUESTION 10) |
| 4 | Unfair baselines (tuning or compute asymmetry) | medium / high | equal tuning budget, compute-matched controls |
| 5 | S1 training too slow or unstable on CPU | medium / medium | small policies, evolution strategies/CEM, EnvA kept small |
| 6 | WM inaccurate, so the downstream tests (H3, S2) are confounded | medium / high | WM-1 validity checks; a ground-truth-model upper bound in E2 |
| 7 | Agent contract drift or safety tampering | low / high | protected paths, human gates, integrity checks, hermetic tests |
| 8 | Agent quota and usage limits stall runs | high / medium | pacing; resumable HALT; no work lost (F5) |
| 9 | Underpowered studies give inconclusive results | medium / medium | pilots + power analysis (L5) |
| 10 | Sim results over-generalised to robots | medium / high | every conclusion labelled "simulation, EnvA"; Gate 7 deferred |

## 10. Decisions needed from you (with my recommendation)

1. **Approve this plan** as the programme baseline (later changes recorded as decisions).
2. **Repository strategy:** (A, recommended) one lab `labs/robolab` whose repo is the
   robot-brain code; or (B) a separate robobrain repo imported by experiments.
3. **Environment:** EnvA = Puck2D as proposed, or your own choice of task.
4. **Budgets:** the per-trial timeout, the trials-per-study cap (default 200) and the pace of
   agent quota use.
5. **Confirmatory policy:** pilot → one confirmatory study per hypothesis (L6), each behind your
   pre-registration gate.
6. **Backup:** the lab repos are local only. Do you want a private remote? (Pushing needs your
   explicit approval each time.)

## 11. Immediate next steps (still no experiments)

1. You review this plan and answer the section 10 decisions.
2. Claude Code implements P0 upgrades L1-L10 with tests (lab maintenance, no experiments).
3. With your go-ahead: the lab validation run.
4. Then P1 (Gate 0) through the lab's new engineering track.
