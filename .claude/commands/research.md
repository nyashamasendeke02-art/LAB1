---
description: Plan-only research (master prompt s.26) -> problem, literature, knowledge, state of the art, gaps, hypotheses, experiment proposals, saved research plan
argument-hint: <problem> [--lab labs/<name>]
---
Run the lab's `/research` workflow for: $ARGUMENTS

1. Lab: use the path after `--lab` if given, else `labs/workbench`. If that lab does not exist, create it with
   `.venv/Scripts/autolab.exe init labs/workbench` and give it working agents with
   `.venv/Scripts/autolab.exe agents labs/workbench preset claude-strengths`.
2. Run it in the background (it calls agents and takes minutes), logging to `<lab>-run.log`:
   `PYTHONIOENCODING=utf-8 .venv/Scripts/autolab.exe research <lab> "<problem>" --run`
3. When it finishes, read the research plan file it prints (`reports/PRJ-*-research-plan.md` in the lab) and
   summarise for the user: question, hypotheses, chosen experiment, the critic's issues, and which claims are
   verified vs unverified. If it HALTed or blocked, say why from `autolab status <lab>`.
Never claim results the plan does not contain; a research plan contains no experimental results.
