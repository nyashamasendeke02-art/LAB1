# Open Questions (lab infrastructure)

1. OPEN_QUESTION: Do real LLM agents reliably produce schema-valid stage payloads,
   especially full protocols? The retry-with-error loop is untested live.
2. OPEN_QUESTION: Should scientific review use a different model or vendor from
   the designing scientist, to reduce correlated blind spots?
3. OPEN_QUESTION: Background-research citations are not verified by the
   controller (stored as sources_verified=false). Add a literature-verification step?
4. OPEN_QUESTION: The ledger is tamper-evident, not tamper-proof. Anchor the head
   hash externally (for example, in a git commit)?
5. OPEN_QUESTION: The statistics are an unpaired bootstrap of means. Add paired
   designs, power analysis and multiple-comparison control for confirmatory work?
6. OPEN_QUESTION: The CLI has no protocol amendment workflow yet (Store.amend
   exists). How should an amendment after data collection downgrade a
   confirmatory study to exploratory?
7. OPEN_QUESTION: The verifier's sandbox (codex workspace-write) can read
   outside its worktree. Is that acceptable for the threat model?
