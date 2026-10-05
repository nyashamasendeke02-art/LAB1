# PROJECT_STATE — Autonomous Research Lab (`autolab`)

_Source of truth for status and priorities. Detail lives in `docs/ARCHITECTURE.md`
and `project_state/` (decisions, failures, open questions)._

## Status

- **Version:** 0.1.0 (commit `e4a1398`), 56/56 tests passing.
- **Phase:** live pilots. pilot-001 HALTED (architectural flaw F4, fixed by D8).
  **pilot-002 running in the background**: it passed DESIGN on the first try and is
  now in SCIENTIFIC_REVIEW. Log: `labs/pilot-002-run.log`.
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
- [ ] Full suite run after the ledger-anchoring change (anchor + store tests pass;
      the full run was in progress when the session ended).

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

- No full live run has completed yet; real-agent schema compliance is unproven.
- The verifier sandbox (codex workspace-write) can read outside its worktree.
- The ledger is anchored in git commit trailers; rewriting both the DB and git is still possible.
- Statistics are an unpaired bootstrap of means only.
- Background-research citations are unverified (`sources_verified: false`).
- The full test suite takes ~5 min on Windows (subprocess/git heavy); there is no fast subset marker.
- The `project_state/*.md` written by hand in LAB1 and the generated per-lab
  `project_state/` share a name; the per-lab files are generated, the LAB1 ones are not.

## Human tasks (only what Claude cannot do)

- None right now. If the pilot blocks on an approval gate, it will appear here
  with the exact command.
