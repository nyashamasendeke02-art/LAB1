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
    p = sub.add_parser("ui", help="open a local web dashboard for a lab")
    p.add_argument("lab")
    p.add_argument("--host", default="127.0.0.1", help="loopback IP address (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765)
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
    if a.cmd == "ui":
        from .web import DashboardServer
        DashboardServer(lab, a.host, a.port).serve_forever()
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
        rec = Gates(lab.store, lab.config["gates"].get("delegation")).decide(
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
