# Implementation plan

Status 2026-10-08. Principle (master prompt section 31): a working vertical slice beats many
incomplete services.

## 1. The vertical slice exists

Inspection result: every step of the slice is implemented, tested offline (`autolab demo`,
153+ tests) and was run live with real agents in `labs/pilot-004` (PRJ-0001: heavy-ball vs
gradient descent; design approved on the 3rd round; verifier wrote independent tests; scientific
validation caught a hard-coded parameter; pre-registered analysis: SUPPORTED, paired effect 265
iterations, 95% CI [229, 302]; report and ledger verified). robolab has since merged nine
engineering deliveries through the same machinery. See ARCHITECTURE.md, "The vertical slice".

What the slice does not yet do: **carry knowledge from one project to the next.** Each project
starts from an empty context, and next questions only feed later cycles of the same project.
That is the gap between "Result -> Knowledge Storage" and the final objective's "Knowledge
Graph -> New Research".

## 2. Increment K1: knowledge plane (done 2026-10-08, D53)

| Step | Deliverable | Acceptance | Evidence |
|---|---|---|---|
| K1.1 | `Store.open_readonly` | another lab's ledger opens with SQLite `mode=ro`; writes raise | test_readonly_store_refuses_writes; pilot-004 ledger opened, write refused |
| K1.2 | `knowledge.py`: nodes, typed edges, BM25 index, cached per ledger head | graph lists a conclusion with edges to result, run, protocol, hypothesis | test_graph_nodes_edges_and_search; pilot-004 + robolab: 82 nodes, 22 edges |
| K1.3 | `[knowledge]` config | defaults: this lab only, 8 items, enabled | config.py; test_knowledge_can_be_disabled |
| K1.4 | `lab_knowledge` for define_problem, background_research, research_question, hypothesis, design; conclusions of matched research lines added by graph expansion | a second project's prompts contain the first project's conclusion; engineer/verify packets do not | test_second_project_receives_prior_knowledge_but_engineers_do_not |
| K1.5 | lab-ledger source verification | `lab:<lab>/<id>` of an existing node -> verified; unknown id or URL -> not | test_claims_citing_lab_records_are_verified |
| K1.6 | spawn a project from a future question | origin provenance; same-lab question `spawned`; cross-lab origin, other lab untouched | test_spawn_project_from_open_question, test_knowledge_flows_across_labs_read_only |
| K1.7 | `autolab knowledge` CLI | stats, search, questions, show, spawn | run on labs/pilot-004 and labs/robolab |
| K1.8 | dashboard Knowledge view + API | search, record drawer with edges, open questions, start project; project page shows origin | test_knowledge_api_search_node_and_spawn; headless browser on pilot-004: 0 console errors |
| K1.9 | tests + real-data demonstration | scripted A -> knowledge -> B loop; retrieval over real ledgers | tests/test_knowledge.py (9); a Nesterov-momentum objective retrieves pilot-004's conclusion and rejected protocol |

Known limit: retrieval is lexical (a conclusion that says "heavy-ball" is not found by
"momentum" alone); graph expansion brings a matched research line's conclusions, and semantic
retrieval is ROADMAP phase 6.

## 3. Increment D54: hierarchical coordination (done 2026-10-08)

| Deliverable | Evidence |
|---|---|
| Programme record + state machine, plan/task validation (keys, deps, cycles, budgets) | tests/test_coordination.py: test_plan_validation, test_task_validation |
| Research Director `programme_plan` / `programme_review`, Engineering Director `engineering_breakdown` | test_programme_runs_the_hierarchy_end_to_end (R1 research -> E1 split into backend + ml tasks -> review) |
| Specialty routing `<stage>@<specialty>`; preset with directors and specialists | test_specialty_allocation; the ml task built by the ml specialist |
| Retry of halted items, replanning, knowledge flowing to replanned items | test_review_retries_a_halted_item_and_replans |
| Escalation with blockers, human resume; stop at human gates | test_escalation_halts_with_blockers_and_resume, test_programme_stops_at_a_human_gate |
| Controller refuses invalid plans and dishonest completion | test_invalid_plans_are_rejected_then_halt, test_complete_requires_every_item_done_or_dropped, test_review_without_runnable_work_halts |
| CLI `autolab programme`, dashboard Programmes view, PROGRAMMES.md | test_programmes_api; headless browser: 0 console errors |

## 3. Next increments

See ROADMAP.md: specialist engineering agents, agent scorecards, release bundles, programme
director, verified external literature, semantic retrieval, deployment plane.
