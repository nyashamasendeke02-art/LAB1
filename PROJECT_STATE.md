# PROJECT_STATE — Autonomous Research Lab (`autolab`)

_Source of truth for status and priorities. Detail lives in `docs/ARCHITECTURE.md`
and `project_state/` (decisions, failures, open questions)._

## Status

- **Version:** 0.1.0 (commit `e4a1398`), 56/56 tests passing.
- **Phase:** live pilots. pilot-001 HALTED (F4, fixed by D8). pilot-002 ran the first
  full live pass (RUN-0001: INCONCLUSIVE, paired effect -0.00008 MSE, CI [-0.00075, 0.00059]),
  then redesigned twice; the review exposed lab gaps that are now fixed (D11-D13).
  **pilot-002 RESTARTED 2026-10-04** (4.5 GB RAM free) from DESIGN, cycle 1; running in
  the background, log: `labs/pilot-002/run-2026-10-04b.log`.
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

- Keep this Claude Code session and the PC open while pilot-002 runs, and avoid heavy apps
  (the previous run was killed under memory pressure).
- Progress check: `PYTHONPATH=src python -m autolab.cli status labs/pilot-002`
