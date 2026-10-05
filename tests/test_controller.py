import json
import os
import stat
from pathlib import Path

import pytest

from autolab.controller import Controller, Lab
from autolab.memory import trace

import scenario
from scenario import FAST_CONFIG, agents, make, ok


def states(steps):
    return [(s.before, s.after) for s in steps]


def test_full_loop_completes_with_traceable_result(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE", steps[-1]
    st = lab.store
    con = st.query("conclusion")[0]
    assert con.data["outcome"] == "supported"
    assert con.data["label"] == "EXPERIMENTAL_RESULT"
    assert con.data["confidence"].startswith("preliminary")  # exploratory
    hyp = st.get(con.data["hypothesis"])
    assert hyp.data["status"] == "supported" and hyp.data["label"] == "HYPOTHESIS"
    run = st.query("run")[0]
    # result -> run -> exact merged commit on main, frozen protocol, env
    assert run.data["commit"] == lab.repo.rev("main")
    assert run.data["freeze_hash"] == st.get(run.data["refs"]["protocol"]).data["_freeze_hash"]
    assert "Autolab-Eng" in lab.repo.commit_message(run.data["commit"])
    tree = json.dumps(trace(st, con.id))
    assert run.id in tree and run.data["commit"] in tree
    # raw data preserved read-only and hashed
    t0 = run.data["trials"][0]
    metrics_file = lab.root / t0["out_dir"] / "metrics.json"
    assert not os.access(metrics_file, os.W_OK)
    assert lab.artifacts.has(t0["files"]["metrics.json"][7:])
    assert (lab.root / st.query("report")[0].data["path"]).exists()
    assert st.verify_chain() > 50
    assert (lab.exports / "CONCLUSIONS.md").read_text().count("CON-0001") == 1
    # verification tests were merged alongside implementation
    assert (lab.repo.path / "tests" / "verification" / "test_v.py").exists()


def test_unsupported_hypothesis_is_a_result_not_a_failure(tmp_path):
    lab, ctl = make(tmp_path, sci__design=scenario.design(effect=0.0))
    pid = ctl.new_project("Investigate whether a null treatment raises score")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    con = lab.store.query("conclusion")[0]
    assert con.data["outcome"] == "unsupported"
    assert lab.store.get(con.data["hypothesis"]).data["status"] == "rejected"
    assert not lab.store.query("failure", category="invalid_experiment")


def test_inconclusive_triggers_redesign_and_retains_every_conclusion(tmp_path):
    lab, ctl = make(tmp_path, sci__design=scenario.design(effect=0.6, noise=3.0))
    pid = ctl.new_project("noisy")
    steps = ctl.run(pid)
    assert ("EVALUATE", "DESIGN") in states(steps)
    cons = lab.store.query("conclusion")
    assert len(cons) >= 2 and all(c.data["outcome"] == "inconclusive" for c in cons)
    assert steps[-1].after == "COMPLETE"


def test_confirmatory_protocol_needs_human_preregistration(tmp_path):
    lab, ctl = make(tmp_path, sci__design=scenario.design(kind="confirmatory"))
    pid = ctl.new_project("confirm")
    steps = ctl.run(pid)
    assert steps[-1].after == "PROTOCOL_FREEZE" and steps[-1].blocked_on
    assert not lab.store.query("eng_task")  # nothing implemented before approval
    assert ctl.step(pid).blocked_on  # stays blocked
    ctl.gates.decide(steps[-1].blocked_on, True, by="human", note="pre-registered")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert lab.store.query("conclusion")[0].data["confidence"] == "confirmatory"


def test_rejected_preregistration_returns_to_design(tmp_path):
    lab, ctl = make(tmp_path, sci__design=scenario.design(kind="confirmatory"))
    pid = ctl.new_project("confirm")
    apr = ctl.run(pid)[-1].blocked_on
    ctl.gates.decide(apr, False, by="human", note="underpowered")
    res = ctl.step(pid)
    assert res.after == "DESIGN"
    assert "underpowered" in json.dumps(lab.store.get(pid).data["feedback"])


def test_protected_experiment_not_run_without_authorization(tmp_path):
    lab, ctl = make(tmp_path, sci__design=scenario.design(protected=True))
    pid = ctl.new_project("protected")
    steps = ctl.run(pid)
    assert steps[-1].after == "RUN_EXPERIMENT" and steps[-1].blocked_on
    assert not lab.store.query("run")
    assert not any(p.name.startswith("RUN-") for p in lab.runs.iterdir())
    ctl.gates.decide(steps[-1].blocked_on, False, by="human", note="not now")
    assert ctl.step(pid).after == "DESIGN"
    assert not lab.store.query("run")


def test_patch_after_failing_tests(tmp_path):
    lab, ctl = make(tmp_path, eng__implement=[scenario.implement_failing, scenario.implement])
    pid = ctl.new_project("patch")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    eng = lab.store.query("eng_task")[0]
    assert eng.data["patch_attempts"] == 1 and eng.data["redesigns"] == 0
    assert [t["passed"] for t in eng.data["test_runs"]] == [False, True]
    assert lab.store.query("failure", category="tests_failed")


def test_repeated_failure_forces_redesign_then_escalates_to_research_design(tmp_path):
    lab, ctl = make(tmp_path, eng__implement=scenario.implement_failing,
                    eng__redesign=scenario.redesign_failing)
    pid = ctl.new_project("doomed")
    steps = ctl.run(pid)
    stages = [s for s, _ in ctl.agents[scenario.Role.ENGINEER].backend.calls]
    assert "redesign" in stages  # did not patch indefinitely
    assert ("ENGINEERING", "DESIGN") in states(steps)  # approach reconsidered
    eng = lab.store.query("eng_task")[0]
    assert eng.data["state"] == "ESCALATED"
    assert lab.repo.branch_exists(f"eng/{eng.id}-d0") and lab.repo.branch_exists(f"eng/{eng.id}-d1")
    assert lab.store.query("failure", category="approach_inadequate")
    assert steps[-1].after == "HALTED"  # design budget exhausted -> human
    assert "design iteration budget" in lab.store.get(pid).data["halt_reason"]
    assert not lab.store.query("run")


def test_engineer_cannot_edit_protocol_or_verification_tests(tmp_path):
    def sneaky(t):
        scenario.write_impl(t)
        wd = Path(t.workdir)
        prot = next((wd / "protocols").glob("PROT-*.json"))
        prot.write_text('{"min_effect": 0}')
        (wd / "tests" / "verification").mkdir(exist_ok=True)
        (wd / "tests" / "verification" / "test_fake.py").write_text("def test(): pass\n")
        return ok({"summary": "sneaky"})

    lab, ctl = make(tmp_path, eng__implement=[sneaky, scenario.implement])
    pid = ctl.new_project("integrity")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert lab.store.query("failure", category="policy_violation")
    prot_file = next((lab.repo.path / "protocols").glob("PROT-*.json"))
    assert json.loads(prot_file.read_text())["decision_rule"]["min_effect"] == 0.5
    assert not (lab.repo.path / "tests" / "verification" / "test_fake.py").exists()


def test_verifier_cannot_modify_implementation(tmp_path):
    def meddling(t):
        scenario.verify_pass(t)
        (Path(t.workdir) / "experiment.py").write_text("# rewritten by verifier\n")
        return ok({"verdict": "pass", "findings": [], "reproducibility_ok": True,
                   "protocol_compliance_ok": True})

    lab, ctl = make(tmp_path, ver__verify=meddling)
    pid = ctl.new_project("verifier scope")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert lab.store.query("failure", category="verifier_policy_violation")
    assert "rewritten" not in (lab.repo.path / "experiment.py").read_text()


def test_critical_review_finding_blocks_merge_even_if_verdict_pass(tmp_path):
    def inconsistent(t):
        scenario.verify_pass(t)
        return ok({"verdict": "pass", "findings": [{"severity": "critical",
                                                    "description": "data leakage"}],
                   "reproducibility_ok": True, "protocol_compliance_ok": True})

    lab, ctl = make(tmp_path, ver__verify=[inconsistent, scenario.verify_pass])
    pid = ctl.new_project("x")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    revs = lab.store.query("review", review_type="code_review")
    assert [r.data["passed"] for r in revs] == [False, True]


def test_invalid_experiment_draws_no_conclusion(tmp_path):
    def impossible(t):
        r = scenario.requirements(t)
        r["payload"]["validity"][0]["value"] = -100  # base score < -100: never true
        return r

    lab, ctl = make(tmp_path, sci__requirements=impossible)
    pid = ctl.new_project("broken instrument")
    steps = ctl.run(pid)
    assert ("EVALUATE", "DESIGN") in states(steps)
    assert not lab.store.query("conclusion")
    assert lab.store.query("failure", category="invalid_experiment")
    assert lab.store.get(lab.store.query("hypothesis")[0].id).data["status"] == "active"
    assert steps[-1].after == "HALTED"


def test_stage_failure_halts_then_fresh_controller_resumes(tmp_path):
    def boom(t):
        raise RuntimeError("backend unavailable")

    lab, ctl = make(tmp_path, sci__define_problem=boom)
    pid = ctl.new_project("resilience")
    steps = ctl.run(pid)
    assert steps[0].error and steps[-1].after == "HALTED"
    assert lab.store.query("failure", category="stage_error")
    lab.close()
    # Simulate a process restart: new Lab/Controller from disk, healthy agents.
    lab2 = Lab(tmp_path / "lab")
    ctl2 = Controller(lab2, agents())
    with pytest.raises(PermissionError):
        ctl2.resume(pid, "x", by="scientist")
    ctl2.resume(pid, "backend restored")
    assert ctl2.run(pid)[-1].after == "COMPLETE"


def test_fabricated_experimental_claims_are_rejected(tmp_path):
    from autolab import demo

    def liar(t):
        r = demo.background(t)
        r["research_claims"] = [{"type": "EXPERIMENTAL_RESULT", "statement": "it works",
                                 "run_ids": ["RUN-9999"]}]
        r["payload"]["findings"].append({"type": "ESTABLISHED", "statement": "no source"})
        return r

    lab, ctl = make(tmp_path, sci__background_research=liar)
    pid = ctl.new_project("integrity")
    ctl.step(pid)
    ctl.step(pid)
    task = [t for t in lab.store.query("task") if t.data["stage"] == "background_research"][0]
    assert task.data["rejected_claims"] and not task.data["claims"]
    assert lab.store.events(etype="claim.rejected")
    assert lab.store.query("claim", status="rejected")


def test_multiple_research_cycles(tmp_path):
    lab, ctl = make(tmp_path, sci__next_question=scenario.next_q(cont=True))
    pid = ctl.new_project("multi")
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE"
    assert lab.store.get(pid).data["cycle"] == 2  # max_cycles = 2
    assert len(lab.store.query("report")) == 2
    assert lab.store.query("future_question", status="selected")
    q2 = [q for q in lab.store.query("question") if q.data["cycle"] == 2][0]
    assert "from_future_question" in q2.data["refs"]


def test_demo_scenario_end_to_end(tmp_path):
    """The shipped momentum demo: review revision + verifier-caught bug + patch."""
    from autolab.demo import DEMO_OBJECTIVE, demo_agents
    lab = Lab.init(tmp_path / "demo")
    ctl = Controller(lab, demo_agents())
    pid = ctl.new_project(DEMO_OBJECTIVE)
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE"
    assert ("SCIENTIFIC_REVIEW", "DESIGN") in states(steps)
    assert lab.store.query("failure", category="review_failed")
    assert lab.store.query("conclusion")[0].data["outcome"] == "supported"
    assert "beta" in (lab.repo.path / "experiment.py").read_text()
