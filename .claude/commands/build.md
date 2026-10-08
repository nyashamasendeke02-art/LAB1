---
description: Engineering Director mode (master prompt s.30) -> inspect requirements, architecture, assign engineers, implement, test, fix, integrate, evaluate quality, release
argument-hint: <system> --accept "<criterion>" [--accept ...] [--lab labs/<name>]
---
Run the lab's `/build` mode for: $ARGUMENTS

1. Lab: the path after `--lab`, else `labs/workbench` (create it as in /research if missing).
2. Acceptance criteria are required; ask the user if none were given.
3. Run in the background, logging to `<lab>-run.log`:
   `PYTHONIOENCODING=utf-8 .venv/Scripts/autolab.exe build <lab> "<system>" --accept "..." --run`
   The Engineering Director splits the system into specialty tasks; each task goes through architecture,
   critique, implementation, tests, independent verification, security and performance review and integration;
   every delivery carries a release manifest (quality summary + provenance).
4. Report each task's delivery (commit, release manifest) or the blocker, from
   `.venv/Scripts/autolab.exe programme <lab> status <PRG-id>`.
