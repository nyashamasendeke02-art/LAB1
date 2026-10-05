# PROJECT_STATE — Autonomous Research Lab (`autolab`)

_Source of truth for status and priorities. Detail lives in `docs/ARCHITECTURE.md`
and `project_state/` (decisions, failures, open questions)._

## Status

- **Version:** 0.1.0 (commit `e4a1398`), 56/56 tests passing.
- **Phase:** live pilots. pilot-001 HALTED (F4, fixed by D8). pilot-002 ran the first
  full live pass (RUN-0001: INCONCLUSIVE, paired effect -0.00008 MSE, CI [-0.00075, 0.00059]),
  then redesigned twice; the review exposed lab gaps that are now fixed (D11-D13).
  **pilot-002 STOPPED 2026-10-04 at the human's request** (still DESIGN, cycle 1, no data).
  **No experiments until the code review's blocking findings (R1-R5 below) are fixed.**
- **Agents:** ChatGPT scientist via `codex exec --sandbox read-only`; Claude engineer
  via `claude -p`; Codex verifier via `codex exec --sandbox workspace-write`.

## High-level goals

1. A lab that takes "Investigate whether X can produce Y" through research →
   engineering → experiment → evaluation → iteration → report → next question,
   with full provenance. **(built; validated offline only)**
2. Prove it works with real agents on a small objective (live pilot).
3. Use it for the Developmental Intelligence first milestone: a minimal predictive
   agent baseline (HYP-001 / EXP-001), as a confirmatory pre-registered protocol.

## Todo

### In Progress
- [ ] Code review 2026-10-04 (no experiments meanwhile). Fix order: R1, R2, R3, R4, R5, then R6-R12.
- [ ] pilot-002: check the outcome (`autolab status labs/pilot-002`, the log, the report);
      fix and record anything it exposes.
- [ ] Full suite run after D13 (68/68 passed up to D12; D13's targeted tests pass).

### Next (priority order)
1. [ ] Fix whatever the live pilot exposes (schema compliance, sandbox behaviour,
       timeouts); add regression tests for each.
2. [x] `autolab amend` CLI: recorded protocol amendments; amending after data
       collection auto-downgrades confirmatory to exploratory.
3. [x] Progress visibility: `autolab watch` / per-step log lines with the agent
       and elapsed time.
4. [~] Statistics: paired bootstrap DONE; still to do: (shared seeds), power/sample-size check at
       scientific review, Holm correction for multiple contrasts.
5. [x] Ledger anchoring: commit the ledger head hash into the research repo
       at each merge/run.
6. [ ] Citation verification step for background research (mark as verified
       or unverified with the method used).
7. [ ] Start the Developmental Intelligence EXP-001 project in a dedicated lab.

### Done
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

### Code review 2026-10-04 (blocking = must fix before any run)
- R1 BLOCKING: `protocol.fixed_params` is never passed to the entrypoint (run_trial sends only
  conditions[].params), so "frozen" parameters are whatever the engineer hard-coded.
- R2 BLOCKING: engineer-controlled conftest.py / pytest.ini / pyproject can silently skip
  tests/verification (demonstrated: `collect_ignore_glob` -> exit 0, verifier test never ran).
  The merge gate checks only that test files exist and the exit code is 0.
- R3 BLOCKING: percentile bootstrap undercovers at small seed counts (simulated 95% CI coverage:
  3 seeds 0.76, 5 seeds 0.86, 10 seeds 0.88, 20 seeds 0.91) -> false "supported" rate well above alpha.
- R4 BLOCKING: SCIENTIFIC_VALIDATION scientist gets no code or diff (no workdir), only the
  verifier's verdict and smoke metrics; it cannot check protocol fidelity.
- R5 BLOCKING: agents inherit uncontrolled context: `claude -p` loads Desktop/CLAUDE.md, user
  plugins/skills/MCP servers (also a likely memory-pressure source, INFERENCE); codex loads
  ~/.codex config/plugins/memories. Tasks must be hermetic.
- R6: inconclusive -> redesign of the same hypothesis with knowledge of the effect (optional
  stopping); no multiplicity accounting across design iterations.
- R7: schemas allow unknown keys; a misplaced key (e.g. `pairing` at top level) is silently
  dropped and defaults apply.
- R8: on ProtocolError the raw agent responses are discarded (only stored on success).
- R9: Windows timeouts kill codex.CMD's cmd.exe but not its node child (orphans).
- R10: stage-retry counter for ENGINEERING spans all sub-steps; unrelated transient errors add up.
- R11: engineer/verifier see the hypothesis and expected direction (no blinding).
- R12: engineer `Bash(python:*)` is unsandboxed (can write lab.db, main checkout, other
  worktrees); isolation is advisory except for codex sandboxes. Crashed runs leave stale
  worktrees under worktrees/readonly.

### Older items

- No live cycle has reached COMMUNICATE yet; every real-agent stage has worked at least once.
- Killing the controller orphans agent subprocesses (codex/claude are not killed with it).
- The scientific review missed min_effect=0 and an under-trained baseline. These are now
  mechanical or prompt rules, but reviewer depth remains an open question.
- The verifier sandbox (codex workspace-write) can read outside its worktree.
- The ledger is anchored in git commit trailers; rewriting both the DB and git is still possible.
- No power analysis or multiple-comparison correction yet.
- Background-research citations are unverified (`sources_verified: false`).
- The full test suite takes ~5 min on Windows (subprocess/git heavy); there is no fast subset marker.
- The `project_state/*.md` written by hand in LAB1 and the generated per-lab
  `project_state/` share a name; the per-lab files are generated, the LAB1 ones are not.

## Human tasks (only what Claude cannot do)

- Decide: approve fixing R1-R5 (then R6-R12) before any further experiment.
