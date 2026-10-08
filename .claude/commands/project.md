---
description: Autonomous project (master prompt s.28) -> research, design, implement, test, evaluate, iterate (project state machine)
argument-hint: <objective> [--lab labs/<name>]
---
Run the lab's `/project` pipeline for: $ARGUMENTS

1. Lab: the path after `--lab`, else `labs/workbench` (create it as in /research if missing).
2. Run in the background, logging to `<lab>-run.log`:
   `PYTHONIOENCODING=utf-8 .venv/Scripts/autolab.exe project <lab> "<objective>" --run`
   This is the full research state machine: problem -> background -> question -> hypothesis -> requirements ->
   pre-registered design + review -> implementation + independent tests -> validation -> experiment ->
   pre-registered analysis -> challenge -> evaluation -> report -> next question (iterate).
3. Report the computed outcome exactly as the conclusion states it (with its evidence label and confidence), the
   report path, and any open questions. Deployment is not part of the lab yet (docs/ROADMAP.md).
