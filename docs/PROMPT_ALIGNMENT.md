# Alignment with PROMPT.txt (master prompt)

Audit of 2026-10-08 against the code at autolab 0.7.0 (D54), section by section; updated the
same day after D55-D59 (closed gaps are marked **closed (Dnn)**). Labels:
**aligned** (implemented and tested), **partial** (implemented with a named gap), **gap** (not
built). Evidence names the code or test; nothing here is claimed from documentation alone.

## Summary

| Area | Verdict |
|---|---|
| Core method: vertical slice, provenance, research <-> engineering, replaceable agents (1-6, 14, 23-25, 31-33) | aligned |
| Agent hierarchy (7) | aligned, two small gaps (programme time limit, configurable depth) |
| Knowledge graph (8) | **closed (D59)** for 16 of 24 entity types and the named relationships; Author, Simulation, Robot, Environment, Publication not yet |
| Experiment engine (9) | partial: reproducible local/simulation runs; containers/GPU **blocked on this machine** (no Docker, no NVIDIA GPU, checked 2026-10-08) |
| Evaluation engine (10) | partial: experiment evaluation is mechanical; no model/agent/algorithm/robot evaluation suites |
| Engineering workflow (11) | **closed (D56)** except deployment |
| Research <-> engineering feedback (12, "mandatory") | **closed (D55)** |
| Events (13) | partial: ledger events are generic; agents do not subscribe |
| Project structure and manifest (15, 16) | **closed (D61)** |
| Model abstraction (17) | partial: LLM backends only |
| Tools, sandboxes (18, 19) | sandboxes **closed (D62)** (six named profiles, secrets scrubbed for executed code; network not enforceable on Windows); tool-call logging still a gap |
| Observability (20) | **closed (D60)** for tokens, cost and time per call (where backends report them) and agent scorecards; tool calls and GPU not tracked |
| Autonomy levels (21) | **closed (D58)** |
| Technology decision document (22) | **closed** (docs/TECHNOLOGY_DECISIONS.md) |
| Slash workflows /research /engineer /project /director /build (26-30) | **closed (D57)**; deployment steps remain a gap |

## Section by section

| # | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 1 | Research + engineering in one loop across AI/ML/LLM/agents/algorithms/robotics/... | aligned | research and engineering state machines; D51 domain-general experiments (item unit, retries, cost); robolab for robotics |
| 1 | ... deploy systems, collect real-world observations | gap | no deployment plane, no observation records |
| 2 | Agent OS: shared knowledge, memory, artifacts, tasks, experiments, provenance, permissions; structured artifacts, not chat | aligned | controller-owned records, schema-validated completions, no conversational memory |
| 2 | ... shared tools, environments, event streams | partial | see 13, 18 |
| 3 | Five planes | partial | research, knowledge, engineering, experimentation built; deployment gap (ARCHITECTURE.md) |
| 4 | Agent runtime: identity, roles, goals, tasks, memory, permissions, artifacts, retries, checkpoints, observability, failure recovery; replaceable; provider-independent | aligned | agents.py, registry.py (D52), controller; tests/test_registry.py |
| 4 | ... planning, event subscription, inter-agent communication, evaluation | partial | directors plan (D54); agents do not subscribe to events; no agent evaluation |
| 5 | Research agents (Director, Literature, Gap, Hypothesis, Designer, Critic, Synthesizer) | aligned | preset `organisation`; each on its stages |
| 5 | Literature: discover literature, track state of the art | partial | no web or paper access; external sources unverified |
| 6 | Engineering Director, Requirements, Systems Architect | aligned | engineering_breakdown (D54), requirements, solution_design |
| 6 | Backend, Frontend, ML, Algorithm, Data, Simulation engineers | aligned | specialist routing `<stage>@<specialty>` (D54) |
| 6 | AI Architect, Robotics Engineer | partial | can be added as specialties ("robotics" is not in the default list); no AI-architecture stage |
| 6 | Security, Testing, Performance, Documentation agents | partial | Testing = verifier; Security/Performance/Documentation have no stages (see 11) |
| 7 | Hierarchy: Research Director over research agents, Engineering Director over requirements/architecture/coding/testing/deployment agents | aligned | coordination.py; tests/test_coordination.py |
| 7 | Agents create subtasks for other agents, no uncontrolled spawning | aligned | only directors create items/tasks; controller validates every plan |
| 7 | Limits: budgets, permissions, maximum depth, time limits, compute limits, task limits | partial | max_items, max_tasks_per_item, max_reviews, stage permissions, per-call/test/trial timeouts, trial and spend gates; depth is fixed at 2 (not configurable); no wall-clock limit per programme |
| 8 | Knowledge graph with 24 entity types | partial | knowledge.py indexes 12 record kinds (question, hypothesis, claim, design, protocol, result, conclusion, failure, future question, delivery, problem, background). Missing as entities: Paper, Author, Method, Algorithm, Dataset, Model, Agent, ExperimentRun, Metric, Architecture, Requirement, CodeArtifact, SoftwareComponent, Simulation, Robot, Environment, Observation, Publication |
| 8 | Typed relations (supports, contradicts, motivates, tested_by, ...) | partial | edges carry the ref name (result, hypothesis, protocol, conclusion, ...), not this vocabulary; no supports/contradicts between results |
| 8 | Provenance for every important artifact | aligned | hash-chained ledger, lineage trace |
| 9 | Experiment record with id, question, hypothesis, objective, method, baseline, variables, dataset, model, environment, configuration, code version, hardware, metrics, seed, results, evaluation, conclusion, provenance | partial | all present but spread over protocol, run, result and conclusion records; no single experiment view; hardware only as the platform string |
| 9 | Reproducible | aligned | frozen protocols, exact commit, lock check, data hashes, seeds |
| 9 | Local / containerized / GPU / distributed / simulation / hardware-in-loop | partial | local and (Python) simulation only |
| 10 | Evaluation of models, agents, algorithms, robots; results in the knowledge system | partial | pre-registered experiment evaluation; results are in the ledger and graph; no evaluation suites per subject; no agent scorecards |
| 11 | Workflow: result -> requirements -> architecture -> critique -> implementation plan -> implementation -> testing -> security -> performance -> integration -> evaluation -> deployment | partial | requirements, solution_design (research track), implementation, testing, adversarial review, integration (merge), evaluation exist; architecture critique, implementation plan, security review, performance review, deployment do not; engineering track has no architecture stage |
| 11 | No major implementation without a machine-readable architecture and requirements spec | partial | requirements are machine-readable; architecture is free text in solution_design, absent on the engineering track |
| 12 | Engineering failures become research observations -> questions -> hypotheses -> experiments (mandatory, explicit) | **gap** | failures are recorded and searchable (K1) and the programme review sees halts, but no mechanism turns an engineering failure into an observation and a research question |
| 13 | Event system with domain events; agents react | partial | ledger events (record.created/updated, task.dispatched, *.transition, gate.*); not the named domain events; no subscriptions |
| 14 | Universal artifacts with id, version, owner, type, provenance, dependencies, timestamp, status | aligned | store.py records + content-addressed artifacts |
| 15 | Executable, machine-readable project structure (project/, research/, architecture/, ...) | gap | projects live in the ledger and the research repo |
| 16 | project.yaml manifest | gap | |
| 17 | ModelProvider / LLM / Embedding / Vision / Reasoning / AgentModel; local and remote | partial | AgentBackend over claude-cli, codex-cli, gemini-cli, openai-api; no embedding or vision providers; no local model backend |
| 18 | Unified tool interface; every call permission-controlled, logged, attributable, observable, replayable | partial | tools are those of each CLI, restricted per stage; prompts and responses are logged per task, individual tool calls are not |
| 19 | Sandbox profiles (Research, Coding, Testing, Simulation, Deployment, Robot) with filesystem/network/tool/compute/secrets limits | partial | Research = read-only, Coding = worktree, Testing = tests-only; no network or secrets controls; trials inherit the environment; no Simulation/Deployment/Robot profiles |
| 20 | Observability: runs, tasks, tool calls, tokens, latency, errors, experiments, compute, GPU, model usage, cost, tests, deployments; dashboard | partial | dashboard, tasks, errors, latency, trial CPU/memory, model per call, tests; no tokens, cost, GPU, tool calls |
| 21 | Autonomy levels 0-5 per project | gap | gates and delegation approximate levels 2-4 |
| 22 | Technology decision document | gap | the stack (Python stdlib, SQLite, git, no services) was chosen but never written up as a comparison |
| 23 | Engineering principles | partial | aligned on modularity, testability, reproducibility, provenance, immutability, least privilege, replaceable models/agents, recovery, no hidden state; no CI, no infrastructure as code, type checking not enforced |
| 24 | Phases 1-9 | partial | 1-6 built; 7 simulation in robolab; 8 robotics later; 9 partly (programmes, knowledge) |
| 25 | Inspect, preserve, plan, implement incrementally, test, document, commit, never claim untested | aligned | decision log D1-D54, tests per increment |
| 26 | /research <problem> -> definition, literature, extraction, state of the art, gaps, hypotheses, experiment proposals, research plan; save artifacts | gap | the research stages exist inside a project, but there is no plan-only research workflow or command |
| 27 | /engineer <project> -> requirements ... integration | gap | engineering track exists without the architecture/critique/plan/security/performance stages or a command |
| 28 | /project <objective> -> research ... deploy, project state machine | partial | `autolab new` + `autolab run` run research -> design -> implement -> test -> evaluate -> iterate with a state machine; no deploy; no /project command |
| 29 | /director <programme> with 10 duties | partial | `autolab programme` (D54) covers objective, subproblems, tasks, delegation, monitoring, additional experiments, next cycle; "challenge weak conclusions" and "consolidate knowledge" are not explicit director duties |
| 30 | /build <system> with 9 duties | partial | Engineering Director breaks work down; tests, fixes, integration via the engineering machine; no architecture construction step, quality evaluation report or release artifacts |
| 31 | Vertical slice | aligned | pilot-004 live; tests |
| 32 | Success criteria | aligned | ARCHITECTURE.md table |
| 33 | Final objective; the nine documents | aligned | docs/ |

## Closed since the audit

| Gap | Closed by | Evidence |
|---|---|---|
| 12 research <-> engineering feedback | D55: failures -> observations -> triage -> research questions | tests/test_feedback.py |
| 11/27/30 engineering workflow | D56: architecture, critique, security and performance reviews, release manifest | tests/test_eng_workflow.py |
| 26-30 workflow modes | D57: autolab research/engineer/project/director/build + .claude/commands | tests/test_modes.py |
| 21 autonomy levels | D58: levels 0-5 enforced by gates, delegation and programme rules | tests/test_autonomy_levels.py |
| 22 technology decisions | docs/TECHNOLOGY_DECISIONS.md | - |
| 8 knowledge vocabulary | D59: entity types, derived Agent/Model/Dataset/Metric/Paper/CodeArtifact/Architecture, typed relations | tests/test_knowledge.py |
| (found in review) generated data in branches | D58: controller removes generated/oversized files after engineer commits | test_generated_data_never_reaches_a_branch |
| 20 observability + 10 agent evaluation | D60: tokens/cost/time per call, agent scorecards (CLI + dashboard) | tests/test_scorecard.py |
| 15/16 project manifest | D61: export project folder + project.yaml, import (incl. the s.16 example) | tests/test_manifest.py |
| 19 sandbox profiles | D62: six profiles, secrets scrubbed for trials and test runs | tests/test_sandbox.py |

## Priority order to close the gaps (as of the audit)

Ordered by the prompt's own weight ("mandatory", "no major implementation without") and by
value per effort:

1. **Research <-> engineering feedback (12, mandatory).** Engineering failures (review findings,
   escalations, halts, failed trials) become `observation` records; a research agent turns
   significant ones into research questions; open questions feed programmes and new projects.
2. **Engineering workflow (11, 27, 30).** Machine-readable architecture on both tracks; an
   architecture-critique stage; an implementation plan; security and performance review stages
   with their own agents; a release record.
3. **Slash workflows (26-30).** `/research` (plan-only, saves the research plan), `/engineer`,
   `/project`, `/director`, `/build` as Claude Code commands over `autolab`.
4. **Autonomy levels (21)** per lab and project, mapped onto gates and delegation.
5. **Technology decision document (22).**
6. **Knowledge vocabulary (8):** more entity types (Method, Dataset, Model, Agent,
   ExperimentRun, Requirement, Architecture, Observation) and typed relations (supports,
   contradicts, tested_by, implements, fails_on, ...).
7. **Project manifest and structure (15, 16)** as an export/import of ledger state.
8. **Observability (20):** tokens, cost, tool calls where the backends report them; agent scorecards (10).
9. **Experiment execution (9):** containers, then GPU; hardware-in-the-loop only behind Gate 7.
10. **Tools and sandboxes (18, 19):** network/secrets policy for trials; deployment and robot profiles.
