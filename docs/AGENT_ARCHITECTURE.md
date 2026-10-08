# Agent architecture

Status labels: **done** = implemented and tested; **partial** = implemented with a known gap; **gap** = not built. Statements are ENGINEERING_DECISIONs about the code in `src/autolab/` unless labelled otherwise.

## Runtime capabilities

| Capability (master prompt section 4) | Implementation | Status |
|---|---|---|
| Identity, roles, goals | named agents (`registry.py`), role per stage, objective + acceptance criteria in each task packet | done |
| Task execution | `Agent.run`: prompt -> backend -> JSON extraction -> schema validation -> retries | done |
| Replaceable, provider-independent | backends: claude-cli, codex-cli, gemini-cli, openai-api; any agent on any stage; backup backend on usage limits | done |
| Memory, context management | explicit context per task (no conversational memory); knowledge-plane context for research stages | done (K1 for cross-project) |
| Tool access, permissions | per stage role; each backend enforces read-only vs writable (SECURITY_ARCHITECTURE.md) | done |
| Artifact creation / retrieval | records and content-addressed artifacts via the controller only | done |
| Event publishing / subscription | ledger events; dashboard SSE | partial: agents do not subscribe |
| Inter-agent communication | through records the controller passes on (by design, no direct messages) | done |
| Retries, checkpoints, failure recovery | protocol retries, stage retries, usage/network waits, HALT/resume, crash recovery | done |
| Observability | handoff files per task, task records with agent/backend/model, dashboard | done |
| Planning | the controller plans via state machines; agents do not plan multi-step work | partial |
| Evaluation of agents | - | gap (ROADMAP: scorecards) |

## Agent hierarchy and hierarchical coordination (D54)

```text
PROGRAMME (objective)                                      coordination.py (controller-owned)
 +- Research Director      programme_plan                  -> work items: research | engineering,
 |                                                           depends_on, priority, rationale
 |   +- research items     -> research projects (full research cycle; Literature, Hypothesis,
 |   |                        Experiment Designer, Critic, Synthesizer agents on their stages)
 |   +- engineering items
 |       +- Engineering Director  engineering_breakdown    -> specialty tasks (read-only checkout
 |           |                                                of main; fit the architecture)
 |           +- specialist engineers  build/implement@<specialty> -> engineering projects
 |              (verification engineer reviews every one; merges through the usual gates)
 +- Research Director      programme_review                -> continue | replan (new items,
                                                              retries, dropped) | complete | escalate
```

* **Coordination is controller-owned.** Directors propose; the controller validates every plan
  (unique keys, known dependencies, no cycles, engineering items have acceptance criteria,
  `[coordination] max_items` / `max_tasks_per_item`, specialties from `[coordination]
  specialties`), schedules ready items by dependency then priority, runs their projects, and
  stops at the first human gate or halt (the programme records `blocked_on`).
* **Honest completion.** `complete` is accepted only when every item is done or listed in
  `dropped` with a reason; `retry` may name only halted items (a fresh project; the halted one
  stays as a record); a review with no new items, retries or completion HALTs for a human;
  `max_reviews` bounds the loop.
* **Routing by specialty.** Engineering projects carry a `specialty`; allocation keys
  `<implement|redesign|build|rebuild>@<specialty>` route them to specialist agents; without one
  the stage's (or role's) agent builds it.
* **Same audited path.** Director calls are ordinary stage calls on the programme record:
  permissions, handoff files, tamper check, task records with agent and model.
* **Knowledge.** `programme_plan` and `programme_review` receive `lab_knowledge`; projects of a
  programme see earlier projects' conclusions through the knowledge plane.
* **Interfaces.** `autolab programme LAB new|run|status|resume`; dashboard Programmes view
  (item tree, director decisions and calls); `PROGRAMMES.md` export.

States: PLANNING -> RUNNING <-> REVIEWING -> COMPLETE | HALTED (resume: human, back to REVIEWING).

## Default roles

| Agent | Default backend | Workspace | May write |
|---|---|---|---|
| Scientist (ChatGPT) | `codex-cli` read-only (ChatGPT login) or `openai-api` | none | nothing |
| Engineer (Claude) | `claude-cli` (`claude -p`, acceptEdits, git disallowed) | `worktrees/engineer/<ENG>-d<n>` | anything except protected paths |
| Verifier (Codex) | `codex-cli` `--sandbox workspace-write` | `worktrees/verifier/<ENG>-r<n>` | `tests/verification/*` only |

Agents never touch the database, never run git and never decide transitions.
Agent CLIs run hermetically (no user settings, CLAUDE.md, plugins, skills, MCP servers or
memories): the task packet is their only context. The engineer and the verifier (verify
stage) are blinded to the hypothesis, decision rule and earlier results. After every agent
call the controller checks that controller-owned state (main checkout, ledger, lab.toml,
agents.toml)
is unchanged, and HALTs on any change (the engineer runs Python outside an OS sandbox).

## Backends and the agent loop

* `AgentBackend.invoke(task, prompt) -> text` (transport only):
  `ClaudeCLIBackend`, `CodexCLIBackend`, `GeminiCLIBackend`, `OpenAIBackend`,
  `FallbackBackend` (primary + backup on usage limits, D50) and `ScriptedBackend`
  (deterministic, for tests and the offline demo). Factories by name in
  `agents.BACKEND_FACTORIES`; capabilities in `registry.BACKENDS`.
* `Agent.run(task)` builds the prompt (common rules + role charter + stage
  instructions + task packet + output schema, `prompts.py`), extracts the JSON
  object from the response, validates it against the stage schema and retries
  up to `max_protocol_retries` times with the validation error. Anything not
  schema-valid never reaches the controller's state.
* Role → stage responsibilities:
  * Scientist: define_problem, background_research, research_question,
    hypothesis, requirements, design (brainstorm/evaluate/choose + protocol),
    scientific_review, scientific_validation, interpret, communicate,
    next_question.
  * Engineer: solution_design (feasibility, read-only), implement, redesign; on the
    engineering track build and rebuild.
  * Verifier: verify (adversarial code review + independent tests), challenge
    (adversarial review of results).
* The scientific review is a *separate* scientist call with a reviewer
  framing. OPEN_QUESTION: whether a different model should review (configure
  a different backend/model to test this).

### Agent registry and stage allocation (D52)

Roles are **permission classes** fixed per stage (`registry.STAGES`: 18 stages with role,
plane, writable, reads-files). **Agents** are named configurations: backend (`claude-cli`,
`codex-cli`, `gemini-cli`, `openai-api`; capabilities in `registry.BACKENDS`), model, optional
title, charter, effort, timeout and backup backend/model. `[allocation]` maps a stage to an
agent; an unallocated stage runs on the agent named after its role.

```toml
# agents.toml (lab root; written by `autolab agents` and the dashboard)
[agents.scientific_critic]
title = "Scientific Critic"
backend = "gemini-cli"
model = "..."
charter = "Challenge assumptions, confounds and unsupported claims."

[allocation]
scientific_review = "scientific_critic"
```

* The controller resolves the agent at every call (`Controller.agent_for`), re-reading
  `agents.toml` when it changes, so a new allocation applies from the next call.
* The task packet (workdir, writable, blinding) still comes from the stage's role; each
  backend enforces read-only vs writable itself. A backend without file tools cannot be
  allocated a writing stage (`stage_fit`).
* `agents.toml` is part of the integrity snapshot: an agent that edits it HALTs the project.
* Task records, `task.dispatched` events and commit trailers (`Autolab-Agent`) name the agent.
* The agent's title and charter are added to the role charter in the prompt.
* Preset `organisation` maps the master prompt's research and engineering agents onto the
  stages (`docs/ROADMAP.md`).

## Agent communication protocol

* `TaskPacket` (`messages.py`): task_id, role, stage, objective, explicit
  context (no conversational memory), constraints, acceptance criteria,
  workdir, writable flag, output schema.
* `Completion`: `status` (complete | blocked | needs_review | failed),
  `summary`, stage `payload`, `research_claims` (labelled), `risks`.
* `STAGE_SCHEMAS` define every payload; `PROTOCOL_SCHEMA` +
  `validate_protocol` add semantic checks (baseline + intervention present,
  decision rule uses the pre-specified primary metric, unique seeds, ≥3 seeds
  for confirmatory).
* Claim enforcement (`taxonomy.validate_claim`): unknown labels rejected;
  ESTABLISHED/SOURCE_CLAIM need sources; EXPERIMENTAL_RESULT must cite a run
  the controller actually recorded. Rejected claims are stored and logged,
  not silently dropped. Background-research sources are stored as
  `sources_verified: false`, because the controller does not verify citations.
* Every packet, prompt, raw response and completion is written to
  `.autolab/handoffs/<TASK>/` and hashed into the artifact store.
