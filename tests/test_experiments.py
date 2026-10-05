import random
from pathlib import Path

from autolab.experiments import (RESOURCE_METRICS, Trial, contrasts, evaluate_decision, evaluate_rule,
                                 holm, required_seeds,
                                 evaluate_requirements, paired_t_ci, run_protocol, summarize, t_quantile, welch_ci)

from scenario import EXPERIMENT, protocol


def trials(cond, vals):
    return [Trial(cond, "x", i, 0, 0.0, {"m": v}, "") for i, v in enumerate(vals)]


RULE = {"metric": "m", "treatment": "t", "control": "c", "direction": "greater",
        "min_effect": 0.5, "alpha": 0.05}


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


def test_t_quantiles_match_tables():
    for df, expected in ((1, 12.706), (2, 4.303), (4, 2.776), (10, 2.228), (30, 2.042)):
        assert abs(t_quantile(0.975, df) - expected) < 1e-3
    assert abs(t_quantile(0.025, 4) + 2.776) < 1e-3


def test_confidence_intervals_have_nominal_coverage_at_small_seed_counts():
    """R3 regression: the old percentile bootstrap covered only ~76% (3 seeds) and
    ~86% (5 seeds) at nominal 95%. The t intervals must be close to 95%."""
    rng = random.Random(0)
    reps = 2000
    for n in (3, 5):
        paired = welch = 0
        for _ in range(reps):
            _, lo, hi, _ = paired_t_ci([rng.gauss(0, 1) for _ in range(n)], 0.05)
            paired += lo <= 0 <= hi
            _, lo, hi, _ = welch_ci([rng.gauss(0, 1) for _ in range(n)],
                                    [rng.gauss(0, 3) for _ in range(n)], 0.05)
            welch += lo <= 0 <= hi
        assert 0.93 <= paired / reps <= 0.97, (n, paired / reps)
        assert 0.93 <= welch / reps <= 0.98, (n, welch / reps)


ECHO = """\
import argparse, json, pathlib
ap = argparse.ArgumentParser()
for a in ('--condition', '--seed', '--out', '--params'):
    ap.add_argument(a)
a = ap.parse_args()
p = json.loads(a.params)
pathlib.Path(a.out, 'metrics.json').write_text(json.dumps(
    {'score': 1.0, 'lr': p['lr'], 'effect': p['effect']}))
"""


def test_fixed_params_reach_the_entrypoint(tmp_path):
    """R1 regression: protocol.fixed_params must be delivered via --params."""
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "echo.py").write_text(ECHO, encoding="utf-8")
    p = protocol()
    p["entrypoint"] = "python echo.py"
    p["fixed_params"] = {"lr": 0.25}
    out = run_protocol(p, wd, tmp_path / "runs", seeds=[1])
    assert not out.failed, [t.error for t in out.trials]
    got = {t.condition: (t.metrics["lr"], t.metrics["effect"]) for t in out.trials}
    assert got == {"base": (0.25, 0.0), "treat": (0.25, 1.0)}


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
    # same seed -> same data (controller-measured resource metrics legitimately vary)
    out2 = run_protocol(protocol(), wd, tmp_path / "runs2")

    def data(o):
        return [{k: v for k, v in t.metrics.items() if k not in RESOURCE_METRICS}
                for t in o.trials]
    assert data(out) == data(out2)
    assert all(set(RESOURCE_METRICS) <= set(t.metrics) for t in out.trials)
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


def mtrials(cond, rows):
    return [Trial(cond, "x", i, 0, 0.0, dict(r), "") for i, r in enumerate(rows)]


def test_non_inferiority():
    ni = {**RULE, "type": "non_inferiority", "margin": 0.5}
    c = trials("c", [1.0, 1.1, 0.9, 1.05, 0.95])
    same = trials("t", [1.0, 1.1, 0.9, 1.05, 0.95])
    assert evaluate_decision(ni, c + same)["outcome"] == "supported"
    worse = trials("t", [-1.0, -0.9, -1.1, -0.95, -1.05])
    assert evaluate_decision(ni, c + worse)["outcome"] == "unsupported"
    noisy = trials("t", [3.0, -3.0, 2.0, -2.0, 1.0])
    assert evaluate_decision(ni, c + noisy)["outcome"] == "inconclusive"
    out = evaluate_decision(ni, c + same)
    assert out["type"] == "non_inferiority" and out["margin"] == 0.5


def test_p_value_and_se_are_reported():
    c = trials("c", [0.0, 0.1, -0.1, 0.05, -0.05])
    out = evaluate_decision(RULE, c + trials("t", [2.0, 2.1, 1.9, 2.05, 1.95]))
    assert out["se"] > 0 and out["p_value"] < 0.001
    out = evaluate_decision(RULE, c + trials("t", [3.0, -3.0, 2.0, -2.0, 1.0]))
    assert out["p_value"] > 0.05


def test_co_primary_intersection_union():
    rule = {**RULE, "co_primary": [{"metric": "n", "direction": "less",
                                    "type": "non_inferiority", "margin": 1.0}]}
    c = mtrials("c", [{"m": v, "n": 5.0 + v} for v in [0.0, 0.1, -0.1, 0.05, -0.05]])
    good = mtrials("t", [{"m": 2.0 + v, "n": 5.0 + v} for v in [0.0, 0.1, -0.1, 0.05, -0.05]])
    out = evaluate_rule(rule, c + good)
    assert out["outcome"] == "supported" and len(out["endpoints"]) == 2
    bad = mtrials("t", [{"m": 2.0 + v, "n": 9.0 + v} for v in [0.0, 0.1, -0.1, 0.05, -0.05]])
    assert evaluate_rule(rule, c + bad)["outcome"] == "unsupported"
    assert evaluate_rule(RULE, trials("c", [0, 1, 2]) + trials("t", [0, 1, 2])) ==         evaluate_decision(RULE, trials("c", [0, 1, 2]) + trials("t", [0, 1, 2]))


def test_holm():
    out = holm([0.01, 0.04, 0.03], 0.05)
    assert [round(a, 6) for a, _ in out] == [0.03, 0.06, 0.06]
    assert [r for _, r in out] == [True, False, False]
    assert holm([], 0.05) == []


def test_secondary_contrasts_are_holm_corrected():
    p = {"conditions": [{"name": "c", "role": "baseline"}, {"name": "t", "role": "intervention"},
                        {"name": "a", "role": "ablation"}, {"name": "b", "role": "ablation"}],
         "decision_rule": {**RULE, "co_primary": [{"metric": "m", "direction": "greater",
                                                   "min_effect": 0.1}]}}
    base = [0.0, 0.1, -0.1, 0.05, -0.05]
    ts = (trials("c", base) + trials("t", base) + trials("a", [v + 2 for v in base])
          + trials("b", [v + 0.01 for v in base]))
    out = contrasts(p, ts)
    assert len(out) == 2 and all("p_holm" in c and c["p_holm"] >= c["p_value"] for c in out)
    assert [c["holm_significant"] for c in out] == [True, False]


def test_required_seeds():
    assert required_seeds(1.0, 1.0) == 10   # (t.975 + t.8) * sd / sqrt(n) <= effect
    assert required_seeds(1.0, 0.5) > required_seeds(1.0, 1.0)
    assert required_seeds(0.0, 1.0) == 3
    assert required_seeds(1.0, 0.0) is None
    assert required_seeds(100.0, 0.01, max_n=50) is None
