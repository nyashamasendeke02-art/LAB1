"""D58: autonomy levels 0-5 (master prompt s.21), each enforced by a controller mechanism."""

import pytest

from autolab.autonomy import AutonomyError, delegation, lab_level, resolve_level
from autolab.coordination import Coordinator
from autolab.gates import GateError

import scenario
from scenario import FAST_CONFIG, make
from test_p0_lab_upgrades import build_ok, verify_spec

OBJECTIVE = "Investigate whether treat can produce higher score"


def at(level: int) -> str:
    return FAST_CONFIG.replace("autonomy_level = 5", f"autonomy_level = {level}")


def test_level_resolution():
    cfg = {"lab": {"autonomy_level": 3}}
    assert lab_level(cfg) == 3 and resolve_level(cfg, None) == 3 and resolve_level(cfg, 1) == 1
    with pytest.raises(AutonomyError, match="exceeds"):
        resolve_level(cfg, 4)
    with pytest.raises(AutonomyError):
        resolve_level(cfg, 9)
    with pytest.raises(AutonomyError):
        lab_level({"lab": {"autonomy_level": "high"}})
    assert delegation({"lab": {"autonomy_level": 4},
                       "gates": {"delegation": {"delegate": "claude-code"}}}) == {}


def test_level_0_calls_no_agent(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project(OBJECTIVE, autonomy_level=0)
    steps = ctl.run(pid)
    assert steps[-1].blocked_on == "autonomy-level-0"
    assert lab.store.query("task") == [] and lab.store.get(pid).data["state"] == "DEFINE_PROBLEM"


def test_level_1_only_suggests(tmp_path):
    lab, ctl = make(tmp_path)
    with pytest.raises(AutonomyError, match="only suggest"):
        ctl.new_project(OBJECTIVE, autonomy_level=1)
    with pytest.raises(AutonomyError, match=">= 2"):
        ctl.new_engineering_project("contract module", ["VERSION exists"], autonomy_level=1)
    pid = ctl.new_project(OBJECTIVE, mode="plan", autonomy_level=1)
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert not lab.store.query("eng_task") and not lab.store.query("run")


def test_level_2_gates_every_merge_and_run(tmp_path):
    lab, ctl = make(tmp_path, config=at(2), eng__build=build_ok, ver__verify=verify_spec)
    pid = ctl.new_engineering_project("contract module", ["VERSION exists"])
    last = ctl.run(pid)[-1]
    apr = lab.store.get(last.blocked_on)
    assert apr.data["gate"] == "merge_to_main" and apr.data["status"] == "pending"
    with pytest.raises(GateError):  # delegation is not honoured below level 5
        ctl.gates.decide(apr.id, True, by="claude-code", note="x")
    ctl.gates.decide(apr.id, True, by="human", note="read the diff")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    # research: the experiment run waits for approval too
    lab2, ctl2 = make(tmp_path / "r", config=at(2))
    rp = ctl2.new_project(OBJECTIVE)
    gates = []
    while True:
        last = ctl2.run(rp)[-1]
        if not last.blocked_on:
            break
        a = lab2.store.get(last.blocked_on)
        gates.append(a.data["gate"])
        ctl2.gates.decide(a.id, True, by="human", note="ok")
    assert "protected_experiment" in gates and "merge_to_main" in gates
    assert lab2.store.get(rp).data["state"] == "COMPLETE"


def test_level_3_runs_without_approvals_but_no_programmes(tmp_path):
    lab, ctl = make(tmp_path, config=at(3))
    pid = ctl.new_project(OBJECTIVE)
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert lab.store.query("approval") == []
    with pytest.raises(AutonomyError, match=">= 4"):
        Coordinator(ctl).new_programme("a programme")
    assert ctl.gates.delegate is None


def test_level_4_allows_programmes_and_level_5_delegation(tmp_path):
    lab, ctl = make(tmp_path, config=at(4))
    assert Coordinator(ctl).new_programme("a programme").startswith("PRG-")
    assert ctl.gates.delegate is None
    cfg5 = FAST_CONFIG + '\n[gates.delegation]\ndelegate = "claude-code"\ngates = ["*"]\n'
    lab5, ctl5 = make(tmp_path / "five", config=cfg5)
    assert ctl5.gates.delegate == "claude-code"
