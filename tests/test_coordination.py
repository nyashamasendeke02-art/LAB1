"""D54: hierarchical coordination -- Research Director plans and reviews programmes, the
Engineering Director splits engineering items into specialty tasks routed to specialists."""

import hashlib
from pathlib import Path

import pytest

from autolab.agents import ScriptedBackend
from autolab.coordination import (COMPLETE, HALTED, REVIEWING, RUNNING, Coordinator,
                                  validate_items, validate_tasks)
from autolab.gates import Gates
from autolab.registry import Registry, RegistryError
from autolab.taxonomy import Role

import scenario
from scenario import FAST_CONFIG, make, ok
from test_p0_lab_upgrades import verify_spec

R1 = {"key": "R1", "kind": "research", "objective": "Investigate whether treat can produce "
      "higher score", "rationale": "the core question", "priority": 1}
E1 = {"key": "E1", "kind": "engineering", "objective": "Message contract library",
      "acceptance_criteria": ["VERSION constant", "tests pass"], "depends_on": ["R1"],
      "rationale": "needed downstream", "priority": 2}
TASKS = [{"key": "api", "specialty": "backend", "spec": "Contract API module",
          "acceptance_criteria": ["VERSION exists"]},
         {"key": "model", "specialty": "ml", "spec": "Contract model module",
          "acceptance_criteria": ["model file exists"], "depends_on": ["api"]}]


def build_unique(t):
    """An engineering build that always changes something task-specific."""
    wd = Path(t.workdir)
    (wd / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (wd / "src" / "contracts" / "msg.py").write_text("VERSION = 1\n", encoding="utf-8")
    tag = hashlib.sha1(t.objective.encode()).hexdigest()[:8]
    (wd / "src" / f"task_{tag}.py").write_text(f"TAG = '{tag}'\n", encoding="utf-8")
    (wd / "tests").mkdir(exist_ok=True)
    (wd / "tests" / f"test_{tag}.py").write_text(
        f"from src.task_{tag} import TAG\n\ndef test_tag():\n    assert TAG == '{tag}'\n",
        encoding="utf-8")
    return ok({"summary": f"built {tag}"})


def verify_any(t):
    """The verifier for whichever project type it is reviewing."""
    if (Path(t.workdir) / "experiment.py").exists():
        return scenario.verify_pass(t)
    return verify_spec(t)


def plan_of(*items, summary="two-line programme"):
    return lambda t: ok({"plan_summary": summary, "items": list(items),
                         "success_criteria": ["R1 answered", "E1 delivered"]})


def reviews(*payloads):
    calls = {"n": 0}

    def h(t):
        p = payloads[min(calls["n"], len(payloads) - 1)]
        calls["n"] += 1
        return ok(p)
    return h


COMPLETE_REVIEW = {"decision": "complete", "assessment": "R1 supported and E1 delivered"}


def coord(tmp_path, config=FAST_CONFIG, **over):
    lab, ctl = make(tmp_path, config=config, **over)
    return lab, ctl, Coordinator(ctl)


# ----------------------------------------------------------------- validation
def test_plan_validation():
    assert validate_items([R1, E1], {}, 12) == []
    assert any("unique" in e for e in validate_items([R1, R1], {}, 12))
    assert any("unknown items" in e for e in validate_items([E1], {}, 12))
    assert any("acceptance_criteria" in e for e in validate_items(
        [R1, {**E1, "acceptance_criteria": []}], {}, 12))
    cyc = [{**R1, "depends_on": ["E1"]}, E1]
    assert any("cycle" in e for e in validate_items(cyc, {}, 12))
    assert any("at most 1" in e for e in validate_items([R1, E1], {}, 1))
    # replans may depend on existing items but not reuse their keys
    existing = {"R1": {"depends_on": []}}
    assert validate_items([E1], existing, 12) == []
    assert any("new and unique" in e for e in validate_items([R1], existing, 12))


def test_task_validation():
    spec = ("backend", "ml")
    assert validate_tasks(TASKS, spec, 8) == []
    assert any("specialty" in e for e in validate_tasks(TASKS, ("backend",), 8))
    bad = [{**TASKS[0], "depends_on": ["model"]}, TASKS[1]]
    assert any("cycle" in e for e in validate_tasks(bad, spec, 8))
    assert any("at most 1" in e for e in validate_tasks(TASKS, spec, 1))


def test_specialty_allocation(tmp_path):
    reg = Registry({"agents": {"scientist": {"backend": "codex-cli"},
                               "engineer": {"backend": "claude-cli"},
                               "verifier": {"backend": "codex-cli"}}}, tmp_path)
    reg.upsert("ml_engineer", {"backend": "gemini-cli", "model": "m"})
    reg.allocate({"build@ml": "ml_engineer"})
    assert reg.resolve("build", Role.ENGINEER, "ml") == "ml_engineer"
    assert reg.resolve("build", Role.ENGINEER, "backend") == "engineer"
    assert reg.resolve("build", Role.ENGINEER) == "engineer"
    with pytest.raises(RegistryError, match="unknown stage"):
        reg.allocate({"design@ml": "ml_engineer"})
    created = reg.apply_preset(specialties=("backend", "ml"))
    assert {"engineering_director", "backend_engineer", "ml_engineer"} <= set(created)
    eff = reg.describe()["effective"]
    assert eff["programme_plan"] == "research_director"
    assert eff["engineering_breakdown"] == "engineering_director"
    assert reg.resolve("implement", Role.ENGINEER, "backend") == "backend_engineer"


# ----------------------------------------------------------------- full hierarchy
def test_programme_runs_the_hierarchy_end_to_end(tmp_path):
    breakdown_seen = []

    def breakdown(t):
        breakdown_seen.append(t)
        return ok({"architecture_notes": "api first, model on top", "tasks": TASKS})

    lab, ctl, co = coord(tmp_path, sci__programme_plan=plan_of(R1, E1),
                         sci__programme_review=reviews(COMPLETE_REVIEW),
                         eng__engineering_breakdown=breakdown, eng__build=build_unique,
                         ver__verify=verify_any)
    ml = ScriptedBackend({"build": build_unique}, "ml-model")
    ctl.registry.upsert("ml_engineer", {"backend": "gemini-cli", "model": "ml-model",
                                        "title": "ML Engineer"})
    ctl.registry.allocate({"build@ml": "ml_engineer"})
    ctl.injected["ml_engineer"] = ml
    prg = co.new_programme("Answer R1 and deliver the contract library")
    steps = co.run(prg)
    assert steps[-1].after == COMPLETE, [(s.before, s.after, s.note, s.error) for s in steps]
    d = co.programme(prg).data
    items = d["items"]
    assert [k for k in d["order"]] == ["R1", "E1", "E1.api", "E1.model"]
    assert items["E1"]["status"] == "done" and items["E1"]["children"] == ["E1.api", "E1.model"]
    assert all(items[k]["status"] == "done" for k in d["order"])
    # dependency order: research first, then api, then model
    pids = [items[k]["projects"][0] for k in ("R1", "E1.api", "E1.model")]
    assert pids == sorted(pids)
    research, api, model = (lab.store.get(p).data for p in pids)
    assert research["kind"] == "research" and research["programme"] == prg
    assert api["specialty"] == "backend" and model["specialty"] == "ml"
    assert api["refs"]["programme"] == prg and model["programme_item"] == "E1.model"
    # specialty routing: the ml task was built by the ml specialist, the backend task by default
    builds = {t.data["project"]: t.data["agent"] for t in lab.store.query("task")
              if t.data["stage"] == "build"}
    assert builds[pids[2]] == "ml_engineer" and builds[pids[1]] == "engineer"
    assert ml.calls and all(stage == "build" for stage, _ in ml.calls)
    # the Engineering Director read the repo through a read-only checkout and saw R1 done
    assert breakdown_seen[0].writable is False and breakdown_seen[0].workdir
    assert breakdown_seen[0].context["specialties"]
    # directors' calls are recorded against the programme
    director = [t for t in lab.store.query("task") if t.data["project"] == prg]
    assert [t.data["stage"] for t in director] == [
        "programme_plan", "engineering_breakdown", "programme_review"]
    assert [x["stage"] for x in d["decisions"]] == ["programme_plan", "programme_review"]
    assert len(lab.store.query("delivery")) == 2 and lab.store.query("conclusion")
    text = (lab.exports / "PROGRAMMES.md").read_text(encoding="utf-8")
    assert prg in text and "E1.model" in text and "**done**" in text


def test_review_retries_a_halted_item_and_replans(tmp_path):
    R2 = {**R1, "key": "R2", "objective": "Investigate whether treat helps on a second "
          "dataset", "depends_on": ["R1"]}
    lab, ctl, co = coord(tmp_path, sci__programme_plan=plan_of(R1),
                         sci__programme_review=reviews(
                             {"decision": "continue", "assessment": "R1 halted by an operator; "
                              "cause addressed", "retry": ["R1"]},
                             {"decision": "replan", "assessment": "R1 answered; extend to R2",
                              "new_items": [R2]},
                             COMPLETE_REVIEW))
    prg = co.new_programme("Answer R1")
    assert co.step(prg).after == RUNNING          # plan
    co.step(prg)                                  # R1 started
    first = co.programme(prg).data["items"]["R1"]["projects"][0]
    ctl.halt(first, "operator stop for the test")
    steps = co.run(prg)
    assert steps[-1].after == COMPLETE, [(s.before, s.after, s.note, s.error) for s in steps]
    d = co.programme(prg).data
    assert len(d["items"]["R1"]["projects"]) == 2          # retried as a fresh project
    assert lab.store.get(first).data["state"] == "HALTED"  # the halted one stays as a record
    assert d["items"]["R2"]["status"] == "done" and d["reviews"] == 3
    assert [x.get("decision") for x in d["decisions"][1:]] == ["continue", "replan", "complete"]
    # the replanned item's project received the earlier project's knowledge
    r2 = d["items"]["R2"]["projects"][0]
    import json
    t = next(t for t in lab.store.query("task")
             if t.data["project"] == r2 and t.data["stage"] == "define_problem")
    ctx = json.loads((lab.handoffs / t.id / "task.json").read_text(encoding="utf-8"))["context"]
    assert any(i["source"].startswith("lab:lab/CON-") for i in ctx["lab_knowledge"]["items"])


def test_escalation_halts_with_blockers_and_resume(tmp_path):
    lab, ctl, co = coord(tmp_path, sci__programme_plan=plan_of(R1),
                         sci__programme_review=reviews(
                             {"decision": "escalate", "assessment": "needs hardware",
                              "blockers": ["no robot available for Gate 7"]}, COMPLETE_REVIEW))
    prg = co.new_programme("Answer R1")
    steps = co.run(prg)
    assert steps[-1].after == HALTED
    assert "no robot available" in co.programme(prg).data["halt_reason"]
    with pytest.raises(ValueError):
        co.resume(co.new_programme("other"), "not halted")
    co.resume(prg, "robot borrowed")
    assert co.programme(prg).data["state"] == REVIEWING
    assert co.run(prg)[-1].after == COMPLETE


def test_programme_stops_at_a_human_gate(tmp_path):
    lab, ctl, co = coord(tmp_path, sci__programme_plan=plan_of(R1),
                         sci__programme_review=reviews(COMPLETE_REVIEW),
                         sci__design=scenario.design(kind="confirmatory"))
    prg = co.new_programme("Answer R1 confirmatorily")
    steps = co.run(prg)
    last = steps[-1]
    assert last.blocked_on and last.blocked_on.startswith("APR-")
    assert co.programme(prg).data["state"] == RUNNING
    Gates(lab.store).decide(last.blocked_on, True, by="human", note="pre-registration read")
    assert co.run(prg)[-1].after == COMPLETE


def test_invalid_plans_are_rejected_then_halt(tmp_path):
    cyclic = [{**R1, "depends_on": ["E1"]}, E1]
    lab, ctl, co = coord(tmp_path, sci__programme_plan=plan_of(*cyclic))
    prg = co.new_programme("bad plan")
    steps = co.run(prg)
    assert steps[-1].after == HALTED
    assert any("cycle" in (s.error or "") for s in steps)
    fails = [f for f in lab.store.query("failure") if f.data["category"] == "programme_stage_error"]
    assert len(fails) == 2 and not lab.store.query("project")


def test_review_without_runnable_work_halts(tmp_path):
    lab, ctl, co = coord(tmp_path, sci__programme_plan=plan_of(R1),
                         sci__programme_review=reviews({"decision": "continue",
                                                        "assessment": "keep going"}))
    prg = co.new_programme("Answer R1")
    steps = co.run(prg)
    assert steps[-1].after == HALTED
    assert "without new items" in co.programme(prg).data["halt_reason"]


def test_complete_requires_every_item_done_or_dropped(tmp_path):
    E2 = {**E1, "key": "E2", "depends_on": ["R1"]}
    lab, ctl, co = coord(tmp_path, sci__programme_plan=plan_of(R1, E2),
                         sci__programme_review=reviews(
                             COMPLETE_REVIEW,  # rejected: R1 halted, E2 never ran
                             {"decision": "complete", "assessment": "R1 cannot be answered with "
                              "this budget; E2 depends on it",
                              "dropped": {"R1": "halted twice; out of scope",
                                          "E2": "depends on R1"}}))
    prg = co.new_programme("Answer R1 then build E2")
    co.step(prg)
    co.step(prg)
    ctl.halt(co.programme(prg).data["items"]["R1"]["projects"][0], "test stop")
    steps = co.run(prg)
    assert steps[-1].after == COMPLETE, [(s.before, s.after, s.note, s.error) for s in steps]
    assert any("neither done nor dropped" in (s.error or "") for s in steps)
    d = co.programme(prg).data
    assert d["items"]["R1"]["status"] == "dropped" and d["items"]["E2"]["status"] == "dropped"
    assert d["items"]["R1"]["drop_reason"].startswith("halted twice")
    assert d["decisions"][-1]["dropped"] == {"R1": "halted twice; out of scope",
                                             "E2": "depends on R1"}
    assert not lab.store.query("delivery")  # E2 was never built
