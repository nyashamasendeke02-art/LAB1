"""Hierarchical coordination (D54): programmes.

A **programme** is an objective too large for one project. The hierarchy that runs it::

    Research Director   programme_plan    -> work items (research | engineering) with dependencies
      research items                      -> research projects (the full research cycle each)
      engineering items
        Engineering Director  engineering_breakdown -> specialty tasks (backend, ml, ...)
          specialist engineers              -> engineering projects routed by <stage>@<specialty>
    Research Director   programme_review  -> continue | replan | complete | escalate

The controller (not an agent) owns the programme's state, validates every plan (keys, kinds,
dependencies, acyclicity, budgets), schedules items in dependency and priority order, runs their
projects, and stops at the first human gate or halt -- nothing is approved or retried behind a
human's back. Directors are ordinary allocated agents going through the same audited call path
as every stage (permissions, handoff files, tamper check, provenance).

Programme states: PLANNING -> RUNNING <-> REVIEWING -> COMPLETE | HALTED.
Item statuses: pending -> running -> done | halted; engineering items whose tasks were created
are ``split`` and become ``done`` when all their tasks are done. A review may mark unfinished
items ``dropped`` (with a reason); a programme completes only when every item is done or dropped.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .agents import agent_wait_kind
from .feedback import open_observations, triage
from .registry import DEFAULT_SPECIALTIES
from .state_machines import ResearchState as R
from .taxonomy import Role

PLANNING, RUNNING, REVIEWING, COMPLETE, HALTED = (
    "PLANNING", "RUNNING", "REVIEWING", "COMPLETE", "HALTED")
PROGRAMME_STATES = (PLANNING, RUNNING, REVIEWING, COMPLETE, HALTED)
PROGRAMME_TRANSITIONS = {
    PLANNING: {RUNNING, HALTED},
    RUNNING: {REVIEWING, HALTED},
    REVIEWING: {RUNNING, COMPLETE, HALTED},
    COMPLETE: set(),
    HALTED: set(),   # leaving HALTED is a human action (resume)
}
ITEM_DONE, ITEM_HALTED, ITEM_DROPPED = "done", "halted", "dropped"


class PlanError(ValueError):
    pass


def _cycle(nodes: dict[str, list[str]]) -> list[str] | None:
    """A dependency cycle among ``nodes`` (key -> deps), or None."""
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(k: str) -> list[str] | None:
        state[k] = 1
        stack.append(k)
        for d in nodes.get(k, []):
            if state.get(d) == 1:
                return stack[stack.index(d):] + [d]
            if d in nodes and state.get(d) is None:
                found = visit(d)
                if found:
                    return found
        state[k] = 2
        stack.pop()
        return None

    for k in nodes:
        if state.get(k) is None:
            found = visit(k)
            if found:
                return found
    return None


def validate_items(new: list[dict], existing: dict[str, dict], max_items: int) -> list[str]:
    """Errors in a plan (or replan) given the items that already exist."""
    errs = []
    keys = [it["key"] for it in new]
    dup = sorted({k for k in keys if keys.count(k) > 1} | (set(keys) & set(existing)))
    if dup:
        errs.append(f"item keys must be new and unique: {dup}")
    if len(existing) + len(new) > max_items:
        errs.append(f"a programme has at most {max_items} work items "
                    f"({len(existing)} exist, {len(new)} proposed)")
    known = set(existing) | set(keys)
    for it in new:
        unknown = sorted(set(it.get("depends_on", [])) - known)
        if unknown:
            errs.append(f"item {it['key']}: depends_on unknown items {unknown}")
        if it["key"] in it.get("depends_on", []):
            errs.append(f"item {it['key']} depends on itself")
        if it["kind"] == "engineering" and not it.get("acceptance_criteria"):
            errs.append(f"engineering item {it['key']} needs acceptance_criteria")
    graph = {k: list(v.get("depends_on", [])) for k, v in existing.items()}
    graph.update({it["key"]: list(it.get("depends_on", [])) for it in new})
    cyc = _cycle(graph)
    if cyc:
        errs.append("dependency cycle: " + " -> ".join(cyc))
    return errs


def validate_tasks(tasks: list[dict], specialties: tuple[str, ...], max_tasks: int) -> list[str]:
    errs = []
    keys = [t["key"] for t in tasks]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        errs.append(f"task keys must be unique: {dup}")
    if len(tasks) > max_tasks:
        errs.append(f"an engineering item has at most {max_tasks} tasks ({len(tasks)} proposed)")
    for t in tasks:
        if t["specialty"] not in specialties:
            errs.append(f"task {t['key']}: specialty {t['specialty']!r} is not one of "
                        f"{list(specialties)}")
        unknown = sorted(set(t.get("depends_on", [])) - set(keys))
        if unknown:
            errs.append(f"task {t['key']}: depends_on unknown tasks {unknown}")
    cyc = _cycle({t["key"]: list(t.get("depends_on", [])) for t in tasks})
    if cyc:
        errs.append("dependency cycle: " + " -> ".join(cyc))
    return errs


@dataclass
class ProgrammeStep:
    programme: str
    before: str
    after: str
    note: str = ""
    blocked_on: str | None = None   # approval id or project id needing a human
    error: str | None = None


class Coordinator:
    """Runs programmes on top of a Controller (which runs the projects)."""

    def __init__(self, ctl):
        self.ctl = ctl
        self.store = ctl.store
        c = ctl.cfg.get("coordination", {}) or {}
        self.specialties = tuple(c.get("specialties") or DEFAULT_SPECIALTIES)
        self.max_items = int(c.get("max_items", 12))
        self.max_tasks = int(c.get("max_tasks_per_item", 8))
        self.max_reviews = int(c.get("max_reviews", 6))

    # ------------------------------------------------------------------ records
    def new_programme(self, objective: str, mandate_refs: list[str] | None = None,
                      author: str = "human", items: list[dict] | None = None) -> str:
        """``items`` given (e.g. /build: one engineering item) skips the Research Director's
        planning step: the programme starts RUNNING with those validated items."""
        if not objective.strip():
            raise ValueError("a programme needs an objective")
        from .autonomy import AutonomyError, lab_level
        if lab_level(self.ctl.cfg) < 4:
            raise AutonomyError("programmes (multi-step planning by directors) need autonomy "
                                "level >= 4 ([lab] autonomy_level)")
        start: dict = {"state": PLANNING, "items": {}, "order": [], "decisions": []}
        if items:
            errs = validate_items(items, {}, self.max_items)
            if errs:
                raise PlanError("; ".join(errs))
            start = {"state": RUNNING, "items": {it["key"]: self._item(it, 1) for it in items},
                     "order": [it["key"] for it in items],
                     "decisions": [{"stage": "submitted_plan", "by": author,
                                    "summary": f"{len(items)} item(s) given with the request"}]}
        rec = self.store.create("programme", {
            "kind": "programme", "objective": objective.strip(), **start,
            "cycle": 1, "reviews": 0,
            "mandate_refs": list(mandate_refs or []), "halt_reason": None, "blocked_on": None,
            "retries": 0, "refs": {}}, prefix="PRG", author=author,
            reason="programme objective submitted")
        self.ctl._export()
        return rec.id

    def programme(self, prg: str):
        rec = self.store.get(prg)
        if rec.kind != "programme":
            raise KeyError(prg)
        return rec

    def _save(self, prg: str, reason: str, **changes) -> None:
        self.store.update(prg, changes, reason=reason)

    def _to(self, prg: str, target: str, reason: str, **changes) -> None:
        cur = self.programme(prg).data["state"]
        if target not in PROGRAMME_TRANSITIONS[cur]:
            raise ValueError(f"illegal programme transition {cur} -> {target}")
        self.store.update(prg, {"state": target, **changes}, reason=f"{cur} -> {target}: {reason}")
        self.store.append_event("controller", "programme.transition", prg,
                                {"from": cur, "to": target, "reason": reason})

    def _halt(self, prg: str, reason: str) -> None:
        self._to(prg, HALTED, reason, halt_reason=reason)

    @staticmethod
    def _item(it: dict, round_: int, parent: str | None = None) -> dict:
        return {"key": it["key"], "kind": it["kind"], "objective": it.get("objective") or it.get("spec"),
                "acceptance_criteria": list(it.get("acceptance_criteria", [])),
                "depends_on": list(it.get("depends_on", [])),
                "priority": int(it.get("priority", 50)), "rationale": it.get("rationale", ""),
                "mandate_refs": list(it.get("mandate_refs", [])),
                "specialty": it.get("specialty"), "parent": parent, "children": [],
                "status": "pending", "projects": [], "round": round_}

    # ------------------------------------------------------------------ status
    def _project_outcome(self, pid: str) -> dict:
        p = self.ctl.project(pid).data
        out = {"project": pid, "state": p["state"], "halt_reason": p.get("halt_reason"),
               "blocked_on": p.get("blocked_on")}
        cons = self.store.query("conclusion", project=pid)
        if cons:
            out["conclusions"] = [{"id": c.id, "outcome": c.data.get("outcome"),
                                   "statement": c.data.get("statement", "")[:400],
                                   "confidence": c.data.get("confidence")} for c in cons]
        dlv = self.store.query("delivery", project=pid)
        if dlv:
            out["delivery"] = {"id": dlv[-1].id, "commit": dlv[-1].data.get("commit")}
        fqs = self.store.query("future_question", project=pid)
        if fqs:
            out["open_questions"] = [q.data.get("question", "")[:300] for q in fqs
                                     if q.data.get("status") == "open"]
        return out

    def status(self, prg: str) -> dict:
        d = self.programme(prg).data
        items = []
        for key in d["order"]:
            it = d["items"][key]
            items.append({k: it[k] for k in ("key", "kind", "objective", "status", "depends_on",
                                             "priority", "specialty", "parent", "children")}
                         | {"latest": self._project_outcome(it["projects"][-1])
                            if it["projects"] else None,
                            "attempts": len(it["projects"])})
        return {"objective": d["objective"], "state": d["state"], "reviews": d["reviews"],
                "items": items, "decisions": d["decisions"][-6:]}

    # ------------------------------------------------------------------ scheduling
    def _deps_done(self, items: dict, it: dict) -> bool:
        return all(items[k]["status"] == ITEM_DONE for k in it["depends_on"])

    def _blocked_by_halt(self, items: dict, it: dict, seen=None) -> bool:
        seen = seen or set()
        for k in it["depends_on"]:
            if k in seen:
                continue
            seen.add(k)
            dep = items[k]
            if dep["status"] in (ITEM_HALTED, ITEM_DROPPED) or self._blocked_by_halt(
                    items, dep, seen):
                return True
        return False

    def _refresh(self, prg: str) -> dict:
        """Update item statuses from their projects; split items finish with their tasks."""
        d = self.programme(prg).data
        items = d["items"]
        changed = False
        for it in items.values():
            if it["status"] == "running" and it["projects"]:
                state = self.ctl.project(it["projects"][-1]).data["state"]
                new = {R.COMPLETE.value: ITEM_DONE, R.HALTED.value: ITEM_HALTED}.get(state)
                if new:
                    it["status"] = new
                    changed = True
        for it in items.values():
            if it["status"] == "split" and it["children"]:
                kids = [items[k]["status"] for k in it["children"]]
                new = (ITEM_DONE if all(s == ITEM_DONE for s in kids)
                       else ITEM_HALTED if any(s == ITEM_HALTED for s in kids) else None)
                if new:
                    it["status"] = new
                    changed = True
        if changed:
            self._save(prg, "item statuses refreshed from projects", items=items)
        return items

    def _next_ready(self, items: dict, order: list[str]) -> dict | None:
        ready = [items[k] for k in order
                 if items[k]["status"] == "pending" and self._deps_done(items, items[k])]
        return min(ready, key=lambda it: (it["priority"], order.index(it["key"]))) if ready else None

    def _start(self, prg: str, it: dict) -> str:
        d = self.programme(prg).data
        refs = list(dict.fromkeys(d["mandate_refs"] + it["mandate_refs"]))
        if it["kind"] == "research":
            pid = self.ctl.new_project(it["objective"], refs, author="controller")
        else:  # engineering task (a child of an engineering item)
            pid = self.ctl.new_engineering_project(it["objective"], it["acceptance_criteria"],
                                                   refs, author="controller",
                                                   specialty=it.get("specialty"))
        self.store.update(pid, {"programme": prg, "programme_item": it["key"],
                                "refs": {**self.ctl.project(pid).data.get("refs", {}),
                                         "programme": prg}},
                          reason=f"work item {it['key']} of {prg}")
        return pid

    # ------------------------------------------------------------------ steps
    def step(self, prg: str, on_project_step: Callable | None = None) -> ProgrammeStep:
        d = self.programme(prg).data
        state = d["state"]
        if state in (COMPLETE, HALTED):
            return ProgrammeStep(prg, state, state, "terminal")
        try:
            if state == PLANNING:
                return self._plan(prg)
            if state == RUNNING:
                return self._run_one(prg, on_project_step)
            return self._review(prg)
        except Exception as exc:
            if agent_wait_kind(exc):
                raise  # usage limits / network: the caller waits and retries
            retries = d.get("retries", 0) + 1
            self._save(prg, f"stage error in {state}", retries=retries)
            self.store.create("failure", {"category": "programme_stage_error",
                                          "summary": f"{state}: {type(exc).__name__}: {exc}"[:500],
                                          "programme": prg, "state": state, "refs": {}},
                              prefix="FAIL", reason="programme stage error")
            if retries > self.ctl.limits["max_stage_retries"]:
                self._halt(prg, f"{state} failed {retries} times; last: {exc}"[:400])
            return ProgrammeStep(prg, state, self.programme(prg).data["state"], "stage error",
                                 error=str(exc)[:400])

    def _plan(self, prg: str) -> ProgrammeStep:
        payload, tid = self.ctl._call(prg, Role.SCIENTIST, "programme_plan",
                                      {"programme_objective": self.programme(prg).data["objective"],
                                       "max_items": self.max_items})
        errs = validate_items(payload["items"], {}, self.max_items)
        if errs:
            raise PlanError("plan rejected by controller: " + "; ".join(errs))
        items = {it["key"]: self._item(it, 1) for it in payload["items"]}
        self._to(prg, RUNNING, f"plan with {len(items)} items ({tid})", items=items,
                 order=[it["key"] for it in payload["items"]],
                 plan_summary=payload["plan_summary"],
                 success_criteria=payload.get("success_criteria", []),
                 decisions=[{"stage": "programme_plan", "task": tid,
                             "summary": payload["plan_summary"]}], retries=0)
        return ProgrammeStep(prg, PLANNING, RUNNING, f"{len(items)} work items")

    def _breakdown(self, prg: str, it: dict) -> ProgrammeStep:
        d = self.programme(prg).data
        wt = self.ctl._scratch_checkout(f"breakdown-{prg}-{it['key']}", self.ctl.repo.rev("main"))
        try:
            payload, tid = self.ctl._call(prg, Role.ENGINEER, "engineering_breakdown", {
                "programme_objective": d["objective"], "work_item": {
                    k: it[k] for k in ("key", "objective", "acceptance_criteria", "rationale")},
                "specialties": list(self.specialties), "max_tasks": self.max_tasks},
                workdir=wt)
        finally:
            self.ctl.repo.remove_worktree(wt)
        errs = validate_tasks(payload["tasks"], self.specialties, self.max_tasks)
        if errs:
            raise PlanError(f"breakdown of {it['key']} rejected by controller: " + "; ".join(errs))
        items, order = d["items"], d["order"]
        prefix = it["key"]
        for t in payload["tasks"]:
            key = f"{prefix}.{t['key']}"[:48]
            child = self._item({**t, "kind": "engineering_task", "objective": t["spec"],
                                "depends_on": [f"{prefix}.{k}"[:48] for k in t.get("depends_on", [])]
                                + list(it["depends_on"]),
                                "priority": it["priority"], "mandate_refs": it["mandate_refs"]},
                               it["round"], parent=prefix)
            child["key"] = key
            items[key] = child
            order.insert(order.index(prefix) + 1 + len(items[prefix]["children"]), key)
            items[prefix]["children"].append(key)
        items[prefix]["status"] = "split"
        items[prefix]["architecture_notes"] = payload["architecture_notes"]
        self._save(prg, f"{prefix} broken into {len(payload['tasks'])} tasks ({tid})",
                   items=items, order=order)
        return ProgrammeStep(prg, RUNNING, RUNNING,
                             f"Engineering Director split {prefix} into {len(payload['tasks'])} tasks")

    def _run_one(self, prg: str, on_project_step: Callable | None) -> ProgrammeStep:
        items = self._refresh(prg)
        d = self.programme(prg).data
        order = d["order"]
        # 1. continue a running project (it may be waiting on an approval)
        running = [items[k] for k in order if items[k]["status"] == "running"]
        if running:
            it = running[0]
            pid = it["projects"][-1]
            steps = self.ctl.run(pid, on_step=on_project_step)
            items = self._refresh(prg)
            last = steps[-1] if steps else None
            if items[it["key"]]["status"] == "running":
                blocked = (last.blocked_on if last else None) or self.ctl.project(pid).data.get(
                    "blocked_on")
                self._save(prg, f"waiting on {pid}", blocked_on=blocked or pid)
                return ProgrammeStep(prg, RUNNING, RUNNING, f"{it['key']}: {pid} needs a human",
                                     blocked_on=blocked or pid)
            self._save(prg, f"{it['key']} {items[it['key']]['status']}", blocked_on=None)
            return ProgrammeStep(prg, RUNNING, RUNNING,
                                 f"{it['key']} {items[it['key']]['status']} ({pid})")
        # 2. start the next ready item (engineering items go to the Engineering Director)
        it = self._next_ready(items, order)
        if it is not None:
            if it["kind"] == "engineering":
                return self._breakdown(prg, it)
            pid = self._start(prg, it)
            items[it["key"]]["status"] = "running"
            items[it["key"]]["projects"].append(pid)
            self._save(prg, f"{it['key']} started as {pid}", items=items)
            return ProgrammeStep(prg, RUNNING, RUNNING, f"{it['key']} started as {pid}")
        # 3. nothing can progress: the Research Director reviews
        self._to(prg, REVIEWING, "no runnable work items left")
        return ProgrammeStep(prg, RUNNING, REVIEWING, "review")

    def _review(self, prg: str) -> ProgrammeStep:
        d = self.programme(prg).data
        if d["reviews"] >= self.max_reviews:
            self._halt(prg, f"review budget exhausted ({self.max_reviews}); human direction "
                            f"required")
            return ProgrammeStep(prg, REVIEWING, HALTED, "review budget exhausted")
        # Feedback loop (D55): the programme's engineering/experiment failures are triaged into
        # research questions before the Research Director decides what to do next.
        projects = {p for it in d["items"].values() for p in it["projects"]}
        fed = triage(self.ctl, open_observations(self.store, projects), f"programme {prg}")
        status = self.status(prg)
        if fed["questions"]:
            status["research_questions_from_engineering"] = [
                {"id": q, "question": self.store.get(q).data["question"],
                 "observation": self.store.get(q).data["refs"]["observation"]}
                for q in fed["questions"]]
        stalled = [it["key"] for it in d["items"].values()
                   if it["status"] == "pending" and self._blocked_by_halt(d["items"], it)]
        payload, tid = self.ctl._call(prg, Role.SCIENTIST, "programme_review", {
            "programme_objective": d["objective"], "success_criteria": d.get("success_criteria", []),
            "programme_status": status, "stalled_by_halted_dependencies": stalled,
            "review_round": d["reviews"] + 1, "max_items": self.max_items})
        decision = payload["decision"]
        record = {"stage": "programme_review", "task": tid, "decision": decision,
                  "assessment": payload["assessment"], "blockers": payload.get("blockers", [])}
        items, order = d["items"], d["order"]
        reviews = d["reviews"] + 1
        dropped = payload.get("dropped") or {}
        unknown = sorted(set(dropped) - set(items))
        if unknown:
            raise PlanError(f"review drops unknown items {unknown}")
        for key, why in dropped.items():
            if items[key]["status"] not in (ITEM_DONE, ITEM_DROPPED):
                items[key]["status"] = ITEM_DROPPED
                items[key]["drop_reason"] = why
                for child in items[key]["children"]:
                    if items[child]["status"] != ITEM_DONE:
                        items[child]["status"] = ITEM_DROPPED
                        items[child]["drop_reason"] = f"parent {key} dropped: {why}"
        if decision == "complete":
            # The director may judge the objective met, but not by ignoring work: every item
            # must be done or explicitly dropped with a reason.
            open_items = sorted(k for k, it in items.items()
                                if it["status"] not in (ITEM_DONE, ITEM_DROPPED))
            if open_items:
                raise PlanError(f"'complete' rejected by controller: items {open_items} are "
                                f"neither done nor dropped (list them in 'dropped' with a "
                                f"reason, or continue)")
            self._to(prg, COMPLETE, payload["assessment"][:200], reviews=reviews, items=items,
                     decisions=d["decisions"] + [record | {"dropped": dropped}], blocked_on=None)
            return ProgrammeStep(prg, REVIEWING, COMPLETE, "Research Director: objective met")
        if decision == "escalate":
            self._to(prg, HALTED, "escalated by Research Director", reviews=reviews,
                     decisions=d["decisions"] + [record],
                     halt_reason="; ".join(payload.get("blockers") or [payload["assessment"]])[:600])
            return ProgrammeStep(prg, REVIEWING, HALTED, "escalated to a human")
        new = payload.get("new_items", [])
        errs = validate_items(new, items, self.max_items)
        retry = payload.get("retry", [])
        bad_retry = [k for k in retry if items.get(k, {}).get("status") != ITEM_HALTED]
        if bad_retry:
            errs.append(f"retry names items that are not halted: {bad_retry}")
        if errs:
            raise PlanError("review rejected by controller: " + "; ".join(errs))
        record["dropped"] = dropped
        for it in new:
            items[it["key"]] = self._item(it, reviews + 1)
            order.append(it["key"])
        for k in retry:
            # A retried research/engineering-task item runs a fresh project (the halted one
            # stays as a record); a retried split item is broken down again.
            items[k]["status"] = "pending"
            for child in items[k]["children"]:
                if items[child]["status"] == ITEM_HALTED:
                    items[child]["status"] = "pending"
            if items[k]["kind"] == "engineering":
                items[k]["status"] = "split"
        if not new and not retry:
            self._to(prg, HALTED, "review proposed no runnable work", reviews=reviews,
                     decisions=d["decisions"] + [record],
                     halt_reason=f"Research Director chose {decision!r} without new items or "
                                 f"retries; human direction required")
            return ProgrammeStep(prg, REVIEWING, HALTED, "no runnable work proposed")
        self._to(prg, RUNNING, f"{decision}: {len(new)} new items, {len(retry)} retries",
                 items=items, order=order, reviews=reviews, cycle=reviews + 1,
                 decisions=d["decisions"] + [record], retries=0)
        return ProgrammeStep(prg, REVIEWING, RUNNING, f"{decision}: +{len(new)} items, "
                                                      f"{len(retry)} retries")

    # ------------------------------------------------------------------ loop
    def run(self, prg: str, max_steps: int = 200,
            on_step: Callable[[ProgrammeStep], None] | None = None,
            on_project_step: Callable | None = None) -> list[ProgrammeStep]:
        """Step until COMPLETE, HALTED or a human is needed. Usage limits and network errors
        in director calls wait (as for projects) instead of counting as failures."""
        out: list[ProgrammeStep] = []
        waited = 0.0
        for _ in range(max_steps):
            try:
                s = self.step(prg, on_project_step)
            except Exception as exc:
                kind = agent_wait_kind(exc)
                wait = float(self.ctl.limits.get(
                    "usage_limit_wait_s" if kind == "usage_limit" else "network_wait_s", 900))
                cap = float(self.ctl.limits.get(
                    "usage_limit_max_wait_s" if kind == "usage_limit" else "network_max_wait_s",
                    43200))
                if waited + wait > cap:
                    self._halt(prg, f"agent {kind} persisted beyond {cap:.0f}s: {exc}"[:400])
                    out.append(ProgrammeStep(prg, self.programme(prg).data["state"], HALTED,
                                             f"{kind} wait exhausted"))
                    break
                waited += wait
                self.ctl.sleep(wait)
                continue
            out.append(s)
            if on_step:
                on_step(s)
            if s.after in (COMPLETE, HALTED) or s.blocked_on:
                break
        self.ctl._export()
        return out

    def resume(self, prg: str, note: str, by: str = "human") -> None:
        d = self.programme(prg).data
        if d["state"] != HALTED:
            raise ValueError(f"{prg} is {d['state']}, not HALTED")
        self.store.update(prg, {"state": REVIEWING, "halt_reason": None, "retries": 0,
                                "reviews": min(d["reviews"], self.max_reviews - 1)},
                          author=by, reason=f"resumed by {by}: {note}")
        self.store.append_event(by, "programme.resumed", prg, {"note": note})
