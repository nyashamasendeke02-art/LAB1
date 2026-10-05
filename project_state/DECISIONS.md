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
