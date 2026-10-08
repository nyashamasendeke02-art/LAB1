# Agent OS roadmap: master prompt vs autolab

Status 2026-10-08 (D52). The master prompt ("Autonomous Research & Engineering Lab", an
*Agent Operating System for Research and Engineering*) arrived in fragments: sections 2-6 are
partly present (core principle, the five planes, the agent runtime, research agents, engineering
agents up to "Data Engineer"), and later sections appear only as stray bullets ("energy",
"reliability", "observable", "replayable where possible"). This document maps what arrived onto
what autolab already does, so later work extends the system instead of rebuilding it.

Labels: **done** (implemented and tested), **partial**, **gap**.

## Core principle: shared substrate, structured artifacts and events

| Master prompt asks for | autolab today |
|---|---|
| Agents communicate through structured artifacts and events, not chat context | **done**: TaskPacket in, schema-validated Completion out; no conversational memory (messages.py) |
| Shared knowledge, memory, artifacts, tasks, experiments | **done**: versioned records, typed memory views, content-addressed artifacts (store.py, memory.py) |
| Provenance | **done**: hash-chained ledger, git trailers, lineage trace from conclusion to raw data |
| Permissions | **done**: per-stage roles, path policies, hermetic CLIs, sandboxed writes, tamper check |
| Event streams | **partial**: append-only ledger events and SSE to the dashboard; no agent-side subscription |
| Tools, environments | **partial**: per-backend tools; experiment environments are Python entrypoints only |
| Evaluation systems | **done** for experiments (pre-registered analysis); **gap** for evaluating agents themselves |

## Agent runtime (section 4)

| Capability | Status |
|---|---|
| Identity, roles, goals, task execution | **done**: named agents (D52), roles fixed per stage, task packets |
| Replaceable agents, no single model provider | **done**: claude-cli, codex-cli, gemini-cli, openai-api; any agent on any stage (D52); automatic backup backend on usage limits (D50) |
| Retries, checkpoints, failure recovery | **done**: stage retries, usage/network waits, HALT/resume, crash recovery, patch -> redesign -> rethink |
| Observability | **done**: dashboard (D48/D49/D52), handoff files per task, ledger |
| Planning, context management | **partial**: the controller plans (state machines); agents do not plan multi-step work |
| Inter-agent communication | **partial**: only through records the controller hands on; no direct messages (by design) |
| Agent evaluation | **gap**: no scorecard per agent/model (acceptance rate, rework, cost) |

## Research agents (section 5)

Created by `autolab agents LAB preset organisation`, each allocated to the controller stages it
covers (src/autolab/registry.py `ORGANISATION`):

| Agent | Stages | Notes |
|---|---|---|
| Research Director | define_problem, next_question | **partial**: does not yet run several projects as a programme |
| Literature Agent | background_research | **partial**: no web/paper access; citations are unverified (todo 6) |
| Research Gap Agent | research_question | done within one project |
| Hypothesis Agent | hypothesis | done |
| Experiment Designer | design | done (protocols, controls, baselines, metrics, datasets via data_paths) |
| Scientific Critic | scientific_review, scientific_validation | done; challenge stays with the verifier for independence |
| Research Synthesizer | interpret, communicate | **partial**: per-project; no cross-project synthesis or knowledge graph |

## Engineering agents (section 6)

| Agent | Status |
|---|---|
| Engineering Director | **gap** (the controller's engineering state machine plays this role) |
| Requirements Agent | done (requirements stage) |
| Systems Architect | done (solution_design) |
| AI Architect, Backend, Frontend, ML Engineer, Algorithm Engineer, Data Engineer, Simulation Engineer | **gap** as separate agents: today one Implementation Engineer covers every build. Next step below |

## Planes

| Plane | Status |
|---|---|
| Research | done (research state machine) |
| Knowledge | **partial**: records + lineage; no knowledge graph across projects, papers or models |
| Engineering | done (engineering state machine, adversarial review, gates) |
| Experimentation | done for simulation/benchmarks (D51: item-level, retries, cost); no training jobs/GPU scheduling, no hardware-in-the-loop |
| Deployment | **gap** |

## Next phases (proposed, in order)

1. **Specialist engineering agents.** Engineering tasks name a specialty (backend, frontend, ML,
   data, simulation, algorithm); the allocation becomes stage x specialty -> agent. Small change
   on top of D52.
2. **Agent scorecards.** Per agent and model: calls, protocol rejections, review findings caused,
   rework, wall time and cost; shown on the Agents page. Needed to choose models on evidence.
3. **Knowledge plane.** A cross-project graph of claims, results, methods and failures with
   their provenance, queried by the Literature and Synthesizer agents.
4. **Programme level.** A Research Director that runs several projects as one programme
   (decompose, schedule, track blockers), on top of the existing queue.
5. **Literature access.** Verified sources (web or paper search behind a controller-run fetch,
   so the scientist stays read-only and citations get a verification status).
6. **Deployment plane.** Only after Gate 7's human safety review for anything physical.

The rest of the master prompt (sections after "Simulation Engineer") is needed before phases 3-6
are designed in detail.
