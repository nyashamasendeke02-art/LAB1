from pathlib import Path

from autolab.experiments import (Trial, bootstrap_mean_diff, evaluate_decision,
                                 evaluate_requirements, run_protocol, summarize)

from scenario import EXPERIMENT, protocol


def trials(cond, vals):
    return [Trial(cond, "x", i, 0, 0.0, {"m": v}, "") for i, v in enumerate(vals)]


RULE = {"metric": "m", "treatment": "t", "control": "c", "direction": "greater",
        "min_effect": 0.5, "alpha": 0.05, "n_boot": 1000}


def test_decision_outcomes():
    c = trials("c", [0.0, 0.1, -0.1, 0.05, -0.05])
    assert evaluate_decision(RULE, c + trials("t", [2.0, 2.1, 1.9, 2.05, 1.95]))["outcome"] == "supported"
    assert evaluate_decision(RULE, c + trials("t", [0.2, 0.3, 0.25, 0.22, 0.28]))["outcome"] == "partially_supported"
    assert evaluate_decision(RULE, c + trials("t", [0.0, 0.1, -0.1, 0.05, -0.05]))["outcome"] == "unsupported"
    noisy = trials("t", [3.0, -3.0, 2.0, -2.0, 1.0])
    assert evaluate_decision(RULE, c + noisy)["outcome"] == "inconclusive"
    assert evaluate_decision(RULE, c + trials("t", [5.0]))["outcome"] == "inconclusive"


def test_direction_less_flips_sign():
    r = {**RULE, "direction": "less"}
    out = evaluate_decision(r, trials("c", [10, 11, 10.5]) + trials("t", [1, 1.2, 0.9]))
    assert out["outcome"] == "supported" and out["effect"] > 0


def test_failed_trials_excluded_from_analysis():
    t = trials("t", [2.0, 2.1, 2.2])
    t[0].error = "crashed"
    s = summarize(t)
    assert s["t"]["n_ok"] == 2 and s["t"]["n_failed"] == 1


def test_bootstrap_deterministic():
    assert bootstrap_mean_diff([1, 2, 3], [0, 1], 500, 0.05, 7) == \
        bootstrap_mean_diff([1, 2, 3], [0, 1], 500, 0.05, 7)


def test_requirements():
    s = summarize(trials("c", [1.0, 2.0, 3.0]))
    res = evaluate_requirements([
        {"id": "A", "description": "", "metric": "m", "condition": "c", "op": "<", "value": 5},
        {"id": "B", "description": "", "metric": "m", "condition": "c", "op": ">", "value": 5,
         "aggregate": "max"},
        {"id": "C", "description": "", "metric": "m", "condition": "zz", "op": ">", "value": 0}], s)
    assert [r["passed"] for r in res] == [True, False, False]


def test_runner_contract_and_failures(tmp_path):
    wd = tmp_path / "code"
    wd.mkdir()
    (wd / "experiment.py").write_text(EXPERIMENT)
    out = run_protocol(protocol(), wd, tmp_path / "runs")
    assert len(out.trials) == 8 and not out.failed
    assert (tmp_path / "runs" / "treat" / "seed-1" / "metrics.json").exists()
    # same seed -> same data
    out2 = run_protocol(protocol(), wd, tmp_path / "runs2")
    assert [t.metrics for t in out.trials] == [t.metrics for t in out2.trials]
    # missing metric is a failure, not silently ignored
    p = protocol()
    p["metrics"]["secondary"] = ["not_written"]
    bad = run_protocol(p, wd, tmp_path / "runs3", seeds=[1])
    assert len(bad.failed) == 2 and "missing" in bad.failed[0].error
    (wd / "experiment.py").write_text("import sys; sys.exit(3)")
    crash = run_protocol(protocol(), wd, tmp_path / "runs4", seeds=[1])
    assert all(not t.ok for t in crash.trials)


def test_paired_analysis_removes_shared_seed_variance():
    # Large between-seed variance, small consistent per-seed effect of +0.6.
    base = [0.0, 10.0, -10.0, 5.0, -5.0, 20.0]
    c = trials("c", base)
    t = trials("t", [b + 0.6 for b in base])
    unpaired = evaluate_decision(RULE, c + t)
    paired = evaluate_decision({**RULE, "pairing": "paired"}, c + t)
    assert unpaired["outcome"] == "inconclusive"
    assert paired["outcome"] == "supported" and paired["n_pairs"] == 6
    assert abs(paired["effect"] - 0.6) < 1e-9


def test_paired_analysis_only_uses_seeds_valid_in_both_arms():
    c = trials("c", [0.0, 0.0, 0.0, 0.0])
    t = trials("t", [1.0, 1.0, 1.0, 1.0])
    t[0].error = "crashed"
    out = evaluate_decision({**RULE, "pairing": "paired"}, c + t)
    assert out["n_pairs"] == 3


def test_paired_difference_checks():
    c = trials("c", [1.0, 2.0, 3.0])
    t = trials("t", [0.5, 1.5, 2.5])
    reqs = [{"id": "D", "description": "", "metric": "m", "condition": "t", "relative_to": "c",
             "op": "<", "value": -0.4}]
    out = evaluate_requirements(reqs, summarize(c + t), c + t)
    assert out[0]["passed"] and abs(out[0]["observed"] + 0.5) < 1e-12 and out[0]["n_pairs"] == 3
    assert not evaluate_requirements(reqs, summarize(c), c)[0]["passed"]  # no pairs
