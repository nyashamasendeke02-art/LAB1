# Autonomous Research Lab — Architecture

Status labels follow the project evidence taxonomy. Unless marked otherwise,
statements below are **ENGINEERING_DECISION**s describing what is implemented
in `src/autolab/`.

---

## 1. System architecture

```text
                         HUMAN RESEARCHER
          objective · approvals · resume · final authority
                               │  autolab CLI
                               ▼
┌──────────────────────────── CONTROLLER (controller.py) ───────────────────────────┐
│  owns authoritative state · one state-machine action per step() · gates · retries │
│                                                                                    │
│  Research SM ◄──────────► Engineering SM        Experiment engine  Report builder │
│  (state_machines.py)      (per ENG task)        (experiments.py)   (report.py)    │
│        │                        │                       │                          │
│        ▼                        ▼                       ▼                          │
│  Agent dispatch ──────► TaskPacket ──► Agent ──► Completion (schema-validated)    │
│  (agents.py, messages.py, prompts.py)                                             │
└───────┬───────────────────────┬───────────────────────┬──────────────────────────┘
        │                       │                       │
   STORE (store.py)       GIT (worktrees.py)      ARTIFACTS (store.py)
   SQLite: versioned      repo/ main = integration content-addressed sha256,
   records + hash-chained per-agent worktrees     read-only raw data, prompts,
   event ledger           + branches               logs, manifests, reports
        │
   MEMORY (memory.py): typed views, lineage trace, project_state/*.md export
```

| Agent | Default backend | Workspace | May write |
|---|---|---|---|
| Scientist (ChatGPT) | `codex-cli` read-only (ChatGPT login) or `openai-api` | none | nothing |
| Engineer (Claude) | `claude-cli` (`claude -p`, acceptEdits, git disallowed) | `worktrees/engineer/<ENG>-d<n>` | anything except protected paths |
| Verifier (Codex) | `codex-cli` `--sandbox workspace-write` | `worktrees/verifier/<ENG>-r<n>` | `tests/verification/*` only |

Agents never touch the database, never run git and never decide transitions.

## 2. Agent architecture

* `AgentBackend.invoke(task, prompt) -> text` (transport only):
  `ClaudeCLIBackend`, `CodexCLIBackend`, `OpenAIBackend`, `ScriptedBackend`
  (deterministic, for tests and the offline demo).
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
  * Engineer: solution_design (feasibility, read-only), implement, redesign.
  * Verifier: verify (adversarial code review + independent tests), challenge
    (adversarial review of results).
* The scientific review is a *separate* scientist call with a reviewer
  framing. OPEN_QUESTION: whether a different model should review (configure
  a different backend/model to test this).

## 3. Research state machine

```text
DEFINE_PROBLEM → BACKGROUND_RESEARCH → RESEARCH_QUESTION → HYPOTHESIS → REQUIREMENTS
   → DESIGN ⇄ SCIENTIFIC_REVIEW → PROTOCOL_FREEZE [gate] → ENGINEERING (Eng SM)
   → SCIENTIFIC_VALIDATION (smoke run + scientist) → RUN_EXPERIMENT [gates]
   → ANALYZE (controller stats + scientist interpretation) → CHALLENGE (verifier)
   → EVALUATE ─ invalid / inconclusive ─→ DESIGN   (Brainstorm, Evaluate, Choose)
             └ valid ─→ COMMUNICATE → NEXT_QUESTION → RESEARCH_QUESTION (next cycle)
                                                    └→ COMPLETE
any non-terminal state → HALTED (retries exhausted, design budget exhausted);
only a human `resume` leaves HALTED.
```

Transitions are whitelisted (`RESEARCH_TRANSITIONS`); e.g. DESIGN→RUN_EXPERIMENT,
ENGINEERING→RUN_EXPERIMENT (skipping validation) and RUN_EXPERIMENT→ENGINEERING
(changing code after data collection) are illegal.

**EVALUATE semantics** (the "critical distinction"):

| Situation | Meaning | Next |
|---|---|---|
| validity requirement failed, trial failures, or *critical* challenge | instrument did not work; **no conclusion drawn** | DESIGN |
| valid, outcome `inconclusive`, design budget left | recorded as inconclusive conclusion | DESIGN |
| valid, outcome supported / partially / unsupported | EXPERIMENTAL_RESULT conclusion; hypothesis status updated | COMMUNICATE |

An **unsupported** hypothesis from a valid experiment is a scientific result,
not an engineering failure. Hypothesis records keep the label HYPOTHESIS: a
test outcome never upgrades them to ESTABLISHED. Exploratory conclusions are
marked `preliminary (exploratory)`; a non-critical "challenged" verdict marks
them `contested`.

## 4. Engineering state machine

```text
SPEC → IMPLEMENTING → TESTING → ADVERSARIAL_REVIEW → MERGE → MERGED
          ▲   │ fail      │ fail          │ fail
          └───┴───────────┴───────────────┘   patch_attempts += 1
patch_attempts ≥ max_patch_attempts → REDESIGN (fresh branch from main; the
engineer gets the full failure history and the `redesign` stage, which requires
an `architecture_change`)
redesigns ≥ max_redesigns → ESCALATED → research DESIGN ("approach inadequate")
```

This implements "do not patch indefinitely": the patch → redesign → rethink-the-
solution escalation is mechanical. Merge requires *controller-run* tests passing
**and** a verifier pass with no critical/major findings, reproducibility and
protocol compliance confirmed. A "pass" verdict accompanied by a critical
finding is treated as a fail.

## 5. Agent communication protocol

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

## 6. Repository / worktree strategy

* `repo/` is the research code repository. `main` is the integration branch
  and changes only via (a) the controller committing frozen protocols to
  `protocols/` and (b) controller `--no-ff` merges.
* Engineer: `eng/<ENG>-d<design>` worktree branched from `main`.
* Verifier: `verify/<ENG>-r<round>` worktree branched from the engineer's
  head. Previous rounds' verification tests are carried forward. The verify
  branch (implementation + independent tests) is what gets merged.
* The controller commits agent changes with agent author identity and
  trailers (`Autolab-Task`, `Autolab-Eng`, `Autolab-Backend`,
  `Autolab-Protocol: PROT@freezehash`, `Autolab-Review`).
* Path policies are enforced on the diff after every agent commit. Protected
  paths (`protocols/*`, `tests/verification/*`) edited by the engineer, or
  non-test files edited by the verifier, are reverted by a controller commit
  and recorded as a policy failure.
* Branches are never deleted, so failed implementations remain inspectable.
  Worktree checkouts are removed after use.
* Experiments, smoke tests and challenges run from detached read-only
  checkouts of the exact merged commit.

## 7. Provenance model

* Records (`store.py`) are immutable versions `(id, version)` with a content
  hash. `update` requires a reason. SQL triggers forbid UPDATE/DELETE.
* Events form a sha256 hash chain; `autolab verify` recomputes the chain and
  record hashes and checks referenced artifacts (tamper-evident, not
  tamper-proof: an attacker with DB write access could rebuild the chain.
  OPEN_QUESTION: external anchoring, such as periodically committing the head
  hash to git).
* Artifacts are content-addressed (sha256), read-only, and verified on read.
* `refs` on every record give a DAG; `memory.trace(id)` walks a conclusion
  back to: result → run (commit, env hash, manifest, per-trial raw-file
  hashes) → frozen protocol version (freeze hash) → design → requirements →
  hypothesis → question → agent tasks (prompt/response/completion artifacts).

## 8. Experiment model

* **Protocol** = pre-registration: kind (exploratory | confirmatory),
  `protected`, entrypoint, conditions (baseline, intervention, ablation,
  null, transfer, robustness), seeds, primary/secondary metrics, decision
  rule, and budget.
* Frozen before any implementation. Changes go only through `Store.amend`,
  which is recorded with a justification and a new freeze hash.
* **Entrypoint contract:** `<entrypoint> --condition N --seed S --out DIR
  --params JSON` writes `DIR/metrics.json`. The interpreter is pinned to the
  recorded `sys.executable`; `PYTHONHASHSEED` is set to the seed.
* **Smoke test:** a seed outside the protocol seeds, so confirmatory data is
  never peeked at, and it is not counted as data.
* **Run:** every condition × seed. Raw stdout/stderr/metrics are hashed and
  made read-only. The manifest links protocol version + freeze hash, commit,
  environment snapshot (Python, platform, installed packages), and command.
* **Analysis** (controller, deterministic, seeded bootstrap): the
  pre-registered decision rule gives supported / partially_supported /
  unsupported / inconclusive. Secondary contrasts (ablations, null) are
  reported but are not decisive. Validity requirements are evaluated
  mechanically. The scientist interprets (INFERENCE) but cannot change the
  outcome.

## 9. Research-memory model

Record kinds: project, problem, background, claim, question, hypothesis,
requirements, design, protocol, eng_task, review (scientific_review,
code_review, scientific_validation, interpretation), run, result, challenge,
conclusion, failure, report, future_question, task, approval, cycle.
Failed approaches, rejected designs, policy violations, invalid experiments and
stage errors are all `failure` records; nothing is deleted.
`project_state/*.md` (CURRENT, HYPOTHESES, CONCLUSIONS, FAILURES,
OPEN_QUESTIONS, DECISIONS, EXPERIMENTS) is regenerated after every step;
`autolab export --json` dumps every version of every record plus the ledger.

## 10. Autonomous control loop

`Controller.step(pid)`:
1. If terminal: no-op. If blocked on an approval: no-op until a human decides.
2. Dispatch the handler for the current research state (ENGINEERING delegates
   to one engineering sub-step).
3. The handler records everything and makes at most one transition, as its
   last action.
4. On any exception: record a `stage_error` failure (with traceback) and
   increment the retry count for that state. Beyond `max_stage_retries` the
   project goes to HALTED.
5. Regenerate the markdown state.

`run()` loops until COMPLETE, HALTED or blocked. Because all state is in the
DB, a new process can resume any project (crash recovery is tested). Budgets:
`max_patch_attempts`, `max_redesigns`, `max_design_iterations` (per cycle),
`max_cycles`, `max_trials_without_approval`, and per-trial and test timeouts.

## 11. Safety and approval gates

| Gate | Trigger | Default |
|---|---|---|
| `protected_experiment` | protocol `protected: true` | **always on** |
| `confirmatory_protocol_freeze` | confirmatory pre-registration | on |
| `compute_budget` | trials > `max_trials_without_approval` | on |
| `merge_to_main` | every merge | off |

Only actor `human` can decide (`autolab approve|reject`); agents cannot. A
rejected gate sends the project back to DESIGN with the human's note as
feedback. HALTED requires a human `resume`. Agent sandboxes: the scientist is
read-only; the engineer runs `claude -p` with git disallowed; the verifier runs
`codex --sandbox workspace-write`. Dangerous bypass flags are never used
(this is tested). The lab never pushes, deploys or touches remotes.

## 12. Implementation plan and status

| Step | Content | Status |
|---|---|---|
| 1 | store, ledger, artifacts | done, tested |
| 2 | research + engineering state machines | done, tested |
| 3 | communication protocol + schemas + claim taxonomy | done, tested |
| 4 | git worktree strategy + path policies + controlled merge | done, tested |
| 5 | experiment runner + pre-registered analysis | done, tested |
| 6 | approval gates | done, tested |
| 7 | controller loop, failure recovery, redesign escalation | done, tested |
| 8 | research memory, trace, exports, reports | done, tested |
| 9 | CLI + offline scripted demo | done, tested |
| 10 | live backends (claude-cli, codex-cli, openai-api) | adapters built; claude-cli and codex-cli smoke-tested with one stage each; **no full live loop run yet** |
| 11 | next | live pilot on an unprotected exploratory objective; protocol amendment workflow in the CLI; external anchoring of the ledger head; multi-project scheduling; richer statistics (paired tests, power analysis) |

Known limitations: see `project_state/OPEN_QUESTIONS.md`.
