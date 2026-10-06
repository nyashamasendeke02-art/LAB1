# PROJECT_STATE — Autonomous Research Lab (`autolab`)

_Source of truth for status and priorities. Detail lives in `docs/ARCHITECTURE.md`
and `project_state/` (decisions, failures, open questions)._

## Status

- **Version:** autolab 0.3.0 + statistics + design-convergence fixes + independent-reviewer
  option (D29). robolab: 223/223 tests pass on main 8d04f05 (2026-10-05 review).
- **Phase:** carrying out the mandate in labs/robolab. Lab validation PASSED (pilot-004).
  Gate 0 PASSED (D26); Gate 1 in progress (G1-1 merged; G1-2 halted on a Claude usage limit).
  North star: one generalised brain for any MHS-described body (D28).
- **Agents:** ChatGPT scientist via `codex exec --sandbox read-only`; Claude engineer
  via `claude -p`; Codex verifier via `codex exec --sandbox workspace-write`.

## Reference documents

- `docs/REQUIREMENTS.md`: robot brain requirements v0.1 (D32): functional, safety, performance,
  reproducibility; research measures kept separate from pass/fail requirements.
- `docs/ROBOT_BRAIN_ARCHITECTURE.md`: the robot brain's full architecture (layers, MHS, components,
  control cycle, safety, code map, build order). `docs/ARCHITECTURE.md` is the lab (autolab).
- `docs/PROJECT_PLAN.md`: programme plan (DRAFT, awaiting approval): phases P0-P11 mapped to
  gates 0-8 and experiments WM-1, E1-E6; design and engineering standards; budget; risks.
- **`AI_Robotics_Full_Documentation.pdf` is the lab's FOUNDATION (D20, 2026-10-04):** the
  research and engineering mandate. Digest, traceable IDs and reconciliation with CLAUDE.md:
  `docs/MANDATE.md`. Direction: H1-H5, E1-E6, gates 0-8. Method: CLAUDE.md invariants;
  every component is earned by an experiment against its ablation.

## High-level goals

1. A lab that takes "Investigate whether X can produce Y" through research →
   engineering → experiment → evaluation → iteration → report → next question,
   with full provenance. **(built; validated offline only)**
2. Prove it works with real agents on a small objective (live pilot).
3. **North star (D28):** one generalised brain for any body described by a Model Hardware
   Standard (RC car, humanoid, self-driving car). HYPOTHESIS, tested body by body.
4. Carry out the mandate (docs/MANDATE.md), in order: Gate 0 contracts -> Gate 1 deterministic
   simulation -> **E1: S1 baseline** (= CLAUDE.md first milestone, a minimal predictive agent
   with a reproducible baseline) -> E4/E3 (World Model utility, H3 prediction error as a
   reconsideration signal) -> E2/E3 (S2, Awareness) -> E5 -> E6.

## Todo

### In Progress
- [ ] robolab G1-2 (episode harness): re-submit after the Claude limit resets (3:10pm PT).

### Next (priority order)
0. [x] Plan adopted under delegation (D21). P0 upgrades L1-L3, L6-L9 DONE (v0.3.0, da94322);
       L4 + L5 DONE (e0f95d4): non-inferiority rules, co-primary endpoints (intersection-union),
       p-values, Holm on secondary contrasts, power check that refuses underpowered confirmatory
       designs (paired pilot SD, 80% power). L10 deferred (D22).
0b. [x] Lab validation PASSED 2026-10-05 (labs/pilot-004, COMPLETE): first fully live cycle.
       Positive control heavy-ball (beta 0.9) vs GD: SUPPORTED, paired effect 265 fewer
       iterations, 95% CI [229, 302], p 6e-9, 12/12 seeds converged in both arms, all 8
       validity checks passed; report labs/pilot-004/reports/PRJ-0001-cycle1.md; ledger verified.
       Design approved on the 3rd attempt (convergence fixes 615d476 worked); verifier wrote
       independent tests; scientific validation caught a hard-coded parameter, fixed.
       pilot-003 HALTED at design (4 rejections; lab gaps, fixed) is kept as a record.
0c. [~] robolab initialised 2026-10-05 (labs/robolab). G0-1 contracts DONE: PRJ-0002 merged
       09ef14d (DLV-0001); verifier caught 2 defects, fixed; APR-0001 approved by claude-code.
       (PRJ-0001 HALTED: verifier sandbox bug, fixed 7ea88b2.) G0-2 telemetry DONE: PRJ-0003
       merged 3bf4a43 (DLV-0002; verifier caught a size-cap bypass, fixed). G0-3 Safety Kernel DONE:
       PRJ-0004 merged 4087f5b (DLV-0003; verifier caught e-stop reset + tamper defects;
       APR-0002 safety review by claude-code with fault injection). G0-4 runner DONE: PRJ-0005
       merged af95831 (DLV-0004). **GATE 0 PASSED (D26)**: 186 tests on robolab main; every
       actuation audited to pass the kernel. G1-1 Puck2D DONE: PRJ-0006 merged 8d04f05 (DLV-0005).
       **G1-2 HALTED** 11:42 at implement: Claude session limit (resets 3:10pm PT); not a code
       defect, re-submit as a fresh project once the limit resets. Then G1-3 (stopping-distance check, added from the
       safety review: v1 is one-step lookahead with a zero-force safe action) (docs/gates/GATE0_GATE1_TASKS.md), in order.

0d. [ ] robolab gaps vs the "Frontier Robotics Architecture" schematic (2026-10-05): add an
       episode visualiser (trajectory/telemetry plots) after G1-2; perception layer and a
       ROS 2 hardware abstraction are needed before Gate 7, not now.
0e. [ ] D27 physics learning: G1-4 ground-truth isolation after G1-3 (spec in
       docs/gates/GATE0_GATE1_TASKS.md); online mass/friction estimation in WM v1; WM-2
       (self-directed exploration vs passive data) after WM-1.
0f. [ ] D28 generalised brain: G1-5 Model Hardware Standard (MHS) v0, G1-6 Car2D (RC-car-like
       second body). Gate 1 order: G1-2, G1-3, G1-4, G1-5, G1-6.
0g. [ ] D33 software baseline (G1-7, after G1-6): robobrain namespace package + pyproject, type
       checking + ruff, kernel 100% branch coverage, fast test marker, Linux test run.
1. [ ] Fix whatever the live pilot exposes (schema compliance, sandbox behaviour,
       timeouts); add regression tests for each.
2. [x] `autolab amend` CLI: recorded protocol amendments; amending after data
       collection auto-downgrades confirmatory to exploratory.
3. [x] Progress visibility: `autolab watch` / per-step log lines with the agent
       and elapsed time.
4. [x] Statistics: paired t intervals, non-inferiority, co-primary endpoints, Holm, power check.
5. [x] Ledger anchoring: commit the ledger head hash into the research repo
       at each merge/run.
5b. [ ] autolab: pause on agent usage-limit errors until the reset time, instead of HALT.
6. [ ] Citation verification step for background research (mark as verified
       or unverified with the method used).
7. [ ] Start the Developmental Intelligence EXP-001 project in a dedicated lab.

### Done
- [x] Project environment: LAB1/.venv (Python 3.13.4, git-ignored) with autolab 0.2.0
      installed editable + pytest; 50 fast tests pass inside it. Activate:
      `.\.venv\Scripts\Activate.ps1` (PowerShell) or `source .venv/Scripts/activate` (Git Bash).
- [x] Architecture schematic: docs/architecture.png (3600x2524) + .svg, generated by
      docs/architecture_diagram.py (headless Edge); linked from docs/ARCHITECTURE.md.
- [x] Code review 2026-10-04: R1-R12 fixed with regression tests (D14-D19, F6); hermetic agent
      CLIs verified live (no CLAUDE.md, memory, skills or MCP for claude; no user config,
      memories or AGENTS.md for codex).
- [x] Store: versioned append-only records, hash-chained ledger, artifacts.
- [x] Research and engineering state machines.
- [x] Agent protocol: schemas, claim taxonomy, retry-on-violation.
- [x] Worktrees, path policies, controlled `--no-ff` merges, provenance trailers.
- [x] Experiment engine: entrypoint contract, smoke runs, raw-data preservation,
      pre-registered decision rule.
- [x] Approval gates, HALT/resume, crash recovery.
- [x] Memory export, lineage trace, reports, CLI, offline demo.
- [x] Live adapter smoke tests (claude-cli, codex-cli).
- [x] Git repository initialised and v0.1.0 committed.

## Known bugs / technical debt

- REVIEW 2026-10-05 (full review; details in DECISIONS D29-D31):
  - robolab: the Safety Kernel's workspace check uses position/velocity from the brain's own
    state estimate (runner `_kinematics`). A wrong or learned estimator can fool it (ADR-003).
    Fix folded into G1-5: the kernel reads pos/vel from the raw Observation via the MHS layout.
  - robolab: CycleRunner defaults to the wall clock; simulated runs must inject the simulation
    clock or staleness/watchdog decisions are not reproducible. Added to the G1-2 spec.
  - D27 vs D28 tension: a hand-written physics step per body is body-specific code. The World
    Model's physics prior must be generic and parameterised by the MHS (OPEN_QUESTION 13).
  - autolab: a Claude/Codex usage limit HALTs a run (F5, G1-2). Todo: detect usage-limit
    errors and pause until the stated reset time instead of halting.
  - All review gates so far were decided by claude-code under delegation (D21); no human has
    reviewed the Safety Kernel. Required before any hardware (Gate 7).
- robolab cycle runner (G0-4) is synchronous. A slow System 2 (e.g. an LLM planner, Gate 5)
  must run asynchronously while S1 keeps control; design this before Gate 5. Local vs cloud
  LLM for S2 is an open research-direction decision for the human (not needed until Gate 5).
- robolab Safety Kernel v1: one-step workspace lookahead + zero-force safe action, so a fast
  body can coast out of the workspace. Fix specified as G1-3 (docs/gates/GATE0_GATE1_TASKS.md).
- FIXED d7f8c70: agents answered status=failed for negative verdicts (stage error/retry
  instead of patch); COMMON prompt now defines status.

- FIXED 2026-10-05: hermetic Codex dropped [windows] sandbox = "elevated", so the verifier
  was read-only (robolab G0-1 PRJ-0001 HALTED at verify). Writable Codex tasks now pass
  -c windows.sandbox="elevated" (human chose this option; live probe passed).

### Code review 2026-10-04: R1-R12 fixed (details in DECISIONS D14-D19, FAILURES F6)
Residual risks the fixes do NOT remove:
- Engineer-written code still runs unsandboxed (tests, trials). Tampering with the main checkout,
  ledger or lab.toml is detected after each agent call and HALTs; other writes (e.g. other
  worktrees, artifact files) are not detected. The ledger stays tamper-evident, not tamper-proof.
- Blinding is partial: condition names and the protocol title can hint at the hypothesis.
- Looks are counted and labelled, but there is no alpha correction across looks.
- t intervals assume roughly normal per-seed metrics; heavy-tailed metrics need more seeds.
- Codex still sees its built-in system skills (imagegen, openai-docs, skill-creator,
  skill-installer); no user content.
- pilot-001/002 results predate these fixes (RUN-0001 used the old bootstrap CI).
- The full test suite now takes ~10.5 min.

### Older items

- Killing the controller orphans agent subprocesses (codex/claude are not killed with it).
- The scientific review missed min_effect=0 and an under-trained baseline. These are now
  mechanical or prompt rules, but reviewer depth remains an open question.
- The verifier sandbox (codex workspace-write) can read outside its worktree.
- The ledger is anchored in git commit trailers; rewriting both the DB and git is still possible.
- Power check uses the noisiest paired pilot only; unpaired pilots give no SD estimate.
- Background-research citations are unverified (`sources_verified: false`).
- The full test suite takes ~5 min on Windows (subprocess/git heavy); there is no fast subset marker.
- The `project_state/*.md` written by hand in LAB1 and the generated per-lab
  `project_state/` share a name; the per-lab files are generated, the LAB1 ones are not.

## Human tasks (only what Claude cannot do)

- **Backup (important):** neither LAB1 nor labs/robolab/repo has a remote; everything is only on
  this PC. Create a private GitHub repo (or two) and tell Claude to push.
- Choose the project licence (recommended Apache-2.0; D34).
- Nothing blocking. G1-2 resumes after the Claude usage limit resets (3:10pm PT).
- Before Gate 7 (hardware): a human safety review of the Safety Kernel.
- By Gate 5: local vs cloud LLM for System 2.
- Any time: change the D32 requirement defaults (target compute, adaptation budget, task family).
