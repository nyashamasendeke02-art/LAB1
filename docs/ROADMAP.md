# Roadmap

Status 2026-10-08. From today's lab to the final objective (ARCHITECTURE.md): a laboratory that
researches, designs, builds, tests, evaluates and improves intelligent systems with decreasing
human intervention. Order is by what raises **research quality, engineering quality,
reproducibility, learning velocity and useful discoveries** most per unit of work, not by the
number of agents.

## Where we are

| Area | State |
|---|---|
| Vertical slice (question -> ... -> result -> stored knowledge) | done, run live (pilot-004) |
| Research plane | done; literature access unverified; one project = one research line |
| Engineering plane | done; one generalist engineer; no packaged releases |
| Experimentation plane | done for code, simulation and benchmarks (D51); no training jobs or hardware |
| Agent runtime | done: any backend/model on any stage (D52); agent hierarchy with Research and Engineering Directors and specialty routing (D54) |
| Knowledge plane | done (K1, D53): graph over lab ledgers, prior knowledge in research stages, verified lab sources, projects spawned from open questions; retrieval lexical |
| Deployment plane | gap |
| Robot-brain programme (robolab) | Gate 0 passed; Gate 1: G1-1..G1-5 merged, G1-6 at review |

## Phases

| # | Phase | Why next | Done when |
|---|---|---|---|
| K1 | **Knowledge plane** (done, D53): graph over all lab ledgers, retrieval into research stages, verified lab sources, spawn projects from open questions (IMPLEMENTATION_PLAN.md) | closes the loop "results -> knowledge -> new research"; every later phase reads from it | acceptance table in IMPLEMENTATION_PLAN.md met |
| 1 | **Specialist engineering agents** (done, D54): engineering tasks carry a specialty (backend, frontend, ML, algorithm, data, simulation); allocation becomes stage x specialty -> agent | match model to work; the master prompt's engineering organisation | robolab tasks routed by specialty with no controller changes per specialty |
| 2 | **Agent scorecards**: per agent and model -- calls, protocol rejections, review findings caused, rework, wall time, cost | choose models on evidence; detect regressions when a provider changes a model | Agents page shows scorecards; allocation decisions cite them |
| 3 | **Release bundles**: `autolab release` packages a delivery (commit, tests, review, ledger excerpt, reports) as a verifiable artifact | "produce release artifacts" with provenance | a bundle re-verifies on another machine |
| 4 | **Programme director** (done, D54: hierarchical coordination): a research programme decomposed into several projects, scheduled through the queue, blockers surfaced | multi-line research instead of one project at a time | a programme runs two dependent projects unattended |
| 5 | **Verified external literature**: controller-run search/fetch; citations get a verification status | background research becomes checkable | claims citing external sources are verified or flagged |
| 6 | **Semantic knowledge**: embeddings or an ontology of methods, entities and results on top of K1 | paraphrase-robust retrieval; method/result reuse | retrieval benchmark on the lab's own records beats BM25 |
| 7 | **Training and hardware experiments**: long-running jobs, GPU scheduling, hardware-in-the-loop behind the Safety Kernel | robolab Gates 5-7 | a training job and a hardware run with full provenance |
| 8 | **Deployment plane**: cloud/edge/robot deployment of merged systems | final objective | only after Gate 7's human safety review |

Each phase follows the lab's own rule: a component is earned by showing it improves the work
against its absence, and every phase ends with tests and an entry in `project_state/DECISIONS.md`.

## Mapping of the master prompt

| Master prompt | Covered by |
|---|---|
| Sections 2-4 (Agent OS principle, planes, runtime) | ARCHITECTURE.md, AGENT_ARCHITECTURE.md |
| Section 5 (research agents) | RESEARCH_ARCHITECTURE.md; preset `organisation` |
| Section 6 (engineering agents) | ENGINEERING_ARCHITECTURE.md; phase 1 |
| Engineering lifecycle steps 7-9 (integration, quality, release) | ENGINEERING_ARCHITECTURE.md; phase 3 |
| Section 31 (vertical slice) | IMPLEMENTATION_PLAN.md section 1 |
| Section 32 (success criteria) | ARCHITECTURE.md, "Success criteria" |
| Section 33 (final objective) | this roadmap |
| All 33 sections (PROMPT.txt) | section-by-section audit and gap priorities in PROMPT_ALIGNMENT.md |
