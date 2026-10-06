# Decisions (ENGINEERING_DECISION)

- D1: The controller owns state in SQLite with append-only versioned records and a
  hash-chained event ledger; agents never touch it.
- D2: Research and engineering are separate state machines with whitelisted transitions.
- D3: Outcomes are computed mechanically from a pre-registered decision rule;
  LLMs interpret but cannot change them.
- D4: One git worktree and branch per agent task; the controller commits and
  merges; path policies are enforced on diffs; branches are never deleted.
- D5: Patch budget leads to forced redesign, then escalation to research DESIGN
  (no indefinite patching).
- D6: An engineer "no changes" response is allowed but always re-verified by
  controller tests and an independent review (added after tests exposed false
  failures in legitimate cases).
- D8: Structured validity/success checks live in the protocol (written at DESIGN,
  frozen with the pre-registration); the REQUIREMENTS stage is prose. (The live
  pilot showed requirements cannot reference conditions that do not exist yet.)
- D9: Amendments are human-only, require HALTED, downgrade confirmatory→exploratory
  after data, and force re-verification via a new engineering task.
- D10: Paired bootstrap is an opt-in `pairing` field of the frozen decision rule.
- D7: The default ChatGPT scientist backend is the Codex CLI in read-only mode,
  because no OPENAI_API_KEY is configured; the openai-api backend is available.
- D11: Merge requires >= 1 independent verifier test (tests/verification/test_*.py).
  A missing test is retried as the verifier's stage error and never charged to the
  engineer. (pilot-002: Codex passed the review without writing any tests.)
- D12: decision_rule.min_effect must be > 0 (smallest effect size of interest);
  prompts require a "baseline actually learns" validity check. (pilot-002 RUN-0001:
  min_effect=0 made a tight null CI permanently 'inconclusive'; all arms had weight
  error ~0.286, i.e. under-trained, which the 'finite/completed' checks did not catch.)
- D13: Checks may use relative_to=<condition> (aggregate of per-seed differences); protocols
  may carry fixed_params, and every reproduction-relevant parameter must be frozen there.
  (pilot-002 review: the scientist could not express a paired-difference success check and
  produced an impossible "mean MSE < -0.001"; operational details were left in prose.)
- D14 (code review 2026-10-04, R1/R7): every trial gets `--params` = protocol.fixed_params merged
  with conditions[].params (overlapping keys are invalid). Protocol objects are closed schemas
  (additionalProperties: false): unknown or misplaced keys are rejected, never defaulted.
- D15 (R3, supersedes D10's bootstrap): decision CIs are Student t (paired) / Welch t (unpaired),
  and every protocol needs >= 3 seeds. EXPERIMENTAL_RESULT (simulation in this session): percentile
  bootstrap 95% CIs covered 0.76 / 0.86 / 0.88 / 0.91 at 3 / 5 / 10 / 20 seeds; t intervals are
  within 0.93-0.97 at 3 and 5 seeds (regression test). The analysis version is now 0.2.0.
- D16 (R2): verifier tests are also run hermetically by the controller (`python -P -E -B -m pytest
  --noconftest`, controller ini, no PYTEST_ADDOPTS) and merge requires a JUnit report with >= 1 pass,
  0 failures, 0 errors. The engineer's own pytest config can no longer hide them.
- D17 (R4, R11): scientific validation runs in a read-only checkout of the merged commit and gets
  the diff. Engineer and verifier (verify stage) are blinded: no hypothesis, question, background,
  decision rule, success checks or earlier results, and a neutral objective. Blinding is partial:
  condition names and the protocol title can still hint at the hypothesis.
- D18 (R6): a redesign may not reuse seeds already used to test the same hypothesis, and every
  conclusion records its look number; only a first look can be confirmatory. Later looks are
  labelled "exploratory; look k, not corrected for multiple looks".
- D19 (R5, R8, R9, R10, R12): agent CLIs run hermetically (claude: no setting sources, no MCP,
  no skills, no auto-memory; codex: --ignore-user-config/--ignore-rules, plugins/apps/browser/
  computer-use/memories disabled). Agent, test and trial subprocesses run in a kill-on-close job
  (Windows) or a process group (POSIX). Rejected agent responses are stored. ENGINEERING stage
  retries are counted per engineering sub-step and reset on progress. After every agent call
  the controller checks main HEAD/clean, ledger head + chain and lab.toml; a change HALTs the
  project (integrity_violation, never retried). Transient worktrees left by a crash are removed
  at the start of `run`.
- D20 (2026-10-04, human): AI_Robotics_Full_Documentation.pdf is the foundation of this lab:
  the research mandate and the engineering mandate. Digest and reconciliation with CLAUDE.md:
  docs/MANDATE.md. The mandate sets the direction (H1-H5, E1-E6, gates 0-8, REQ-*, ADR-001..005);
  CLAUDE.md sets the method. Every component is earned by an experiment against its ablation;
  sequencing is Gate 0 (contracts) -> Gate 1 (simulation) -> E1 (S1 baseline), which is
  CLAUDE.md's first milestone. The Safety Kernel is never a research variable.
- D21 (2026-10-04, human -> Claude Code): full control delegated ("100% in control ... start it end
  to end, utilising the lab"). Claude Code decides the PROJECT_PLAN section 10 items:
  (1) plan adopted as the programme baseline; (2) repo strategy A, a single lab `labs/robolab`
  whose repo is the robot-brain code; (3) EnvA = Puck2D; (4) budgets: trial timeout 300 s, at most
  200 trials per study, one active agent run at a time; (5) pilot -> one confirmatory study per
  hypothesis; (6) no remote backup (pushing still needs explicit human approval). Gate decisions
  taken under this delegation are recorded as decided_by="claude-code" with delegated_by="human",
  never as the human. Acceptance of major scientific conclusions stays flagged for the human.
- D22: P0 sequencing (smallest justified change). Before the validation run: L1 engineering track,
  L2 path gates + recorded delegation, L3 resource metering, L6 pilot->confirmatory, L7 mandate
  refs + lab charter in scientist context, L8 output cap, L9 dependency lock check. L4
  (non-inferiority / co-primary / Holm) and L5 (power) come before the first confirmatory study or
  E3. L10 (citation verification) is deferred: sources stay `sources_verified: false`.
- D23 (2026-10-05, claude-code): L4/L5 implemented before any confirmatory study (e0f95d4):
  non-inferiority rules, co-primary endpoints by intersection-union, p-values, Holm on secondary
  contrasts, and a power check that refuses underpowered confirmatory designs.
- D24 (2026-10-05, claude-code): design convergence (615d476). pilot-003 HALTED after 4 rejected
  designs because the designer rewrote each protocol from scratch and the reviewer did not know
  the fixed analysis method or run contract. The designer now revises the rejected protocol;
  both prompts state the analysis method; review 'revise' is limited to validity threats.
  pilot-003 stays HALTED as a record: `autolab resume` records the human, so under delegation a
  fresh lab (pilot-004) was used instead.
- D25 (2026-10-05, human): Codex verifier gets `-c windows.sandbox="elevated"` for writable tasks
  (hermetic mode had made it read-only). The human chose this option and granted Claude permission
  to run `autolab run`. Lab validation then PASSED: pilot-004 positive control SUPPORTED.
- D26 (2026-10-05, claude-code): GATE 0 PASSED in labs/robolab. G0-1 contracts (DLV-0001),
  G0-2 telemetry (DLV-0002), G0-3 Safety Kernel v1 (DLV-0003), G0-4 cycle runner (DLV-0004); 186
  tests on main; contracts and safety reviews by claude-code with independent checks (APR-0001,
  APR-0002); audited that Environment.actuate only receives KernelResult.actuator_command. Known
  limitation carried to G1-3: one-step workspace lookahead with a zero-force safe action.
  Deviation from D21(4): pilot-004 and robolab G0-1 ran in parallel for ~15 min on 2026-10-05
  (no shared state; both completed correctly). Back to one active run at a time.
- D27 (2026-10-05, claude-code under delegation; human: "no preference"): the simulation's role
  is to teach the robot physics through consequences only. Keep WM-1 as planned (integrator +
  learned residual; fully learned model as ablation) and add: (a) G1-4 ground-truth isolation,
  brain modules see only observations and their own actions, enforced by test; (b) online
  mass/friction estimation in World Model v1, scored on change-detection latency (links H3);
  (c) a later WM-2: self-directed exploration vs passive logged data, by prediction-error
  learning curve. Learn-from-scratch stays a comparison condition, not the default (mandate:
  "physics-informed", "compared progressively with more learned physics").
- D28 (2026-10-05, human direction; plan changes by claude-code): GOAL: one generalised brain that
  runs any body described by a Model Hardware Standard (MHS): RC car, humanoid, self-driving car.
  Labelled HYPOTHESIS (cross-embodiment generality is an open problem); it is the mandate's
  long-term direction (embodiment-agnostic brain, H5, ADR-005) made concrete. Plan changes:
  G1-5 MHS v0 (body description; Safety Kernel configured from it), G1-6 Car2D second body,
  both in Gate 1 so no component is designed against one body. Expectation set: "figure out"
  = the same brain code learns a new body quickly from its MHS and its own experience, not
  zero-shot competence; fast body-specific reflexes (balance, motor loops) may live below
  the adapter and are declared in the MHS. Real vehicles stay deferred (Gate 7, human decision).
- D29 (2026-10-05, claude-code): optional independent reviewer: `[agents.reviewer]` in lab.toml
  runs the listed stages (default scientific_review) on a different backend from the designing
  scientist (OPEN_QUESTION 2). Disabled by default; the reviewer's backend/model is recorded on
  each task. Tests: test_independent_reviewer_runs_scientific_review, test_reviewer_disabled_by_default.
- D30 (2026-10-05, review): the Safety Kernel must not depend on the brain's state estimate;
  it reads position/velocity from the raw Observation via the MHS (folded into G1-5). The
  harness injects the simulation clock (G1-2 spec).
- D31 (2026-10-05, review): D27 and D28 reconciled: any hand-written physics in the World Model
  must be a generic prior parameterised by the MHS (e.g. Newtonian rigid body with declared
  actuator kinds), never per-body code; otherwise the brain is not body-agnostic. Open as
  OPEN_QUESTION 13 until WM v1 is designed.
- D32 (2026-10-05, claude-code under delegation; human: "no preference" on all four): requirements
  v0.1 adopted in docs/REQUIREMENTS.md. Scope: edge-board-class target compute for the fast loop
  (Pi 5 / Jetson Orin Nano class), "figured out a new body" = fast adaptation within a fixed
  experience budget vs a tuned body-specific controller with zero safety violations, navigation as
  the first task family. New: REQ-MHS, REQ-ISO, REQ-NAV, REQ-SAFE+, REQ-SAFE-H, REQ-RT,
  REQ-COMPUTE, REQ-COST, REQ-REPRO, REQ-WM+. Hypotheses stay out of requirements. Changes only by
  recorded amendment.
- D33 (2026-10-05, claude-code): software requirements SW-* added to docs/REQUIREMENTS.md. Gaps found:
  no packaging/namespace (SW-PKG), Windows-only testing (SW-OS, SW-CI), no type/lint checks
  (SW-STATIC), kernel coverage unmeasured (SW-SAFETY-CODE), and NO REMOTE BACKUP of either
  repository (SW-BACKUP; pushing needs the human's choice of remote). Planned as G1-7 software
  baseline after G1-6.
- D34 (2026-10-05, claude-code): open-source stack mapped to the user's schematic layers in
  docs/REQUIREMENTS.md, each with licence and gate. Licence policy SW-LICENSE-DEP: permissive or
  weak-copyleft inside the brain; GPL only as separate processes/firmware; AGPL excluded. Isaac Sim
  excluded (proprietary, GPU). Nav2/MoveIt 2 used as baselines, not as the brain. Project licence
  (recommended Apache-2.0) is the human's decision.
- D35 (2026-10-05, human: "I want full agentic autonomy on this project"): the lab runs unattended.
  (a) Agent usage/rate limits no longer HALT a run: the controller records a usage_limit failure,
  waits usage_limit_wait_s (900 s) and retries without counting a stage retry, up to
  usage_limit_max_wait_s (12 h). (b) `autolab queue LAB FILE.toml` runs engineering tasks in order,
  submitted as claude-code; it stops at a HALT or an approval gate and never re-submits a HALTED
  task by itself. (c) Gate 1 queue: docs/gates/gate1_queue.toml (G1-2..G1-7). (d) Claude Code
  decides research-direction defaults, reviews gates (real reviews, evidence in the note), and
  restarts the queue. Kept with the human: physical hardware runs (Gate 7, REQ-SAFE-H), spending
  money or creating accounts, publishing or pushing to a remote, deleting research artifacts, and
  acceptance of major scientific conclusions.
- D36 (2026-10-05, claude-code): robolab G1-2 (PRJ-0008) HALTED at adversarial review: Codex 0.160's
  default model gpt-6.1-sol is "not supported when using Codex with a ChatGPT account". Probed:
  gpt-6-luna and gpt-5.6-terra both work; pinned model = "gpt-6-luna" for the scientist and verifier
  in labs/robolab/lab.toml (newest generation available to the account). Added `autolab queue
  --retry ID` to submit a HALTED task again as a fresh project once its cause is fixed (the HALTED
  project stays as a record). PRJ-0008 kept HALTED; G1-2 re-submitted.
- D37 (2026-10-06, claude-code under delegation): APR-0003 (G1-3 Safety Kernel v1.1) APPROVED after a
  real review: diff read, 268 tests pass on the branch, independent Puck2D fault injection (clamp and
  reject modes, random / push-to-wall / bang-bang, with and without damping+friction, 40 seeds x 400
  steps): never left the workspace. Confirmed limitation: a configured mass below the true mass can
  exit (2x mass: 2.452 m vs 2 m bound), so the MHS mass_kg is an upper bound. Integration gap found:
  CycleRunner calls tick()/emergency_stop() without velocity and actuates nothing on abstain, so a
  moving body would coast on hardware. Folded into the G1-5 spec (runner passes observed velocity;
  safe action actuated every cycle without an approved command) with a new acceptance criterion.
