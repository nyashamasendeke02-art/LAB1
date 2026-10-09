# Decisions (ENGINEERING_DECISION)

- D1: The controller owns state in SQLite with append-only versioned records and a
  hash-chained event ledger; agents never touch it.
- D2: Research and engineering are separate state machines with whitelisted transitions.
- D3: Outcomes are computed mechanically from a pre-registered decision rule;
  LLMs interpret but cannot change them.
- D4: One git worktree and branch per agent task; the controller commits and
  merges; path policies are enforced on diffs; branches are never deleted.
- D5: Patch budget leads to forced redesign, then escalation to research DESIGN
  (no indefinite patching).
- D6: An engineer "no changes" response is allowed but always re-verified by
  controller tests and an independent review (added after tests exposed false
  failures in legitimate cases).
- D8: Structured validity/success checks live in the protocol (written at DESIGN,
  frozen with the pre-registration); the REQUIREMENTS stage is prose. (The live
  pilot showed requirements cannot reference conditions that do not exist yet.)
- D9: Amendments are human-only, require HALTED, downgrade confirmatory→exploratory
  after data, and force re-verification via a new engineering task.
- D10: Paired bootstrap is an opt-in `pairing` field of the frozen decision rule.
- D7: The default ChatGPT scientist backend is the Codex CLI in read-only mode,
  because no OPENAI_API_KEY is configured; the openai-api backend is available.
- D11: Merge requires >= 1 independent verifier test (tests/verification/test_*.py).
  A missing test is retried as the verifier's stage error and never charged to the
  engineer. (pilot-002: Codex passed the review without writing any tests.)
- D12: decision_rule.min_effect must be > 0 (smallest effect size of interest);
  prompts require a "baseline actually learns" validity check. (pilot-002 RUN-0001:
  min_effect=0 made a tight null CI permanently 'inconclusive'; all arms had weight
  error ~0.286, i.e. under-trained, which the 'finite/completed' checks did not catch.)
- D13: Checks may use relative_to=<condition> (aggregate of per-seed differences); protocols
  may carry fixed_params, and every reproduction-relevant parameter must be frozen there.
  (pilot-002 review: the scientist could not express a paired-difference success check and
  produced an impossible "mean MSE < -0.001"; operational details were left in prose.)
- D14 (code review 2026-10-04, R1/R7): every trial gets `--params` = protocol.fixed_params merged
  with conditions[].params (overlapping keys are invalid). Protocol objects are closed schemas
  (additionalProperties: false): unknown or misplaced keys are rejected, never defaulted.
- D15 (R3, supersedes D10's bootstrap): decision CIs are Student t (paired) / Welch t (unpaired),
  and every protocol needs >= 3 seeds. EXPERIMENTAL_RESULT (simulation in this session): percentile
  bootstrap 95% CIs covered 0.76 / 0.86 / 0.88 / 0.91 at 3 / 5 / 10 / 20 seeds; t intervals are
  within 0.93-0.97 at 3 and 5 seeds (regression test). The analysis version is now 0.2.0.
- D16 (R2): verifier tests are also run hermetically by the controller (`python -P -E -B -m pytest
  --noconftest`, controller ini, no PYTEST_ADDOPTS) and merge requires a JUnit report with >= 1 pass,
  0 failures, 0 errors. The engineer's own pytest config can no longer hide them.
- D17 (R4, R11): scientific validation runs in a read-only checkout of the merged commit and gets
  the diff. Engineer and verifier (verify stage) are blinded: no hypothesis, question, background,
  decision rule, success checks or earlier results, and a neutral objective. Blinding is partial:
  condition names and the protocol title can still hint at the hypothesis.
- D18 (R6): a redesign may not reuse seeds already used to test the same hypothesis, and every
  conclusion records its look number; only a first look can be confirmatory. Later looks are
  labelled "exploratory; look k, not corrected for multiple looks".
- D19 (R5, R8, R9, R10, R12): agent CLIs run hermetically (claude: no setting sources, no MCP,
  no skills, no auto-memory; codex: --ignore-user-config/--ignore-rules, plugins/apps/browser/
  computer-use/memories disabled). Agent, test and trial subprocesses run in a kill-on-close job
  (Windows) or a process group (POSIX). Rejected agent responses are stored. ENGINEERING stage
  retries are counted per engineering sub-step and reset on progress. After every agent call
  the controller checks main HEAD/clean, ledger head + chain and lab.toml; a change HALTs the
  project (integrity_violation, never retried). Transient worktrees left by a crash are removed
  at the start of `run`.
- D20 (2026-10-04, human): AI_Robotics_Full_Documentation.pdf is the foundation of this lab:
  the research mandate and the engineering mandate. Digest and reconciliation with CLAUDE.md:
  docs/MANDATE.md. The mandate sets the direction (H1-H5, E1-E6, gates 0-8, REQ-*, ADR-001..005);
  CLAUDE.md sets the method. Every component is earned by an experiment against its ablation;
  sequencing is Gate 0 (contracts) -> Gate 1 (simulation) -> E1 (S1 baseline), which is
  CLAUDE.md's first milestone. The Safety Kernel is never a research variable.
- D21 (2026-10-04, human -> Claude Code): full control delegated ("100% in control ... start it end
  to end, utilising the lab"). Claude Code decides the PROJECT_PLAN section 10 items:
  (1) plan adopted as the programme baseline; (2) repo strategy A, a single lab `labs/robolab`
  whose repo is the robot-brain code; (3) EnvA = Puck2D; (4) budgets: trial timeout 300 s, at most
  200 trials per study, one active agent run at a time; (5) pilot -> one confirmatory study per
  hypothesis; (6) no remote backup (pushing still needs explicit human approval). Gate decisions
  taken under this delegation are recorded as decided_by="claude-code" with delegated_by="human",
  never as the human. Acceptance of major scientific conclusions stays flagged for the human.
- D22: P0 sequencing (smallest justified change). Before the validation run: L1 engineering track,
  L2 path gates + recorded delegation, L3 resource metering, L6 pilot->confirmatory, L7 mandate
  refs + lab charter in scientist context, L8 output cap, L9 dependency lock check. L4
  (non-inferiority / co-primary / Holm) and L5 (power) come before the first confirmatory study or
  E3. L10 (citation verification) is deferred: sources stay `sources_verified: false`.
- D23 (2026-10-05, claude-code): L4/L5 implemented before any confirmatory study (e0f95d4):
  non-inferiority rules, co-primary endpoints by intersection-union, p-values, Holm on secondary
  contrasts, and a power check that refuses underpowered confirmatory designs.
- D24 (2026-10-05, claude-code): design convergence (615d476). pilot-003 HALTED after 4 rejected
  designs because the designer rewrote each protocol from scratch and the reviewer did not know
  the fixed analysis method or run contract. The designer now revises the rejected protocol;
  both prompts state the analysis method; review 'revise' is limited to validity threats.
  pilot-003 stays HALTED as a record: `autolab resume` records the human, so under delegation a
  fresh lab (pilot-004) was used instead.
- D25 (2026-10-05, human): Codex verifier gets `-c windows.sandbox="elevated"` for writable tasks
  (hermetic mode had made it read-only). The human chose this option and granted Claude permission
  to run `autolab run`. Lab validation then PASSED: pilot-004 positive control SUPPORTED.
- D26 (2026-10-05, claude-code): GATE 0 PASSED in labs/robolab. G0-1 contracts (DLV-0001),
  G0-2 telemetry (DLV-0002), G0-3 Safety Kernel v1 (DLV-0003), G0-4 cycle runner (DLV-0004); 186
  tests on main; contracts and safety reviews by claude-code with independent checks (APR-0001,
  APR-0002); audited that Environment.actuate only receives KernelResult.actuator_command. Known
  limitation carried to G1-3: one-step workspace lookahead with a zero-force safe action.
  Deviation from D21(4): pilot-004 and robolab G0-1 ran in parallel for ~15 min on 2026-10-05
  (no shared state; both completed correctly). Back to one active run at a time.
- D27 (2026-10-05, claude-code under delegation; human: "no preference"): the simulation's role
  is to teach the robot physics through consequences only. Keep WM-1 as planned (integrator +
  learned residual; fully learned model as ablation) and add: (a) G1-4 ground-truth isolation,
  brain modules see only observations and their own actions, enforced by test; (b) online
  mass/friction estimation in World Model v1, scored on change-detection latency (links H3);
  (c) a later WM-2: self-directed exploration vs passive logged data, by prediction-error
  learning curve. Learn-from-scratch stays a comparison condition, not the default (mandate:
  "physics-informed", "compared progressively with more learned physics").
- D28 (2026-10-05, human direction; plan changes by claude-code): GOAL: one generalised brain that
  runs any body described by a Model Hardware Standard (MHS): RC car, humanoid, self-driving car.
  Labelled HYPOTHESIS (cross-embodiment generality is an open problem); it is the mandate's
  long-term direction (embodiment-agnostic brain, H5, ADR-005) made concrete. Plan changes:
  G1-5 MHS v0 (body description; Safety Kernel configured from it), G1-6 Car2D second body,
  both in Gate 1 so no component is designed against one body. Expectation set: "figure out"
  = the same brain code learns a new body quickly from its MHS and its own experience, not
  zero-shot competence; fast body-specific reflexes (balance, motor loops) may live below
  the adapter and are declared in the MHS. Real vehicles stay deferred (Gate 7, human decision).
- D29 (2026-10-05, claude-code): optional independent reviewer: `[agents.reviewer]` in lab.toml
  runs the listed stages (default scientific_review) on a different backend from the designing
  scientist (OPEN_QUESTION 2). Disabled by default; the reviewer's backend/model is recorded on
  each task. Tests: test_independent_reviewer_runs_scientific_review, test_reviewer_disabled_by_default.
- D30 (2026-10-05, review): the Safety Kernel must not depend on the brain's state estimate;
  it reads position/velocity from the raw Observation via the MHS (folded into G1-5). The
  harness injects the simulation clock (G1-2 spec).
- D31 (2026-10-05, review): D27 and D28 reconciled: any hand-written physics in the World Model
  must be a generic prior parameterised by the MHS (e.g. Newtonian rigid body with declared
  actuator kinds), never per-body code; otherwise the brain is not body-agnostic. Open as
  OPEN_QUESTION 13 until WM v1 is designed.
- D32 (2026-10-05, claude-code under delegation; human: "no preference" on all four): requirements
  v0.1 adopted in docs/REQUIREMENTS.md. Scope: edge-board-class target compute for the fast loop
  (Pi 5 / Jetson Orin Nano class), "figured out a new body" = fast adaptation within a fixed
  experience budget vs a tuned body-specific controller with zero safety violations, navigation as
  the first task family. New: REQ-MHS, REQ-ISO, REQ-NAV, REQ-SAFE+, REQ-SAFE-H, REQ-RT,
  REQ-COMPUTE, REQ-COST, REQ-REPRO, REQ-WM+. Hypotheses stay out of requirements. Changes only by
  recorded amendment.
- D33 (2026-10-05, claude-code): software requirements SW-* added to docs/REQUIREMENTS.md. Gaps found:
  no packaging/namespace (SW-PKG), Windows-only testing (SW-OS, SW-CI), no type/lint checks
  (SW-STATIC), kernel coverage unmeasured (SW-SAFETY-CODE), and NO REMOTE BACKUP of either
  repository (SW-BACKUP; pushing needs the human's choice of remote). Planned as G1-7 software
  baseline after G1-6.
- D34 (2026-10-05, claude-code): open-source stack mapped to the user's schematic layers in
  docs/REQUIREMENTS.md, each with licence and gate. Licence policy SW-LICENSE-DEP: permissive or
  weak-copyleft inside the brain; GPL only as separate processes/firmware; AGPL excluded. Isaac Sim
  excluded (proprietary, GPU). Nav2/MoveIt 2 used as baselines, not as the brain. Project licence
  (recommended Apache-2.0) is the human's decision.
- D35 (2026-10-05, human: "I want full agentic autonomy on this project"): the lab runs unattended.
  (a) Agent usage/rate limits no longer HALT a run: the controller records a usage_limit failure,
  waits usage_limit_wait_s (900 s) and retries without counting a stage retry, up to
  usage_limit_max_wait_s (12 h). (b) `autolab queue LAB FILE.toml` runs engineering tasks in order,
  submitted as claude-code; it stops at a HALT or an approval gate and never re-submits a HALTED
  task by itself. (c) Gate 1 queue: docs/gates/gate1_queue.toml (G1-2..G1-7). (d) Claude Code
  decides research-direction defaults, reviews gates (real reviews, evidence in the note), and
  restarts the queue. Kept with the human: physical hardware runs (Gate 7, REQ-SAFE-H), spending
  money or creating accounts, publishing or pushing to a remote, deleting research artifacts, and
  acceptance of major scientific conclusions.
- D36 (2026-10-05, claude-code): robolab G1-2 (PRJ-0008) HALTED at adversarial review: Codex 0.160's
  default model gpt-6.1-sol is "not supported when using Codex with a ChatGPT account". Probed:
  gpt-6-luna and gpt-5.6-terra both work; pinned model = "gpt-6-luna" for the scientist and verifier
  in labs/robolab/lab.toml (newest generation available to the account). Added `autolab queue
  --retry ID` to submit a HALTED task again as a fresh project once its cause is fixed (the HALTED
  project stays as a record). PRJ-0008 kept HALTED; G1-2 re-submitted.
- D37 (2026-10-06, claude-code under delegation): APR-0003 (G1-3 Safety Kernel v1.1) APPROVED after a
  real review: diff read, 268 tests pass on the branch, independent Puck2D fault injection (clamp and
  reject modes, random / push-to-wall / bang-bang, with and without damping+friction, 40 seeds x 400
  steps): never left the workspace. Confirmed limitation: a configured mass below the true mass can
  exit (2x mass: 2.452 m vs 2 m bound), so the MHS mass_kg is an upper bound. Integration gap found:
  CycleRunner calls tick()/emergency_stop() without velocity and actuates nothing on abstain, so a
  moving body would coast on hardware. Folded into the G1-5 spec (runner passes observed velocity;
  safe action actuated every cycle without an approved command) with a new acceptance criterion.
- D38 (2026-10-06, human: "Connect to Github", "Create the repo and commit"): private GitHub repos
  nyashamasendeke02-art/LAB1 and nyashamasendeke02-art/robolab created and pushed (SW-BACKUP).
  Pushing to these two remotes is now routine. The ledger DB and artifacts (.autolab) are not in
  git yet; a snapshot backup is the next step.
- D39 (2026-10-06, human: "Create a script that automatically continues after session limit removed"):
  scripts/autopilot.py supervises the lab: runs the active queue (docs/gates/ACTIVE_QUEUE), and when
  it stops runs headless Claude Code in LAB1 (`claude -p`, permission-mode acceptEdits, tools Read/
  Edit/Write/Glob/Grep/Bash; memory and PROJECT_STATE give it the rules) to do gate reviews, fixes and
  next queues, ending with an AUTOPILOT directive. Claude usage limits: wait 15 min and retry (up to
  a week). Stops on NEEDS_HUMAN, DONE, or the same queue stop repeating. Single instance via lock
  file; never starts a second queue. Optional logon start: scripts/install_autopilot_at_logon.ps1.
  Risk accepted under D35: an unattended agent with Bash runs on the user's PC.
- D40 (2026-10-06, human: "use Apache-2.0"): project licence Apache-2.0 (SW-LICENSE). LAB1: LICENSE
  (official text via the GitHub licenses API), pyproject license field, README section; the mandate
  PDF keeps its own terms. robolab: queued as G1-8 (its main checkout belongs to the lab controller,
  so the change goes through the engineering track, not a direct commit).
- D41 (2026-10-06, claude-code; from the human's question "are embodiments programmed or does the MHS tell the
  modules?"): explicit rule: per-body code is allowed ONLY in the body itself (simulator/hardware), its
  embodiment adapter and its reflexes; everything else reads the MHS; dynamics are learned (D27, D31).
  Found: the Safety Kernel v1.1 still assumes a point mass with Cartesian force actions, so the G1-6 spec
  (Car2D, 'do not modify src/safety') was contradictory. G1-6 now makes the kernel body-agnostic: bounds
  declared in the MHS safety envelope (max speed, max acceleration, guaranteed braking deceleration) and
  a declared safe-action kind (oppose_velocity | fixed); static test forbids body-specific branches in
  src/safety. G1-6 will pass a safety review gate.
- D42 (2026-10-06, claude-code): ROS 2 integration design (docs/ROBOT_BRAIN_ARCHITECTURE.md section 12):
  ROS 2 Jazzy only below the embodiment adapter; the brain runs as ONE deterministic rclpy node (cycle
  runner + Safety Kernel immediately before publishing), not one node per module; the MHS gains optional
  ROS bindings (topic, type, field mapping, QoS) so the adapter is generic; ROS clock / use_sim_time
  feeds the kernel; Gazebo via ros_gz for rehearsal; hardware e-stop independent of software. Gate 7.
- D43 (2026-10-06, claude-code; human asked about VLAs/LLMs): foundation models enter only as experimental
  conditions: LLM as a System 2 condition at Gate 5 (local open model via llama.cpp vs cloud vs classical
  planner; local-vs-cloud still the human's choice); VLMs for perception once the simulators render
  images; VLAs as an end-to-end baseline against the modular brain and as an E6 cross-embodiment
  comparison, which needs cameras and GPU-class compute (a REQ-COMPUTE change would be recorded).
  Section 13 of docs/ROBOT_BRAIN_ARCHITECTURE.md.
- D44 (2026-10-06, claude-code under delegation, interactive): APR-0004 (G1-5: MHS v0.1, kernel v1.2, runner
  braking) APPROVED after review: 388 tests pass on the branch; independent fault injection (lag 0-1 s, both
  modes, three adversarial policies, lying estimator, abstain at speed) never left the workspace. Finding:
  worst-case in-flight force during latency freezes bodies with lag >= 0.5 s; folded into G1-6 with an
  acceptance test. The autopilot's headless Claude session had no tool permissions and correctly stopped with
  NEEDS_HUMAN instead of approving unreviewed (03:32).
- D46 (2026-10-06, claude-code; human asked about limit detection): transient API/network errors (no response,
  ECONNRESET, connection dropped/reset/refused, overloaded, 5xx) are now waited out (network_wait_s 120 s, up to
  network_max_wait_s 1 h per run) and retried without counting as a stage failure, like usage limits (D35).
  G1-5 came within one failure of a HALT from two such errors on 2026-10-06. Our own agent timeouts still count
  as failures. Test: test_network_errors_wait_briefly_and_are_not_failures.
- D47 (2026-10-06, claude-code): all lab waits (usage limit, network, autopilot polling) sleep by the wall clock,
  so they end on time after the PC wakes (F8). The sleeping queue process was restarted (no agent was running).
- D48 (2026-10-06, human: "Finish up the web interface"): `autolab ui LAB` local dashboard committed
  (src/autolab/web.py, dashboard.html, docs/USER_INTERFACE.md; the draft was found uncommitted in the tree).
  Finished with: Host-header check against DNS rebinding (421), refusal of ledger writes while an agent
  call is in flight (would trip the tamper check and HALT), stale-dispatch handling (>2 h = abandoned;
  robolab had one, TASK-0017), titled/collapsible task specs, and 8 tests (tests/test_web.py).
- D49 (2026-10-06, human: "Update the user interface to state of the art in UI, UX, backend"): dashboard v2.
  Backend: ThreadingHTTPServer with per-thread Lab, richer JSON API (overview with gate board, alerts, queue
  log, ledger verification; project detail with pipeline/reviews/failures/calls/events; approval with diff;
  agents with readable error classification; activity), Server-Sent Events for live updates, strict CSP (no
  inline code) and security headers, required note for human decisions. Frontend: dependency-free ES module
  SPA (hash routes), light/dark design system, command palette and keyboard shortcuts, diff viewer, pipeline
  stepper, accessible markup. Still stdlib-only and loopback-only. 13 tests (tests/test_web.py); every view
  checked in headless Edge via the DevTools protocol with no page errors.
- D50 (2026-10-06, human: "keep codex and let gemini bcome backup"): Gemini CLI backend (`gemini-cli` via `agy`) and `FallbackBackend` added to autolab (`src/autolab/agents.py`). The controller attempts the primary backend (Codex) first; upon detecting a quota or usage limit (`is_usage_limit` / "upgrade to plus" / 429), it sets a cooldown window and automatically falls back to Gemini (`gemini-3.8-flash-high`) without halting or charging a stage failure. Configured in `labs/robolab/lab.toml` for both verifier and scientist. Tests added to `tests/test_messages_and_agents.py`.
- D51 (2026-10-08, human: "revise the autolab. can this lab do diverse research in AI, LLM, agents, software and
  code"): autolab made domain-general for benchmark-style research. Before this, the only unit of analysis was the
  seed (>= 3 seeds), trials ran one at a time, an API rate limit inside a trial counted as a failed trial, spend
  was not tracked, and nothing pinned evaluation data. Added: decision_rule.unit = "item" (entrypoint writes
  items.json; per-item values averaged over seeds, paired t interval over items; >= 1 seed; n_items frozen;
  power counted in items); automatic validity checks AUTO-ITEM-COVERAGE (every trial reports all items) and
  AUTO-FRESH-ITEMS (a confirmatory study cannot reuse items already analysed for that hypothesis);
  trial exit code 75 = transient failure, retried with backoff (limits.max_trial_retries 6, trial_retry_wait_s
  60); budget.max_parallel; budget.max_cost_usd with a required cost_usd metric, plus a compute_budget gate when
  smoke-test cost x seeds > limits.max_cost_usd_without_approval (20 USD); protocol.data_paths hashed into the
  run manifest (missing data fails the smoke test); raw trial files hashed recursively (transcripts in
  subfolders). Prompts gained DOMAIN_GUIDANCE (models and decoding settings as frozen params, executable
  graders preferred, blinded and validated LLM judges, contamination controls, sandboxed generated code).
  Existing seed-unit protocols behave exactly as before. Tests: tests/test_domains.py (12).
  Not solved: the scientist cannot browse the web, so background research is still unverified (todo 6); cost is
  reported by the experiment code, not measured by the controller; there is no GPU scheduling.
- D52 (2026-10-08, human: "THE LAB SHOULD BE ABLE TO USE DIFFERENT AGENTS/MODELS ... ALLOCATING DIFFERENT AGENTS
  TO THE PROCESS ... web ui ... no hardcoded values, models"): agent registry and stage allocation
  (src/autolab/registry.py). Permissions stay with the stage (each of the 18 stages has a fixed role: scientist
  read-only, engineer writable worktree, verifier tests only); WHO performs a stage is configuration: any number of
  named agents (backend + model + optional title/charter/backup) in lab.toml [agents.*] or agents.toml, and
  [allocation] stage -> agent. Unallocated stages use the role's agent, so existing labs are unchanged (robolab
  verified). Backends with no file tools (openai-api) cannot be allocated writing stages. agents.toml is in the
  controller's tamper check (an engineer cannot reallocate its own reviewer: test). Task records, dispatch events
  and commit trailers (Autolab-Agent) name the agent. `autolab agents LAB [list|set|allocate|remove|preset]`.
  Preset "organisation" creates the master prompt's research/engineering agents (Research Director, Literature,
  Research Gap, Hypothesis, Requirements, Experiment Designer, Scientific Critic, Research Synthesizer, Systems
  Architect, Implementation Engineer, Verification Engineer) on their role's current backend/model.
  Dashboard: /api/meta publishes states, tones, pipelines, stages, roles, backends, project kinds and milestone
  settings, so app.js hardcodes none of them; the Agents page creates/edits/removes agents (model is free text with
  suggestions from models already in use) and edits the allocation; writes refused during agent calls. Lab-specific
  task-key/milestone patterns and the port moved to lab.toml [ui]. Tests: tests/test_registry.py (11), 3 web tests.
  The master prompt (Agent OS: research/knowledge/engineering/experimentation/deployment planes) arrived truncated;
  docs/AGENT_OS_ROADMAP.md maps it onto what exists and the next phases.
- D53 (2026-10-08, human: master prompt sections 31-33 -- "inspect the existing repository ... produce ARCHITECTURE,
  RESEARCH_, ENGINEERING_, AGENT_, KNOWLEDGE_, EXPERIMENT_, SECURITY_ARCHITECTURE, IMPLEMENTATION_PLAN, ROADMAP ...
  then implement the minimum viable vertical slice"): inspection found the vertical slice already built and run live
  (pilot-004); the missing link was knowledge -> new research. Docs: the old docs/ARCHITECTURE.md was split into
  the nine documents (detailed sections moved, not copied; ARCHITECTURE.md is now the overview with the final
  objective, planes, vertical slice and success-criteria tables); AGENT_OS_ROADMAP.md became ROADMAP.md.
  Built K1, the knowledge plane (src/autolab/knowledge.py): a graph DERIVED from the ledgers (never stored, so it
  cannot drift), nodes = knowledge records (stage_error failures excluded as noise), edges = refs, BM25 retrieval
  (stdlib), cached per ledger head; other labs read-only via Store.open_readonly ([knowledge] include_labs).
  Scientist stages define_problem/background_research/research_question/hypothesis/design get `lab_knowledge`
  (top 8 of other projects + conclusions of matched research lines by graph expansion); engineer/verify packets
  never do (also in BLINDED_KEYS). Claims citing `lab:<lab>/<id>` are verified against the ledgers. Projects can
  be spawned from open future questions with origin provenance. `autolab knowledge`, dashboard Knowledge view.
  Tests: tests/test_knowledge.py (9, full scripted A -> knowledge -> B loops incl. cross-lab), web test.
  Security review while writing SECURITY_ARCHITECTURE.md found F11 (fixed): see FAILURES.md.
- D54 (2026-10-08, human: "7. AGENT HIERARCHY" / "Implement hierarchical coordination"; section 7's text was not
  received, so the design follows master prompt sections 5, 6 and 33): src/autolab/coordination.py. A `programme`
  record (PLANNING -> RUNNING <-> REVIEWING -> COMPLETE | HALTED). Research Director (`programme_plan`) decomposes the
  objective into research items (-> research projects) and engineering items; the Engineering Director
  (`engineering_breakdown`, engineer role, read-only checkout of main) splits each engineering item into specialty
  tasks (-> engineering projects with `specialty`, routed by allocation `<stage>@<specialty>` to specialist agents);
  the Research Director (`programme_review`) continues, replans (new items, retries of halted items), completes or
  escalates with blockers. The controller validates every plan (unique keys, known deps, no cycles, acceptance
  criteria, budgets: [coordination] max_items 12, max_tasks_per_item 8, max_reviews 6), schedules by dependency then
  priority, runs projects one at a time, and stops at the first human gate or halt. Honest completion: 'complete' is
  refused unless every item is done or explicitly `dropped` with a reason (found while testing: a scripted director
  "completed" a programme whose items had halted). Preset 'organisation' adds an Engineering Director and one
  specialist engineer per specialty. Vendor names removed from role charters (any model plays any role since D52).
  Fixed in passing: TOML keys with '@' are now quoted in agents.toml; tasks were inserted into the programme order
  in reverse (stale item copy). CLI `autolab programme`, dashboard Programmes view, PROGRAMMES.md. Tests:
  tests/test_coordination.py (10), web test. Not yet: running a programme's independent projects in parallel.
- D55 (2026-10-08, human: "check for gaps and close them" + "use different claude models based on their strengths"):
  (a) Research <-> engineering feedback loop, master prompt s.12 ("mandatory"), src/autolab/feedback.py: every
  failure in OBSERVED_FAILURES (tests/review failed, escalation, smoke, validation, run/invalid experiment,
  infeasible design) is recorded by the controller as an `observation` (event ObservationCreated); stage
  `observation_triage` (research agent) answers every observation: research_question | engineering_fix | noise;
  the controller creates `future_question` records (origin engineering_failure, refs to observation and failure,
  event ResearchQuestionCreated); programme reviews triage their projects' observations first; `autolab observe`.
  Tests: tests/test_feedback.py (5). (b) Claude models by strength: preset `claude-strengths` (data file
  src/autolab/presets/claude-strengths.toml; models are data, not code): Opus 5.5 authors (designs, hypotheses,
  architecture, code, plans), Sonnet 5.5 reviews everything Opus authors (author and reviewer always different
  models), Haiku 4.5 writes reports; Fable 5.1 not allocated (no evidence of its relative strengths). All three
  model ids probed live through the hermetic CLI. Applied to robolab (26 stages); G1-6 then passed review on
  Sonnet (937 s) and waits on the safety gate APR-0006. Vendor names removed from role charters.
- D56 (2026-10-08): engineering workflow, master prompt s.11/27/30, src/autolab/eng_workflow.py: engineering-track
  SPEC runs `architecture` (machine-readable: components, interfaces, data flows, decisions, risks, test strategy,
  implementation plan, requirements trace) and `architecture_critique` by a different agent; no worktree or code
  until approved; HALT after [engineering] architecture_rounds. Before merge: `security_review` and
  `performance_review` of the exact candidate (critical/major -> patch loop). Every delivery carries a release
  manifest artifact (spec, architecture, all reviews, quality summary, commit, ledger head). Events
  ArchitectureCreated/Approved, Security/PerformanceReviewCompleted, ReleaseProduced. Research track unchanged.
  Tests: tests/test_eng_workflow.py (5); the shared fast test config disables these stages for unrelated tests.
- D57 (2026-10-08): workflow modes, master prompt s.26-30: `autolab research` (plan-only: ends at the
  critic-reviewed experiment proposal with a saved research plan report, guarded PROTOCOL_FREEZE -> COMPLETE),
  `autolab engineer` (with --specialty), `autolab project` (full pipeline), `autolab director` (programme),
  `autolab build` (programme starting at the Engineering Director with one engineering item); each with --run.
  Claude Code commands /research /engineer /project /director /build in .claude/commands/. Dashboard: agents
  that are allocated no stage no longer raise "blocked" alerts (a stale Codex usage-limit alert showed after
  verification moved to Claude). Audit of PROMPT.txt: docs/PROMPT_ALIGNMENT.md. Tests: tests/test_modes.py (6).
- D58 (2026-10-08, human: "do both" -- reject APR-0006 with the hygiene finding and keep closing gaps): APR-0006
  rejected by claude-code (delegate) for 59 committed `.scratch/` files (224k lines); full kernel fault injection
  deferred to the cleaned candidate, the commit that would merge; robolab queue restarted (engineer patched as
  5af4ad2). New controller guard: after every engineer commit, files matching [engineering] generated_paths or new
  files over max_committed_file_kb (1024) are removed by a controller commit, recorded (generated_data_removed,
  event GeneratedDataRemoved), not counted as a failed patch; engineers are told the rule up front.
  Autonomy levels (master prompt s.21, src/autolab/autonomy.py): [lab] autonomy_level (default 3 for new labs)
  caps every project; 0 = no agent called, 1 = plan-only research, 2 = every merge and experiment run gated,
  3 = gates as configured, 4 = programmes allowed, 5 = gate delegation honoured (below 5 only the human decides).
  ACTION: robolab relies on delegation (D35) -> set `autonomy_level = 5` in labs/robolab/lab.toml when its queue is
  stopped (editing lab.toml during an agent call trips the tamper check). docs/TECHNOLOGY_DECISIONS.md (s.22).
  Tests: tests/test_autonomy_levels.py (6), guard test.
- D59 (2026-10-08): knowledge vocabulary (s.8): nodes carry entity types (ResearchQuestion, Hypothesis, Claim,
  Method, Experiment, ExperimentRun, Result, Failure, Observation, Requirement, SoftwareComponent); derived entities
  Agent (incl. pre-D52 tasks via role), Model, Dataset, Metric, Paper, CodeArtifact, Architecture; relations use the
  prompt's vocabulary (a conclusion supports/contradicts its hypothesis by outcome, motivates follow-up questions;
  protocol tested_by run; run uses dataset/code; agent produces records and uses a model). On the real ledgers:
  pilot-004 CON-0001 supports HYP-0001 and motivates FQ-0001..4. Dashboard Knowledge view lists entities and
  relationships. Not derived yet: Author, Simulation, Robot, Environment, Publication.
- D60 (2026-10-08, human: "Close remaining gaps"): observability and agent scorecards (s.20, s.10). Backends report
  usage per call when they can (Claude CLI JSON: tokens incl. cache, cost USD, API time, turns, model; OpenAI API:
  tokens); Codex/Gemini CLIs report nothing structured, so their usage stays unknown (never estimated). Agent.run sums
  usage across protocol retries; the controller stores usage and measured wall time on every task record (also on
  errors). src/autolab/scorecard.py: per agent -- calls, success rate, protocol rejections, avg time, tokens, cost,
  models, stages, and quality: reviews of the code it authored (passed/failed, findings caused) and findings it
  raised as reviewer. `autolab agents LAB scorecard`, dashboard Agents scorecards, Overview cost KPI. robolab history:
  default engineer 66 calls / 33% ok, 10 of 20 reviews passed, 9 major findings caused; Codex verifier raised 10 major.
  Tests: tests/test_scorecard.py (4). Docker and NVIDIA GPU are absent on this PC: container/GPU execution (s.9) is
  blocked by hardware, not built.
- D61: project manifest and structure (s.15/16), src/autolab/manifest.py: `autolab manifest LAB export PRJ` writes
  project.yaml (s.16 shape + provenance: ledger head) and research/, requirements/, architecture/, agents/,
  experiments/, datasets/, models/, results/, evaluations/, papers/, src/SOURCE.md (exact commits), documentation/;
  `import` creates a project from project.yaml (the s.16 example verbatim works) and briefs research stages with its
  questions, hypotheses, metrics and domains (`project_manifest` context; engineers stay blinded). New dependency
  PyYAML 6 (requirement-driven, TECHNOLOGY_DECISIONS.md). Tests: tests/test_manifest.py (4).
- D62: sandbox profiles (s.19), src/autolab/sandbox.py: Research/Coding/Testing/Simulation/Deployment/Robot profiles
  with enforced vs not-enforced parts, recorded per task; credentials scrubbed from experiment trials and controller
  test runs (protocol.secrets allows named ones, frozen with the protocol); network not enforceable on Windows
  without admin firewall rules (documented). Tests: tests/test_sandbox.py (3). Remaining s.18 gap: per-tool-call
  logging (needs the Claude backend on stream-json; deferred to its own change with a live check).
- D63 (2026-10-08, human: "is the ui standard ... functionality, UI design, UX design and backend design" then
  "AUTO MODE ON"): an evidence-based UI review (desktop + phone screenshots, accessibility counts, API timings 6-42 ms)
  rated backend good, functionality/UI/UX fair; fixed: (1) research projects get a Research tab -- 17-step research
  progress bar with plain-language state labels and readable cards for problem, literature claims (verified/unverified
  badges, lab-record citations link into the knowledge graph), state of the art and gaps, question, hypotheses (tested
  one marked), requirements, design options (chosen marked), protocol, reviews, result with an effect/CI chart,
  conclusion, next questions and the saved research plan; (2) Agents page: active agents first, unallocated ones
  collapsed, short titles, success/time/cost always visible, success-rate and cost charts; (3) dependency-free SVG
  charts (agent cost or calls per day on Overview; CI chart; linked-records graph in the knowledge drawer); (4) gate
  board only when a lab has milestone tasks; state badges explain themselves (tooltips + header label); collapsible
  menu on phones; palette input labelled; (5) backend: scorecards cached per ledger head, activity paging (?before=).
  Scorecard input tokens now include cached prompt tokens (fresh input alone read "20" for 307k tokens read).
  Live demo (workbench lab, plan-only /research on Nesterov vs heavy-ball, pilot-004 as read-only knowledge):
  8 calls, 757 s agent time, $2.53; claims citing pilot-004 verified against its ledger; Sonnet approved Opus's
  design with a major numerical caveat (validity check V6 likely unsatisfiable at ~1e-14 noise).
- D64 (2026-10-08, human: "3" -- tool-call logging, master prompt s.18): the Claude backend now runs with
  `--output-format stream-json --verbose`; ClaudeCLIBackend.parse_stream extracts every tool_use, its tool_result
  (ok/error, result size) and permission denials, and hands the final "result" line to the unchanged json parser (a
  plain-json stdout still parses; tool calls then stay unknown). Agent.run collects calls across protocol retries;
  the controller writes them per task (handoffs/<TASK>/tool_calls.jsonl + content-addressed artifact) with a summary
  on the task record (count, by tool, errors, denied) and a ToolPermissionDenied event; long inputs (file contents,
  edits) are logged as their size, not copied. Scorecards count tool calls and denials; the dashboard's agent-call
  drawer shows the tool trail. Format taken from a real capture (tests/data/claude_stream_tools.jsonl, anonymised).
  Live checks with Haiku (~$0.03): in a normal lab folder Write ok, `python hello.py` ok, `git status` denied, answer
  returned; in Claude Code's own temp folder Write was denied (that folder is protected -- worktrees never live there).
  Codex and Gemini tool calls are not logged (their CLIs' event formats were not verified here); recorded as
  `tools.logged = false`. Tests: tests/test_tool_logging.py (5).
- D65 (2026-10-08, human: "remove unnecessary steps for g1-6; a minimum viable brain is enough"): the robot-brain
  programme now targets the minimum viable brain (docs/MVB.md) = the mandate's E1 / first milestone: one MHS-driven
  S1 predictive controller (online one-step forward model + lookahead) on Puck2D and Car2D, every action through the
  Safety Kernel, measured against PD and random baselines. robolab process trimmed: architecture stage off,
  security/performance pre-merge reviews off, contracts gate dropped (labs/robolab/lab.toml); kept: adversarial review
  + tests on every change and the Safety Kernel gate (every brain action passes the kernel). G1-7 (packaging, ruff,
  100% coverage) and G1-8 (licence) moved to docs/gates/deferred_queue.toml. Next: finish G1-6 (safety gate review,
  proportionate fault injection), then docs/gates/mvb_queue.toml (MVB-1), then MVB-2 = the E1 experiment.
- D66 (2026-10-08): APR-0007 (G1-6 safety gate) APPROVED by claude-code for simulation after fault injection (29
  cases, true position per step): Car2D always inside; Puck2D inside except a sustained full-force push plus an
  undeclared external impulse (2 of 6 tasks: 2.03 m, 2.14 m at 0.5 s lag; inside when the impulse is removed).
  Kernel holds its declared envelope; the gap is undeclared disturbances (F9). Liveness fixed (PD 7/8 goals at
  0.5 s lag). Follow-up G1-9 (declared disturbance margin) is REQUIRED before any hardware (deferred_queue.toml).
  Review method note: an earlier batch of my bang-bang cases was invalid (malformed proposals from my own test
  policy -> kernel correctly braked); caught from the kernel's telemetry reasons and rerun.
- D67 (2026-10-08, human: "is it possible to make an interactive terminal based ui ... minimal but very functional"):
  `autolab tui LAB` (src/autolab/tui.py), built on Textual 8 as an OPTIONAL extra (`pip install autolab[tui]`; core
  dependencies stay jsonschema + PyYAML). curses is unavailable on Windows and raw ANSI would be fragile; Textual has
  tables, keyboard navigation and a headless test pilot. It reuses the web dashboard's data layer
  (DashboardServer.offline), so both interfaces show the same data. Screens: 1 Overview (projects + one-line lab
  summary incl. cost and ledger check), 2 Approvals (approve/reject with a required note, recorded as the human's
  decision, refused during agent calls), 3 Agents (scorecards incl. tool calls/denials), 4 Knowledge (search, Enter
  opens a record with its links), 5 Activity (ledger), 6 Queue (log); Enter on a project opens its research/
  engineering summary; auto-refresh on ledger or queue-log change. Tests: tests/test_tui.py (3, Textual pilot).
  Meanwhile robolab: G1-6 merged (DLV-0010) -> Gate 1 COMPLETE; MVB-1 submitted as PRJ-0014.
