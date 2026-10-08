# Engineering architecture

Status labels: **done** = implemented and tested; **partial** = implemented with a known gap; **gap** = not built. Statements are ENGINEERING_DECISIONs about the code in `src/autolab/` unless labelled otherwise.

## Lifecycle

| Master prompt step | Implementation | Status |
|---|---|---|
| Requirements | research track: `requirements` stage; engineering track: spec + acceptance criteria (`autolab task`) | done |
| Architecture | `solution_design` (read-only checkout: feasibility, files, interfaces, risks); `redesign` must state an `architecture_change` | done |
| Implementation | `implement` / `build` in a per-attempt worktree | done |
| Testing | controller runs the test command; verifier adds independent tests run hermetically | done |
| Perform integration | controller `--no-ff` merge of the verified branch into `main`, after review gates | done |
| Evaluate system quality | adversarial review (findings by severity; any critical/major blocks), smoke test, scientific validation, path-based review gates (e.g. safety) | done |
| Produce release artifacts | `delivery` record (spec, acceptance criteria, commit, review), commit trailers, ledger head anchored in git, reports | partial: no packaged release bundle |

## Engineering agents

| Master prompt agent | Today |
|---|---|
| Engineering Director | agent on `engineering_breakdown` (D54): splits a programme's engineering item into specialty tasks from a read-only checkout of main; the engineering state machine still governs each task (patch -> redesign -> escalate) |
| Systems Architect | `solution_design` (allocatable agent) |
| Implementation (Backend, Frontend, ML, Algorithm, Data, Simulation engineers) | specialist agents routed by `<stage>@<specialty>` (D54); preset `organisation` creates one per `[coordination] specialties` |
| Testing / QA | verifier role (`verify`), adversarial and independent |

## Engineering state machine

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
solution escalation is mechanical. Merge requires *controller-run* tests passing, the
verifier's tests passing in a hermetic run (no conftest, controller ini, JUnit-checked),
**and** a verifier pass with no critical/major findings, reproducibility and
protocol compliance confirmed. A "pass" verdict accompanied by a critical
finding is treated as a fail.

### Engineering track (v0.3.0)

`autolab task LAB "spec" --accept "..." --refs "REQ-SAFE,Gate 0"` creates an
*engineering* project for gate work with no hypothesis. It starts in ENGINEERING
and runs the same engineering machine (build → controller tests → adversarial review
with hermetic independent tests → review gates → merge), then ends COMPLETE with a
`delivery` record (spec, acceptance criteria, mandate refs, commit, review). A
research project can never go ENGINEERING → COMPLETE. Engineering tasks are not
blinded: the spec is the objective.

**Review gates on paths:** `[gates] review_paths` (e.g. `src/safety/*` → `safety`)
blocks a merge that touches those files until the gate is decided. **Delegation:**
`[gates.delegation]` names a non-agent delegate for chosen gates. Delegated decisions
need a rationale and are recorded as `decided_by=<delegate>, delegated_by=human`.

**Measurement and reproducibility:** each trial gets controller-measured
`autolab_wall_s`, `autolab_cpu_s` and `autolab_peak_mb` (job-object accounting; the
code under test cannot overwrite them), an output cap (`max_trial_output_mb`), and a
check of `requirements.lock` against the interpreter before any data is collected
(a mismatch HALTs). A confirmatory study after exploratory pilots counts as
confirmatory; only one confirmatory study per hypothesis. Projects, protocols,
deliveries and conclusions carry `mandate_refs`; `autolab mandate LAB` reports
coverage. `[lab] charter` gives the scientist a charter file (the mandate digest).

## Repository / worktree strategy

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
