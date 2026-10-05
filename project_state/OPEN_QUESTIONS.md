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
8. OPEN_QUESTION (mandate): which concrete task and environment for Gate 1/E1? The mandate
   names none. It must be small enough for this machine (8 GB RAM) but have dynamics a World
   Model can learn and states where a fast controller fails.
9. OPEN_QUESTION (mandate): the mandate gives no numeric acceptance thresholds (latency,
   success, calibration) or compute budgets; each must be fixed at pre-registration.
10. OPEN_QUESTION (mandate): how are "surprise", "novelty" and "stakes" operationalised for
    Awareness v1 rules? They must be defined before E3.
11. OPEN_QUESTION (mandate vs CLAUDE.md): does adaptive allocation in a designed modular brain
    count as evidence about *emergent* general capability? Default: no, unless the capability
    was not hard-coded and alternatives were excluded.
12. OPEN_QUESTION: should autolab expose the 13 mandate roles as more agent roles, or keep three
    agents with the role responsibilities folded in (current default, docs/MANDATE.md section 3)?
