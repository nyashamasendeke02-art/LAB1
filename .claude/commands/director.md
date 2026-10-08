---
description: Research Director mode (master prompt s.29) -> decompose a research programme, delegate, monitor, challenge, replan, propose the next cycle
argument-hint: <research programme> [--lab labs/<name>]
---
Run the lab's `/director` mode for: $ARGUMENTS

1. Lab: the path after `--lab`, else `labs/workbench` (create it as in /research if missing).
2. Run in the background, logging to `<lab>-run.log`:
   `PYTHONIOENCODING=utf-8 .venv/Scripts/autolab.exe director <lab> "<programme>" --run`
   The Research Director plans work items (research and engineering, with dependencies); research items run as
   full projects; engineering items go to the Engineering Director; engineering failures are triaged into
   research questions; the Director reviews (continue / replan / retry / drop with reasons / complete / escalate).
3. Report with `.venv/Scripts/autolab.exe programme <lab> status <PRG-id>`: items, outcomes, the Director's
   decisions and any blockers that need the user.
