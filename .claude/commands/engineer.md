---
description: Engineering workflow for one spec (master prompt s.27) -> requirements, architecture, critique, implementation, testing, security, performance, integration
argument-hint: <spec> --accept "<criterion>" [--accept ...] [--specialty <name>] [--lab labs/<name>]
---
Run the lab's `/engineer` workflow for: $ARGUMENTS

1. Lab: the path after `--lab`, else `labs/workbench` (create it as in /research if missing).
2. Every engineering task needs acceptance criteria; if none were given, ask the user for them before submitting.
3. Run in the background, logging to `<lab>-run.log`:
   `PYTHONIOENCODING=utf-8 .venv/Scripts/autolab.exe engineer <lab> "<spec>" --accept "..." [--specialty ...] --run`
   The lab runs: approved machine-readable architecture -> critique -> implementation by the allocated
   (specialty) engineer -> controller tests -> independent verification -> security review -> performance review
   -> review gates -> merge -> delivery with a release manifest.
4. Report the outcome: delivery id and commit, or the halt/block reason and the approval id if a gate is waiting.
