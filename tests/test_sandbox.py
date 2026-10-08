"""D62: sandbox profiles (master prompt s.19); credentials never reach code the lab runs."""

import json
from pathlib import Path

from autolab.experiments import run_protocol
from autolab.messages import validate_protocol
from autolab.sandbox import PROFILES, profile_for, scrubbed_env
from autolab.taxonomy import Role

from scenario import make, protocol

LEAK = """\
import argparse, json, os, pathlib
ap = argparse.ArgumentParser()
for a in ('--condition', '--seed', '--out', '--params'):
    ap.add_argument(a)
a = ap.parse_args()
seen = sorted(k for k in os.environ if k.startswith('LABTEST_'))
pathlib.Path(a.out, 'seen.json').write_text(json.dumps(seen))
pathlib.Path(a.out, 'metrics.json').write_text(json.dumps({'score': 1.0}))
"""


def test_scrubbed_env():
    env = {"PATH": "p", "OPENAI_API_KEY": "sk", "GITHUB_TOKEN": "t", "DB_PASSWORD": "x",
           "AWS_SECRET_ACCESS_KEY": "y", "LANG": "en", "PYTHONHASHSEED": "1", "SESSIONNAME": "c"}
    assert scrubbed_env(env) == {"PATH": "p", "LANG": "en", "PYTHONHASHSEED": "1",
                                 "SESSIONNAME": "c"}
    assert scrubbed_env(env, ["OPENAI_API_KEY"])["OPENAI_API_KEY"] == "sk"


def test_trials_see_only_declared_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("LABTEST_API_KEY", "secret-1")
    monkeypatch.setenv("LABTEST_TOKEN", "secret-2")
    monkeypatch.setenv("LABTEST_PLAIN", "ok")
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "leak.py").write_text(LEAK, encoding="utf-8")
    p = protocol()
    p["entrypoint"] = "python leak.py"
    out = run_protocol(p, wd, tmp_path / "r1", seeds=[1], conditions=["base"])
    seen = json.loads((Path(out.trials[0].out_dir) / "seen.json").read_text())
    assert seen == ["LABTEST_PLAIN"]
    p["secrets"] = ["LABTEST_API_KEY"]
    assert validate_protocol(p) == []
    out = run_protocol(p, wd, tmp_path / "r2", seeds=[1], conditions=["base"])
    seen = json.loads((Path(out.trials[0].out_dir) / "seen.json").read_text())
    assert seen == ["LABTEST_API_KEY", "LABTEST_PLAIN"]
    p["secrets"] = ["not a name"]
    assert validate_protocol(p)


def test_profiles_and_task_records(tmp_path):
    assert set(PROFILES) == {"ResearchSandbox", "CodingSandbox", "TestingSandbox",
                             "SimulationSandbox", "DeploymentSandbox", "RobotSandbox"}
    for name, prof in PROFILES.items():
        assert "enforced" in prof and "not_enforced" in prof, name
    assert profile_for(Role.ENGINEER, True) == "CodingSandbox"
    assert profile_for(Role.ENGINEER, False) == "ResearchSandbox"
    assert profile_for(Role.VERIFIER, True) == "TestingSandbox"
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    ctl.run(pid)
    by_stage = {t.data["stage"]: t.data["sandbox"] for t in lab.store.query("task")}
    assert by_stage["design"] == "ResearchSandbox"
    assert by_stage["implement"] == "CodingSandbox" and by_stage["verify"] == "TestingSandbox"
    assert by_stage["solution_design"] == "ResearchSandbox"
