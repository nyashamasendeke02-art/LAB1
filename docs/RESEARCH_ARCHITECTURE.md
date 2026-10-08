# Research architecture

Status labels: **done** = implemented and tested; **partial** = implemented with a known gap; **gap** = not built. Statements are ENGINEERING_DECISIONs about the code in `src/autolab/` unless labelled otherwise.

## Responsibilities and agents

| Master prompt agent | Stages it performs (preset `organisation`) | Output records |
|---|---|---|
| Research Director | programme_plan, programme_review (D54), define_problem, next_question | programme plan and decisions, problem, future_question |
| Literature Agent | background_research | background, claim (with evidence labels and sources) |
| Research Gap Agent | research_question | question |
| Hypothesis Agent | hypothesis | hypothesis (statement, prediction, null, falsification) |
| Requirements Agent | requirements | requirements (validity criteria, success criteria, engineering requirements) |
| Experiment Designer | design | design (options, choice, rationale) + protocol draft |
| Scientific Critic | scientific_review, scientific_validation | review |
| Research Synthesizer | interpret, communicate | review (interpretation), report |

Every stage is a controller call with a fixed role (scientist: read-only). Which model performs
it is configuration (AGENT_ARCHITECTURE.md).

## Inputs from the knowledge plane

The scientist stages that frame research (define_problem, background_research,
research_question, hypothesis, design) receive `lab_knowledge`: the most relevant earlier
conclusions, failures, open questions, methods and claims from other projects of this lab and
of the labs listed in `[knowledge] include_labs`, each with its lab, record id and evidence
label (KNOWLEDGE_ARCHITECTURE.md). Agents cite them as `SOURCE_CLAIM` with source
`lab:<lab>/<record id>`; the controller verifies such sources against the ledger.

## Research state machine

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
Every analysed run of a hypothesis is a *look*: a redesign must use seeds not yet
used for that hypothesis, and only a first look can be confirmatory (later looks
are labelled exploratory with their look number; no multiplicity correction).

## Evidence taxonomy

Every claim carries one label: ESTABLISHED, SOURCE_CLAIM, HYPOTHESIS, ENGINEERING_DECISION,
EXPERIMENTAL_RESULT, INFERENCE, OPEN_QUESTION (`taxonomy.py`). ESTABLISHED/SOURCE_CLAIM need
sources; EXPERIMENTAL_RESULT must cite a run the controller recorded. Rejected claims are stored,
not dropped.

## Gaps

- Literature access: the scientist has no web or paper search, so external sources are
  recorded as unverified (`sources_verified: false`). Lab-internal sources are verified (K1).
- Programme level is built (D54, AGENT_ARCHITECTURE.md): programmes run several dependent
  research and engineering projects. Projects of one programme run one at a time.
