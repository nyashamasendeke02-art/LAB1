"""D61: project.yaml manifest and project structure (master prompt s.15/16)."""

import json

import pytest
import yaml

from autolab.manifest import export_project, import_project, load_manifest

import scenario
from scenario import make
from test_p0_lab_upgrades import build_ok, verify_spec

# The example manifest from master prompt section 16, verbatim.
PROMPT_EXAMPLE = """\
project:
  id: adaptive-routing
  name: Adaptive Intelligence Routing

research:
  questions:
    - id: RQ1
      statement: "Can adaptive routing improve heterogeneous AI systems?"

  hypotheses:
    - id: H1
      statement: "Dynamic routing improves task success."

domains:
  - algorithms
  - AI
  - agents
  - robotics

experiments:
  - baseline
  - proposed

evaluation:
  metrics:
    - accuracy
    - latency
    - robustness
    - compute_cost
"""


def packet_context(lab, pid, stage):
    t = next(t for t in lab.store.query("task")
             if t.data["project"] == pid and t.data["stage"] == stage)
    return json.loads((lab.handoffs / t.id / "task.json").read_text(encoding="utf-8"))["context"]


def test_export_writes_the_project_structure(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    out = export_project(lab, pid, tmp_path / "export")
    for rel in ("project.yaml", "research/question.md", "requirements/requirements.yaml",
                "agents/agents.yaml", "models/models.yaml", "results/conclusions.yaml",
                "evaluations/reviews.yaml", "src/SOURCE.md", "documentation"):
        assert (out / rel).exists(), rel
    hyp = lab.store.query("hypothesis")[0]
    assert (out / "research" / "hypotheses" / f"{hyp.id}.md").exists()
    prot = lab.store.query("protocol")[-1]
    exp = yaml.safe_load((out / "experiments" / f"{prot.id}.yaml").read_text(encoding="utf-8"))
    assert exp["id"] == prot.id and exp["decision_rule"]["metric"] == "score"
    m = load_manifest(out / "project.yaml")
    assert m["project"]["ledger_id"] == pid and m["project"]["state"] == "COMPLETE"
    assert m["research"]["hypotheses"][0]["statement"] == hyp.data["statement"]
    assert m["evaluation"]["metrics"] == ["score"]
    assert m["evaluation"]["outcomes"][0]["outcome"] == "supported"
    assert m["provenance"]["ledger_head"] == lab.store.head()
    run = lab.store.query("run")[0]
    assert run.data["commit"] in (out / "src" / "SOURCE.md").read_text(encoding="utf-8")


def test_prompt_example_manifest_imports_and_briefs_the_agents(tmp_path):
    path = tmp_path / "project.yaml"
    path.write_text(PROMPT_EXAMPLE, encoding="utf-8")
    lab, ctl = make(tmp_path / "lab")
    pid = import_project(ctl, path)
    proj = lab.store.get(pid).data
    assert proj["objective"].startswith("Adaptive Intelligence Routing: Can adaptive routing")
    assert proj["domains"] == ["algorithms", "AI", "agents", "robotics"]
    assert ctl.run(pid)[-1].after == "COMPLETE"
    brief = packet_context(lab, pid, "hypothesis")["project_manifest"]
    assert brief["hypotheses"] == ["Dynamic routing improves task success."]
    assert brief["metrics"] == ["accuracy", "latency", "robustness", "compute_cost"]
    assert "project_manifest" not in packet_context(lab, pid, "implement")  # blinded


def test_engineering_manifest_and_round_trip(tmp_path):
    path = tmp_path / "eng.yaml"
    path.write_text(yaml.safe_dump({
        "project": {"name": "Contract module", "autonomy_level": 3},
        "engineering": {"spec": "Versioned message contract module",
                        "acceptance_criteria": ["VERSION exists"], "specialty": "backend"}}),
        encoding="utf-8")
    lab, ctl = make(tmp_path / "lab", eng__build=build_ok, ver__verify=verify_spec)
    pid = import_project(ctl, path)
    d = lab.store.get(pid).data
    assert d["kind"] == "engineering" and d["specialty"] == "backend" and d["autonomy_level"] == 3
    assert ctl.run(pid)[-1].after == "COMPLETE"
    out = export_project(lab, pid, tmp_path / "export")
    m = load_manifest(out / "project.yaml")
    assert m["engineering"]["acceptance_criteria"] == ["VERSION exists"]
    # an exported manifest is itself importable
    again = import_project(ctl, out / "project.yaml")
    assert lab.store.get(again).data["objective"] == "Versioned message contract module"


def test_invalid_manifests_are_rejected(tmp_path):
    for bad in ("project: {}\n", "research: {}\n",
                "project: {name: x}\nengineering: {spec: s, acceptance_criteria: []}\n"):
        p = tmp_path / "bad.yaml"
        p.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="project.yaml invalid"):
            load_manifest(p)
