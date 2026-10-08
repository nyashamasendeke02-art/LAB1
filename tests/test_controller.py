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


def test_independent_reviewer_runs_scientific_review(tmp_path):
    from autolab import demo
    from autolab.agents import ScriptedBackend
    from autolab.taxonomy import Role

    reviewer = ScriptedBackend({"scientific_review": demo.review_approve}, "independent")
    lab = Lab.init(tmp_path / "lab", config_text=FAST_CONFIG)
    ctl = Controller(lab, agents(), reviewer=reviewer)
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE", steps[-1]
    assert [s for s, _ in reviewer.calls] == ["scientific_review"] * len(reviewer.calls)
    assert reviewer.calls
    sci_stages = [s for s, _ in ctl.agents[Role.SCIENTIST].backend.calls]
    assert "scientific_review" not in sci_stages and "design" in sci_stages
    reviews = [t for t in lab.store.query("task") if t.data["stage"] == "scientific_review"]
    assert reviews and all(t.data["backend"]["model"] == "independent" for t in reviews)


def test_reviewer_disabled_by_default(tmp_path):
    lab, ctl = make(tmp_path)
    from autolab.taxonomy import Role
    assert "reviewer" not in ctl.registry.agents
    assert ctl.agent_for(Role.SCIENTIST, "scientific_review")[0] == "scientist"


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
        r = scenario.design()(t)
        r["payload"]["protocol"]["validity_checks"][0]["value"] = -100  # never true
        return r

    lab, ctl = make(tmp_path, sci__design=impossible)
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


def test_run_reports_each_step_as_it_happens(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("streaming")
    seen = []
    steps = ctl.run(pid, max_steps=3, on_step=seen.append)
    assert seen == steps and len(seen) == 3
    assert all(s.elapsed_s is not None and s.elapsed_s >= 0 for s in seen)


def _boom(t):
    raise RuntimeError("stop here")


def test_amendment_is_recorded_and_reverified(tmp_path):
    lab, ctl = make(tmp_path, sci__scientific_validation=_boom)
    pid = ctl.new_project("amend")
    assert ctl.run(pid)[-1].after == "HALTED"
    prot_id = lab.store.get(pid).data["current"]["protocol"]
    old = lab.store.get(prot_id)
    p = dict(old.data["protocol"], seeds=[1, 2, 3, 4, 5, 6])
    with pytest.raises(PermissionError):
        ctl.amend_protocol(pid, p, "more power", by="scientist")
    with pytest.raises(ValueError):
        ctl.amend_protocol(pid, p, "  ")
    bad = dict(p, conditions=p["conditions"][:1])
    with pytest.raises(ValueError):
        ctl.amend_protocol(pid, bad, "drop baseline")
    rec = ctl.amend_protocol(pid, p, "more power")
    assert rec.frozen and rec.data["_freeze_hash"] != old.data["_freeze_hash"]
    assert rec.data["_amendments"][-1]["reason"] == "more power"
    assert rec.data["downgraded_after_data"] is False
    committed = json.loads((lab.repo.path / "protocols" / f"{prot_id}.json").read_text())
    assert committed["seeds"] == [1, 2, 3, 4, 5, 6]
    ctl2 = Controller(lab, agents())
    ctl2.resume(pid, "amended")
    assert lab.store.get(pid).data["state"] == "ENGINEERING"
    assert ctl2.run(pid)[-1].after == "COMPLETE"
    run = lab.store.query("run")[-1]
    assert run.data["protocol_version"] == rec.version and len(run.data["seeds"]) == 6
    assert len(lab.store.query("eng_task")) == 2  # re-verified implementation


def test_amendment_after_data_downgrades_confirmatory(tmp_path):
    lab, ctl = make(tmp_path, sci__design=scenario.design(kind="confirmatory"),
                    ver__challenge=_boom)
    pid = ctl.new_project("post-data amend")
    apr = ctl.run(pid)[-1].blocked_on
    ctl.gates.decide(apr, True, by="human")
    assert ctl.run(pid)[-1].after == "HALTED"
    assert lab.store.query("run")  # data already collected
    prot_id = lab.store.get(pid).data["current"]["protocol"]
    p = dict(lab.store.get(prot_id).data["protocol"])
    p["decision_rule"] = dict(p["decision_rule"], min_effect=0.1)
    rec = ctl.amend_protocol(pid, p, "lower threshold after seeing data")
    assert rec.data["protocol"]["kind"] == "exploratory"
    assert rec.data["downgraded_after_data"] is True
    ctl2 = Controller(lab, agents())
    ctl2.resume(pid, "continue as exploratory")
    assert ctl2.run(pid)[-1].after == "COMPLETE"
    con = lab.store.query("conclusion")[-1]
    assert con.data["experiment_kind"] == "exploratory"


def test_human_halt_and_amend_requires_post_freeze(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("early")
    ctl.step(pid)
    with pytest.raises(PermissionError):
        ctl.halt(pid, "x", by="engineer")
    ctl.halt(pid, "pause")
    assert lab.store.get(pid).data["state"] == "HALTED"
    with pytest.raises(ValueError):
        ctl.amend_protocol(pid, scenario.protocol(), "too early")


def test_ledger_head_anchored_in_git_and_verified(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("anchor")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    checked, missing = lab.verify_anchors()
    assert checked >= 2 and missing == []  # protocol freeze + merge
    # Rebuild the DB from scratch (a forged history): git anchors no longer match.
    lab.close()
    (lab.state_dir / "lab.db").unlink()
    for suffix in ("-wal", "-shm"):
        p = lab.state_dir / f"lab.db{suffix}"
        if p.exists():
            p.unlink()
    forged = Lab(lab.root)
    forged.store.append_event("controller", "forged", "X", {})
    checked, missing = forged.verify_anchors()
    assert checked >= 2 and len(missing) == checked


def test_merge_requires_independent_verification_tests(tmp_path):
    def lazy_verifier(t):  # passes everything, writes no tests
        return ok({"verdict": "pass", "findings": [], "reproducibility_ok": True,
                   "protocol_compliance_ok": True})

    lab, ctl = make(tmp_path, ver__verify=lazy_verifier)
    pid = ctl.new_project("lazy verifier")
    steps = ctl.run(pid)
    assert steps[-1].after == "HALTED"
    assert lab.store.query("failure", category="verifier_no_tests")
    eng = lab.store.query("eng_task")[0]
    assert eng.data["state"] == "ADVERSARIAL_REVIEW" and eng.data["patch_attempts"] == 0
    assert not lab.store.query("run")
    # once the verifier does its job, the project completes
    ctl2 = Controller(lab, agents())
    ctl2.resume(pid, "verifier fixed")
    assert ctl2.run(pid)[-1].after == "COMPLETE"


# ------------------------------------------------- code review 2026-10-04 regressions
def _until(ctl, pid, cond, max_steps=200):
    for _ in range(max_steps):
        if cond():
            return
        res = ctl.step(pid)
        if res.after in ("COMPLETE", "HALTED"):
            break
    assert cond()


def test_engineer_config_cannot_hide_failing_verification_tests(tmp_path):
    """R2: a conftest.py that deselects tests/verification must not let a failing
    independent test through (pytest alone would report success)."""
    def hide(t):
        scenario.write_impl(t)
        (Path(t.workdir) / "conftest.py").write_text(
            'collect_ignore_glob = ["tests/verification/*"]\n', encoding="utf-8")
        return ok({"summary": "implemented"})

    def finds_bug(t):
        vdir = Path(t.workdir) / "tests" / "verification"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "test_v.py").write_text("def test_bug():\n    assert False, 'real defect'\n",
                                        encoding="utf-8")
        return ok({"verdict": "pass", "findings": [], "reproducibility_ok": True,
                   "protocol_compliance_ok": True})

    lab, ctl = make(tmp_path, eng__implement=hide, ver__verify=finds_bug)
    pid = ctl.new_project("hidden tests")
    _until(ctl, pid, lambda: lab.store.query("review", review_type="code_review"))
    rev = lab.store.query("review", review_type="code_review")[0]
    assert rev.data["tests_passed"] is True  # the project's own pytest config hid the test
    assert rev.data["verification_tests_passed"] is False
    assert rev.data["verification_test_counts"]["failures"] == 1
    assert rev.data["passed"] is False
    assert not lab.store.query("run")


def test_hermetic_verification_run_counts_passing_tests(tmp_path):
    lab, ctl = make(tmp_path)
    wd = tmp_path / "wd"
    (wd / "tests" / "verification").mkdir(parents=True)
    (wd / "experiment.py").write_text(scenario.EXPERIMENT, encoding="utf-8")
    (wd / "tests" / "verification" / "test_v.py").write_text(scenario.VERIFY_TEST,
                                                             encoding="utf-8")
    (wd / "pytest.ini").write_text("[pytest]\naddopts = -k nothing_matches\n", encoding="utf-8")
    ok_, out, _, counts = ctl._run_verification_tests(wd)
    assert ok_, out
    assert counts["passed"] == 1 and counts["failures"] == 0


def test_scientific_validation_reads_the_merged_code(tmp_path):
    """R4: the scientist validating the implementation gets the code, not just a verdict."""
    seen = []

    def validation(t):
        wd = Path(t.workdir)
        seen.append(((wd / "experiment.py").exists(),
                     "experiment.py" in t.context["implementation_diff"], wd))
        return ok({"verdict": "approve", "issues": []})

    lab, ctl = make(tmp_path, sci__scientific_validation=validation)
    pid = ctl.new_project("validate")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert seen and seen[0][:2] == (True, True)
    assert not seen[0][2].exists()  # read-only checkout removed afterwards


def test_engineer_and_verifier_are_blinded(tmp_path):
    """R11: implementers do not see the hypothesis, decision rule or earlier results."""
    packets = []

    def implement(t):
        packets.append(t)
        return scenario.implement(t)

    def verify(t):
        packets.append(t)
        return scenario.verify_pass(t)

    lab, ctl = make(tmp_path, eng__implement=implement, ver__verify=verify)
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert len(packets) == 2
    for t in packets:
        assert "treat can produce higher score" not in t.objective
        assert "hypothesis" not in t.context and "question" not in t.context
        assert "decision_rule" not in t.context["protocol"]
        assert "success_checks" not in t.context["protocol"]
        assert t.context["protocol"]["conditions"]  # the spec itself is intact


def test_redesign_must_collect_fresh_data_and_later_looks_are_exploratory(tmp_path):
    """R6: no re-testing a hypothesis on the same seeds; a second look is not
    confirmatory and is labelled with its look number."""
    lab, ctl = make(tmp_path, sci__design=scenario.design(effect=0.6, noise=3.0,
                                                          seeds=(1, 2, 3, 4)))
    pid = ctl.new_project("same seeds")
    ctl.run(pid)
    fails = lab.store.query("failure", category="design_invalid")
    assert fails and "already used" in fails[0].data["summary"]
    assert len(lab.store.query("run")) == 1

    lab2, ctl2 = make(tmp_path / "b", sci__design=scenario.design(effect=0.6, noise=3.0))
    pid2 = ctl2.new_project("fresh seeds")
    ctl2.run(pid2)
    cons = sorted(lab2.store.query("conclusion"), key=lambda c: c.id)
    assert [c.data["look"] for c in cons][:2] == [1, 2]
    assert "look 2" in cons[1].data["confidence"]
    seeds = [set(r.data["seeds"]) for r in lab2.store.query("run")]
    assert not seeds[0] & seeds[1]


def test_agent_tampering_with_controller_state_halts(tmp_path):
    """R12: the engineer is not OS-sandboxed; touching the main checkout is detected."""
    def tamper(t):
        scenario.write_impl(t)
        main = Path(t.workdir).parents[2] / "repo"
        (main / "protocols" / "note.txt").write_text("edited outside my worktree")
        return ok({"summary": "implemented"})

    lab, ctl = make(tmp_path, eng__implement=tamper)
    pid = ctl.new_project("tamper")
    steps = ctl.run(pid)
    assert steps[-1].after == "HALTED"
    assert "integrity violation" in lab.store.get(pid).data["halt_reason"]
    assert lab.store.query("failure", category="integrity_violation")
    assert not lab.store.query("run")


def test_stale_transient_worktrees_are_cleaned(tmp_path):
    lab, ctl = make(tmp_path)
    stale = lab.repo.add_detached_worktree(lab.worktrees / "readonly" / "design-TASK-9",
                                           lab.repo.rev("main"))
    assert stale.exists()
    assert ctl.cleanup_stale_worktrees() == [str(Path("worktrees/readonly/design-TASK-9"))]
    assert not stale.exists()


def test_rejected_agent_responses_are_kept(tmp_path):
    """R8: when an agent never produces a valid answer, what it said is still stored."""
    lab, ctl = make(tmp_path, sci__define_problem=lambda t: "I refuse to answer in JSON")
    pid = ctl.new_project("junk")
    ctl.step(pid)
    task = [t for t in lab.store.query("task") if t.data["status"] == "error"][0]
    assert len(task.data["rejections"]) == 3
    raw = lab.artifacts.get_text(task.data["refs"]["responses"][7:])
    assert "I refuse to answer in JSON" in raw
    assert (lab.handoffs / task.id / "rejected_responses.md").exists()


def test_engineering_retries_are_counted_per_substep(tmp_path):
    """R10: one transient error while implementing and another while verifying must not
    add up to a HALT (max_stage_retries = 1 in FAST_CONFIG)."""
    def flaky(t):
        raise RuntimeError("transient backend error")

    lab, ctl = make(tmp_path, eng__implement=[flaky, scenario.implement],
                    ver__verify=[flaky, scenario.verify_pass])
    pid = ctl.new_project("flaky")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    keys = [f.data["summary"].split(":")[0:3] for f in
            lab.store.query("failure", category="stage_error")]
    assert ["ENGINEERING", "ENG-0001", "IMPLEMENTING"] in keys
    assert ["ENGINEERING", "ENG-0001", "ADVERSARIAL_REVIEW"] in keys
