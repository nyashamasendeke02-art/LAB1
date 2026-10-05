# Autonomous Research Lab (`autolab`)

A controller-owned research + engineering loop with three AI agents:

* **ChatGPT — Research Scientist** (problem, background, question, hypothesis,
  requirements, experimental design, review, interpretation, next question)
* **Claude — Engineer** (solution design, implementation, tests, redesign)
* **Codex — Verifier** (adversarial code review, independent tests, challenge
  of results)

The **controller**, not any LLM, owns the authoritative state. It dispatches
schema-validated task packets and gives each agent an isolated git worktree. It
commits agents' work with provenance trailers, runs the tests itself, merges
under controlled conditions, executes pre-registered experiments from the exact
merged commit, computes outcomes mechanically, enforces human approval gates,
and records everything in an append-only, hash-chained ledger.

```text
research → hypothesis → requirements → design ⇄ scientific review → freeze protocol
→ implement → test → adversarial review (fail → patch → redesign → rethink design)
→ scientific validation → run → analyse → challenge → meets requirements?
   ├─ no  → back to Brainstorm/Evaluate/Choose (DESIGN)
   └─ yes → communicate → next research question → …
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design: system,
agents, both state machines, the communication protocol, worktrees,
provenance, the experiment and memory models, the control loop, gates, and the
plan.

## Quick start

```bash
pip install -e .[dev]            # or: set PYTHONPATH=src
python -m pytest                 # full test suite

# Offline demo with scripted agents (no LLM calls): full loop incl. a
# review-requested redesign and a verifier-caught bug that gets patched.
autolab demo ./demo-lab
cat ./demo-lab/reports/PRJ-0001-cycle1.md

# Real lab
autolab init ./lab               # edit ./lab/lab.toml to pick backends/models
autolab new ./lab "Investigate whether X can produce Y"
autolab run ./lab                # runs until COMPLETE, HALTED, or an approval gate
autolab status ./lab
autolab approvals ./lab
autolab approve ./lab APR-0001 --note "pre-registration OK"
autolab run ./lab
autolab trace ./lab CON-0001     # conclusion → result → run → commit/protocol/env/prompts
autolab verify ./lab             # ledger hash chain + artifact integrity
autolab resume ./lab PRJ-0001 --note "fixed backend"   # after HALTED
```

Backends: `claude-cli` (Claude Code headless), `codex-cli` (Codex CLI; also
used read-only as the ChatGPT scientist via your ChatGPT login), and
`openai-api` (needs `OPENAI_API_KEY`). Requires Python ≥ 3.11 and git; the CLI
backends need `claude` / `codex` on PATH.

## Lab layout

```text
lab/
  lab.toml                 configuration (backends, budgets, gates)
  .autolab/lab.db          authoritative state (records + hash-chained events)
  .autolab/artifacts/      content-addressed, read-only artifacts
  .autolab/handoffs/TASK-* task packet, prompt, completion per agent call
  repo/                    research code (main = integration branch)
  worktrees/               per-agent, per-task checkouts (temporary)
  runs/RUN-*/<cond>/seed-*/ raw experiment data (read-only)
  reports/                 per-cycle reports with provenance traces
  project_state/*.md       generated human-readable state
```

## Integrity guarantees (tested)

* Records are append-only and versioned; frozen protocols change only through
  recorded amendments; the ledger is hash-chained (tampering is detected).
* Engineers cannot edit protocols or verification tests; verifiers cannot edit
  the implementation. Violations are reverted and recorded.
* No merge without controller-run tests plus an independent review; a critical
  finding blocks the merge even if the verdict says "pass".
* The decision rule is applied by the controller. Agents cannot assert
  EXPERIMENTAL_RESULTs for runs that do not exist.
* Invalid experiments draw no conclusion. Unsupported hypotheses are recorded
  as results, not failures. Hypotheses are never auto-upgraded to ESTABLISHED.
* Protected experiments, confirmatory pre-registrations and large compute
  budgets need human approval. Only a human can approve or resume.
* Repeated engineering failure forces a redesign, then escalation back to
  research design. It never patches indefinitely.
* Failed experiments, designs, branches and implementations are retained.

## Status

The scripted end-to-end loop works and is tested. The live `claude-cli` and
`codex-cli` adapters have each passed a single-stage smoke test, but **a full
live autonomous run has not yet been performed**. Start with an unprotected,
exploratory objective and watch the first cycle.
