"""The controller / orchestrator.

The controller owns the authoritative state. Each :meth:`Controller.step`
performs exactly one state-machine action for a project:

* dispatches a task packet to one agent (scientist / engineer / verifier) and
  validates its completion, or
* performs a mechanical action itself (commit, test, merge, run, analyse,
  evaluate), and then
* records everything (records + hash-chained events + artifacts) and makes at
  most one transition, as the *last* action of the handler.

Failures are recorded, retried up to ``max_stage_retries``, then the project
HALTs for a human. A fresh Controller can resume any project from the DB.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .agents import Agent, make_backend
from .config import DEFAULT_TOML, load_config
from .experiments import (Trial, contrasts, environment_snapshot, evaluate_decision,
                          evaluate_requirements, run_protocol, summarize)
from .gates import (COMPUTE_BUDGET, CONFIRMATORY_FREEZE, MERGE_TO_MAIN,
                    PROTECTED_EXPERIMENT, Gates)
from .memory import export_markdown
from .messages import TaskPacket, validate_protocol
from .report import build_report
from .state_machines import (EngineeringState as E, ResearchState as R,
                             check_engineering, check_research)
from .store import ArtifactStore, Record, Store, canonical
from .taxonomy import Evidence, Outcome, Role, validate_claim
from .worktrees import AgentIdentity, GitError, GitRepo, path_violations

IDENTITIES = {
    Role.ENGINEER: AgentIdentity("claude-engineer", "engineer@autolab.local"),
    Role.VERIFIER: AgentIdentity("codex-verifier", "verifier@autolab.local"),
    Role.CONTROLLER: AgentIdentity("autolab-controller", "controller@autolab.local"),
}

DEFAULT_REPO_FILES = {
    "README.md": "# Research code\n\nManaged by the Autonomous Research Lab controller.\n"
                 "`main` changes only through controller merges.\n",
    ".gitignore": "__pycache__/\n*.py[cod]\n.pytest_cache/\n",
    "conftest.py": "# repo root on sys.path for tests\n",
    "protocols/README.md": "Frozen experiment protocols (controller-owned; agents may not edit).\n",
    "tests/verification/README.md": "Independent verification tests (verifier-owned).\n",
    "AGENTS.md": (
        "# Rules for agents working in this repository\n\n"
        "This repository is managed by the Autonomous Research Lab controller.\n\n"
        "- Do not run git; the controller commits your changes with provenance.\n"
        "- `protocols/` holds frozen, pre-registered protocols: never edit.\n"
        "- `tests/verification/` belongs to the independent verifier: the engineer must not "
        "edit it; the verifier may ONLY edit it.\n"
        "- Entrypoint contract: `<entrypoint> --condition NAME --seed N --out DIR --params JSON`"
        " writes `DIR/metrics.json` (flat object of finite numbers), deterministic given the seed.\n"
        "- Tests run with `python -m pytest -q` from the repo root and are required.\n"
        "- Never change code, tests or metrics to make a hypothesis look supported.\n"),
}

TERMINAL = {R.COMPLETE, R.HALTED}


class StageError(Exception):
    """A recoverable failure inside a stage handler."""


@dataclass
class StepResult:
    project: str
    before: str
    after: str
    note: str = ""
    error: str | None = None
    blocked_on: str | None = None
    elapsed_s: float | None = None


def _tail(text: str, n: int = 4000) -> str:
    return text if len(text) <= n else "...[truncated]...\n" + text[-n:]


# ====================================================================== Lab
class Lab:
    """Filesystem layout of one lab instance."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.config_path = self.root / "lab.toml"
        self.state_dir = self.root / ".autolab"
        self.repo_path = self.root / "repo"
        self.worktrees = self.root / "worktrees"
        self.runs = self.root / "runs"
        self.reports = self.root / "reports"
        self.handoffs = self.state_dir / "handoffs"
        self.exports = self.root / "project_state"
        if not self.config_path.exists():
            raise FileNotFoundError(f"{self.root} is not an autolab lab (no lab.toml)")
        self.config = load_config(self.config_path)
        self.store = Store(self.state_dir / "lab.db")
        self.artifacts = ArtifactStore(self.state_dir / "artifacts")
        self.repo = GitRepo(self.repo_path)

    @classmethod
    def init(cls, root: str | Path, config_text: str | None = None,
             repo_files: dict[str, str] | None = None) -> "Lab":
        root = Path(root).resolve()
        if (root / "lab.toml").exists():
            raise FileExistsError(f"{root} already contains a lab")
        root.mkdir(parents=True, exist_ok=True)
        (root / "lab.toml").write_text(config_text or DEFAULT_TOML, encoding="utf-8")
        files = dict(DEFAULT_REPO_FILES)
        files.update(repo_files or {})
        GitRepo.init(root / "repo", files)
        for d in ("worktrees", "runs", "reports", ".autolab/handoffs"):
            (root / d).mkdir(parents=True, exist_ok=True)
        lab = cls(root)
        lab.store.append_event("human", "lab.initialized", "LAB",
                               {"version": __version__, "repo_head": lab.repo.rev("main")})
        return lab

    def close(self) -> None:
        self.store.close()

    def verify_anchors(self) -> tuple[int, list[str]]:
        """Check every ledger head anchored in main's commit trailers exists in the DB chain."""
        log = self.repo.git("log", "main",
                            "--format=@@COMMIT %H%n%(trailers:key=Autolab-Ledger-Head,valueonly)")
        checked, missing, sha = 0, [], ""
        for line in log.splitlines():
            line = line.strip()
            if line.startswith("@@COMMIT "):
                sha = line.split()[1]
            elif line:
                checked += 1
                if not self.store.has_event_hash(line):
                    missing.append(f"commit {sha[:10]} anchors unknown ledger head {line[:16]}")
        return checked, missing


# =============================================================== Controller
class Controller:
    def __init__(self, lab: Lab, agents: dict[Role, Agent] | None = None):
        self.lab = lab
        self.store = lab.store
        self.repo = lab.repo
        self.cfg = lab.config
        self.limits = self.cfg["limits"]
        self.gates = Gates(self.store)
        if agents is None:
            agents = {role: Agent(role, make_backend(self.cfg["agents"][role.value]))
                      for role in (Role.SCIENTIST, Role.ENGINEER, Role.VERIFIER)}
        self.agents = agents

    # ------------------------------------------------------------ projects
    def new_project(self, objective: str) -> str:
        rec = self.store.create("project", {
            "objective": objective, "state": R.DEFINE_PROBLEM.value, "cycle": 1,
            "current": {}, "retries": {}, "design_iterations": 0, "feedback": [],
            "blocked_on": None, "halt_reason": None, "halted_from": None, "refs": {},
        }, prefix="PRJ", author="human", reason="research objective submitted")
        self._export()
        return rec.id

    def project(self, pid: str) -> Record:
        return self.store.get(pid)

    def _set(self, pid: str, reason: str, **changes) -> Record:
        return self.store.update(pid, changes, reason=reason)

    def _cur(self, pid: str) -> dict:
        return dict(self.project(pid).data.get("current", {}))

    def _transition(self, pid: str, target: R, reason: str, pointers: dict | None = None,
                    **changes) -> None:
        proj = self.project(pid)
        cur = R(proj.data["state"])
        check_research(cur, target)
        current = {**proj.data.get("current", {}), **(pointers or {})}
        self.store.update(pid, {"state": target.value, "current": current, "retries": {},
                                **changes}, reason=f"{cur.value} -> {target.value}: {reason}")
        self.store.append_event("controller", "research.transition", pid,
                                {"from": cur.value, "to": target.value, "reason": reason})

    def _halt(self, pid: str, reason: str) -> None:
        state = self.project(pid).data["state"]
        self._transition(pid, R.HALTED, reason, halt_reason=reason, halted_from=state)

    def resume(self, pid: str, note: str, by: str = "human") -> None:
        """Human action: leave HALTED and retry the state that halted."""
        proj = self.project(pid)
        if proj.data["state"] != R.HALTED.value:
            raise ValueError(f"{pid} is not halted")
        if by != "human":
            raise PermissionError("only the human researcher can resume a halted project")
        target = proj.data["halted_from"]
        self.store.update(pid, {"state": target, "retries": {}, "halt_reason": None,
                                "halted_from": None, "design_iterations": 0
                                if target == R.DESIGN.value else proj.data["design_iterations"]},
                          author=by, reason=f"resumed by human: {note}")
        self.store.append_event(by, "research.resumed", pid, {"to": target, "note": note})

    def halt(self, pid: str, note: str, by: str = "human") -> None:
        """Human action: stop a running project (e.g. to amend its protocol)."""
        if by != "human":
            raise PermissionError("only the human researcher can halt a project")
        state = R(self.project(pid).data["state"])
        if state in TERMINAL:
            raise ValueError(f"{pid} is {state.value}")
        self._halt(pid, f"halted by human: {note}")

    POST_FREEZE = {R.ENGINEERING, R.SCIENTIFIC_VALIDATION, R.RUN_EXPERIMENT, R.ANALYZE,
                   R.CHALLENGE, R.EVALUATE, R.COMMUNICATE, R.NEXT_QUESTION}

    def amend_protocol(self, pid: str, protocol: dict, reason: str, by: str = "human") -> Record:
        """Recorded amendment of the current frozen protocol (human-only, while HALTED).

        * the amendment is stored via Store.amend (justification + new freeze hash);
        * if any run already used this protocol, a confirmatory protocol is
          downgraded to exploratory -- post-data changes cannot stay confirmatory;
        * the amended protocol is committed to the research repo;
        * on resume the project re-enters ENGINEERING with a new task so the
          implementation is re-verified against the amended protocol.
        """
        if by != "human":
            raise PermissionError("only the human researcher can amend a frozen protocol")
        if not reason or not reason.strip():
            raise ValueError("an amendment needs a justification")
        proj = self.project(pid)
        if proj.data["state"] != R.HALTED.value:
            raise ValueError(f"{pid} must be HALTED to amend its protocol (use halt)")
        if R(proj.data["halted_from"]) not in self.POST_FREEZE:
            raise ValueError("project is before protocol freeze; revise the design instead")
        prot = self.store.get(proj.data["current"]["protocol"])
        if not prot.frozen:
            raise ValueError(f"{prot.id} is not frozen")
        errs = validate_protocol(protocol)
        if errs:
            raise ValueError("invalid amended protocol: " + "; ".join(errs))
        has_data = any(r.data["refs"]["protocol"] == prot.id for r in self.store.query("run"))
        downgraded = bool(prot.data.get("downgraded_after_data"))
        if has_data and protocol["kind"] == "confirmatory":
            protocol = {**protocol, "kind": "exploratory"}
            downgraded = True
        rec = self.store.amend(prot.id, {"protocol": protocol,
                                         "downgraded_after_data": downgraded},
                               author=by, reason=reason)
        rel = f"protocols/{prot.id}.json"
        (self.repo.path / rel).write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
        self.repo.commit_all(self.repo.path, f"Amend protocol {prot.id} (v{rec.version})",
                             IDENTITIES[Role.CONTROLLER],
                             {"Autolab-Protocol": f"{prot.id}@{rec.data['_freeze_hash'][:16]}",
                              "Autolab-Amendment": reason[:200], "Autolab-Project": pid,
                              "Autolab-Ledger-Head": self.store.head()})
        eng = self._new_eng_task(pid, prot.id, [
            f"Protocol {prot.id} amended to v{rec.version} ({reason}). Update the "
            f"implementation so it satisfies the amended protocol exactly."])
        self.store.update(pid, {"halted_from": R.ENGINEERING.value,
                                "current": {**proj.data["current"], "eng_task": eng.id},
                                "design_iterations": proj.data["design_iterations"]},
                          author=by, reason=f"protocol amended ({prot.id} v{rec.version}); "
                                            f"resume re-enters ENGINEERING")
        self.store.append_event(by, "protocol.amended", prot.id,
                                {"version": rec.version, "reason": reason,
                                 "downgraded_after_data": downgraded, "had_data": has_data})
        self._export()
        return rec

    def _feedback(self, pid: str, text: str) -> None:
        fb = list(self.project(pid).data.get("feedback", []))[-9:] + [text]
        self._set(pid, "feedback recorded", feedback=fb)

    def _failure(self, pid: str, category: str, summary: str, refs: dict | None = None,
                 details: dict | None = None) -> Record:
        rec = self.store.create("failure", {
            "project": pid, "category": category, "summary": summary,
            "details": details or {}, "refs": refs or {},
            "state": self.project(pid).data["state"],
        }, prefix="FAIL", reason=f"failure recorded: {category}")
        return rec

    def _block(self, pid: str, approval: Record) -> str:
        self._set(pid, f"blocked on {approval.id}", blocked_on=approval.id)
        return f"awaiting human approval {approval.id} ({approval.data['gate']})"

    def _gate(self, pid: str, gate: str, subject: str, summary: str,
              details: dict | None = None) -> tuple[str, Record]:
        """Return ('approved'|'rejected'|'pending', record); request if absent."""
        apr = self.gates.find(gate, subject)
        if apr is None:
            apr = self.gates.request(gate, subject, summary, details, project=pid)
        return apr.data["status"], apr

    # --------------------------------------------------------------- loop
    def step(self, pid: str) -> StepResult:
        proj = self.project(pid)
        state = R(proj.data["state"])
        if state in TERMINAL:
            return StepResult(pid, state.value, state.value, "terminal state")
        blocked = proj.data.get("blocked_on")
        if blocked:
            apr = self.store.get(blocked)
            if apr.data["status"] == "pending":
                return StepResult(pid, state.value, state.value, "blocked", blocked_on=blocked)
            self._set(pid, f"approval {blocked} decided: {apr.data['status']}", blocked_on=None)
        handler = getattr(self, f"_h_{state.value.lower()}")
        try:
            note = handler(pid) or ""
        except Exception as exc:  # recorded, retried, then HALT
            return self._stage_failed(pid, state, exc)
        after = self.project(pid)
        self._export()
        return StepResult(pid, state.value, after.data["state"], note,
                          blocked_on=after.data.get("blocked_on"))

    def _stage_failed(self, pid: str, state: R, exc: Exception) -> StepResult:
        proj = self.project(pid)
        retries = dict(proj.data.get("retries", {}))
        retries[state.value] = retries.get(state.value, 0) + 1
        msg = f"{type(exc).__name__}: {exc}"
        self._failure(pid, "stage_error", f"{state.value}: {msg}"[:500],
                      details={"traceback": traceback.format_exc()[-6000:]})
        self._set(pid, f"stage error in {state.value} (attempt {retries[state.value]})",
                  retries=retries)
        if retries[state.value] > self.limits["max_stage_retries"]:
            self._halt(pid, f"{state.value} failed {retries[state.value]} times; last: {msg}"[:500])
        self._export()
        return StepResult(pid, state.value, self.project(pid).data["state"], "", error=msg)

    def run(self, pid: str, max_steps: int = 500,
            on_step: Callable[[StepResult], None] | None = None) -> list[StepResult]:
        out: list[StepResult] = []
        for _ in range(max_steps):
            t0 = time.perf_counter()
            res = self.step(pid)
            res.elapsed_s = round(time.perf_counter() - t0, 1)
            out.append(res)
            if on_step:
                on_step(res)
            if res.after in (R.COMPLETE.value, R.HALTED.value) or res.blocked_on:
                break
        return out

    def _export(self) -> None:
        export_markdown(self.store, self.lab.exports)

    # -------------------------------------------------------- agent calls
    def _constraints(self, role: Role) -> list[str]:
        eng = self.cfg["engineering"]
        common = ["Do not run git commands; the controller commits.",
                  "Never fabricate sources, data or results."]
        if role == Role.ENGINEER:
            return common + [f"Do not modify: {', '.join(eng['protected_paths'])}"]
        if role == Role.VERIFIER:
            return common + [f"Only add/modify files matching: {', '.join(eng['verifier_allowed_paths'])}"]
        return common + ["Read-only role: do not modify files."]

    def _call(self, pid: str, role: Role, stage: str, context: dict, *,
              workdir: Path | None = None, writable: bool = False) -> tuple[dict, str]:
        proj = self.project(pid)
        task_id = self.store.next_id("TASK")
        packet = TaskPacket(task_id=task_id, role=role, stage=stage,
                            objective=proj.data["objective"],
                            context={"project": pid, "cycle": proj.data["cycle"], **context},
                            constraints=self._constraints(role),
                            workdir=str(workdir) if workdir else None, writable=writable)
        agent = self.agents[role]
        hdir = self.lab.handoffs / task_id
        hdir.mkdir(parents=True, exist_ok=True)
        (hdir / "task.json").write_text(json.dumps(packet.to_dict(), indent=2, default=str),
                                        encoding="utf-8")
        self.store.append_event("controller", "task.dispatched", task_id,
                                {"role": role.value, "stage": stage, "project": pid,
                                 **agent.backend.describe()})
        try:
            result = agent.run(packet)
        except Exception as exc:
            self.store.create("task", {
                "project": pid, "role": role.value, "stage": stage, "status": "error",
                "error": f"{type(exc).__name__}: {exc}"[:2000],
                "backend": agent.backend.describe(), "refs": {}},
                record_id=task_id, author=role.value, reason=f"{stage} errored")
            raise
        comp = result.completion
        (hdir / "completion.json").write_text(json.dumps(comp, indent=2), encoding="utf-8")
        (hdir / "prompt.md").write_text(result.prompt, encoding="utf-8")
        a = self.lab.artifacts
        refs = {"prompt": "sha256:" + a.put_text(result.prompt),
                "responses": "sha256:" + a.put_text("\n\n-----\n\n".join(result.raw_responses)),
                "completion": "sha256:" + a.put_text(canonical(comp))}
        known_runs = {r.id for r in self.store.query("run")}
        ok_claims, rejected = [], []
        for c in comp.get("research_claims", []):
            errs = validate_claim(c, known_runs)
            (rejected if errs else ok_claims).append({**c, "errors": errs} if errs else c)
        self.store.create("task", {
            "project": pid, "role": role.value, "stage": stage, "status": comp["status"],
            "summary": comp.get("summary", ""), "attempts": result.attempts,
            "backend": agent.backend.describe(), "claims": ok_claims,
            "rejected_claims": rejected, "risks": comp.get("risks", []), "refs": refs,
        }, record_id=task_id, author=role.value, reason=f"{stage} completed")
        for c in rejected:
            self.store.append_event("controller", "claim.rejected", task_id, c)
        if comp["status"] in ("blocked", "failed"):
            raise StageError(f"{role.value}/{stage} reported {comp['status']}: "
                             f"{comp.get('summary', '')}")
        return comp["payload"], task_id

    def _context(self, pid: str) -> dict:
        """Compact, explicit context for agents (no reliance on conversation)."""
        cur = self._cur(pid)
        ctx: dict = {}
        for key, field in (("problem", None), ("question", "question"),
                           ("hypothesis", None), ("requirements", None)):
            if key in cur:
                data = self.store.get(cur[key]).data
                ctx[key] = data[field] if field else {k: v for k, v in data.items()
                                                      if k not in ("refs", "project")}
        if "background" in cur:
            bg = self.store.get(cur["background"]).data
            ctx["background"] = {"findings": [self.store.get(c).data for c in bg["refs"]["claims"]],
                                 "gaps": bg.get("gaps", [])}
        if "protocol" in cur:
            prot = self.store.get(cur["protocol"])
            ctx["protocol"] = {"id": prot.id, "version": prot.version,
                               "frozen": prot.frozen, **prot.data["protocol"]}
        fb = self.project(pid).data.get("feedback", [])
        if fb:
            ctx["feedback_from_previous_iterations"] = fb[-6:]
        return ctx

    def _scratch_checkout(self, name: str, commit: str) -> Path:
        path = self.lab.worktrees / "readonly" / name
        if path.exists():
            self.repo.remove_worktree(path)
        return self.repo.add_detached_worktree(path, commit)

    # =================================================== research handlers
    def _h_define_problem(self, pid: str) -> str:
        payload, tid = self._call(pid, Role.SCIENTIST, "define_problem", {})
        rec = self.store.create("problem", {**payload, "project": pid, "refs": {"task": tid}},
                                prefix="PRB", author="scientist", reason="problem defined")
        self._transition(pid, R.BACKGROUND_RESEARCH, "problem defined", {"problem": rec.id})
        return rec.id

    def _h_background_research(self, pid: str) -> str:
        payload, tid = self._call(pid, Role.SCIENTIST, "background_research",
                                  self._context(pid))
        claim_ids = []
        for f in payload["findings"]:
            errs = validate_claim(f)
            rec = self.store.create("claim", {
                "label": f["type"], "statement": f["statement"],
                "sources": f.get("sources", []), "status": "rejected" if errs else "recorded",
                "errors": errs, "sources_verified": False, "project": pid,
                "refs": {"task": tid}}, prefix="CLM", author="scientist",
                reason="background claim" + (" (rejected)" if errs else ""))
            if not errs:
                claim_ids.append(rec.id)
        bg = self.store.create("background", {
            "known_methods": payload.get("known_methods", []), "gaps": payload.get("gaps", []),
            "project": pid, "refs": {"task": tid, "claims": claim_ids}},
            prefix="BKG", author="scientist", reason="background research")
        self._transition(pid, R.RESEARCH_QUESTION, "background recorded", {"background": bg.id})
        return bg.id

    def _h_research_question(self, pid: str) -> str:
        ctx = self._context(pid)
        proj = self.project(pid)
        if proj.data.get("next_question"):
            ctx["selected_next_question"] = self.store.get(proj.data["next_question"]).data
        ctx["previous_conclusions"] = [
            {"id": c.id, "hypothesis": c.data["hypothesis"], "outcome": c.data["outcome"],
             "kind": c.data["experiment_kind"]}
            for c in self.store.query("conclusion", project=pid)]
        payload, tid = self._call(pid, Role.SCIENTIST, "research_question", ctx)
        refs = {"task": tid}
        if proj.data.get("next_question"):
            refs["from_future_question"] = proj.data["next_question"]
        rec = self.store.create("question", {**payload, "project": pid,
                                             "cycle": proj.data["cycle"], "refs": refs},
                                prefix="QST", author="scientist", reason="research question")
        self._transition(pid, R.HYPOTHESIS, "question formulated", {"question": rec.id},
                         design_iterations=0, feedback=[])
        return rec.id

    def _h_hypothesis(self, pid: str) -> str:
        cur = self._cur(pid)
        payload, tid = self._call(pid, Role.SCIENTIST, "hypothesis", self._context(pid))
        ids = []
        for i, h in enumerate(payload["hypotheses"]):
            rec = self.store.create("hypothesis", {
                **h, "label": Evidence.HYPOTHESIS.value,
                "status": "active" if i == 0 else "proposed", "project": pid,
                "refs": {"question": cur["question"], "task": tid}},
                prefix="HYP", author="scientist", reason="hypothesis formulated")
            ids.append(rec.id)
        self._transition(pid, R.REQUIREMENTS, f"{len(ids)} hypotheses; testing {ids[0]}",
                         {"hypothesis": ids[0]})
        return ids[0]

    def _h_requirements(self, pid: str) -> str:
        cur = self._cur(pid)
        payload, tid = self._call(pid, Role.SCIENTIST, "requirements", self._context(pid))
        rec = self.store.create("requirements", {
            "validity_criteria": payload["validity_criteria"],
            "success_criteria": payload.get("success_criteria", []),
            "engineering": payload["engineering"], "project": pid,
            "refs": {"hypothesis": cur["hypothesis"], "task": tid}},
            prefix="REQ", author="scientist", reason="requirements specified")
        self._transition(pid, R.DESIGN, "requirements specified", {"requirements": rec.id})
        return rec.id

    def _design_iteration(self, pid: str, reason: str) -> None:
        n = self.project(pid).data["design_iterations"] + 1
        self._set(pid, f"design iteration {n}: {reason}", design_iterations=n)

    def _h_design(self, pid: str) -> str:
        proj = self.project(pid)
        if proj.data["design_iterations"] >= self.limits["max_design_iterations"]:
            self._halt(pid, "design iteration budget exhausted for this cycle; "
                            "human direction required")
            return "halted"
        cur = self._cur(pid)
        ctx = self._context(pid)
        ctx.pop("protocol", None)
        ctx["previous_failures"] = [
            f.data["summary"] for f in self.store.query("failure", project=pid)
            if f.data["category"] != "stage_error"][-6:]
        payload, tid = self._call(pid, Role.SCIENTIST, "design", ctx)
        protocol = payload["protocol"]
        errs = validate_protocol(protocol)
        if errs:
            self._failure(pid, "design_invalid", "; ".join(errs), {"task": tid})
            self._feedback(pid, "Protocol rejected by controller: " + "; ".join(errs))
            self._design_iteration(pid, "invalid protocol")
            return "protocol invalid; redesign"
        wt = self._scratch_checkout(f"design-{tid}", self.repo.rev("main"))
        try:
            sd, tid2 = self._call(pid, Role.ENGINEER, "solution_design",
                                  {**ctx, "proposed_protocol": protocol,
                                   "chosen_option": payload["chosen"]}, workdir=wt)
        finally:
            self.repo.remove_worktree(wt)
        if not sd["feasible"]:
            self._failure(pid, "design_infeasible", sd["solution_design"][:500], {"task": tid2})
            self._feedback(pid, "Engineer judged the design infeasible: " + sd["solution_design"])
            self._design_iteration(pid, "infeasible")
            return "design infeasible; redesign"
        dsn = self.store.create("design", {
            "options": payload["options"], "chosen": payload["chosen"],
            "rationale": payload["rationale"], "solution_design": sd, "project": pid,
            "refs": {"scientist_task": tid, "engineer_task": tid2,
                     "requirements": cur["requirements"]}},
            prefix="DSN", author="scientist", reason="solution chosen")
        prot = self.store.create("protocol", {
            "protocol": protocol, "status": "draft", "project": pid,
            "refs": {"design": dsn.id, "hypothesis": cur["hypothesis"],
                     "requirements": cur["requirements"]}},
            prefix="PROT", author="scientist", reason="protocol drafted")
        self._transition(pid, R.SCIENTIFIC_REVIEW, "design chosen",
                         {"design": dsn.id, "protocol": prot.id})
        return prot.id

    def _h_scientific_review(self, pid: str) -> str:
        cur = self._cur(pid)
        ctx = self._context(pid)
        ctx["design"] = {k: v for k, v in self.store.get(cur["design"]).data.items()
                         if k != "refs"}
        payload, tid = self._call(pid, Role.SCIENTIST, "scientific_review", ctx)
        critical = [i for i in payload["issues"] if i["severity"] == "critical"]
        approved = payload["verdict"] == "approve" and not critical
        rev = self.store.create("review", {
            "review_type": "scientific_review", **payload, "approved": approved,
            "project": pid, "refs": {"protocol": cur["protocol"], "task": tid}},
            prefix="REV", author="scientist", reason="scientific review")
        if approved:
            self._transition(pid, R.PROTOCOL_FREEZE, "design approved", {"scientific_review": rev.id})
            return "approved"
        self.store.update(cur["protocol"], {"status": "rejected_in_review"},
                          reason=f"rejected by {rev.id}")
        issues = "; ".join(f"[{i['severity']}] {i['description']}" for i in payload["issues"])
        self._failure(pid, "design_rejected", issues[:500] or "revise requested", {"review": rev.id})
        self._feedback(pid, f"Scientific review {rev.id} requested revision: {issues} "
                            f"Required changes: {payload.get('required_changes', [])}")
        self._design_iteration(pid, "review requested revision")
        self._transition(pid, R.DESIGN, "review requested revision")
        return "revise"

    def _h_protocol_freeze(self, pid: str) -> str:
        cur = self._cur(pid)
        prot = self.store.get(cur["protocol"])
        p = prot.data["protocol"]
        if p["kind"] == "confirmatory" and self.cfg["gates"]["confirmatory_protocol_freeze"]:
            status, apr = self._gate(pid, CONFIRMATORY_FREEZE, prot.id,
                                     f"Pre-register confirmatory protocol {prot.id}: {p['title']}",
                                     {"protocol": p})
            if status == "pending":
                return self._block(pid, apr)
            if status == "rejected":
                self._feedback(pid, f"Human rejected pre-registration ({apr.id}): "
                                    f"{apr.data.get('note', '')}")
                self._design_iteration(pid, "pre-registration rejected")
                self._transition(pid, R.DESIGN, f"pre-registration rejected ({apr.id})")
                return "rejected"
        # Co-version the protocol with the code: commit it to main.
        rel = f"protocols/{prot.id}.json"
        path = self.repo.path / rel
        path.write_text(json.dumps(p, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sha = self.repo.commit_all(self.repo.path, f"Freeze protocol {prot.id}",
                                   IDENTITIES[Role.CONTROLLER],
                                   {"Autolab-Protocol": prot.id, "Autolab-Project": pid,
                                    "Autolab-Ledger-Head": self.store.head()})
        self.store.update(prot.id, {"status": "frozen", "repo_file": rel,
                                    "repo_commit": sha or self.repo.rev("main")},
                          reason="protocol committed to research repo")
        frozen = self.store.freeze(prot.id, author="controller",
                                   reason="pre-registration: protocol frozen before implementation")
        eng = self._new_eng_task(pid, prot.id, [])
        self._transition(pid, R.ENGINEERING, f"protocol frozen ({frozen.data['_freeze_hash'][:12]})",
                         {"eng_task": eng.id})
        return eng.id

    def _new_eng_task(self, pid: str, protocol_id: str, feedback: list[str]) -> Record:
        return self.store.create("eng_task", {
            "state": E.SPEC.value, "project": pid, "patch_attempts": 0, "redesigns": 0,
            "review_round": 0, "feedback": feedback, "history": [],
            "refs": {"protocol": protocol_id}}, prefix="ENG", reason="engineering task created")

    # ------------------------------------------------------- engineering
    def _h_engineering(self, pid: str) -> str:
        cur = self._cur(pid)
        eng = self.store.get(cur["eng_task"])
        state = E(eng.data["state"])
        if state == E.MERGED:
            self._transition(pid, R.SCIENTIFIC_VALIDATION, f"{eng.id} merged",
                             {"commit": eng.data["merge_commit"]})
            return "merged"
        if state == E.ESCALATED:
            self._failure(pid, "approach_inadequate",
                          f"{eng.id} escalated after {eng.data['redesigns']} redesigns",
                          {"eng_task": eng.id}, {"feedback": eng.data["feedback"][-5:]})
            self._feedback(pid, f"Engineering task {eng.id} could not meet requirements after "
                                f"redesigns; reconsider the solution approach. Last problems: "
                                f"{eng.data['feedback'][-2:]}")
            self._design_iteration(pid, "engineering escalated")
            self._transition(pid, R.DESIGN, f"{eng.id} escalated: approach inadequate")
            return "escalated"
        return getattr(self, f"_eng_{state.value.lower()}")(pid, eng)

    def _eng_to(self, eng: Record, target: E, reason: str, **changes) -> None:
        cur = E(eng.data["state"])
        check_engineering(cur, target)
        hist = list(eng.data.get("history", [])) + [
            {"from": cur.value, "to": target.value, "reason": reason[:300]}]
        self.store.update(eng.id, {"state": target.value, "history": hist, **changes},
                          reason=f"{cur.value} -> {target.value}: {reason[:200]}")
        self.store.append_event("controller", "engineering.transition", eng.id,
                                {"from": cur.value, "to": target.value, "reason": reason[:300]})

    def _eng_fail(self, pid: str, eng: Record, feedback: str, category: str) -> str:
        self._failure(pid, category, feedback[:500], {"eng_task": eng.id},
                      {"feedback": feedback[-4000:]})
        pa = eng.data["patch_attempts"] + 1
        fb = list(eng.data.get("feedback", [])) + [feedback[-4000:]]
        if pa >= self.limits["max_patch_attempts"]:
            if eng.data["redesigns"] < self.limits["max_redesigns"]:
                self._eng_to(eng, E.REDESIGN, f"{pa} failed patches: redesign required",
                             patch_attempts=pa, feedback=fb)
                return "redesign"
            self._eng_to(eng, E.ESCALATED, "patch and redesign budget exhausted",
                         patch_attempts=pa, feedback=fb)
            return "escalated"
        self._eng_to(eng, E.IMPLEMENTING, f"{category}; patch attempt {pa}",
                     patch_attempts=pa, feedback=fb)
        return "patch"

    def _eng_worktree(self, eng: Record, design_index: int) -> tuple[str, Path, str]:
        branch = f"eng/{eng.id}-d{design_index}"
        wt = self.lab.worktrees / "engineer" / f"{eng.id}-d{design_index}"
        base = self.repo.rev("main")
        self.repo.add_worktree(wt, branch, "main")
        return branch, wt, base

    def _eng_spec(self, pid: str, eng: Record) -> str:
        branch, wt, base = self._eng_worktree(eng, 0)
        self._eng_to(eng, E.IMPLEMENTING, "worktree created", branch=branch,
                     worktree=str(wt), base=base, head=base, pending_redesign=False)
        return branch

    def _eng_context(self, pid: str, eng: Record) -> dict:
        ctx = self._context(pid)
        req = ctx.pop("requirements", {})
        ctx["engineering_requirements"] = req.get("engineering", [])
        ctx["validity_criteria"] = req.get("validity_criteria", [])
        ctx["engineering_task"] = eng.id
        ctx["patch_attempt"] = eng.data["patch_attempts"]
        ctx["redesign_index"] = eng.data["redesigns"]
        if eng.data.get("feedback"):
            ctx["failures_to_address"] = eng.data["feedback"][-3:]
        return ctx

    def _restore_paths(self, wt: Path, base: str, paths: list[str], why: str, task: str) -> str:
        base_files = set(self.repo.git("ls-tree", "-r", "--name-only", base, cwd=wt).splitlines())
        for p in paths:
            if p in base_files:
                self.repo.git("checkout", base, "--", p, cwd=wt)
            else:
                self.repo.git("rm", "-f", "--quiet", "--", p, cwd=wt, check=False)
        sha = self.repo.commit_all(wt, f"controller: revert {why}",
                                   IDENTITIES[Role.CONTROLLER],
                                   {"Autolab-Task": task, "Autolab-Policy": why})
        return sha or self.repo.rev("HEAD", cwd=wt)

    def _eng_implementing(self, pid: str, eng: Record) -> str:
        stage = "redesign" if eng.data.get("pending_redesign") else "implement"
        wt = Path(eng.data["worktree"])
        ctx = self._eng_context(pid, eng)
        if stage == "redesign":
            ctx["failure_history"] = eng.data["feedback"]
        payload, tid = self._call(pid, Role.ENGINEER, stage, ctx, workdir=wt, writable=True)
        prot = self.store.get(eng.data["refs"]["protocol"])
        backend = self.agents[Role.ENGINEER].backend.describe()
        sha = self.repo.commit_all(
            wt, f"[{eng.id}] {stage}: {payload['summary'][:72]}", IDENTITIES[Role.ENGINEER],
            {"Autolab-Task": tid, "Autolab-Eng": eng.id, "Autolab-Role": "engineer",
             "Autolab-Backend": f"{backend['backend']}/{backend['model'] or 'default'}",
             "Autolab-Protocol": f"{prot.id}@{prot.data.get('_freeze_hash', '')[:16]}"})
        if sha is None:
            # No diff: the engineer may be disputing a finding, or main may already
            # implement the (revised) protocol. Either way the claim is checked by
            # the controller's tests and an independent review, never accepted as-is.
            self.store.append_event("controller", "engineering.no_changes", eng.id,
                                    {"task": tid, "summary": payload["summary"][:500]})
            self._eng_to(eng, E.TESTING, f"{stage}: no code changes; re-verifying",
                         pending_redesign=False, last_engineer_task=tid)
            return "no changes"
        protected = self.cfg["engineering"]["protected_paths"]
        bad = path_violations(self.repo.changed_files(eng.data["base"], sha), None, protected)
        if bad:
            self._restore_paths(wt, eng.data["base"], bad, "engineer edited protected paths", tid)
            eng = self.store.update(eng.id, {"head": self.repo.rev("HEAD", cwd=wt)},
                                    reason="protected path edits reverted")
            return self._eng_fail(pid, eng, f"engineer modified protected paths {bad}; "
                                            f"changes reverted by controller", "policy_violation")
        self._eng_to(eng, E.TESTING, f"{stage} committed {sha[:10]}", head=sha,
                     pending_redesign=False, last_engineer_task=tid)
        return sha

    def _run_tests(self, cwd: Path) -> tuple[bool, str, str]:
        cmd = shlex.split(self.cfg["engineering"]["test_command"])
        if cmd and cmd[0] in ("python", "python3", "py"):
            cmd[0] = sys.executable
        try:
            proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=self.limits["test_timeout_s"],
                                  env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            out, rc = proc.stdout + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired:
            out, rc = "test command timed out", -1
        if rc == 5 and "pytest" in " ".join(cmd):
            out += "\n[controller] no tests were collected; tests are required."
        art = self.lab.artifacts.put_text(f"$ {' '.join(cmd)}\n(exit {rc})\n{out}")
        return rc == 0, out, art

    def _eng_testing(self, pid: str, eng: Record) -> str:
        wt = Path(eng.data["worktree"])
        ok, out, art = self._run_tests(wt)
        tests = list(eng.data.get("test_runs", [])) + [
            {"head": eng.data["head"], "passed": ok, "artifact": "sha256:" + art}]
        eng = self.store.update(eng.id, {"test_runs": tests},
                                reason=f"controller test run: {'pass' if ok else 'fail'}")
        if ok:
            self._eng_to(eng, E.ADVERSARIAL_REVIEW, "controller tests passed")
            return "tests passed"
        return self._eng_fail(pid, eng, "Controller-run tests failed:\n" + _tail(out),
                              "tests_failed")

    def _eng_adversarial_review(self, pid: str, eng: Record) -> str:
        rnd = eng.data["review_round"] + 1
        vbranch = f"verify/{eng.id}-r{rnd}"
        vwt = self.lab.worktrees / "verifier" / f"{eng.id}-r{rnd}"
        if vwt.exists():
            self.repo.remove_worktree(vwt)
        self.repo.add_worktree(vwt, vbranch, eng.data["head"])
        try:
            prev = eng.data.get("last_verify_head")
            if prev and self.repo.checkout_paths_from(vwt, prev, "tests/verification"):
                self.repo.commit_all(vwt, "carry forward verification tests",
                                     IDENTITIES[Role.CONTROLLER],
                                     {"Autolab-Eng": eng.id, "Autolab-From": prev})
            base_v = self.repo.rev("HEAD", cwd=vwt)
            ctx = self._eng_context(pid, eng)
            ctx.pop("failures_to_address", None)
            diff = self.repo.diff(eng.data["base"], eng.data["head"])
            ctx["implementation_diff"] = _tail(diff, 20000)
            ctx["changed_files"] = self.repo.changed_files(eng.data["base"], eng.data["head"])
            ctx["engineer_summary"] = self.store.get(eng.data["last_engineer_task"]).data["summary"]
            payload, tid = self._call(pid, Role.VERIFIER, "verify", ctx, workdir=vwt,
                                      writable=True)
            backend = self.agents[Role.VERIFIER].backend.describe()
            vsha = self.repo.commit_all(
                vwt, f"[{eng.id}] verification round {rnd}", IDENTITIES[Role.VERIFIER],
                {"Autolab-Task": tid, "Autolab-Eng": eng.id, "Autolab-Role": "verifier",
                 "Autolab-Backend": f"{backend['backend']}/{backend['model'] or 'default'}"})
            findings = list(payload["findings"])
            if vsha:
                bad = path_violations(self.repo.changed_files(base_v, vsha),
                                      self.cfg["engineering"]["verifier_allowed_paths"], [])
                if bad:
                    self._restore_paths(vwt, base_v, bad, "verifier edited non-test paths", tid)
                    self._failure(pid, "verifier_policy_violation",
                                  f"verifier modified {bad}; reverted", {"task": tid})
            head_v = self.repo.rev("HEAD", cwd=vwt)
            has_vtests = any((vwt / "tests" / "verification").glob("test_*.py"))
            ok, out, art = self._run_tests(vwt)
        finally:
            self.repo.remove_worktree(vwt)
        if not has_vtests:
            # The verifier's omission, not the engineer's: retried via the stage-retry
            # path (then HALTED), never counted against the engineer's patch budget.
            self._failure(pid, "verifier_no_tests",
                          f"verification round {rnd} added no tests/verification/test_*.py",
                          {"eng_task": eng.id, "task": tid})
            raise StageError(f"verifier added no independent tests in round {rnd}; "
                             f"independent tests are required before merge")
        blocking = [f for f in findings if f["severity"] in ("critical", "major")]
        passed = (payload["verdict"] == "pass" and ok and not blocking
                  and payload["reproducibility_ok"] and payload["protocol_compliance_ok"])
        rev = self.store.create("review", {
            "review_type": "code_review", "round": rnd, "verdict": payload["verdict"],
            "findings": findings, "tests_passed": ok, "passed": passed,
            "reproducibility_ok": payload["reproducibility_ok"],
            "protocol_compliance_ok": payload["protocol_compliance_ok"],
            "branch": vbranch, "commit": head_v, "project": pid,
            "refs": {"eng_task": eng.id, "task": tid, "tests": "sha256:" + art}},
            prefix="REV", author="verifier", reason=f"adversarial review round {rnd}")
        eng = self.store.update(eng.id, {"review_round": rnd, "last_verify_head": head_v,
                                         "last_verify_branch": vbranch, "last_review": rev.id},
                                reason=f"review {rev.id}")
        if passed:
            self._eng_to(eng, E.MERGE, f"review {rev.id} passed", merge_candidate=vbranch)
            return "review passed"
        lines = [f"[{f['severity']}] {f['description']} ({f.get('location', '')})" for f in findings]
        if not ok:
            lines.append("Tests (incl. independent verification tests) failed:\n" + _tail(out, 3000))
        if not payload["protocol_compliance_ok"]:
            lines.append("Verifier: implementation does not comply with the frozen protocol.")
        if not payload["reproducibility_ok"]:
            lines.append("Verifier: reproducibility problem.")
        return self._eng_fail(pid, eng, f"Adversarial review {rev.id} failed:\n" + "\n".join(lines),
                              "review_failed")

    def _eng_redesign(self, pid: str, eng: Record) -> str:
        if eng.data.get("worktree"):
            self.repo.remove_worktree(eng.data["worktree"])  # branch is kept
        r = eng.data["redesigns"] + 1
        branch, wt, base = self._eng_worktree(eng, r)
        self._eng_to(eng, E.IMPLEMENTING, f"redesign {r}: fresh branch from main",
                     redesigns=r, patch_attempts=0, branch=branch, worktree=str(wt),
                     base=base, head=base, pending_redesign=True, last_verify_head=None)
        return branch

    def _eng_merge(self, pid: str, eng: Record) -> str:
        if self.cfg["gates"]["merge_to_main"]:
            status, apr = self._gate(pid, MERGE_TO_MAIN, eng.id,
                                     f"Merge {eng.data['merge_candidate']} into main")
            if status == "pending":
                return self._block(pid, apr)
            if status == "rejected":
                return self._eng_fail(pid, eng, f"human rejected merge ({apr.id}): "
                                                f"{apr.data.get('note', '')}", "merge_rejected")
        prot = self.store.get(eng.data["refs"]["protocol"])
        try:
            sha = self.repo.merge_into_main(
                eng.data["merge_candidate"],
                f"Merge {eng.data['merge_candidate']} ({eng.id})",
                {"Autolab-Eng": eng.id, "Autolab-Review": eng.data["last_review"],
                 "Autolab-Ledger-Head": self.store.head(),
                 "Autolab-Protocol": f"{prot.id}@{prot.data.get('_freeze_hash', '')[:16]}"})
        except GitError as exc:
            return self._eng_fail(pid, eng, f"merge failed: {exc}", "merge_conflict")
        self.repo.remove_worktree(eng.data["worktree"])
        self._eng_to(eng, E.MERGED, f"merged as {sha[:10]}", merge_commit=sha)
        return sha

    # ---------------------------------------------- validation and running
    def _h_scientific_validation(self, pid: str) -> str:
        cur = self._cur(pid)
        prot = self.store.get(cur["protocol"])
        p = prot.data["protocol"]
        eng = self.store.get(cur["eng_task"])
        commit = eng.data["merge_commit"]
        smoke_seed = 1_000_003
        while smoke_seed in p["seeds"]:
            smoke_seed += 1
        wt = self._scratch_checkout(f"smoke-{eng.id}", commit)
        try:
            out = run_protocol(p, wt, self.lab.runs / "_smoke" / eng.id, seeds=[smoke_seed])
        finally:
            self.repo.remove_worktree(wt)
        smoke = [{"condition": t.condition, "ok": t.ok, "error": t.error,
                  "metrics": t.metrics} for t in out.trials]
        if out.failed:
            msg = "; ".join(f"{t.condition}: {t.error}" for t in out.failed)
            self._failure(pid, "smoke_test_failed", msg[:500], {"eng_task": eng.id})
            new = self._new_eng_task(pid, prot.id, [f"Smoke test of merged commit {commit[:10]} "
                                                    f"failed: {msg}"])
            self._transition(pid, R.ENGINEERING, "smoke test failed", {"eng_task": new.id})
            return "smoke failed"
        ctx = self._context(pid)
        ctx["merged_commit"] = commit
        ctx["changed_files"] = self.repo.changed_files(eng.data["base"], commit)
        ctx["verifier_review"] = {k: v for k, v in
                                  self.store.get(eng.data["last_review"]).data.items()
                                  if k != "refs"}
        ctx["smoke_test"] = {"note": "seed outside the protocol seeds; not data", "seed": smoke_seed,
                             "trials": smoke}
        payload, tid = self._call(pid, Role.SCIENTIST, "scientific_validation", ctx)
        approved = payload["verdict"] == "approve" and not any(
            i["severity"] == "critical" for i in payload["issues"])
        rev = self.store.create("review", {
            "review_type": "scientific_validation", **payload, "approved": approved,
            "smoke": smoke, "commit": commit, "project": pid,
            "refs": {"protocol": prot.id, "eng_task": eng.id, "task": tid}},
            prefix="REV", author="scientist", reason="scientific validation")
        if approved:
            self._transition(pid, R.RUN_EXPERIMENT, "implementation validated",
                             {"validation": rev.id})
            return "validated"
        issues = "; ".join(i["description"] for i in payload["issues"])
        self._failure(pid, "validation_rejected", issues[:500], {"review": rev.id})
        if payload.get("send_back_to") == "design":
            self._feedback(pid, f"Scientific validation {rev.id}: protocol flaw: {issues}")
            self._design_iteration(pid, "validation found protocol flaw")
            self._transition(pid, R.DESIGN, "validation: protocol flaw")
        else:
            new = self._new_eng_task(pid, prot.id, [f"Scientific validation {rev.id} found "
                                                    f"implementation problems: {issues}"])
            self._transition(pid, R.ENGINEERING, "validation: implementation problem",
                             {"eng_task": new.id})
        return "rejected"

    def _h_run_experiment(self, pid: str) -> str:
        cur = self._cur(pid)
        prot = self.store.get(cur["protocol"])
        p = prot.data["protocol"]
        subject = f"{prot.id}@v{prot.version}"
        if p.get("protected"):
            status, apr = self._gate(pid, PROTECTED_EXPERIMENT, subject,
                                     f"Run protected experiment {prot.id}: {p['title']}",
                                     {"conditions": p["conditions"], "seeds": p["seeds"]})
            if status == "pending":
                return self._block(pid, apr)
            if status == "rejected":
                self._feedback(pid, f"Human declined protected run ({apr.id}): "
                                    f"{apr.data.get('note', '')}")
                self._design_iteration(pid, "protected run declined")
                self._transition(pid, R.DESIGN, f"protected run declined ({apr.id})")
                return "declined"
        n_trials = len(p["conditions"]) * len(p["seeds"])
        if (self.cfg["gates"]["compute_budget"]
                and n_trials > self.limits["max_trials_without_approval"]):
            status, apr = self._gate(pid, COMPUTE_BUDGET, subject,
                                     f"{n_trials} trials exceeds budget "
                                     f"{self.limits['max_trials_without_approval']}")
            if status == "pending":
                return self._block(pid, apr)
            if status == "rejected":
                self._feedback(pid, f"Compute budget declined ({apr.id}); reduce trials.")
                self._design_iteration(pid, "budget declined")
                self._transition(pid, R.DESIGN, "compute budget declined")
                return "declined"
        commit = cur["commit"]
        run_id = self.store.next_id("RUN")
        out_root = self.lab.runs / run_id
        env = environment_snapshot()
        env_sha = self.lab.artifacts.put_text(canonical(env))
        wt = self._scratch_checkout(run_id, commit)
        try:
            out = run_protocol(p, wt, out_root)
        finally:
            self.repo.remove_worktree(wt)
        trials = []
        a = self.lab.artifacts
        for t in out.trials:
            d = Path(t.out_dir)
            hashes = {f.name: "sha256:" + a.put_file(f) for f in sorted(d.iterdir()) if f.is_file()}
            for f in d.iterdir():  # raw data is read-only from now on
                if f.is_file():
                    os.chmod(f, stat.S_IREAD)
            trials.append({"condition": t.condition, "role": t.role, "seed": t.seed,
                           "returncode": t.returncode, "duration_s": t.duration_s,
                           "metrics": t.metrics, "error": t.error, "files": hashes,
                           "out_dir": str(d.relative_to(self.lab.root))})
        manifest = {"run_id": run_id, "protocol": prot.id, "protocol_version": prot.version,
                    "freeze_hash": prot.data["_freeze_hash"], "commit": commit,
                    "command_template": out.command_template, "env_hash": env_sha,
                    "trials": trials}
        man_sha = a.put_text(canonical(manifest))
        n_failed = sum(1 for t in trials if t["error"] or t["returncode"] != 0)
        run = self.store.create("run", {
            "commit": commit, "protocol_version": prot.version,
            "freeze_hash": prot.data["_freeze_hash"], "experiment_kind": p["kind"],
            "seeds": p["seeds"], "n_trials": len(trials), "n_failed": n_failed,
            "trials": trials, "command_template": out.command_template,
            "env_hash": env_sha, "run_dir": str(out_root.relative_to(self.lab.root)),
            "project": pid,
            "refs": {"protocol": prot.id, "eng_task": cur["eng_task"],
                     "validation": cur.get("validation"), "env": "sha256:" + env_sha,
                     "manifest": "sha256:" + man_sha}},
            record_id=run_id, reason="experiment executed")
        if n_failed == len(trials):
            self._failure(pid, "run_failed", f"all {len(trials)} trials failed", {"run": run.id})
            self._feedback(pid, f"Run {run.id}: every trial failed.")
            self._design_iteration(pid, "run failed")
            self._transition(pid, R.DESIGN, "all trials failed", {"run": run.id})
            return "run failed"
        self._transition(pid, R.ANALYZE, f"{run.id}: {len(trials)} trials, {n_failed} failed",
                         {"run": run.id})
        return run.id

    @staticmethod
    def _trials(run: Record) -> list[Trial]:
        return [Trial(t["condition"], t["role"], t["seed"], t["returncode"], t["duration_s"],
                      t["metrics"], t["out_dir"], t["error"]) for t in run.data["trials"]]

    def _h_analyze(self, pid: str) -> str:
        cur = self._cur(pid)
        run = self.store.get(cur["run"])
        prot = self.store.get(cur["protocol"], run.data["protocol_version"])
        p = prot.data["protocol"]
        existing = cur.get("result")
        if existing and self.store.get(existing).data["refs"]["run"] == run.id:
            res = self.store.get(existing)  # idempotent on retry
        else:
            trials = self._trials(run)
            seed = int(hashlib.sha256(run.id.encode()).hexdigest()[:8], 16)
            summary = summarize(trials)
            decision = evaluate_decision(p["decision_rule"], trials, seed)
            res = self.store.create("result", {
                "label": Evidence.EXPERIMENTAL_RESULT.value, "summary": summary,
                "decision": decision,
                "contrasts": contrasts(p, trials, seed),
                "validity": evaluate_requirements(p.get("validity_checks", []), summary, trials),
                "scientific": evaluate_requirements(p.get("success_checks", []), summary, trials),
                "bootstrap_seed": seed, "analysis_version": __version__,
                "outcome": decision["outcome"], "project": pid,
                "refs": {"run": run.id, "protocol": prot.id, "hypothesis": cur["hypothesis"],
                         "requirements": cur["requirements"]}},
                prefix="RES", reason="pre-registered analysis computed by controller")
            self._set(pid, "result recorded", current={**cur, "result": res.id})
        ctx = self._context(pid)
        ctx["run_id"] = run.id
        ctx["result"] = {k: v for k, v in res.data.items() if k != "refs"}
        payload, tid = self._call(pid, Role.SCIENTIST, "interpret", ctx)
        interp = self.store.create("review", {
            "review_type": "interpretation", "label": Evidence.INFERENCE.value, **payload,
            "project": pid, "refs": {"result": res.id, "task": tid}},
            prefix="REV", author="scientist", reason="interpretation (INFERENCE)")
        self._transition(pid, R.CHALLENGE, f"{res.id}: {res.data['decision']['outcome']}",
                         {"result": res.id, "interpretation": interp.id})
        return res.data["decision"]["outcome"]

    def _h_challenge(self, pid: str) -> str:
        cur = self._cur(pid)
        run = self.store.get(cur["run"])
        res = self.store.get(cur["result"])
        ctx = self._context(pid)
        ctx["run"] = {k: v for k, v in run.data.items() if k not in ("refs",)}
        ctx["result"] = {k: v for k, v in res.data.items() if k != "refs"}
        ctx["interpretation"] = {k: v for k, v in self.store.get(cur["interpretation"]).data.items()
                                 if k != "refs"}
        ctx["raw_data_dir"] = str(self.lab.root / run.data["run_dir"])
        wt = self._scratch_checkout(f"challenge-{run.id}", run.data["commit"])
        try:
            payload, tid = self._call(pid, Role.VERIFIER, "challenge", ctx, workdir=wt)
        finally:
            self.repo.remove_worktree(wt)
        chl = self.store.create("challenge", {
            **payload, "project": pid, "refs": {"result": res.id, "run": run.id, "task": tid}},
            prefix="CHL", author="verifier", reason="adversarial challenge of results")
        self._transition(pid, R.EVALUATE, f"challenge: {payload['verdict']}", {"challenge": chl.id})
        return payload["verdict"]

    def _h_evaluate(self, pid: str) -> str:
        cur = self._cur(pid)
        res = self.store.get(cur["result"])
        run = self.store.get(cur["run"])
        chl = self.store.get(cur["challenge"])
        hyp = self.store.get(cur["hypothesis"])
        prot = self.store.get(cur["protocol"], run.data["protocol_version"])
        kind = prot.data["protocol"]["kind"]
        validity_fail = [v for v in res.data["validity"] if not v["passed"]]
        critical = [i for i in chl.data["issues"] if i["severity"] == "critical"]
        problems = []
        if validity_fail:
            problems.append("validity requirements failed: " + ", ".join(v["id"] for v in validity_fail))
        if run.data["n_failed"]:
            problems.append(f"{run.data['n_failed']} trials failed")
        if critical:
            problems.append("critical challenge: " + "; ".join(i["description"] for i in critical))
        outcome = res.data["decision"]["outcome"]
        if problems:
            # The instrument did not work: no scientific conclusion is drawn.
            self._failure(pid, "invalid_experiment", "; ".join(problems)[:500],
                          {"result": res.id, "challenge": chl.id})
            self._feedback(pid, f"Experiment {run.id} invalid as an instrument: {'; '.join(problems)}")
            self._design_iteration(pid, "invalid experiment")
            self._transition(pid, R.DESIGN, "requirements not met: experiment invalid")
            return "invalid"
        contested = chl.data["verdict"] == "challenged"
        confidence = ("contested" if contested else
                      "preliminary (exploratory)" if kind == "exploratory" else "confirmatory")
        interp = self.store.get(cur["interpretation"]).data
        con = self.store.create("conclusion", {
            "hypothesis": hyp.id, "statement": hyp.data["statement"], "outcome": outcome,
            "label": Evidence.EXPERIMENTAL_RESULT.value, "experiment_kind": kind,
            "confidence": confidence, "decision": res.data["decision"],
            "scientific_criteria": res.data["scientific"],
            "caveats": [i["description"] for i in chl.data["issues"]] + interp.get("limitations", []),
            "project": pid, "cycle": self.project(pid).data["cycle"],
            "refs": {"result": res.id, "challenge": chl.id, "run": run.id,
                     "protocol": prot.id, "hypothesis": hyp.id,
                     "interpretation": cur["interpretation"]}},
            prefix="CON", reason=f"conclusion: {outcome}")
        status = {"supported": "supported", "partially_supported": "partially_supported",
                  "unsupported": "rejected", "inconclusive": "inconclusive"}[outcome]
        # The hypothesis label stays HYPOTHESIS: a test result never silently
        # upgrades it to ESTABLISHED.
        self.store.update(hyp.id, {"status": status, "evidence_kind": kind,
                                   "last_conclusion": con.id},
                          reason=f"{con.id}: {outcome} ({kind}, {confidence})")
        proj = self.project(pid)
        if (outcome == Outcome.INCONCLUSIVE.value
                and proj.data["design_iterations"] + 1 < self.limits["max_design_iterations"]):
            self._feedback(pid, f"{con.id} inconclusive (CI {res.data['decision'].get('ci_low')}"
                                f"..{res.data['decision'].get('ci_high')}); consider power, "
                                f"seeds, effect size or measurement.")
            self._design_iteration(pid, "inconclusive result")
            self._transition(pid, R.DESIGN, "inconclusive: redesign", {"conclusion": con.id})
            return "inconclusive -> redesign"
        self._transition(pid, R.COMMUNICATE, f"{con.id}: {outcome}", {"conclusion": con.id})
        return outcome

    def _h_communicate(self, pid: str) -> str:
        cur = self._cur(pid)
        ctx = self._context(pid)
        ctx["conclusion"] = {k: v for k, v in self.store.get(cur["conclusion"]).data.items()
                             if k != "refs"}
        ctx["challenge"] = {k: v for k, v in self.store.get(cur["challenge"]).data.items()
                            if k != "refs"}
        payload, tid = self._call(pid, Role.SCIENTIST, "communicate", ctx)
        cycle = self.project(pid).data["cycle"]
        text = build_report(self.store, pid, cycle, cur, payload["summary"])
        path = self.lab.reports / f"{pid}-cycle{cycle}.md"
        path.write_text(text, encoding="utf-8")
        sha = self.lab.artifacts.put_text(text)
        rpt = self.store.create("report", {
            "path": str(path.relative_to(self.lab.root)), "artifact": "sha256:" + sha,
            "project": pid, "cycle": cycle,
            "refs": {"conclusion": cur["conclusion"], "task": tid, "report": "sha256:" + sha}},
            prefix="RPT", reason="results communicated")
        self._transition(pid, R.NEXT_QUESTION, f"report {rpt.id}", {"report": rpt.id})
        return str(path)

    def _h_next_question(self, pid: str) -> str:
        cur = self._cur(pid)
        proj = self.project(pid)
        ctx = self._context(pid)
        ctx["conclusion"] = self.store.get(cur["conclusion"]).data
        ctx["open_questions"] = [q.data["question"] for q in
                                 self.store.query("future_question", project=pid, status="open")]
        payload, tid = self._call(pid, Role.SCIENTIST, "next_question", ctx)
        fq = []
        for q in payload["questions"]:
            fq.append(self.store.create("future_question", {
                **q, "status": "open", "project": pid,
                "refs": {"conclusion": cur["conclusion"], "task": tid}},
                prefix="FQ", author="scientist", reason="proposed next question"))
        self.store.create("cycle", {"project": pid, "cycle": proj.data["cycle"],
                                    "pointers": cur, "refs": {"report": cur["report"]}},
                          prefix="CYC", reason=f"cycle {proj.data['cycle']} closed")
        if payload["continue"] and fq and proj.data["cycle"] < self.limits["max_cycles"]:
            chosen = sorted(fq, key=lambda r: r.data.get("priority", 99))[0]
            self.store.update(chosen.id, {"status": "selected"},
                              reason=f"selected for cycle {proj.data['cycle'] + 1}")
            keep = {k: cur[k] for k in ("problem", "background") if k in cur}
            self.store.update(pid, {"current": keep}, reason="new cycle: reset pointers")
            self._transition(pid, R.RESEARCH_QUESTION, f"next cycle on {chosen.id}",
                             cycle=proj.data["cycle"] + 1, next_question=chosen.id)
            return chosen.id
        why = ("scientist judged objective answered" if not payload["continue"]
               else "cycle budget exhausted" if fq else "no further questions")
        self._transition(pid, R.COMPLETE, why)
        return why
