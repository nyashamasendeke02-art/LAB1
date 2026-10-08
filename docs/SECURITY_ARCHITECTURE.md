# Security architecture

Status labels: **done** = implemented and tested; **partial** = implemented with a known gap; **gap** = not built. Statements are ENGINEERING_DECISIONs about the code in `src/autolab/` unless labelled otherwise.

## Threat model

| Threat | Why it is real here |
|---|---|
| A model writes or runs harmful code | engineers and verifiers execute code they wrote (tests, trials) |
| An agent games its own evaluation | e.g. edits tests, protocols, the ledger or its reviewer's allocation |
| Prompt injection through stored content | agent outputs are later fed to other agents and shown in the dashboard |
| Silent drift of results | non-reproducible runs, changed data, changed code after data collection |
| A local web page abused from the browser | DNS rebinding, cross-site requests to the dashboard |
| Secrets leaking | API keys in the environment, provider logins |

## Controls

| Control | Mechanism | Status |
|---|---|---|
| Stage permissions | role per stage fixes workdir, writable flag, blinding and path policy (`registry.STAGES`) | done |
| Backend enforcement | claude-cli: read-only tools or an allowlist (Read/Glob/Grep/Edit/Write, python, pytest), git denied; codex-cli: `--sandbox read-only` or `workspace-write`; gemini-cli: `--mode plan` or accept-edits inside `--sandbox` (F11); openai-api: no tools, cannot be allocated writing stages | done |
| Hermetic agents | no user settings, CLAUDE.md, MCP, skills, plugins or memories; the task packet is the only context | done (claude, codex); gemini partial (slash commands disabled only) |
| Path policies | engineer edits to `protocols/*`, `tests/verification/*` and verifier edits outside tests are reverted and recorded | done |
| Tamper check | after every agent call: main checkout, ledger chain, `lab.toml` and `agents.toml` unchanged, else HALT | done |
| Tamper evidence | hash-chained ledger, immutable record versions (SQL triggers), content-addressed artifacts, ledger head anchored in git trailers | done |
| Pre-registration | protocols frozen before code; amendments human-only; confirmatory downgraded if amended after data | done |
| Reproducibility | exact merged commit, pinned interpreter, lock-file check, data hashes, raw data read-only | done |
| Human gates | protected experiments, confirmatory freeze, compute/spend budget, merge, path-based review (e.g. safety); only the human (or a named delegate) decides | done |
| Dashboard | loopback only, Host check (421), per-process token + same-origin for writes, strict CSP, no innerHTML, no writes during agent calls | done |
| Prompt-injection containment | outputs never reach state unvalidated (JSON schema), never rendered as HTML, never granted tools beyond the stage's | partial: content is still read by later agents |

## Safety and approval gates

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
`codex --sandbox workspace-write`. Approval-bypass flags are never used for Claude or
Codex; Gemini's headless mode needs `--dangerously-skip-permissions` and is therefore
confined by `--sandbox` (F11). All of this is asserted in tests. The lab never pushes, deploys or touches remotes.

## Sandbox profiles (D62)

Every stage and trial runs under a named profile (`src/autolab/sandbox.py`, recorded on each task
record and dispatch event): ResearchSandbox (scientist stages and read-only engineer/verifier
stages), CodingSandbox (engineer writing stages), TestingSandbox (verifier), SimulationSandbox
(experiment trials), DeploymentSandbox and RobotSandbox (unavailable: no deployment plane; no
hardware before Gate 7). Each states what is enforced and what is not. Secrets: experiment trials
and controller test runs get an environment scrubbed of credential-like variables (KEY, TOKEN,
SECRET, PASSWORD, CREDENTIAL, AUTH, COOKIE, SESSION); a trial receives only the variables its
frozen protocol lists in `secrets`. On the lab PC this removed CLAUDE_CODE_MESSAGING_TOKEN from
code the lab executes. Network access is not enforceable without OS firewall rules and is
documented as not enforced.

## Findings and residual risks

- **F11 (2026-10-08, fixed):** the Gemini backend (D50) auto-approved every tool request on
  writing stages without agy's terminal sandbox, so as a backup verifier it could run any shell
  command, git included. Writable Gemini tasks now add `--sandbox` (test asserts it). A live
  probe that the sandbox still lets agy edit the worktree is pending (Gemini quota).
- Engineer-written code runs outside an OS sandbox (tests, trials); tampering with controller
  state is detected, other writes on the machine are not.
- (fixed D62) Experiment trials no longer inherit credentials; only protocol-declared secrets.
- The verifier sandbox can read outside its worktree.
- The ledger is tamper-evident, not tamper-proof: rewriting both the database and git history
  is possible for someone with full disk access.
- No human has reviewed the Safety Kernel; required before any hardware (Gate 7).
