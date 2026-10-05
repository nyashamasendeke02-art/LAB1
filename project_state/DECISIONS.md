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
