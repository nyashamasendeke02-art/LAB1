"""D51: domain-general research (AI, LLMs, agents, software/code): item-level analysis,
transient-failure retries, parallel trials, spend caps and pinned evaluation data."""

import json
import os
import random
from pathlib import Path

import pytest

from autolab.experiments import (Trial, evaluate_decision, evaluate_rule, hash_paths,
                                 item_validity, load_items, run_protocol)
from autolab.messages import validate_protocol

import scenario
from scenario import make, ok, protocol


def item_trial(cond, seed, values, ok_=True):
    items = {f"q{i}": {"acc": v} for i, v in enumerate(values)}
    return Trial(cond, "x", seed, 0, 0.0, {"acc": sum(values) / len(values)}, "",
                 None if ok_ else "crashed", items=items)


ITEM_RULE = {"metric": "acc", "treatment": "t", "control": "c", "direction": "greater",
             "min_effect": 0.1, "alpha": 0.05, "unit": "item"}


def test_item_unit_pairs_by_item_and_averages_over_seeds():
    rng = random.Random(1)
    base = [rng.random() for _ in range(40)]
    trials = [item_trial("c", s, [b + rng.gauss(0, 0.01) for b in base]) for s in (1, 2)]
    trials += [item_trial("t", s, [b + 0.3 + rng.gauss(0, 0.01) for b in base]) for s in (1, 2)]
    out = evaluate_decision(ITEM_RULE, trials)
    assert out["outcome"] == "supported", out
    assert out["unit"] == "item" and out["n_pairs"] == 40
    assert out["ci_method"] == "student_t_paired_items"
    assert abs(out["effect"] - 0.3) < 0.01
    # the same data analysed per seed has only 2 replicates and cannot conclude
    seed_rule = {**ITEM_RULE, "unit": "seed", "pairing": "paired"}
    assert evaluate_decision(seed_rule, trials)["n_pairs"] == 2


def test_item_unit_ignores_failed_trials_and_needs_two_items():
    good = [item_trial("c", 1, [0.0, 0.0, 0.0]), item_trial("t", 1, [1.0, 1.0, 1.0])]
    bad = item_trial("t", 2, [-9.0, -9.0, -9.0], ok_=False)
    out = evaluate_decision(ITEM_RULE, good + [bad])
    assert out["effect"] == pytest.approx(1.0)
    one = [item_trial("c", 1, [0.0]), item_trial("t", 1, [1.0])]
    assert evaluate_decision(ITEM_RULE, one)["outcome"] == "inconclusive"


def test_co_primary_inherits_item_unit():
    trials = [item_trial("c", 1, [0.0, 0.1, 0.0, 0.1]), item_trial("t", 1, [0.5, 0.6, 0.5, 0.6])]
    out = evaluate_rule({**ITEM_RULE, "co_primary": [{"metric": "acc", "direction": "greater",
                                                      "min_effect": 0.2}]}, trials)
    assert all(e["unit"] == "item" for e in out["endpoints"])


def test_load_items_validation(tmp_path):
    f = tmp_path / "items.json"
    f.write_text(json.dumps([{"id": "a", "acc": 1}, {"id": 2, "acc": 0.5, "extra": "x"}]))
    assert load_items(f, ["acc"]) == {"a": {"acc": 1.0}, "2": {"acc": 0.5}}
    for bad in ([], [{"acc": 1}], [{"id": "a", "acc": 1}, {"id": "a", "acc": 0}],
                [{"id": "a", "acc": float("nan")}], [{"id": "a"}], {"id": "a"}):
        f.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            load_items(f, ["acc"])


ITEM_EXP = """\
import argparse, json, os, pathlib, random, sys
ap = argparse.ArgumentParser()
for a in ('--condition', '--seed', '--out', '--params'):
    ap.add_argument(a)
a = ap.parse_args()
p = json.loads(a.params)
out = pathlib.Path(a.out)
flaky = p.get('flaky_marker')
if flaky and not os.path.exists(flaky):
    pathlib.Path(flaky).write_text('x')
    sys.exit(75)
if p.get('fail_always_transient'):
    sys.exit(75)
rng = random.Random(int(a.seed))
items = [{'id': f'q{i}', 'acc': min(1.0, (i % 5) / 5 + p['effect'] + rng.random() * 0.01)}
         for i in range(p.get('n', 10))]
if not p.get('no_items'):
    (out / 'items.json').write_text(json.dumps(items))
(out / 'transcripts').mkdir(exist_ok=True)
(out / 'transcripts' / 'q0.txt').write_text('prompt/response log')
(out / 'metrics.json').write_text(json.dumps(
    {'acc': sum(i['acc'] for i in items) / len(items), 'cost_usd': p.get('cost', 0.0)}))
"""


def item_protocol(**over):
    p = {
        "title": "prompting study", "kind": "exploratory", "entrypoint": "python exp.py",
        "conditions": [{"name": "base", "role": "baseline", "params": {"effect": 0.0}},
                       {"name": "treat", "role": "intervention", "params": {"effect": 0.2}}],
        "seeds": [1], "n_items": 10,
        "metrics": {"primary": "acc", "secondary": ["cost_usd"]},
        "decision_rule": {"metric": "acc", "treatment": "treat", "control": "base",
                          "direction": "greater", "min_effect": 0.1, "unit": "item"},
        "budget": {"timeout_s": 60},
        "validity_checks": [{"id": "V1", "description": "sane", "metric": "acc",
                             "condition": "base", "op": "<=", "value": 1.0}],
    }
    p.update(over)
    return p


@pytest.fixture
def wd(tmp_path):
    d = tmp_path / "wd"
    d.mkdir()
    (d / "exp.py").write_text(ITEM_EXP, encoding="utf-8")
    return d


def test_item_protocol_runs_and_requires_items_json(wd, tmp_path):
    out = run_protocol(item_protocol(), wd, tmp_path / "r1")
    assert not out.failed, [t.error for t in out.trials]
    assert all(len(t.items) == 10 for t in out.trials)
    assert evaluate_decision(item_protocol()["decision_rule"] | {"treatment": "treat",
                                                                  "control": "base"},
                             out.trials)["outcome"] == "supported"
    p = item_protocol(fixed_params={"no_items": True})
    missing = run_protocol(p, wd, tmp_path / "r2")
    assert len(missing.failed) == 2 and "items.json" in missing.failed[0].error


def test_transient_exit_is_retried_not_failed(wd, tmp_path):
    waits = []
    marker = tmp_path / "flaky"
    p = item_protocol(fixed_params={"flaky_marker": str(marker)})
    out = run_protocol(p, wd, tmp_path / "r", conditions=["base"], max_retries=2,
                       retry_wait_s=5, sleep=waits.append)
    assert not out.failed and out.trials[0].attempts == 2 and waits == [5]
    # retries exhausted -> a recorded failure that says it was transient
    p = item_protocol(fixed_params={"fail_always_transient": True})
    waits.clear()
    out = run_protocol(p, wd, tmp_path / "r2", conditions=["base"], max_retries=3,
                       retry_wait_s=1, sleep=waits.append)
    assert out.failed and "transient" in out.trials[0].error and out.trials[0].attempts == 4
    assert waits == [1, 2, 4]  # exponential backoff


def test_cost_budget_stops_new_trials(wd, tmp_path):
    p = item_protocol(seeds=[1, 2, 3], fixed_params={"cost": 1.0},
                      budget={"timeout_s": 60, "max_cost_usd": 2.5})
    out = run_protocol(p, wd, tmp_path / "r")
    ran = [t for t in out.trials if t.ok]
    assert len(ran) == 3
    assert all("cost budget exhausted" in t.error for t in out.failed) and len(out.failed) == 3


def test_parallel_trials_match_serial(wd, tmp_path):
    p = item_protocol(seeds=[1, 2, 3, 4])
    serial = run_protocol(p, wd, tmp_path / "s")
    par = run_protocol({**p, "budget": {"timeout_s": 60, "max_parallel": 4}}, wd, tmp_path / "p")
    key = lambda o: [(t.condition, t.seed, t.items) for t in o.trials]  # noqa: E731
    assert key(serial) == key(par)


def test_protocol_validation_for_item_studies():
    assert validate_protocol(item_protocol()) == []
    p = item_protocol()
    del p["n_items"]
    assert any("n_items" in e for e in validate_protocol(p))
    p = item_protocol()
    p["decision_rule"]["pairing"] = "unpaired"
    assert any("always paired" in e for e in validate_protocol(p))
    p = item_protocol(budget={"max_cost_usd": 5})
    p["metrics"]["secondary"] = []
    assert any("cost_usd" in e for e in validate_protocol(p))
    for bad in ("../outside", "/abs", "C:/x"):
        assert any("data_paths" in e for e in validate_protocol(item_protocol(data_paths=[bad])))
    assert validate_protocol(item_protocol(data_paths=["data/eval.jsonl"])) == []
    # seed-unit studies still need >= 3 seeds
    assert any(">= 3 seeds" in e for e in validate_protocol(protocol(seeds=(1,))))


def test_item_validity_checks():
    p = item_protocol(n_items=3)
    full = [item_trial("base", 1, [0, 0, 0]), item_trial("treat", 1, [1, 1, 1])]
    assert [c["passed"] for c in item_validity(p, full, set())] == [True]
    short = [item_trial("base", 1, [0, 0]), item_trial("treat", 1, [1, 1, 1])]
    assert item_validity(p, short, set())[0]["passed"] is False
    conf = {**p, "kind": "confirmatory"}
    checks = {c["id"]: c["passed"] for c in item_validity(conf, full, {"q1"})}
    assert checks == {"AUTO-ITEM-COVERAGE": True, "AUTO-FRESH-ITEMS": False}
    assert item_validity(protocol(), full, set()) == []


def test_hash_paths(tmp_path):
    (tmp_path / "data" / "sub").mkdir(parents=True)
    (tmp_path / "data" / "a.json").write_text("1")
    (tmp_path / "data" / "sub" / "b.json").write_text("2")
    hashes, missing = hash_paths(tmp_path, ["data", "nope"])
    assert set(hashes) == {"data/a.json", "data/sub/b.json"} and missing == ["nope"]


ITEM_EXPERIMENT = scenario.EXPERIMENT.replace(
    '''    (out / "metrics.json").write_text(json.dumps(
        {"score": score(p.get("effect", 0.0), p.get("noise", 0.1), a.seed)}))''',
    '''    items = [{"id": f"q{i}", "score": score(p.get("effect", 0.0), p.get("noise", 0.1),
                                             a.seed * 1000 + i)} for i in range(12)]
    (out / "items.json").write_text(json.dumps(items))
    (out / "metrics.json").write_text(json.dumps(
        {"score": sum(i["score"] for i in items) / len(items)}))''')


def test_item_study_end_to_end_through_controller(tmp_path):
    assert ITEM_EXPERIMENT != scenario.EXPERIMENT

    def design(t):
        p = protocol(seeds=(1,))
        p["n_items"] = 12
        p["decision_rule"]["unit"] = "item"
        p["data_paths"] = ["experiment.py"]
        return ok({"options": [{"name": "A", "description": "two-arm"}], "chosen": "A",
                   "rationale": "item-level", "protocol": p})

    def implement(t):
        scenario.write_impl(t)
        (Path(t.workdir) / "experiment.py").write_text(ITEM_EXPERIMENT, encoding="utf-8")
        return ok({"summary": "implemented"})

    lab, ctl = make(tmp_path, sci__design=design, eng__implement=implement)
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE", steps[-1]
    run = lab.store.query("run")[0]
    assert all(len(t["items"]) == 12 for t in run.data["trials"])
    assert list(run.data["data"]) == ["experiment.py"]
    assert "items.json" in run.data["trials"][0]["files"]
    res = lab.store.query("result")[0]
    assert res.data["decision"]["unit"] == "item" and res.data["decision"]["n_pairs"] == 12
    assert res.data["outcome"] == "supported"
    assert res.data["validity"][0]["id"] == "AUTO-ITEM-COVERAGE"
    assert res.data["validity"][0]["passed"] and len(res.data["item_ids"]) == 12
    f = lab.root / run.data["trials"][0]["out_dir"] / "items.json"
    assert not os.access(f, os.W_OK)
