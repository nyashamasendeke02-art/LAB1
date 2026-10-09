"""Command-line interface.

    autolab init LAB                       create a lab (config, research repo, DB)
    autolab new LAB "Investigate whether X can produce Y" [--refs "H3,E4"]
    autolab task LAB "engineering spec" --accept "criterion" [--accept ...] [--refs "REQ-SAFE,Gate 0"]
                                           engineering track (no hypothesis)
    autolab mandate LAB                    mandate traceability: refs -> deliveries / conclusions
    autolab run LAB [PRJ] [--max-steps N]  advance autonomously until done/blocked/halted
    autolab step LAB [PRJ]                 advance one state-machine action
    autolab status LAB                     projects, states, pending approvals
    autolab ui LAB                         local project and approval dashboard
    autolab approvals LAB                  list pending approval gates
    autolab approve LAB APR-0001 [--note] [--as NAME]  gate decision (human, or a
                                           delegate named in lab.toml; delegates need --note)
    autolab reject LAB APR-0001 [--note] [--as NAME]
    autolab resume LAB PRJ --note "..."    human: leave HALTED and retry
    autolab halt LAB PRJ --note "..."      human: stop a project
    autolab show LAB RECORD [--protocol]   print a record (or just its protocol JSON)
    autolab amend LAB PRJ --file P.json --reason "..."   recorded protocol amendment
    autolab trace LAB RECORD               provenance lineage of any record
    autolab verify LAB                     check ledger hash chain + artifacts
    autolab export LAB [--json FILE]       regenerate project_state/*.md
    autolab demo LAB                       offline scripted end-to-end demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

from .controller import Controller, Lab
from .gates import Gates
from .memory import dump_json, export_markdown, format_trace, trace
from .store import ChainError


def _project(lab: Lab, pid: str | None) -> str:
    if pid:
        return pid
    projects = lab.store.query("project")
    if not projects:
        sys.exit("no projects; create one with `autolab new`")
    return projects[-1].id


def _refs(text: str) -> list[str]:
    return [r.strip() for r in text.split(",") if r.strip()]


def mandate_coverage(store) -> dict[str, list[str]]:
    """Mandate ref -> what the lab produced for it (projects, deliveries, conclusions)."""
    out: dict[str, list[str]] = {}
    for proj in store.query("project"):
        for ref in proj.data.get("mandate_refs", []):
            out.setdefault(ref, []).append(
                f"{proj.id} [{proj.data.get('kind', 'research')}] {proj.data['state']}: "
                f"{proj.data['objective'][:80]}")
    for dlv in store.query("delivery"):
        for ref in dlv.data.get("mandate_refs", []):
            out.setdefault(ref, []).append(f"{dlv.id} delivered at {dlv.data['commit'][:10]} "
                                           f"(review {dlv.data['review']})")
    for con in store.query("conclusion"):
        for ref in con.data.get("mandate_refs", []):
            out.setdefault(ref, []).append(f"{con.id} {con.data['outcome']} "
                                           f"({con.data['confidence']})")
    return out


def _print_step(s) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    took = f"{s.elapsed_s:>6.1f}s" if s.elapsed_s is not None else "       "
    line = f"{stamp} {took} {s.before:>22} -> {s.after:<22} {s.note}"
    if s.error:
        line += f"  ERROR: {s.error}"
    if s.blocked_on:
        line += f"  [blocked on {s.blocked_on}]"
    print(line, flush=True)


def _print_steps(steps) -> None:
    for s in steps:
        _print_step(s)


def _print_programme(co, prg: str) -> None:
    st = co.status(prg)
    rec = co.programme(prg).data
    print(f"{prg}  state={st['state']}  reviews={st['reviews']}  "
          f"halt={rec.get('halt_reason') or '-'}  blocked_on={rec.get('blocked_on') or '-'}")
    print(f"    {st['objective']}")
    for it in st["items"]:
        latest = it["latest"] or {}
        pad = "      " if it["parent"] else "    "
        spec = f"/{it['specialty']}" if it["specialty"] else ""
        print(f"{pad}{it['key']:20} [{it['kind']}{spec}] {it['status']:8} "
              f"{latest.get('project', '')} {latest.get('state', '')}  {it['objective'][:80]}")
    for dcs in st["decisions"]:
        print(f"    {dcs['stage']}: {dcs.get('decision', '')} {dcs.get('summary') or dcs.get('assessment', '')}"[:200])


def _programme_cmd(lab: Lab, a) -> int:
    from .coordination import Coordinator
    ctl = Controller(lab) if a.programme_cmd == "run" else Controller(lab, agents={})
    co = Coordinator(ctl)
    if a.programme_cmd == "new":
        print(co.new_programme(a.objective, _refs(a.refs)))
    elif a.programme_cmd == "run":
        steps = co.run(a.programme, a.max_steps,
                       on_step=lambda s: print(f"[{s.programme}] {s.before} -> {s.after}: {s.note}"
                                               + (f" ERROR {s.error}" if s.error else "")),
                       on_project_step=_print_step)
        _print_programme(co, a.programme)
        last = steps[-1] if steps else None
        return 0 if last and last.after == "COMPLETE" else 2 if last and last.blocked_on else 1
    elif a.programme_cmd == "resume":
        co.resume(a.programme, a.note)
        print(f"{a.programme} resumed (REVIEWING)")
    else:
        ids = [a.programme] if getattr(a, "programme", None) else [
            r.id for r in lab.store.query("programme")]
        for prg in ids:
            _print_programme(co, prg)
    return 0


def _mode_cmd(lab: Lab, a) -> int:
    """The five workflow modes. Each prints the id it created; --run executes it now."""
    from .coordination import Coordinator
    ctl = Controller(lab) if a.run else Controller(lab, agents={})
    if a.cmd in ("research", "project"):
        text = a.problem if a.cmd == "research" else a.objective
        pid = ctl.new_project(text, _refs(getattr(a, "refs", "")),
                              mode="plan" if a.cmd == "research" else "full",
                              autonomy_level=a.autonomy)
        print(pid)
        if a.run:
            steps = ctl.run(pid, on_step=_print_step)
            state = ctl.project(pid).data["state"]
            if a.cmd == "research" and state == "COMPLETE":
                rep = lab.store.get(ctl.project(pid).data["current"]["report"]).data
                print(f"research plan: {lab.root / rep['path']}")
            return 0 if state == "COMPLETE" else 2 if steps and steps[-1].blocked_on else 1
        return 0
    if a.cmd == "engineer":
        pid = ctl.new_engineering_project(a.spec, a.accept, _refs(a.refs), specialty=a.specialty,
                                          autonomy_level=a.autonomy)
        print(pid)
        if a.run:
            steps = ctl.run(pid, on_step=_print_step)
            state = ctl.project(pid).data["state"]
            return 0 if state == "COMPLETE" else 2 if steps and steps[-1].blocked_on else 1
        return 0
    co = Coordinator(ctl)
    if a.cmd == "director":
        prg = co.new_programme(a.programme_objective, _refs(a.refs))
    else:  # build: the Engineering Director takes the system as one engineering item
        prg = co.new_programme(a.system, _refs(a.refs), items=[{
            "key": "SYSTEM", "kind": "engineering", "objective": a.system,
            "acceptance_criteria": a.accept, "rationale": "build request", "priority": 1}])
    print(prg)
    if a.run:
        steps = co.run(prg, on_step=lambda s: print(f"[{s.programme}] {s.before} -> {s.after}: "
                                                     f"{s.note}"), on_project_step=_print_step)
        _print_programme(co, prg)
        last = steps[-1] if steps else None
        return 0 if last and last.after == "COMPLETE" else 2 if last and last.blocked_on else 1
    return 0


def _observe_cmd(lab: Lab, a) -> int:
    from .feedback import open_observations, triage
    if a.observe_cmd == "triage":
        ctl = Controller(lab)
        obs = open_observations(lab.store, set(a.project) if a.project else None)
        out = triage(ctl, obs, "cli" + (f" {','.join(a.project)}" if a.project else ""), a.max)
        print(f"{out['triage'] or 'nothing to triage'}: {out['counts']}")
        for q in out["questions"]:
            print(f"  {q}: {lab.store.get(q).data['question']}")
        for pat in out.get("patterns", []):
            print(f"  pattern: {pat}")
        return 0
    recs = lab.store.query("observation") if a.all else open_observations(lab.store)
    for o in recs:
        d = o.data
        print(f"{o.id}  [{d['status']}] {d['kind']}/{d['category']} {d['project']}"
              f"{'/' + d['specialty'] if d.get('specialty') else ''}  {d['summary'][:110]}")
    print(f"{len(recs)} observation(s)")
    return 0


def _knowledge_cmd(lab: Lab, a) -> int:
    ctl = Controller(lab, agents={})
    kn = ctl.knowledge
    for prob in kn.problems:
        print(f"PROBLEM: {prob}")
    g = kn.graph()
    if a.knowledge_cmd in (None, "stats"):
        st = g.stats()
        print(f"labs: {', '.join(st['labs'])}; {st['nodes']} nodes, {st['edges']} edges, "
              f"{st['open_questions']} open questions")
        for kind, n in st["by_kind"].items():
            print(f"  {kind:16} {n}")
    elif a.knowledge_cmd == "search":
        for score, n in g.search(a.text, a.k, tuple(a.kind) if a.kind else None):
            print(f"{score:6.2f}  lab:{n.lab}/{n.record_id:12} {n.kind:15} {n.status or '':14} "
                  f"{n.text[:110]}")
    elif a.knowledge_cmd == "questions":
        for n in g.open_questions():
            print(f"lab:{n.lab}/{n.record_id}  p{n.data.get('priority', '-')}  "
                  f"({n.project})  {n.data.get('question', '')[:140]}")
    elif a.knowledge_cmd == "show":
        lab_name, _, rid = a.node.removeprefix("lab:").partition("/")
        node = g.nodes.get(f"{lab_name}:{rid}")
        if node is None:
            print(f"no node {a.node}")
            return 1
        print(json.dumps(node.brief(4000), indent=2))
        nb = g.neighbours(node.id)
        for rel, dst in nb["out"]:
            print(f"  -{rel}-> {dst}")
        for src, rel in nb["in"]:
            print(f"  <-{rel}- {src}")
    elif a.knowledge_cmd == "spawn":
        try:
            pid = ctl.new_project_from_question(a.source, author=a.by)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(pid)
    return 0


def _agents_cmd(lab: Lab, a) -> int:
    from .registry import STAGE_BY_NAME, STAGES, Registry, RegistryError
    reg = Registry(lab.config, lab.root)
    if a.agents_cmd == "scorecard":
        from .scorecard import scorecards, totals
        cards = scorecards(lab.store)
        fmt = lambda v, unit="": "-" if v is None else f"{v}{unit}"  # noqa: E731
        print(f"{'agent':16} {'calls':>5} {'ok%':>5} {'rej':>4} {'avg s':>7} {'tokens in/out':>17} "
              f"{'cost $':>8}  reviews of code (pass/fail; findings C/M/m)   findings raised")
        for c in cards:
            rv, fc, fr = c["reviews_of_my_code"], c["findings_caused"], c["findings_raised"]
            tok = (f"{c['input_tokens']}/{c['output_tokens']}"
                   if c["input_tokens"] is not None else "-")
            print(f"{c['agent']:16} {c['calls']:>5} {fmt(round(100 * c['success_rate']) if c['success_rate'] is not None else None):>5} "
                  f"{c['protocol_rejections']:>4} {fmt(c['avg_wall_s']):>7} {tok:>17} "
                  f"{fmt(c['cost_usd']):>8}  {rv['passed']}/{rv['failed']}; "
                  f"{fc['critical']}/{fc['major']}/{fc['minor']}{'':>25}"
                  f"{fr['critical']}/{fr['major']}/{fr['minor']}")
        t = totals(cards)
        print(f"\nlab: {t['calls']} calls, {t['errors']} errors, {t['wall_s']} s agent time; "
              f"tokens/cost reported for {t['usage_reported_calls']} calls: "
              f"in {fmt(t['input_tokens'])}, out {fmt(t['output_tokens'])}, ${fmt(t['cost_usd'])}")
        return 0
    try:
        if a.agents_cmd == "preset":
            print("created: " + ", ".join(reg.apply_preset(a.name)))
        elif a.agents_cmd == "set":
            spec = {k: v for k, v in {
                "backend": a.backend, "model": a.model, "title": a.title, "charter": a.charter,
                "effort": a.effort, "backup_backend": a.backup_backend,
                "backup_model": a.backup_model, "timeout": a.timeout}.items() if v is not None}
            reg.upsert(a.name, spec)
            print(f"agent {a.name} saved")
        elif a.agents_cmd == "allocate":
            reg.allocate({a.stage: a.agent})
            print(f"{a.stage} -> {reg.resolve(a.stage, STAGE_BY_NAME[a.stage].role)}")
        elif a.agents_cmd == "remove":
            reg.remove(a.name)
            print(f"agent {a.name} removed")
    except RegistryError as exc:
        print(f"error: {exc}")
        return 1
    for name, spec in sorted(reg.agents.items()):
        print(f"{name:22} {spec.get('backend') or '-':12} {spec.get('model') or 'default':24} "
              f"{spec.get('title', '')}")
    print()
    for st in STAGES:
        print(f"  {st.plane:15} {st.name:22} [{st.role.value:9}] -> {reg.resolve(st.name, st.role)}")
    for prob in reg.problems():
        print(f"PROBLEM: {prob}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # User objectives may contain characters outside the active Windows code
    # page. Escape those characters instead of crashing the status command.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(prog="autolab", description="Autonomous Research Lab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("lab")
    p = sub.add_parser("new")
    p.add_argument("lab")
    p.add_argument("objective")
    p.add_argument("--refs", default="")
    p = sub.add_parser("task")
    p.add_argument("lab")
    p.add_argument("spec")
    p.add_argument("--accept", action="append", required=True)
    p.add_argument("--refs", default="")
    sub.add_parser("mandate").add_argument("lab")
    p = sub.add_parser("queue")
    p.add_argument("lab")
    p.add_argument("file")
    p.add_argument("--as", dest="by", default="claude-code")
    p.add_argument("--retry", action="append", default=[],
                   help="task id whose HALTED project should be submitted again")
    for name in ("run", "step"):
        p = sub.add_parser(name)
        p.add_argument("lab")
        p.add_argument("project", nargs="?")
        p.add_argument("--max-steps", type=int, default=500)
    sub.add_parser("status").add_argument("lab")
    sub.add_parser("approvals").add_argument("lab")
    sub.add_parser("tui", help="interactive terminal UI for a lab (needs: pip install autolab[tui])"
                   ).add_argument("lab")
    p = sub.add_parser("ui", help="open a local web dashboard for a lab")
    p.add_argument("lab")
    p.add_argument("--host", default="127.0.0.1", help="loopback IP address (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="default: [ui] port in lab.toml")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("lab")
        p.add_argument("approval")
        p.add_argument("--note", default="")
        p.add_argument("--as", dest="by", default="human")
    p = sub.add_parser("resume")
    p.add_argument("lab")
    p.add_argument("project")
    p.add_argument("--note", required=True)
    p = sub.add_parser("halt")
    p.add_argument("lab")
    p.add_argument("project")
    p.add_argument("--note", required=True)
    p = sub.add_parser("show")
    p.add_argument("lab")
    p.add_argument("record")
    p.add_argument("--protocol", action="store_true")
    p = sub.add_parser("amend")
    p.add_argument("lab")
    p.add_argument("project")
    p.add_argument("--file", required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("trace")
    p.add_argument("lab")
    p.add_argument("record")
    p.add_argument("--json", action="store_true")
    sub.add_parser("verify").add_argument("lab")
    p = sub.add_parser("export")
    p.add_argument("lab")
    p.add_argument("--json", dest="json_path")
    sub.add_parser("demo").add_argument("lab")
    p = sub.add_parser("agents", help="list, create and allocate agents (models) to stages")
    p.add_argument("lab")
    asub = p.add_subparsers(dest="agents_cmd")
    asub.add_parser("list")
    asub.add_parser("scorecard", help="evidence per agent: success, time, tokens, cost, reviews")
    q = asub.add_parser("preset", help="create the research/engineering organisation")
    q.add_argument("name", nargs="?", default="organisation")
    q = asub.add_parser("set", help="create or update an agent")
    q.add_argument("name")
    q.add_argument("--backend", required=True)
    for opt in ("model", "title", "charter", "effort", "backup-backend", "backup-model"):
        q.add_argument(f"--{opt}")
    q.add_argument("--timeout", type=float)
    q = asub.add_parser("allocate", help="assign a stage to an agent ('' = role default)")
    q.add_argument("stage")
    q.add_argument("agent")
    q = asub.add_parser("remove")
    q.add_argument("name")
    p = sub.add_parser("programme", help="hierarchical coordination: programmes of projects")
    p.add_argument("lab")
    psub = p.add_subparsers(dest="programme_cmd")
    q = psub.add_parser("new", help="submit a programme objective")
    q.add_argument("objective")
    q.add_argument("--refs", default="")
    q = psub.add_parser("run", help="run a programme until it completes, halts or needs a human")
    q.add_argument("programme")
    q.add_argument("--max-steps", type=int, default=200)
    q = psub.add_parser("status")
    q.add_argument("programme", nargs="?")
    q = psub.add_parser("resume", help="resume a HALTED programme (human)")
    q.add_argument("programme")
    q.add_argument("--note", required=True)
    # Workflow modes (master prompt sections 26-30); each submits, and with --run executes.
    p = sub.add_parser("research", help="/research: plan-only research -> saved research plan")
    p.add_argument("lab")
    p.add_argument("problem")
    p.add_argument("--run", action="store_true")
    p = sub.add_parser("engineer", help="/engineer: engineering workflow for one spec")
    p.add_argument("lab")
    p.add_argument("spec")
    p.add_argument("--accept", action="append", required=True)
    p.add_argument("--specialty")
    p.add_argument("--refs", default="")
    p.add_argument("--run", action="store_true")
    p = sub.add_parser("project", help="/project: full research -> design -> implement -> test "
                                       "-> evaluate -> iterate pipeline")
    p.add_argument("lab")
    p.add_argument("objective")
    p.add_argument("--refs", default="")
    p.add_argument("--run", action="store_true")
    p = sub.add_parser("director", help="/director: Research Director runs a research programme")
    p.add_argument("lab")
    p.add_argument("programme_objective")
    p.add_argument("--refs", default="")
    p.add_argument("--run", action="store_true")
    p = sub.add_parser("build", help="/build: Engineering Director builds a system")
    p.add_argument("lab")
    p.add_argument("system")
    p.add_argument("--accept", action="append", required=True)
    p.add_argument("--refs", default="")
    p.add_argument("--run", action="store_true")
    for name in ("research", "engineer", "project"):
        sub.choices[name].add_argument("--autonomy", type=int, default=None,
                                       help="autonomy level 0-5 for this project (<= lab max)")
    p = sub.add_parser("manifest", help="project.yaml: export a project's structure, or import one")
    p.add_argument("lab")
    msub = p.add_subparsers(dest="manifest_cmd")
    q = msub.add_parser("export")
    q.add_argument("project")
    q.add_argument("--out", default=None, help="default: <lab>/projects")
    q = msub.add_parser("import")
    q.add_argument("file")
    q.add_argument("--run", action="store_true")
    p = sub.add_parser("observe", help="engineering failures -> research observations -> questions")
    p.add_argument("lab")
    osub = p.add_subparsers(dest="observe_cmd")
    q = osub.add_parser("list")
    q.add_argument("--all", action="store_true", help="include triaged observations")
    q = osub.add_parser("triage", help="have a research agent triage open observations")
    q.add_argument("--project", action="append", help="only observations of these projects")
    q.add_argument("--max", type=int, default=30)
    p = sub.add_parser("knowledge", help="the lab's knowledge graph: search, questions, spawn")
    p.add_argument("lab")
    ksub = p.add_subparsers(dest="knowledge_cmd")
    ksub.add_parser("stats")
    q = ksub.add_parser("search")
    q.add_argument("text")
    q.add_argument("-k", type=int, default=10)
    q.add_argument("--kind", action="append", help="limit to a record kind (repeatable)")
    ksub.add_parser("questions", help="open future questions, ranked")
    q = ksub.add_parser("show", help="a node and its edges")
    q.add_argument("node", help="lab:RECORD-ID")
    q = ksub.add_parser("spawn", help="start a research project from an open question")
    q.add_argument("source", help="lab:FQ-NNNN")
    q.add_argument("--as", dest="by", default="human")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        lab = Lab.init(a.lab)
        print(f"initialised lab at {lab.root}\nedit {lab.config_path} to choose agent backends")
        return 0
    if a.cmd == "demo":
        from .demo import DEMO_OBJECTIVE, demo_agents
        lab = Lab.init(a.lab)
        ctl = Controller(lab, demo_agents())
        pid = ctl.new_project(DEMO_OBJECTIVE)
        print(f"[demo] scripted agents, no LLM calls. project {pid}")
        ctl.run(pid, on_step=_print_step)
        print(f"\nreports: {lab.reports}\nstate:   {lab.exports}")
        return 0

    lab = Lab(a.lab)
    if a.cmd == "agents":
        return _agents_cmd(lab, a)
    if a.cmd == "knowledge":
        return _knowledge_cmd(lab, a)
    if a.cmd == "programme":
        return _programme_cmd(lab, a)
    if a.cmd == "observe":
        return _observe_cmd(lab, a)
    if a.cmd == "manifest":
        from .manifest import export_project, import_project
        if a.manifest_cmd == "export":
            print(export_project(lab, a.project, Path(a.out) if a.out else lab.root / "projects"))
            return 0
        ctl = Controller(lab) if a.run else Controller(lab, agents={})
        pid = import_project(ctl, Path(a.file))
        print(pid)
        if a.run:
            steps = ctl.run(pid, on_step=_print_step)
            return 0 if ctl.project(pid).data["state"] == "COMPLETE" else 1
        return 0
    if a.cmd in ("research", "engineer", "project", "director", "build"):
        return _mode_cmd(lab, a)
    if a.cmd == "tui":
        try:
            from .tui import run as run_tui
        except ImportError:
            print("The terminal UI needs Textual: pip install textual  (or pip install -e .[tui])")
            return 1
        run_tui(lab.root)
        return 0
    if a.cmd == "ui":
        from .web import DashboardServer
        port = a.port or int(lab.config.get("ui", {}).get("port") or 8765)
        DashboardServer(lab, a.host, port).serve_forever()
    elif a.cmd == "new":
        pid = Controller(lab, agents={}).new_project(a.objective, _refs(a.refs))
        print(pid)
    elif a.cmd == "task":
        pid = Controller(lab, agents={}).new_engineering_project(a.spec, a.accept, _refs(a.refs))
        print(pid)
    elif a.cmd == "queue":
        from .queue import load_queue, run_queue
        out = run_queue(Controller(lab), load_queue(a.file), author=a.by,
                        on_step=_print_step, retry=set(a.retry))
        print(f"QUEUE {out.status.upper()}"
              + (f": {out.task_id} {out.project} {out.detail}" if out.task_id else ""))
        return {"done": 0, "blocked": 2}.get(out.status, 1)
    elif a.cmd == "mandate":
        for ref, items in sorted(mandate_coverage(lab.store).items()):
            print(ref)
            for line in items:
                print(f"    {line}")
    elif a.cmd in ("run", "step"):
        ctl = Controller(lab)
        pid = _project(lab, a.project)
        if a.cmd == "run":
            ctl.run(pid, a.max_steps, on_step=_print_step)
        else:
            _print_steps([ctl.step(pid)])
    elif a.cmd == "status":
        for proj in lab.store.query("project"):
            d = proj.data
            print(f"{proj.id}  [{d.get('kind', 'research')}]  state={d['state']}  cycle={d['cycle']}  "
                  f"blocked_on={d.get('blocked_on') or '-'}  halt={d.get('halt_reason') or '-'}")
            print(f"    {d['objective']}")
        for apr in Gates(lab.store).pending():
            print(f"PENDING {apr.id}: {apr.data['gate']} on {apr.data['subject']} -- "
                  f"{apr.data['summary']}")
    elif a.cmd == "approvals":
        for apr in Gates(lab.store).pending():
            print(f"{apr.id}: {apr.data['gate']} on {apr.data['subject']}\n  {apr.data['summary']}")
            print("  details:", json.dumps(apr.data["details"])[:2000])
    elif a.cmd in ("approve", "reject"):
        from .autonomy import delegation
        rec = Gates(lab.store, delegation(lab.config)).decide(
            a.approval, a.cmd == "approve", by=a.by, note=a.note)
        print(f"{rec.id}: {rec.data['status']}")
    elif a.cmd == "resume":
        Controller(lab, agents={}).resume(a.project, a.note)
        print(f"{a.project} resumed")
    elif a.cmd == "halt":
        Controller(lab, agents={}).halt(a.project, a.note)
        print(f"{a.project} halted")
    elif a.cmd == "show":
        rec = lab.store.get(a.record)
        if a.protocol:
            print(json.dumps(rec.data["protocol"], indent=2, sort_keys=True))
        else:
            print(json.dumps({"id": rec.id, "version": rec.version, "kind": rec.kind,
                              "author": rec.author, "reason": rec.reason,
                              "data": rec.data}, indent=2, default=str))
    elif a.cmd == "amend":
        with open(a.file, encoding="utf-8") as fh:
            new_protocol = json.load(fh)
        rec = Controller(lab, agents={}).amend_protocol(a.project, new_protocol, a.reason)
        kind = rec.data["protocol"]["kind"]
        print(f"{rec.id} amended to v{rec.version} (kind={kind}, "
              f"downgraded_after_data={rec.data['downgraded_after_data']}); "
              f"`autolab resume` re-enters ENGINEERING")
    elif a.cmd == "trace":
        tree = trace(lab.store, a.record)
        print(json.dumps(tree, indent=2) if a.json else format_trace(tree))
    elif a.cmd == "verify":
        try:
            n = lab.store.verify_chain()
        except ChainError as exc:
            print(f"LEDGER INVALID: {exc}")
            return 1
        bad = []
        for kind in ("run", "task", "report", "review"):
            for rec in lab.store.query(kind):
                for v in rec.data.get("refs", {}).values():
                    for ref in ([v] if isinstance(v, str) else v if isinstance(v, list) else []):
                        if isinstance(ref, str) and ref.startswith("sha256:"):
                            try:
                                lab.artifacts.get_bytes(ref[7:])
                            except Exception as exc:  # missing or corrupted
                                bad.append(f"{rec.id}: {ref[:20]} {exc}")
        if bad:
            print("ARTIFACT PROBLEMS:\n" + "\n".join(bad))
            return 1
        anchored, missing = lab.verify_anchors()
        if missing:
            print("LEDGER/GIT ANCHOR MISMATCH:")
            for m in missing:
                print("  " + m)
            return 1
        print(f"ledger OK ({n} events); referenced artifacts intact; "
              f"{anchored} git anchors match")
    elif a.cmd == "export":
        for p in export_markdown(lab.store, lab.exports):
            print(p)
        if a.json_path:
            print(dump_json(lab.store, a.json_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
