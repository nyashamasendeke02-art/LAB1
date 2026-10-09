# PROJECT_STATE — Autonomous Research Lab (`autolab`)

_Source of truth for status and priorities. Detail lives in `docs/ARCHITECTURE.md`
and `project_state/` (decisions, failures, open questions)._

## Status

- **Version:** autolab 0.12.0 (D64, 2026-10-08: tool-call logging for Claude agents -- audit trail per task,
  denials as events, dashboard trail; verified live).
  0.11.0 (D63, 2026-10-08: dashboard upgrade -- research view, charts, agents page,
  plain-language states, phone menu, caching/paging; live /research demo in labs/workbench: $2.53, plan saved).
  0.10.0 (D60-D62, 2026-10-08: tokens/cost/time per agent call + agent scorecards,
  project.yaml manifest export/import, sandbox profiles with secrets scrubbing; PyYAML dependency).
  0.9.0 (D58-D59, 2026-10-08: autonomy levels 0-5, generated-data guard,
  technology decisions doc, knowledge-graph entity types and typed relations).
  0.8.0 (D55-D57, 2026-10-08: research<->engineering feedback loop, engineering
  workflow with architecture/critique/security/performance reviews and release manifests, /research
  /engineer /project /director /build modes, preset claude-strengths; 204/204 tests pass).
  0.7.0 (D54, 2026-10-08: hierarchical coordination -- programmes planned and
  reviewed by a Research Director, engineering split into specialty tasks by an Engineering Director,
  specialist routing <stage>@<specialty>; `autolab programme`, dashboard Programmes view).
  0.6.0 (D53, 2026-10-08: knowledge plane K1 -- graph over lab ledgers, prior
  knowledge in research stages, verified lab sources, projects spawned from open questions; the nine
  architecture documents in docs/; F11 Gemini sandbox fix). 0.5.0 (D52, 2026-10-08: agent registry -- any backend/model on any stage via
  [allocation]/agents.toml, `autolab agents`, organisation preset from the master prompt; dashboard
  vocabulary from /api/meta, Agents page edits agents and allocation; docs/ROADMAP.md).
  0.4.0 (D51, 2026-10-08: domain-general research -- item-level analysis
  for LLM/agent/code benchmarks, transient-failure retries, parallel trials, spend cap, pinned data;
  see docs/ARCHITECTURE.md 8a). Before that: 0.3.0 + statistics + design-convergence fixes + independent-reviewer
  option (D29); 111/111 passed 2026-10-05 (14 min) + 2 reviewer tests. robolab: 223/223 tests pass on main 8d04f05 (2026-10-05 review).
- **Phase:** carrying out the mandate in labs/robolab. Lab validation PASSED (pilot-004).
  Gate 0 PASSED (D26); Gate 1 in progress (G1-1 merged; G1-2 halted on a Claude usage limit).
  North star: one generalised brain for any MHS-described body (D28).
- **Agents:** ChatGPT scientist via `codex exec --sandbox read-only`; Claude engineer
  via `claude -p`; Codex verifier via `codex exec --sandbox workspace-write`.

## Reference documents

- `PROMPT.txt` (repo root): the master prompt; alignment audit in `docs/PROMPT_ALIGNMENT.md`.
- `docs/ARCHITECTURE.md`: entry point to the lab's nine architecture documents (research, engineering,
  agent, knowledge, experiment, security, implementation plan, roadmap) -- D53.

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

### In Progress (checked 2026-10-08)
- [ ] APR-0006 REJECTED 2026-10-08 (claude-code): candidate committed 59 `.scratch/` files. Engineer patched
      (5af4ad2); the cleaned candidate returns to the safety gate -> run the FULL kernel review there (fault
      injection: Puck2D + Car2D MHS, latency 0-1 s, clamp/reject, adversarial policies, lying estimator, slippery
      patches vs declared braking, liveness). robolab runs on preset claude-strengths.
- [x] robolab autonomy_level = 5 set 2026-10-08 (queue stopped; delegation to claude-code verified).
- [ ] D65/D66 MINIMUM VIABLE BRAIN (docs/MVB.md): APR-0007 approved (G1-6 safe in simulation; disturbance
      margin G1-9 required before hardware). Queue running: merge G1-6 (= Gate 1 complete) then MVB-1 (S1 predictive
      controller). Next: MVB-2 = E1 experiment (MVB vs PD vs random, both bodies).
- [ ] robolab Gate 1 in progress (D50): Codex kept as primary; Gemini (gemini-3.8-flash-high via
      gemini-cli / agy) configured as automatic backup on usage limit. G1-6 (PRJ-0013) redesign built
      (84f6a44) and tests passed; waiting at adversarial review. Resuming with
      `autolab queue labs/robolab docs/gates/gate1_queue.toml`. Split plan for G1-6 also ready:
      docs/gates/g1_6_split.toml.
- [ ] AUTOPILOT not running. Unattended reviews need headless sessions without approval prompts; Claude Code
      will not configure that itself (classifier: Create Unsafe Agents). The human may make the one-line change
      in scripts/autopilot.py (see the 2026-10-06 conversation) and start it; until then reviews are interactive.
      Manual resume: `.venv/Scripts/autolab.exe status labs/robolab`; `autolab approvals`;
      `autolab queue labs/robolab docs/gates/gate1_queue.toml [--retry G1-x]`.
- [x] GitHub backup DONE 2026-10-06 (D38): private repos github.com/nyashamasendeke02-art/LAB1
      (main) and github.com/nyashamasendeke02-art/robolab (all 29 branches). Push after each
      commit/gate. Not in git: labs/robolab/.autolab (ledger DB, artifacts) - backup TODO.

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
       G1-2 DONE (PRJ-0009), G1-3 kernel v1.1 DONE (PRJ-0010),
       G1-4 ground-truth isolation DONE (PRJ-0011), G1-5 MHS v0 DONE (PRJ-0012). G1-6 Car2D (PRJ-0013)
       built, waiting at adversarial review (status checked 2026-10-08; no queue process running).

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
5b. [x] autolab: agent usage limits wait and retry instead of HALT (D35).
5d. [x] D52: agent registry + stage allocation + config-driven dashboard (see roadmap).
5e. [x] D53: nine architecture docs (docs/ARCHITECTURE.md is the index) + K1 knowledge plane.
5f. [x] D54: hierarchical coordination (ROADMAP phases 1 and 4).
5i. [x] D60-D62: observability + scorecards, project manifest, sandbox profiles. Still open: tool-call logging
       for Codex/Gemini (Claude done, D64), containers/GPU (s.9; no Docker/GPU on this PC), deployment plane, Author/Robot/... entities.
5h. [x] PROMPT.txt gaps 1-6 closed (D55-D59): feedback loop, engineering workflow, modes, autonomy levels,
       technology decisions, knowledge vocabulary. Remaining (PROMPT_ALIGNMENT.md): project manifest
       (s.15/16), observability tokens/cost/GPU (s.20), containers/GPU execution (s.9), tool/sandbox
       profiles (s.18/19), deployment plane.
5h-old. Close PROMPT.txt gaps in docs/PROMPT_ALIGNMENT.md order: 1 research<->engineering feedback (s.12,
       mandatory), 2 engineering workflow stages (s.11/27/30), 3 slash workflows (s.26-30), 4 autonomy
       levels, 5 technology decision doc, 6 knowledge vocabulary, ...
5g. [ ] Next ROADMAP phases: 2 agent scorecards, 3 release bundles, 5 verified external
       literature, 6 semantic knowledge; parallel projects within a programme.
5c. [x] D51: autolab can run AI/LLM/agent/software research (item unit, retries, cost cap,
       data pinning, domain prompts). Next: a first LLM pilot lab to validate it live (todo 8).
6. [ ] Citation verification step (more important now: LLM/AI literature moves fast and the
       scientist has no web access) for background research (mark as verified
       or unverified with the method used).
7. [ ] Start the Developmental Intelligence EXP-001 project in a dedicated lab.
8. [ ] LLM pilot lab (positive control, like pilot-004): e.g. "does few-shot prompting raise
       exact-match accuracy over zero-shot on a fixed 50-item arithmetic set" with unit=item, run
       through a CLI model. Needs a model the trials may call (see Human tasks).

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

- **Decide the verifier backend (F10):** ChatGPT Plus for Codex, a Claude-based verifier, or wait until 2026-11-03.
  The verifier's last call (2026-10-07) failed on the Gemini backup too ("Individual quota reached", reset
  ~16 h later), so both providers were exhausted then; the Gemini quota has probably reset by now. Since D52 a Claude verifier is one command:
  `autolab agents labs/robolab set claude_verifier --backend claude-cli --title "Verification Engineer"`
  then `autolab agents labs/robolab allocate verify claude_verifier` (same model family as the engineer, so
  less independent; your call).

- **Live-probe Gemini's sandbox (F11)** when its quota allows: one verifier call on robolab. If agy's
  `--sandbox` blocks worktree edits on Windows, the backup verifier will fail visibly.
- Nothing blocking: the lab runs unattended (D35).
- Before Gate 7 (hardware): a human safety review of the Safety Kernel, and G1-9 (declared disturbance
  margin; APR-0007 found a sustained push + external impulse can exceed the workspace by up to 0.14 m).
- By Gate 5: local vs cloud LLM for System 2.
- For LLM/agent research: decide which models experiments may call and who pays (an API key with
  a spending limit, or the existing Claude/Codex/Gemini subscriptions, which share limits with the lab's
  own agents). Default spend gate: 20 USD per run (limits.max_cost_usd_without_approval).
- Any time: change the D32 requirement defaults (target compute, adaptation budget, task family).
