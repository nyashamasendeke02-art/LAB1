"""Scripted demonstration agents (no LLM calls).

These handlers stand in for ChatGPT / Claude / Codex so the full loop can be
exercised offline and deterministically. Their *content* is hard-coded: the
demo shows the lab's machinery (state machines, worktrees, gates, tests,
merges, runs, analysis, provenance), not autonomous discovery.

Scenario: "Does heavy-ball momentum reduce iterations-to-tolerance of
gradient descent on ill-conditioned quadratics?"

Scripted twists that exercise the loop:
* design v1 lacks a null model -> scientific review requests revision;
* implementation v1 ignores the ``beta`` parameter -> the verifier catches
  it with an independent test -> engineer patches.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .agents import Agent, ScriptedBackend
from .messages import TaskPacket
from .taxonomy import Role


def ok(payload: dict, summary: str = "done", claims: list | None = None) -> dict:
    return {"status": "complete", "summary": summary, "payload": payload,
            "research_claims": claims or [], "risks": []}


# ------------------------------------------------------------------ science
def define_problem(t: TaskPacket) -> dict:
    return ok({"problem_statement": "Quantify whether heavy-ball momentum speeds up gradient "
                                    "descent on ill-conditioned convex quadratics.",
               "scope": "Deterministic, synthetic diagonal quadratics, dim 10, kappa=100.",
               "out_of_scope": ["non-convex objectives", "stochastic gradients"],
               "success_notion": "A pre-registered, reproducible comparison with controls."})


def background(t: TaskPacket) -> dict:
    return ok({"findings": [
        {"type": "SOURCE_CLAIM",
         "statement": "Heavy-ball momentum was proposed to accelerate convergence of iterative "
                      "methods.",
         "sources": ["Polyak, B. T. (1964). Some methods of speeding up the convergence of "
                     "iteration methods. USSR Comput. Math. Math. Phys. 4(5):1-17."]},
        {"type": "INFERENCE",
         "statement": "On quadratics, momentum's benefit should grow with the condition number."},
        {"type": "OPEN_QUESTION",
         "statement": "How sensitive is the speed-up to the momentum coefficient at fixed step?"},
    ], "known_methods": ["gradient descent", "heavy-ball momentum", "Nesterov acceleration"],
        "gaps": ["empirical check in this lab's harness"]})


def question(t: TaskPacket) -> dict:
    return ok({"question": "At step size 1/L, does heavy-ball momentum (beta=0.9) reduce the "
                           "iterations needed to reach a 1e-6 relative loss on random "
                           "diagonal quadratics with kappa=100?",
               "rationale": "Smallest experiment that discriminates the mechanism."})


def hypothesis(t: TaskPacket) -> dict:
    return ok({"hypotheses": [{
        "statement": "Heavy-ball momentum (beta=0.9) reduces iterations-to-tolerance versus "
                     "plain gradient descent at the same step size.",
        "prediction": "mean iters_to_tol(momentum) is lower than gd by at least 100.",
        "null_hypothesis": "Momentum does not reduce iterations-to-tolerance by >= 100.",
        "falsification": "Bootstrap CI of the reduction lies below 100."}]})


def requirements(t: TaskPacket) -> dict:
    return ok({
        "validity": [
            {"id": "V1", "description": "Baseline GD converges within budget (instrument works)",
             "metric": "iters_to_tol", "condition": "gd", "op": "<", "value": 5000},
            {"id": "V2", "description": "Momentum run does not diverge (finite, non-increasing loss)",
             "metric": "final_loss_ratio", "condition": "momentum", "op": "<=", "value": 1.0},
        ],
        "scientific": [],
        "engineering": ["Implement the entrypoint contract exactly",
                        "Deterministic given --seed", "Unit tests for the optimiser"]})


def _protocol(with_null: bool) -> dict:
    conds = [
        {"name": "gd", "role": "baseline", "params": {"method": "gd", "beta": 0.0}},
        {"name": "momentum", "role": "intervention", "params": {"method": "gd", "beta": 0.9}},
        {"name": "momentum_weak", "role": "ablation", "params": {"method": "gd", "beta": 0.5}},
    ]
    if with_null:
        conds.append({"name": "random_search", "role": "null",
                      "params": {"method": "random_search"}})
    return {
        "title": "Heavy-ball momentum vs GD on ill-conditioned quadratics",
        "kind": "exploratory", "protected": False,
        "entrypoint": "python experiment.py",
        "conditions": conds, "seeds": [0, 1, 2, 3, 4, 5],
        "metrics": {"primary": "iters_to_tol", "secondary": ["final_loss_ratio"]},
        "decision_rule": {"metric": "iters_to_tol", "treatment": "momentum", "control": "gd",
                          "direction": "less", "min_effect": 100, "alpha": 0.05, "n_boot": 2000},
        "budget": {"timeout_s": 120},
        "transfer_tests": [], "robustness_tests": [],
    }


def design_v1(t: TaskPacket) -> dict:
    return ok({"options": [
        {"name": "A: GD vs momentum + ablation", "description": "two-arm + beta ablation"},
        {"name": "B: sweep beta", "description": "dose-response over beta"}],
        "chosen": "A: GD vs momentum + ablation", "rationale": "smallest discriminating test",
        "protocol": _protocol(with_null=False)})


def design_v2(t: TaskPacket) -> dict:
    d = design_v1(t)
    d["payload"]["protocol"] = _protocol(with_null=True)
    d["payload"]["rationale"] += "; null model added after review"
    return d


def review_revise(t: TaskPacket) -> dict:
    return ok({"verdict": "revise", "issues": [
        {"severity": "major", "description": "No null model: cannot show the metric "
                                             "discriminates real optimisation from chance."}],
        "required_changes": ["add a random-search null condition"]})


def review_approve(t: TaskPacket) -> dict:
    return ok({"verdict": "approve", "issues": [
        {"severity": "minor", "description": "Single problem family limits generality."}]})


def validation(t: TaskPacket) -> dict:
    return ok({"verdict": "approve", "issues": []})


def interpret(t: TaskPacket) -> dict:
    d = t.context["result"]["decision"]
    return ok({"interpretation": f"Under this protocol the computed outcome is {d['outcome']} "
                                 f"(effect {d.get('effect')}).",
               "alternative_explanations": ["step size tuned to L favours momentum's regime"],
               "limitations": ["synthetic diagonal quadratics only", "single kappa"]})


def communicate(t: TaskPacket) -> dict:
    c = t.context["conclusion"]
    return ok({"summary": f"Hypothesis {c['hypothesis']} was {c['outcome']} in an "
                          f"{c['experiment_kind']} experiment (confidence: {c['confidence']})."})


def next_question(t: TaskPacket) -> dict:
    return ok({"questions": [
        {"question": "Does the momentum advantage grow with the condition number?",
         "rationale": "INFERENCE from background; dose-response test", "priority": 1},
        {"question": "Is the effect robust to rotated (non-diagonal) quadratics?",
         "rationale": "robustness", "priority": 2}], "continue": False})


# --------------------------------------------------------------- engineering
EXPERIMENT_PY = '''\
"""Heavy-ball momentum vs gradient descent on random ill-conditioned quadratics.

Entrypoint contract: --condition --seed --out --params ; writes metrics.json.
"""
import argparse
import json
import random
from pathlib import Path


def make_problem(seed, dim=10, kappa=100.0):
    rng = random.Random(seed)
    eig = [kappa ** (i / (dim - 1)) for i in range(dim)]
    rng.shuffle(eig)
    x0 = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    return eig, x0


def loss(eig, x):
    return 0.5 * sum(l * xi * xi for l, xi in zip(eig, x))


def optimize(eig, x0, method, lr, beta, seed, tol=1e-6, max_iters=5000):
    rng = random.Random(seed + 7919)
    x = list(x0)
    v = [0.0] * len(x)
    f0 = loss(eig, x0)
    fx = f0
    for t in range(1, max_iters + 1):
        if method == "random_search":
            cand = [xi - lr * rng.gauss(0.0, 1.0) for xi in x]
            fc = loss(eig, cand)
            if fc < fx:
                x, fx = cand, fc
        else:
            g = [l * xi for l, xi in zip(eig, x)]
            v = [beta * vi - lr * gi for vi, gi in zip(v, g)]
            x = [xi + vi for xi, vi in zip(x, v)]
            fx = loss(eig, x)
        if fx <= tol * f0:
            return t, fx / f0
    return max_iters, fx / f0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--params", default="{}")
    a = ap.parse_args(argv)
    params = json.loads(a.params)
    method = params.get("method", "gd")
    beta = float(params.get(BETA_KEY, 0.0))
    kappa = float(params.get("kappa", 100.0))
    eig, x0 = make_problem(a.seed, kappa=kappa)
    iters, ratio = optimize(eig, x0, method, 1.0 / max(eig), beta, a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(
        {"iters_to_tol": iters, "final_loss_ratio": ratio}))


if __name__ == "__main__":
    main()
'''

ENGINEER_TESTS = '''\
from experiment import loss, make_problem, optimize


def test_problem_deterministic():
    assert make_problem(3) == make_problem(3)


def test_gd_converges():
    eig, x0 = make_problem(0)
    iters, ratio = optimize(eig, x0, "gd", 1.0 / max(eig), 0.0, 0)
    assert iters < 5000 and ratio <= 1e-6


def test_loss_nonnegative():
    eig, x0 = make_problem(1)
    assert loss(eig, x0) >= 0
'''

VERIFY_TEST = '''\
"""Independent verification (verifier-owned). Checks the protocol's `beta`
parameter is honoured -- without assuming which condition should win."""
import json
import subprocess
import sys


def _run(tmp_path, beta):
    out = tmp_path / f"b{beta}"
    subprocess.run([sys.executable, "experiment.py", "--condition", "x", "--seed", "0",
                    "--out", str(out), "--params", json.dumps({"method": "gd", "beta": beta})],
                   check=True)
    return json.loads((out / "metrics.json").read_text())


def test_beta_parameter_changes_dynamics(tmp_path):
    assert _run(tmp_path, 0.0) != _run(tmp_path, 0.9)


def test_seed_determinism(tmp_path):
    assert _run(tmp_path, 0.5) == _run(tmp_path, 0.5)
'''


def _write_impl(t: TaskPacket, beta_key: str) -> None:
    wd = Path(t.workdir)
    (wd / "experiment.py").write_text(EXPERIMENT_PY.replace("BETA_KEY", repr(beta_key)),
                                      encoding="utf-8")
    (wd / "tests").mkdir(exist_ok=True)
    (wd / "tests" / "test_experiment.py").write_text(ENGINEER_TESTS, encoding="utf-8")


def solution_design(t: TaskPacket) -> dict:
    return ok({"solution_design": "single-file pure-Python experiment.py implementing GD, "
                                  "heavy-ball and random search; unit tests in tests/",
               "feasible": True, "files": ["experiment.py", "tests/test_experiment.py"]})


def implement_buggy(t: TaskPacket) -> dict:
    _write_impl(t, "momentum")  # BUG: protocol uses "beta"
    return ok({"summary": "implemented optimisers and entrypoint",
               "files_changed": ["experiment.py", "tests/test_experiment.py"]})


def implement_fixed(t: TaskPacket) -> dict:
    _write_impl(t, "beta")
    return ok({"summary": "fix: read momentum coefficient from params['beta'] per protocol",
               "files_changed": ["experiment.py"]})


def verify(t: TaskPacket) -> dict:
    wd = Path(t.workdir)
    vdir = wd / "tests" / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "test_independent.py").write_text(VERIFY_TEST, encoding="utf-8")
    results = []
    for beta in (0.0, 0.9):
        out = wd / f".probe-{beta}"
        subprocess.run([sys.executable, "experiment.py", "--condition", "p", "--seed", "0",
                        "--out", str(out), "--params", json.dumps({"beta": beta})],
                       cwd=wd, check=True, capture_output=True)
        results.append((out / "metrics.json").read_text())
        for f in out.iterdir():
            f.unlink()
        out.rmdir()
    if results[0] == results[1]:
        return ok({"verdict": "fail", "findings": [{
            "severity": "major", "location": "experiment.py:main",
            "description": "params['beta'] is ignored: momentum and gd conditions produce "
                           "identical results, violating the frozen protocol."}],
            "tests_added": ["tests/verification/test_independent.py"],
            "reproducibility_ok": True, "protocol_compliance_ok": False})
    return ok({"verdict": "pass", "findings": [
        {"severity": "minor", "description": "lr fixed to 1/L; fine for this protocol"}],
        "tests_added": ["tests/verification/test_independent.py"],
        "reproducibility_ok": True, "protocol_compliance_ok": True})


def challenge(t: TaskPacket) -> dict:
    return ok({"verdict": "upheld", "issues": [
        {"severity": "minor", "description": "Only diagonal quadratics with one kappa were tested."}],
        "alternative_explanations": ["Effect may be specific to step size 1/L"],
        "requested_controls": ["rotated quadratics", "kappa sweep"]})


def demo_agents() -> dict[Role, Agent]:
    scientist = ScriptedBackend({
        "define_problem": define_problem, "background_research": background,
        "research_question": question, "hypothesis": hypothesis,
        "requirements": requirements, "design": [design_v1, design_v2],
        "scientific_review": [review_revise, review_approve],
        "scientific_validation": validation, "interpret": interpret,
        "communicate": communicate, "next_question": next_question,
    }, model="scripted-scientist")
    engineer = ScriptedBackend({
        "solution_design": solution_design,
        "implement": [implement_buggy, implement_fixed],
        "redesign": implement_fixed,
    }, model="scripted-engineer")
    verifier = ScriptedBackend({"verify": verify, "challenge": challenge},
                               model="scripted-verifier")
    return {Role.SCIENTIST: Agent(Role.SCIENTIST, scientist),
            Role.ENGINEER: Agent(Role.ENGINEER, engineer),
            Role.VERIFIER: Agent(Role.VERIFIER, verifier)}


DEMO_OBJECTIVE = ("Investigate whether heavy-ball momentum can produce faster convergence "
                  "than plain gradient descent on ill-conditioned quadratic objectives.")
