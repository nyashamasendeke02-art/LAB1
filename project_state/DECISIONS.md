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
- D7: The default ChatGPT scientist backend is the Codex CLI in read-only mode,
  because no OPENAI_API_KEY is configured; the openai-api backend is available.
