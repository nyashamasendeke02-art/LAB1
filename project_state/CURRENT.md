# Current State — Autonomous Research Lab (LAB1)

## Phase
Lab infrastructure v0.1.0 built and tested with scripted agents.

## What exists (verified 2026-10-04)
- `src/autolab/`: store/ledger/artifacts, research + engineering state machines,
  agent protocol and backends, worktree manager, experiment engine, gates,
  memory/trace/export, report builder, controller, CLI, offline demo.
- `tests/`: 56 tests covering every subsystem plus end-to-end controller scenarios.
- Offline demo (`autolab demo`) completes a full cycle: SUPPORTED (exploratory)
  for the momentum toy question, with a review-requested redesign and a
  verifier-caught bug that gets patched.

## Evidence labels
- ENGINEERING_DECISION: architecture in docs/ARCHITECTURE.md.
- EXPERIMENTAL_RESULT (infrastructure only): scripted end-to-end runs pass.
- The demo's "supported" outcome demonstrates the machinery; the scripted
  agents' content is hard-coded, so it is not evidence of autonomous research ability.

## Not yet done
- No full live autonomous run with ChatGPT/Claude/Codex (only one-stage smoke
  tests of the claude-cli and codex-cli adapters).
- Not yet connected to the Developmental Intelligence research program (EXP-001).
