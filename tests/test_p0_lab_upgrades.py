"""P0 lab upgrades (docs/PROJECT_PLAN.md section 5): engineering track, review gates and
delegation, resource metering, output cap, dependency lock, pilot -> confirmatory, mandate refs."""

from pathlib import Path

import pytest

from autolab.cli import mandate_coverage
from autolab.controller import Controller, Lab
from autolab.experiments import run_trial
from autolab.gates import GateError, Gates
from autolab.state_machines import IllegalTransition

import scenario
from scenario import FAST_CONFIG, agents, make, ok

REVIEW_CONFIG = FAST_CONFIG.replace(
    "compute_budget = true",
    'compute_budget = true\nreview_paths = [{pattern = "src/safety/*", gate = "safety"}]\n'
    '[gates.delegation]\ndelegate = "claude-code"\ngates = ["review:safety"]')
CHARTER_CONFIG = FAST_CONFIG.replace('name = "test"', 'name = "test"\ncharter = "docs/MANDATE.md"')


def build_ok(t):
    wd = Path(t.workdir)
    (wd / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (wd / "src" / "contracts" / "msg.py").write_text("VERSION = 1\n", encoding="utf-8")
    (wd / "tests").mkdir(exist_ok=True)
    (wd / "tests" / "test_msg.py").write_text(
        "from src.contracts.msg import VERSION\n\ndef test_version():\n    assert VERSION == 1\n",
        encoding="utf-8")
    return ok({"summary": "contract module", "mandate_refs": ["REQ-LOG"]})


def verify_spec(t):
    vdir = Path(t.workdir) / "tests" / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "test_spec.py").write_text(
        "from src.contracts.msg import VERSION\n\ndef test_v():\n    assert VERSION >= 1\n",
        encoding="utf-8")
    return ok({"verdict": "pass", "findings": [], "reproducibility_ok": True,
               "protocol_compliance_ok": True})


def test_engineering_track_delivers_without_a_research_cycle(tmp_path):
    seen = []

    def build(t):
        seen.append(t)
        return build_ok(t)

    lab, ctl = make(tmp_path, eng__build=build, ver__verify=verify_spec)
    pid = ctl.new_engineering_project("Versioned message contract module",
                                      ["VERSION constant exists", "tests pass"],
                                      ["REQ-LOG", "Gate 0"])
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE", steps[-1]
    assert {s.before for s in steps} <= {"ENGINEERING"}  # no research states at all
    dlv = lab.store.query("delivery")[0]
    assert dlv.data["mandate_refs"] == ["REQ-LOG", "Gate 0"]
    assert dlv.data["commit"] == lab.repo.rev("main")
    assert "Autolab-Mandate: REQ-LOG, Gate 0" in lab.repo.commit_message("main")
    # engineering tasks are not blinded: the spec is the objective
    assert seen[0].objective == "Versioned message contract module"
    assert seen[0].context["acceptance_criteria"] == ["VERSION constant exists", "tests pass"]
    cov = mandate_coverage(lab.store)
    assert any(dlv.id in line for line in cov["Gate 0"])
    assert (lab.exports / "DELIVERIES.md").read_text().count(dlv.id) == 1


def test_engineering_track_needs_spec_and_acceptance(tmp_path):
    lab, ctl = make(tmp_path)
    with pytest.raises(ValueError):
        ctl.new_engineering_project("x", [])


def test_research_project_cannot_complete_from_engineering(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("research")
    lab.store.update(pid, {"state": "ENGINEERING"}, reason="test setup")
    with pytest.raises(IllegalTransition):
        ctl._transition(pid, scenario_state("COMPLETE"), "shortcut")


def scenario_state(name):
    from autolab.state_machines import ResearchState
    return ResearchState(name)


def test_safety_paths_need_review_and_delegation_is_recorded(tmp_path):
    def build_safety(t):
        build_ok(t)
        (Path(t.workdir) / "src" / "safety").mkdir(parents=True, exist_ok=True)
        (Path(t.workdir) / "src" / "safety" / "kernel.py").write_text("LIMIT = 1.0\n")
        return ok({"summary": "safety kernel"})

    lab, ctl = make(tmp_path, config=REVIEW_CONFIG, eng__build=build_safety,
                    ver__verify=verify_spec)
    pid = ctl.new_engineering_project("Safety kernel v1", ["limits enforced"], ["REQ-SAFE"])
    steps = ctl.run(pid)
    apr_id = steps[-1].blocked_on
    assert apr_id and lab.store.get(apr_id).data["gate"] == "review:safety"
    assert "src/safety/kernel.py" in lab.store.get(apr_id).data["details"]["files"]
    assert not lab.store.query("delivery")  # not merged before review
    gates = Gates(lab.store, ctl.cfg["gates"]["delegation"])
    with pytest.raises(GateError):
        gates.decide(apr_id, True, by="engineer", note="lgtm")  # agents never decide
    with pytest.raises(GateError):
        gates.decide(apr_id, True, by="claude-code")  # delegates must give a rationale
    rec = gates.decide(apr_id, True, by="claude-code", note="limits clamp; fault tests present")
    assert rec.data["decided_by"] == "claude-code" and rec.data["delegated_by"] == "human"
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert "by claude-code (delegated by human)" in (lab.exports / "DECISIONS.md").read_text()


def test_delegate_cannot_decide_undelegated_gates(tmp_path):
    lab, ctl = make(tmp_path, config=REVIEW_CONFIG)
    gates = Gates(lab.store, ctl.cfg["gates"]["delegation"])
    apr = gates.request("confirmatory_protocol_freeze", "PROT-1", "x")
    with pytest.raises(GateError):
        gates.decide(apr.id, True, by="claude-code", note="x")
    with pytest.raises(GateError):
        Gates(lab.store, {"delegate": "verifier", "gates": ["*"]})


def test_trials_carry_controller_measured_resources(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("resources")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    t = lab.store.query("run")[0].data["trials"][0]
    assert t["resources"]["autolab_cpu_s"] is not None and t["resources"]["autolab_peak_mb"] > 0
    assert t["metrics"]["autolab_wall_s"] == t["resources"]["autolab_wall_s"]


def test_resource_metrics_cannot_be_faked_and_output_is_capped(tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "fake.py").write_text(
        "import argparse, json, pathlib\n"
        "ap = argparse.ArgumentParser()\n"
        "for a in ('--condition', '--seed', '--out', '--params'):\n    ap.add_argument(a)\n"
        "a = ap.parse_args()\n"
        "pathlib.Path(a.out, 'blob.bin').write_bytes(b'0' * 3 * 2**20)\n"
        "pathlib.Path(a.out, 'metrics.json').write_text(json.dumps("
        "{'score': 1.0, 'autolab_cpu_s': 0.0}))\n", encoding="utf-8")
    cond = {"name": "c", "role": "baseline"}
    t = run_trial("python fake.py", wd, tmp_path / "o1", cond, 1, ["score"], 60)
    assert t.ok and t.metrics["autolab_cpu_s"] == t.resources["autolab_cpu_s"]
    capped = run_trial("python fake.py", wd, tmp_path / "o2", cond, 1, ["score"], 60,
                       output_cap_mb=1)
    assert not capped.ok and "exceeds" in capped.error


def test_dependency_lock_mismatch_halts_before_data(tmp_path):
    def impl_with_lock(t):
        scenario.write_impl(t)
        (Path(t.workdir) / "requirements.lock").write_text("jsonschema==0.0.1\n")
        return ok({"summary": "implemented with lock"})

    lab, ctl = make(tmp_path, eng__implement=impl_with_lock)
    pid = ctl.new_project("lock")
    steps = ctl.run(pid)
    assert steps[-1].after == "HALTED"
    assert "requirements.lock" in lab.store.get(pid).data["halt_reason"]
    assert lab.store.query("failure", category="environment_mismatch")
    assert not lab.store.query("run")


def test_pilot_then_one_confirmatory_study(tmp_path):
    """L6: exploratory pilot (inconclusive), then a confirmatory study on fresh seeds counts
    as confirmatory; a second confirmatory study of the same hypothesis is refused."""
    lab, ctl = make(tmp_path, sci__design=[
        scenario.design(effect=0.6, noise=3.0, seeds=(1, 2, 3, 4)),
        scenario.design(kind="confirmatory", effect=2.0, seeds=(11, 12, 13, 14, 15))])
    pid = ctl.new_project("pilot then confirm")
    steps = ctl.run(pid)
    assert steps[-1].blocked_on  # confirmatory pre-registration gate
    ctl.gates.decide(steps[-1].blocked_on, True, by="human", note="pre-registered")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    cons = sorted(lab.store.query("conclusion"), key=lambda c: c.id)
    assert cons[0].data["outcome"] == "inconclusive"
    assert cons[-1].data["experiment_kind"] == "confirmatory"
    assert cons[-1].data["confidence"].startswith("confirmatory (after 1 exploratory pilot")


def test_second_confirmatory_study_of_a_hypothesis_is_refused(tmp_path):
    lab, ctl = make(tmp_path, sci__design=scenario.design(kind="confirmatory", effect=0.6,
                                                          noise=3.0))
    pid = ctl.new_project("confirm twice")
    for _ in range(3):
        steps = ctl.run(pid)
        if steps[-1].blocked_on:
            ctl.gates.decide(steps[-1].blocked_on, True, by="human", note="ok")
        else:
            break
    fails = lab.store.query("failure", category="design_invalid")
    assert any("one confirmatory study" in f.data["summary"] for f in fails)


def test_scientist_receives_lab_charter_and_project_refs(tmp_path):
    seen = []

    def define(t):
        seen.append(t.context)
        return scenario.demo.define_problem(t)

    lab = Lab.init(tmp_path / "lab", config_text=CHARTER_CONFIG,
                   repo_files={"docs/MANDATE.md": "# Mandate\nH3: prediction error ...\n"})
    ctl = Controller(lab, agents(sci__define_problem=define))
    pid = ctl.new_project("charter", ["H3", "E4"])
    ctl.step(pid)
    assert "H3: prediction error" in seen[0]["lab_charter"]
    assert seen[0]["project_mandate_refs"] == ["H3", "E4"]


def test_conclusions_carry_mandate_refs(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("refs", ["H1", "E2"])
    assert ctl.run(pid)[-1].after == "COMPLETE"
    con = lab.store.query("conclusion")[0]
    assert con.data["mandate_refs"] == ["E2", "H1"]
    assert any(con.id in line for line in mandate_coverage(lab.store)["H1"])


def test_hermetic_verification_supports_src_layout(tmp_path):
    lab, ctl = make(tmp_path)
    wd = tmp_path / "wd"
    (wd / "src" / "contracts").mkdir(parents=True)
    (wd / "src" / "contracts" / "__init__.py").write_text("VERSION = 2\n")
    (wd / "tests" / "verification").mkdir(parents=True)
    (wd / "tests" / "verification" / "test_v.py").write_text(
        "from contracts import VERSION\n\ndef test_v():\n    assert VERSION == 2\n")
    ok_, out, _, counts = ctl._run_verification_tests(wd)
    assert ok_, out
    assert counts["passed"] == 1


def paired_design(**kw):
    inner = scenario.design(**kw)

    def h(t):
        res = inner(t)
        prot = res["payload"]["protocol"]
        prot["decision_rule"]["pairing"] = "paired"
        prot["conditions"][0]["params"]["noise"] = 0.0  # else the arms share noise: SD 0
        return res
    return h


def run_until_design_fails(lab, ctl, pid, text):
    for _ in range(4):
        steps = ctl.run(pid)
        if any(text in f.data["summary"] for f in lab.store.query("failure",
                                                                   category="design_invalid")):
            return True
        if not steps[-1].blocked_on:
            return False
        ctl.gates.decide(steps[-1].blocked_on, True, by="human", note="ok")
    return False


def test_underpowered_confirmatory_study_is_refused(tmp_path):
    """L5: a noisy paired pilot sets the per-seed SD; a 5-seed confirmatory design is then
    refused as underpowered, and the scientific review sees the power analysis."""
    seen = []

    def review(t):
        seen.append(t.context.get("power_analysis"))
        return scenario.demo.review_approve(t)

    lab, ctl = make(tmp_path, sci__scientific_review=review, sci__design=[
        paired_design(effect=0.6, noise=3.0, seeds=(1, 2, 3, 4)),
        paired_design(kind="confirmatory", effect=2.0, seeds=(11, 12, 13, 14, 15))])
    pid = ctl.new_project("pilot then underpowered confirm")
    assert run_until_design_fails(lab, ctl, pid, "underpowered")
    assert seen[0]["pilots"] == [] and "required_seeds" not in seen[0]


def test_confirmatory_can_require_a_pilot(tmp_path):
    cfg = FAST_CONFIG.replace("test_timeout_s = 300",
                              "test_timeout_s = 300\nrequire_pilot_for_confirmatory = true")
    lab, ctl = make(tmp_path, config=cfg, sci__design=scenario.design(kind="confirmatory"))
    pid = ctl.new_project("confirm without pilot")
    assert run_until_design_fails(lab, ctl, pid, "exploratory pilot")


def test_redesign_after_review_revises_the_rejected_protocol(tmp_path):
    """pilot-003: designs written from scratch after each review added new conflicts and
    never converged; the designer now receives the rejected protocol to revise."""
    seen = []
    inner = scenario.design()

    def design(t):
        seen.append(t.context.get("rejected_protocol"))
        return inner(t)

    lab, ctl = make(tmp_path, sci__design=design, sci__scientific_review=[
        scenario.demo.review_revise, scenario.demo.review_approve])
    pid = ctl.new_project("revise")
    ctl.run(pid, max_steps=9)
    assert len(seen) >= 2 and seen[0] is None
    assert seen[1]["id"] == "PROT-0001" and seen[1]["seeds"] == [1, 2, 3, 4]
