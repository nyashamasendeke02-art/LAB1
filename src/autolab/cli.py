"""Command-line interface.

    autolab init LAB                       create a lab (config, research repo, DB)
    autolab new LAB "Investigate whether X can produce Y"
    autolab run LAB [PRJ] [--max-steps N]  advance autonomously until done/blocked/halted
    autolab step LAB [PRJ]                 advance one state-machine action
    autolab status LAB                     projects, states, pending approvals
    autolab approvals LAB                  list pending approval gates
    autolab approve LAB APR-0001 [--note]  human decision (gates)
    autolab reject LAB APR-0001 [--note]
    autolab resume LAB PRJ --note "..."    human: leave HALTED and retry
    autolab trace LAB RECORD               provenance lineage of any record
    autolab verify LAB                     check ledger hash chain + artifacts
    autolab export LAB [--json FILE]       regenerate project_state/*.md
    autolab demo LAB                       offline scripted end-to-end demo
"""

from __future__ import annotations

import argparse
import json
import sys

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


def _print_steps(steps) -> None:
    for s in steps:
        line = f"{s.before:>22} -> {s.after:<22} {s.note}"
        if s.error:
            line += f"  ERROR: {s.error}"
        if s.blocked_on:
            line += f"  [blocked on {s.blocked_on}]"
        print(line)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="autolab", description="Autonomous Research Lab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("lab")
    p = sub.add_parser("new")
    p.add_argument("lab")
    p.add_argument("objective")
    for name in ("run", "step"):
        p = sub.add_parser(name)
        p.add_argument("lab")
        p.add_argument("project", nargs="?")
        p.add_argument("--max-steps", type=int, default=500)
    sub.add_parser("status").add_argument("lab")
    sub.add_parser("approvals").add_argument("lab")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("lab")
        p.add_argument("approval")
        p.add_argument("--note", default="")
    p = sub.add_parser("resume")
    p.add_argument("lab")
    p.add_argument("project")
    p.add_argument("--note", required=True)
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
        _print_steps(ctl.run(pid))
        print(f"\nreports: {lab.reports}\nstate:   {lab.exports}")
        return 0

    lab = Lab(a.lab)
    if a.cmd == "new":
        pid = Controller(lab, agents={}).new_project(a.objective)
        print(pid)
    elif a.cmd in ("run", "step"):
        ctl = Controller(lab)
        pid = _project(lab, a.project)
        _print_steps(ctl.run(pid, a.max_steps) if a.cmd == "run" else [ctl.step(pid)])
    elif a.cmd == "status":
        for proj in lab.store.query("project"):
            d = proj.data
            print(f"{proj.id}  state={d['state']}  cycle={d['cycle']}  "
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
        rec = Gates(lab.store).decide(a.approval, a.cmd == "approve", by="human", note=a.note)
        print(f"{rec.id}: {rec.data['status']}")
    elif a.cmd == "resume":
        Controller(lab, agents={}).resume(a.project, a.note)
        print(f"{a.project} resumed")
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
        print(f"ledger OK ({n} events); referenced artifacts intact")
    elif a.cmd == "export":
        for p in export_markdown(lab.store, lab.exports):
            print(p)
        if a.json_path:
            print(dump_json(lab.store, a.json_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
