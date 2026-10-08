"""D52: named agents (any backend/model) allocated to stages; permissions stay with stages."""

import json
import tomllib
from pathlib import Path

import pytest

from autolab import demo
from autolab.agents import ScriptedBackend
from autolab.controller import Controller, Lab
from autolab.registry import (AGENTS_FILE, ORGANISATION, STAGE_BY_NAME, STAGES, Registry,
                              RegistryError, dump_toml)
from autolab.taxonomy import Role

import scenario
from scenario import FAST_CONFIG, agents, make, ok

BASE = {"agents": {"scientist": {"backend": "codex-cli", "model": "m-sci"},
                   "engineer": {"backend": "claude-cli"},
                   "verifier": {"backend": "codex-cli"},
                   "reviewer": {"backend": "", "stages": ["scientific_review"]}}}


def test_every_controller_stage_is_registered_with_its_role():
    import re
    src = (Path(__file__).parents[1] / "src" / "autolab" / "controller.py").read_text()
    called = set(re.findall(r'_call\(pid, Role\.([A-Z]+), "([a-z_]+)"', src))
    for role, stage in called:
        assert STAGE_BY_NAME[stage].role == Role[role], stage
    assert {"implement", "redesign", "build", "rebuild"} <= set(STAGE_BY_NAME)
    from autolab.prompts import STAGES as PROMPTS
    assert set(STAGE_BY_NAME) == set(PROMPTS)


def test_defaults_resolve_to_role_agents(tmp_path):
    reg = Registry(BASE, tmp_path)
    assert all(reg.resolve(s.name, s.role) == s.role.value for s in STAGES)
    assert "reviewer" not in reg.agents and reg.problems() == []


def test_legacy_reviewer_section_allocates_its_stages(tmp_path):
    cfg = {"agents": {**BASE["agents"], "reviewer": {"backend": "gemini-cli",
                                                     "stages": ["scientific_review", "challenge"]}}}
    reg = Registry(cfg, tmp_path)
    assert reg.resolve("scientific_review", Role.SCIENTIST) == "reviewer"
    assert reg.resolve("challenge", Role.VERIFIER) == "reviewer"
    assert reg.resolve("design", Role.SCIENTIST) == "scientist"


def test_upsert_allocate_remove_round_trip(tmp_path):
    reg = Registry(BASE, tmp_path)
    reg.upsert("critic", {"backend": "gemini-cli", "model": "g-1", "title": "Critic",
                          "charter": 'Say "no" when\nthe design is weak.'})
    reg.allocate({"scientific_review": "critic"})
    again = Registry(BASE, tmp_path)  # persisted in agents.toml
    assert again.resolve("scientific_review", Role.SCIENTIST) == "critic"
    assert again.spec("critic")["charter"] == 'Say "no" when\nthe design is weak.'
    with pytest.raises(RegistryError, match="allocated"):
        again.remove("critic")
    again.allocate({"scientific_review": ""})
    assert again.resolve("scientific_review", Role.SCIENTIST) == "scientist"
    again.remove("critic")
    assert "critic" not in Registry(BASE, tmp_path).agents


def test_validation_rules(tmp_path):
    reg = Registry(BASE, tmp_path)
    for name, spec, msg in [
            ("Bad Name", {"backend": "claude-cli"}, "lowercase"),
            ("x", {"backend": "nope"}, "backend must be"),
            ("x", {"backend": "openai-api"}, "needs a model"),
            ("x", {"backend": "claude-cli", "shell": "rm"}, "unknown agent fields"),
            ("x", {"backend": "claude-cli", "timeout": -1}, "positive")]:
        with pytest.raises(RegistryError, match=msg):
            reg.upsert(name, spec)
    with pytest.raises(RegistryError, match="role's default"):
        reg.remove("engineer")
    with pytest.raises(RegistryError, match="unknown stage"):
        reg.allocate({"deploy_to_mars": "scientist"})


def test_writing_stages_need_a_backend_with_tools(tmp_path):
    reg = Registry(BASE, tmp_path)
    reg.upsert("api_writer", {"backend": "openai-api", "model": "gpt-x"})
    with pytest.raises(RegistryError, match="cannot perform a writing stage"):
        reg.allocate({"implement": "api_writer"})
    reg.allocate({"interpret": "api_writer"})  # read-only stages are fine
    assert reg.resolve("interpret", Role.SCIENTIST) == "api_writer"
    reg.upsert("tooled", {"backend": "claude-cli", "backup_backend": "openai-api",
                          "backup_model": "gpt-x"})
    with pytest.raises(RegistryError, match="backup backend"):
        reg.allocate({"verify": "tooled"})


def test_organisation_preset_maps_master_prompt_agents_onto_stages(tmp_path):
    reg = Registry(BASE, tmp_path)
    created = reg.apply_preset()
    assert set(created) == set(ORGANISATION)
    eff = reg.describe()["effective"]
    assert eff["background_research"] == "literature"
    assert eff["design"] == "experiment_designer"
    assert eff["scientific_review"] == "scientific_critic"
    assert eff["implement"] == "engineer" and eff["verify"] == "verifier"
    assert set(eff.values()) <= set(reg.agents)
    # each inherits its role's backend and model until changed
    assert reg.spec("literature")["backend"] == "codex-cli"
    assert reg.spec("literature")["model"] == "m-sci"
    assert reg.spec("systems_architect")["backend"] == "claude-cli"
    assert reg.problems() == []
    tomllib.loads((tmp_path / AGENTS_FILE).read_text(encoding="utf-8"))  # valid TOML


def test_dump_toml_escapes():
    text = dump_toml({"a": {"backend": "claude-cli", "charter": 'q"\\\n\tx', "timeout": 5}},
                     {"design": "a"})
    data = tomllib.loads(text)
    assert data["agents"]["a"]["charter"] == 'q"\\\n\tx' and data["allocation"]["design"] == "a"


def test_controller_routes_a_stage_to_the_allocated_agent(tmp_path):
    lab, ctl = make(tmp_path)
    designer = ScriptedBackend({"design": scenario.design()}, "designer-model")
    ctl.registry.upsert("designer", {"backend": "gemini-cli", "model": "designer-model",
                                     "title": "Experiment Designer",
                                     "charter": "Design minimal controlled experiments."})
    ctl.registry.allocate({"design": "designer"})
    ctl.injected["designer"] = designer
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE", steps[-1]
    assert [s for s, _ in designer.calls] == ["design"] * len(designer.calls)
    sci = [s for s, _ in ctl.injected["scientist"].calls]
    assert "design" not in sci and "hypothesis" in sci
    tasks = lab.store.query("task")
    design = [t for t in tasks if t.data["stage"] == "design"]
    assert design and all(t.data["agent"] == "designer" for t in design)
    assert all(t.data["role"] == "scientist" for t in design)  # permissions follow the stage
    prompt = (lab.handoffs / design[0].id / "prompt.md").read_text(encoding="utf-8")
    assert "AGENT: Experiment Designer" in prompt and "Design minimal" in prompt
    impl = [t for t in tasks if t.data["stage"] == "implement"]
    assert impl[0].data["agent"] == "engineer"
    head = lab.repo.rev("main")
    log = lab.repo.git("log", "--format=%B", "-n", "20", head)
    assert "Autolab-Agent: engineer" in log and "Autolab-Agent: verifier" in log


def test_agent_editing_the_registry_halts(tmp_path):
    """An engineer (not OS-sandboxed) must not be able to reallocate its own reviewer."""
    def tamper(t):
        scenario.write_impl(t)
        lab_root = Path(t.workdir).parents[2]
        (lab_root / AGENTS_FILE).write_text('[allocation]\nverify = "engineer"\n')
        return ok({"summary": "implemented"})

    lab, ctl = make(tmp_path, eng__implement=tamper)
    pid = ctl.new_project("tamper")
    steps = ctl.run(pid)
    assert steps[-1].after == "HALTED"
    assert "agents_toml" in lab.store.get(pid).data["halt_reason"]


def test_lab_without_registry_behaves_as_before(tmp_path):
    lab = Lab.init(tmp_path / "lab", config_text=FAST_CONFIG)
    ctl = Controller(lab, agents())
    assert {ctl.agent_for(s.role, s.name)[0] for s in STAGES} == {"scientist", "engineer",
                                                                   "verifier"}
    assert not (lab.root / AGENTS_FILE).exists()
