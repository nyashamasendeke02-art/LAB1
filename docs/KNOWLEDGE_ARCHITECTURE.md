# Knowledge architecture

Status labels: **done** = implemented and tested; **partial** = implemented with a known gap; **gap** = not built. Statements are ENGINEERING_DECISIONs about the code in `src/autolab/` unless labelled otherwise.

Three layers, each derived from the one below it:

1. **Ledger** (authoritative): versioned, hash-chained records and content-addressed artifacts.
2. **Memory**: typed views, lineage trace, markdown exports (`memory.py`).
3. **Knowledge graph** (`knowledge.py`): knowledge-bearing records of one or more labs as nodes,
   their `refs` as typed edges, a retrieval index over their text, and the feedback loop from
   results to new research.

## Provenance model

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

## Research-memory model

Record kinds: project, problem, background, claim, question, hypothesis,
requirements, design, protocol, eng_task, review (scientific_review,
code_review, scientific_validation, interpretation), run, result, challenge,
conclusion, failure, report, future_question, task, approval, cycle.
Failed approaches, rejected designs, policy violations, invalid experiments and
stage errors are all `failure` records; nothing is deleted.
`project_state/*.md` (CURRENT, HYPOTHESES, CONCLUSIONS, FAILURES,
OPEN_QUESTIONS, DECISIONS, EXPERIMENTS) is regenerated after every step;
`autolab export --json` dumps every version of every record plus the ledger.

## Knowledge graph (K1, done 2026-10-08)

**Source of truth.** The graph is computed from the ledgers, never stored separately, so it
cannot drift from them; it is rebuilt when a ledger head changes. Other labs are opened
read-only (SQLite `mode=ro`) from `[knowledge] include_labs` in `lab.toml`.

**Nodes.** One per knowledge-bearing record: problem, claim, question, hypothesis, design,
protocol, result, conclusion, failure, future_question, delivery. Node id `<lab>:<record id>`;
each node keeps its kind, project, evidence label, status or outcome, creation time and a text
used for retrieval (for a conclusion: hypothesis statement, outcome, confidence and caveats; for
a failure: category and summary; and so on). Operational records (tasks, approvals, events) stay
in the ledger and are reachable through lineage, not indexed.

**Edges.** Every `refs` entry between two indexed records becomes an edge labelled with the ref
name (e.g. conclusion -result-> result -run-> ...; future_question -conclusion-> conclusion), so
"what supports this" and "what came from this" are graph walks.

**Retrieval.** Okapi BM25 (k1 = 1.2, b = 0.75) over lower-cased word tokens with a small stopword
list, in the standard library. Lexical by design: deterministic, explainable, testable; semantic
retrieval is a roadmap item.

**Use in research.** For define_problem, background_research, research_question, hypothesis and
design, the controller queries the graph with the project objective (plus the current question
and hypothesis), excludes the project's own records, and passes the top `[knowledge]
context_items` nodes as `lab_knowledge`. Graph expansion then adds the conclusions of every earlier
research line (lab, project) that a hit belongs to, because lexical matching can miss the
conclusion itself while matching its question or protocol. Conclusions and failures are kept even when they
contradict the new objective: negative results are knowledge. Only scientist stages receive it;
engineer and verify stages stay blinded.

**Verified internal sources.** A background claim whose sources are all `lab:<lab>/<id>` and
that resolve to graph nodes is stored with `sources_verified: true` and
`verification: "lab-ledger"`; any other source stays unverified.

**Feedback.** Open `future_question` records from every included lab are ranked (priority, then
recency). `autolab knowledge LAB spawn <lab:FQ-id>` (or the dashboard) creates a research project
from one, with `origin` provenance (lab, question, conclusion it came from); a same-lab question
is marked `spawned` with a ref to the new project.

**Interfaces.** `autolab knowledge LAB [stats | search TEXT | questions | spawn ID]`;
`GET /api/knowledge`, `GET /api/knowledge/search?q=`, `POST /api/knowledge/spawn`.

## Limits

- Lexical retrieval misses paraphrases; there is no ontology of methods or entities yet.
- Cross-lab knowledge is read-only; cited cross-lab records are verified to exist, not
  re-evaluated.
