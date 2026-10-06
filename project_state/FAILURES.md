# Failures during lab development (retained)

- F1 (2026-10-04): Initial controller treated "engineer made no code changes" as a
  failure, which halted legitimate scenarios (disputed review findings; main already
  implements a revised protocol). Fixed by re-verifying instead (D6).
- F2 (2026-10-04): Test scenario's redesign handler returned an implement-shaped
  payload; the protocol validator correctly rejected it. Fixed in the test.
- F3 (2026-10-04): The live smoke test exposed locale (cp1252) decoding of
  subprocess output on Windows. Experiment, test and merge subprocesses now decode UTF-8.
- F4 (2026-10-04): LIVE PILOT pilot-001 HALTED in DESIGN (budget 3). Root cause:
  architectural. The REQUIREMENTS stage demanded structured checks naming conditions
  before DESIGN created them; the scientist wrote prose ("each paired seed ...")
  as condition ids, and DESIGN could not change requirements, so the loop could not
  converge. The controller correctly rejected all three designs. Fixed by D8.
  Evidence retained in labs/pilot-001 (git-ignored local lab) and labs/pilot-001-run.log.
- F5 (2026-10-04): LIVE PILOT pilot-002 HALTED in ENGINEERING after 3x
  `claude exited 1:` with an empty message (Claude usage limit hit mid-run). Root cause
  of the empty message: Claude Code reports errors as JSON on stdout; the backend read
  only stderr. Fixed: ClaudeCLIBackend.parse_output surfaces stdout JSON errors (and
  is_error with exit 0). Resumed via `autolab resume` with no lost work.
- F6 (2026-10-04): CODE REVIEW (no experiment run) found 12 defects R1-R12 (see PROJECT_STATE.md
  and D14-D19). Most serious: frozen fixed_params never reached the experiment (R1); engineer
  pytest config could hide failing verifier tests (R2, reproduced); percentile bootstrap CIs
  undercovered (R3, simulated); the engineer agent loaded the user's Claude memory index ("user
  granted 100% autonomy"), skills and MCP servers (R5, observed with a probe prompt). pilot-001/002
  results were produced before these fixes; RUN-0001 used the bootstrap CI.
- F7 (2026-10-05): robolab G1-2 PRJ-0008 HALTED at ADVERSARIAL_REVIEW after 3 Codex errors: the
  CLI's default model (gpt-6.1-sol) is not available to the ChatGPT-account login. Not a code
  defect; the engineer's build had passed tests. Fixed by pinning the model (D36). Lesson: pin
  agent models in lab.toml instead of relying on CLI defaults, which change with CLI updates.
