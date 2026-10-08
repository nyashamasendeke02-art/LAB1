"""Fast scripted scenario for controller tests (tiny synthetic experiment)."""

from __future__ import annotations

from pathlib import Path

from autolab import demo
from autolab.agents import Agent, ScriptedBackend
from autolab.controller import Controller, Lab
from autolab.taxonomy import Role

ok = demo.ok

FAST_CONFIG = """
[lab]
name = "test"
autonomy_level = 5   # tests exercise every mechanism; levels are tested in test_autonomy_levels.py
[agents.scientist]
backend = "codex-cli"
[agents.engineer]
backend = "claude-cli"
[agents.verifier]
backend = "codex-cli"
[limits]
max_stage_retries = 1
max_patch_attempts = 2
max_redesigns = 1
max_design_iterations = 3
max_cycles = 2
max_trials_without_approval = 200
test_timeout_s = 300
[gates]
confirmatory_protocol_freeze = true
merge_to_main = false
compute_budget = true
[engineering]
architecture_stage = false   # D56 stages are tested in test_eng_workflow.py
pre_merge_reviews = []
test_command = "python -m pytest -q -p no:cacheprovider"
protected_paths = ["protocols/*", "tests/verification/*"]
verifier_allowed_paths = ["tests/verification/*"]
"""

EXPERIMENT = '''\
import argparse, json, random
from pathlib import Path

def score(effect, noise, seed):
    rng = random.Random(seed)
    return effect + rng.gauss(0.0, noise)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition"); ap.add_argument("--seed", type=int)
    ap.add_argument("--out"); ap.add_argument("--params", default="{}")
    a = ap.parse_args()
    p = json.loads(a.params)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(
        {"score": score(p.get("effect", 0.0), p.get("noise", 0.1), a.seed)}))

if __name__ == "__main__":
    main()
'''

TEST = '''\
from experiment import score

def test_deterministic():
    assert score(1.0, 0.1, 3) == score(1.0, 0.1, 3)
'''

FAILING_TEST = '''\
def test_broken():
    assert False, "implementation incomplete"
'''

VERIFY_TEST = '''\
from experiment import score

def test_effect_param_used():
    assert score(0.0, 0.0, 1) != score(5.0, 0.0, 1)
'''


def protocol(kind="exploratory", protected=False, effect=1.0, seeds=(1, 2, 3, 4),
             noise=0.1):
    return {
        "title": "fast synthetic test", "kind": kind, "protected": protected,
        "entrypoint": "python experiment.py",
        "conditions": [
            {"name": "base", "role": "baseline", "params": {"effect": 0.0, "noise": noise}},
            {"name": "treat", "role": "intervention",
             "params": {"effect": effect, "noise": noise}},
        ],
        "seeds": list(seeds),
        "metrics": {"primary": "score", "secondary": []},
        "decision_rule": {"metric": "score", "treatment": "treat", "control": "base",
                          "direction": "greater", "min_effect": 0.5, "alpha": 0.05},
        "budget": {"timeout_s": 60},
        "validity_checks": [{"id": "V1", "description": "baseline sane", "metric": "score",
                             "condition": "base", "op": "<", "value": 10}],
    }


def design(**kw):
    calls = {"n": 0}

    def h(t):
        args = dict(kw)
        if "seeds" not in args:  # fresh data per design (the controller rejects reused seeds)
            args["seeds"] = tuple(range(4 * calls["n"] + 1, 4 * calls["n"] + 5))
        calls["n"] += 1
        return ok({"options": [{"name": "A", "description": "two-arm"}], "chosen": "A",
                   "rationale": "minimal", "protocol": protocol(**args)})
    return h


def requirements(t):
    return ok({"validity_criteria": ["baseline score is in a sane range"],
               "engineering": ["entrypoint contract"]})


def write_impl(t, test=TEST):
    wd = Path(t.workdir)
    (wd / "experiment.py").write_text(EXPERIMENT, encoding="utf-8")
    (wd / "tests").mkdir(exist_ok=True)
    (wd / "tests" / "test_experiment.py").write_text(test, encoding="utf-8")


def implement(t):
    write_impl(t)
    return ok({"summary": "implemented"})


def redesign(t):
    write_impl(t)
    return ok({"summary": "re-implemented", "architecture_change": "single module"})


def redesign_failing(t):
    write_impl(t, FAILING_TEST)
    return ok({"summary": "re-implemented (tests fail)", "architecture_change": "new layout"})


def implement_failing(t):
    write_impl(t, FAILING_TEST)
    return ok({"summary": "implemented (tests fail)"})


def verify_pass(t):
    vdir = Path(t.workdir) / "tests" / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "test_v.py").write_text(VERIFY_TEST, encoding="utf-8")
    return ok({"verdict": "pass", "findings": [], "reproducibility_ok": True,
               "protocol_compliance_ok": True})


def challenge_upheld(t):
    return ok({"verdict": "upheld", "issues": [], "alternative_explanations": ["chance"]})


def next_q(cont=False):
    def h(t):
        return ok({"questions": [{"question": "Does a larger effect replicate?",
                                  "rationale": "follow-up", "priority": 1}],
                   "continue": cont})
    return h


def handlers(**over):
    sci = {
        "define_problem": demo.define_problem, "background_research": demo.background,
        "research_question": demo.question, "hypothesis": demo.hypothesis,
        "requirements": requirements, "design": design(),
        "scientific_review": demo.review_approve, "scientific_validation": demo.validation,
        "interpret": demo.interpret, "communicate": demo.communicate,
        "next_question": next_q(),
    }
    eng = {"solution_design": demo.solution_design, "implement": implement,
           "redesign": redesign}
    ver = {"verify": verify_pass, "challenge": challenge_upheld}
    for k, v in over.items():
        role, stage = k.split("__")
        {"sci": sci, "eng": eng, "ver": ver}[role][stage] = v
    return sci, eng, ver


def agents(**over) -> dict:
    sci, eng, ver = handlers(**over)
    return {Role.SCIENTIST: Agent(Role.SCIENTIST, ScriptedBackend(sci, "s")),
            Role.ENGINEER: Agent(Role.ENGINEER, ScriptedBackend(eng, "e")),
            Role.VERIFIER: Agent(Role.VERIFIER, ScriptedBackend(ver, "v"))}


def make(tmp_path, config: str = FAST_CONFIG, **over) -> tuple[Lab, Controller]:
    lab = Lab.init(tmp_path / "lab", config_text=config)
    return lab, Controller(lab, agents(**over))
