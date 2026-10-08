"""D57: workflow modes (master prompt s.26-30): /research (plan-only), /engineer, /project,
/director, /build; presets that give a lab working agents."""

from pathlib import Path

import pytest

from autolab.cli import main
from autolab.coordination import RUNNING, Coordinator
from autolab.registry import Registry, available_presets
from autolab.state_machines import IllegalTransition, ResearchState as R

import scenario
from scenario import make, ok
from test_coordination import TASKS, build_unique, verify_any

PROBLEM = "Investigate whether treat can produce higher score"


def test_research_mode_saves_a_plan_and_builds_nothing(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project(PROBLEM, mode="plan")
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE", steps[-1]
    stages = [t.data["stage"] for t in lab.store.query("task") if t.data["project"] == pid]
    assert stages == ["define_problem", "background_research", "research_question", "hypothesis",
                      "requirements", "design", "solution_design", "scientific_review"]
    assert not lab.store.query("eng_task") and not lab.store.query("run")
    proj = lab.store.get(pid).data
    rep = lab.store.get(proj["current"]["report"]).data
    assert rep["type"] == "research_plan"
    text = (lab.root / rep["path"]).read_text(encoding="utf-8")
    for heading in ("## 1. Problem", "## 2. Literature and knowledge",
                    "## 3. State of the art and gaps", "## 4. Research question",
                    "## 5. Hypothesis", "## 7. Experiment proposals", "## 8. Proposed protocol",
                    "## 9. Scientific review"):
        assert heading in text, heading
    assert lab.artifacts.has(rep["artifact"][7:])
    prot = lab.store.get(proj["current"]["protocol"])
    assert prot.data["status"] == "proposed_in_plan" and not prot.frozen
    assert any(e["type"] == "ResearchPlanProduced" for e in lab.store.events())


def test_only_plan_mode_may_end_at_the_protocol(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project(PROBLEM)
    ctl.store.update(pid, {"state": R.PROTOCOL_FREEZE.value}, reason="test")
    with pytest.raises(IllegalTransition, match="plan-only"):
        ctl._transition(pid, R.COMPLETE, "shortcut")
    with pytest.raises(ValueError):
        ctl.new_project(PROBLEM, mode="sometimes")


def test_build_mode_starts_with_the_engineering_director(tmp_path):
    lab, ctl = make(tmp_path, eng__engineering_breakdown=lambda t: ok(
                        {"architecture_notes": "two parts", "tasks": TASKS}),
                    eng__build=build_unique, ver__verify=verify_any,
                    sci__programme_review=lambda t: ok({"decision": "complete",
                                                        "assessment": "built"}))
    co = Coordinator(ctl)
    prg = co.new_programme("Contract library", items=[{
        "key": "SYSTEM", "kind": "engineering", "objective": "Contract library",
        "acceptance_criteria": ["VERSION exists"], "rationale": "build request"}])
    assert co.programme(prg).data["state"] == RUNNING
    assert co.run(prg)[-1].after == "COMPLETE"
    stages = [t.data["stage"] for t in lab.store.query("task") if t.data["project"] == prg]
    assert stages == ["engineering_breakdown", "programme_review"]  # no planning call
    assert len(lab.store.query("delivery")) == 2


def test_presets_cover_every_stage(tmp_path):
    assert {"organisation", "claude-strengths"} <= set(available_presets())
    reg = Registry({"agents": {"scientist": {"backend": "codex-cli"},
                               "engineer": {"backend": "claude-cli"},
                               "verifier": {"backend": "codex-cli"}}}, tmp_path)
    assert reg.apply_preset("claude-strengths") == ["claude_haiku", "claude_opus",
                                                     "claude_sonnet"]
    eff = reg.describe()["effective"]
    assert set(eff.values()) == {"claude_opus", "claude_sonnet", "claude_haiku"}
    # every reviewer stage runs on a different model from the stage it reviews
    for author, reviewer in (("design", "scientific_review"), ("implement", "verify"),
                             ("architecture", "architecture_critique"),
                             ("programme_plan", "programme_review")):
        assert reg.spec(eff[author])["model"] != reg.spec(eff[reviewer])["model"]
    with pytest.raises(Exception, match="unknown preset"):
        reg.apply_preset("nope")


def test_cli_modes_submit_without_running(tmp_path, capsys):
    lab_dir = tmp_path / "lab"
    assert main(["init", str(lab_dir)]) == 0
    capsys.readouterr()
    toml = lab_dir / "lab.toml"  # programmes need autonomy level >= 4 (new labs default to 3)
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        "autonomy_level = 3", "autonomy_level = 4"), encoding="utf-8")
    assert main(["research", str(lab_dir), PROBLEM]) == 0
    pid = capsys.readouterr().out.strip()
    assert main(["engineer", str(lab_dir), "Contract module", "--accept", "VERSION exists",
                 "--specialty", "backend"]) == 0
    eng = capsys.readouterr().out.strip()
    assert main(["build", str(lab_dir), "Contract library", "--accept", "VERSION exists"]) == 0
    prg = capsys.readouterr().out.strip()
    assert main(["director", str(lab_dir), "Answer whether treat helps"]) == 0
    prg2 = capsys.readouterr().out.strip()
    from autolab.controller import Lab
    lab = Lab(lab_dir)
    assert lab.store.get(pid).data["mode"] == "plan"
    assert lab.store.get(eng).data["specialty"] == "backend"
    assert lab.store.get(prg).data["state"] == "RUNNING"
    assert lab.store.get(prg2).data["state"] == "PLANNING"


def test_slash_commands_exist_for_every_mode():
    root = Path(__file__).parents[1] / ".claude" / "commands"
    for mode in ("research", "engineer", "project", "director", "build"):
        text = (root / f"{mode}.md").read_text(encoding="utf-8")
        assert text.startswith("---\ndescription:") and "$ARGUMENTS" in text
        assert f"autolab.exe {mode} " in text
