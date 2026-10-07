"""Experiment execution and pre-registered analysis.

Entrypoint contract (enforced): the protocol's ``entrypoint`` is invoked as

    <entrypoint> --condition NAME --seed N --out DIR --params JSON

from a *detached checkout of the exact merged commit*, and must write
``DIR/metrics.json`` (a flat object of numeric metrics). Each trial's
stdout/stderr/metrics are hashed into the artifact store; the run manifest
links protocol version + freeze hash, commit, environment and seeds.

Analysis is mechanical: the decision rule fixed in the frozen protocol is
evaluated by :func:`evaluate_decision`. Agents interpret afterwards but can
not change the computed outcome.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
import os
import platform
import shlex
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .procs import run_tree
from .taxonomy import Outcome


@dataclass
class Trial:
    condition: str
    role: str
    seed: int
    returncode: int
    duration_s: float
    metrics: dict
    out_dir: str
    error: str | None = None
    resources: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.error is None


@dataclass
class RunOutput:
    trials: list[Trial] = field(default_factory=list)
    command_template: list[str] = field(default_factory=list)

    @property
    def failed(self) -> list[Trial]:
        return [t for t in self.trials if not t.ok]


def environment_snapshot() -> dict:
    dists = sorted(f"{d.metadata['Name']}=={d.version}"
                   for d in importlib.metadata.distributions() if d.metadata["Name"])
    return {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": dists,
    }


def build_command(entrypoint: str) -> list[str]:
    parts = shlex.split(entrypoint, posix=True)
    if parts and parts[0] in ("python", "python3", "py"):
        parts[0] = sys.executable  # pin the interpreter that is recorded
    return parts


def _finite_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def trial_params(protocol: dict, condition: dict) -> dict:
    """The frozen parameters a trial receives: protocol-wide fixed_params plus the
    condition's own params (validate_protocol forbids overlapping keys)."""
    return {**protocol.get("fixed_params", {}), **condition.get("params", {})}


# Controller-measured resource metrics, injected into every trial's metrics. Code under
# test cannot fake them: values it writes under these names are overwritten.
RESOURCE_METRICS = ("autolab_wall_s", "autolab_cpu_s", "autolab_peak_mb")


def dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 2**20


def check_lock(lock_file: Path) -> list[str]:
    """Compare a pinned ``name==version`` lock file with the running interpreter's packages."""
    problems = []
    for line in lock_file.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        name, want = (x.strip() for x in line.split("==", 1))
        try:
            have = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            problems.append(f"{name}=={want} not installed")
            continue
        if have != want:
            problems.append(f"{name}: locked {want}, installed {have}")
    return problems


def run_trial(entrypoint: str, workdir: Path, out_dir: Path, condition: dict,
              seed: int, required_metrics: list[str], timeout_s: float,
              params: dict | None = None, output_cap_mb: float | None = None) -> Trial:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(entrypoint) + [
        "--condition", condition["name"], "--seed", str(seed),
        "--out", str(out_dir),
        "--params", json.dumps(condition.get("params", {}) if params is None else params,
                               sort_keys=True),
    ]
    env = {**os.environ, "PYTHONHASHSEED": str(seed), "AUTOLAB_SEED": str(seed)}
    t0 = time.perf_counter()
    error = None
    proc = run_tree(cmd, cwd=str(workdir), timeout=timeout_s, env=env,
                    output_dir=str(out_dir),
                    output_cap_bytes=(int(output_cap_mb * 2**20)
                                      if output_cap_mb is not None else None))
    rc, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    resources = {"autolab_wall_s": proc.wall_s, "autolab_cpu_s": proc.cpu_s,
                 "autolab_peak_mb": proc.peak_mb}
    if proc.output_limit_exceeded:
        error = f"trial output exceeded the {output_cap_mb} MB cap; process tree terminated"
    elif proc.timed_out:
        error = f"timeout after {timeout_s}s"
    dur = time.perf_counter() - t0
    (out_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (out_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    metrics: dict = {}
    mpath = out_dir / "metrics.json"
    if rc == 0 and error is None:
        try:
            metrics = json.loads(mpath.read_text(encoding="utf-8"))
            if not isinstance(metrics, dict):
                raise ValueError("metrics.json is not an object")
            metrics.update({k: v for k, v in resources.items() if v is not None})
            missing = [m for m in required_metrics if not _finite_number(metrics.get(m))]
            if missing:
                error = f"missing/non-finite metrics: {missing}"
        except FileNotFoundError:
            error = "entrypoint did not write metrics.json"
        except (ValueError, json.JSONDecodeError) as exc:
            error = f"invalid metrics.json: {exc}"
    elif error is None:
        error = f"exit code {rc}"
    if output_cap_mb is not None:
        size = dir_size_mb(out_dir)
        if size > output_cap_mb and error is None:
            error = f"trial output {size:.1f} MB exceeds the {output_cap_mb} MB cap"
    return Trial(condition["name"], condition["role"], seed, rc, round(dur, 4),
                 metrics, str(out_dir), error, resources)


def run_protocol(protocol: dict, workdir: Path, out_root: Path,
                 seeds: list[int] | None = None,
                 conditions: list[str] | None = None,
                 output_cap_mb: float | None = None) -> RunOutput:
    """Run every (condition x seed). ``seeds``/``conditions`` override only for smoke tests."""
    timeout = float(protocol.get("budget", {}).get("timeout_s", 600))
    required = [protocol["metrics"]["primary"], *protocol["metrics"].get("secondary", [])]
    out = RunOutput(command_template=build_command(protocol["entrypoint"]))
    for cond in protocol["conditions"]:
        if conditions and cond["name"] not in conditions:
            continue
        for seed in seeds if seeds is not None else protocol["seeds"]:
            out.trials.append(run_trial(protocol["entrypoint"], workdir,
                                        out_root / cond["name"] / f"seed-{seed}",
                                        cond, seed, required, timeout,
                                        params=trial_params(protocol, cond),
                                        output_cap_mb=output_cap_mb))
    return out


# ------------------------------------------------------------------ analysis
def values(trials: list[Trial], condition: str, metric: str) -> list[float]:
    return [float(t.metrics[metric]) for t in trials
            if t.ok and t.condition == condition and metric in t.metrics]


def summarize(trials: list[Trial]) -> dict:
    out: dict = {}
    conds = sorted({t.condition for t in trials})
    for c in conds:
        ok = [t for t in trials if t.condition == c and t.ok]
        metrics = sorted({m for t in ok for m in t.metrics if _finite_number(t.metrics[m])})
        out[c] = {"n_ok": len(ok), "n_failed": sum(1 for t in trials
                                                     if t.condition == c and not t.ok)}
        for m in metrics:
            xs = values(trials, c, m)
            out[c][m] = {
                "n": len(xs), "mean": statistics.fmean(xs),
                "std": statistics.stdev(xs) if len(xs) > 1 else 0.0,
                "median": statistics.median(xs), "min": min(xs), "max": max(xs),
            }
    return out


# Confidence intervals use Student t (paired) / Welch t (unpaired). The percentile
# bootstrap used before undercovers badly at lab-sized seed counts (simulated 95%
# coverage: 0.76 at 3 seeds, 0.86 at 5, 0.91 at 20), inflating false "supported".
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (Lentz's method)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    tail = 0.5 * _betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t >= 0 else tail


def t_quantile(p: float, df: float) -> float:
    """Inverse Student t CDF by bisection (0 < p < 1)."""
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_quantile(1.0 - p, df)
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def welch_ci(t: list[float], c: list[float], alpha: float) -> tuple[float, float, float, float]:
    """(difference of means, CI low, CI high, Welch df)."""
    diff = statistics.fmean(t) - statistics.fmean(c)
    vt, vc = statistics.variance(t) / len(t), statistics.variance(c) / len(c)
    se = math.sqrt(vt + vc)
    den = (vt * vt / (len(t) - 1) if vt else 0.0) + (vc * vc / (len(c) - 1) if vc else 0.0)
    df = (vt + vc) ** 2 / den if den else float(len(t) + len(c) - 2)
    half = t_quantile(1 - alpha / 2, df) * se
    return diff, diff - half, diff + half, df


def paired_values(trials: list[Trial], treatment: str, control: str,
                  metric: str) -> list[tuple[int, float, float]]:
    """(seed, treatment, control) for seeds where BOTH arms produced a valid value."""
    def by_seed(cond):
        return {t.seed: float(t.metrics[metric]) for t in trials
                if t.ok and t.condition == cond and metric in t.metrics}
    tv, cv = by_seed(treatment), by_seed(control)
    return [(s, tv[s], cv[s]) for s in sorted(tv.keys() & cv.keys())]


def paired_t_ci(diffs: list[float], alpha: float) -> tuple[float, float, float, float]:
    """(mean per-seed difference, CI low, CI high, df) with a Student t interval."""
    mean = statistics.fmean(diffs)
    df = len(diffs) - 1
    half = t_quantile(1 - alpha / 2, df) * statistics.stdev(diffs) / math.sqrt(len(diffs))
    return mean, mean - half, mean + half, float(df)


def evaluate_decision(rule: dict, trials: list[Trial]) -> dict:
    """Apply the pre-registered decision rule.

    effect is oriented so that positive == the hypothesised direction.
    * supported:           CI_low > 0 and effect >= min_effect
    * partially_supported: CI_low > 0 but effect < min_effect
    * unsupported:         CI_high < min_effect (a meaningful effect is excluded)
    * inconclusive:        otherwise, or < 2 valid trials in either arm
    With ``rule["type"] == "non_inferiority"`` the outcome instead compares the CI
    with ``-margin``: supported if CI_low > -margin, unsupported if CI_high < -margin.

    The CI is a (1 - alpha) Student t interval: ``rule["pairing"] == "paired"``
    uses per-seed differences over seeds valid in both arms (seed-matched
    designs); default "unpaired" uses Welch's interval. Fully deterministic.
    """
    alpha = rule.get("alpha", 0.05)
    t = values(trials, rule["treatment"], rule["metric"])
    c = values(trials, rule["control"], rule["metric"])
    base = {"metric": rule["metric"], "treatment": rule["treatment"],
            "control": rule["control"], "n_treatment": len(t), "n_control": len(c),
            "min_effect": rule.get("min_effect"), "alpha": alpha, "direction": rule["direction"]}
    pairing = rule.get("pairing", "unpaired")
    base["pairing"] = pairing
    if pairing == "paired":
        pairs = paired_values(trials, rule["treatment"], rule["control"], rule["metric"])
        base["n_pairs"] = len(pairs)
        if len(pairs) < 2:
            return {**base, "outcome": Outcome.INCONCLUSIVE.value,
                    "reason": "fewer than 2 seeds valid in both arms"}
        diff, lo, hi, df = paired_t_ci([a - b for _, a, b in pairs], alpha)
        base["ci_method"] = "student_t_paired"
    else:
        if len(t) < 2 or len(c) < 2:
            return {**base, "outcome": Outcome.INCONCLUSIVE.value,
                    "reason": "fewer than 2 valid trials in an arm"}
        diff, lo, hi, df = welch_ci(t, c, alpha)
        base["ci_method"] = "welch_t"
    base["df"] = df
    if rule["direction"] == "less":
        diff, lo, hi = -diff, -hi, -lo
    tq = t_quantile(1 - alpha / 2, df)
    se = (hi - lo) / (2 * tq)
    base["se"] = se
    base["p_value"] = (1.0 if diff == 0 else 0.0) if se == 0 else 2 * (1 - t_cdf(abs(diff) / se, df))
    kind = rule.get("type", "superiority")
    base["type"] = kind
    if kind == "non_inferiority":
        # Oriented effect: positive = better. Non-inferior if the CI excludes a loss
        # larger than the margin; inferior if the CI lies entirely below -margin.
        margin = rule["margin"]
        base["margin"] = margin
        if lo > -margin:
            outcome = Outcome.SUPPORTED
        elif hi < -margin:
            outcome = Outcome.UNSUPPORTED
        else:
            outcome = Outcome.INCONCLUSIVE
    elif lo > 0 and diff >= rule["min_effect"]:
        outcome = Outcome.SUPPORTED
    elif lo > 0:
        outcome = Outcome.PARTIALLY_SUPPORTED
    elif hi < rule["min_effect"]:
        outcome = Outcome.UNSUPPORTED
    else:
        outcome = Outcome.INCONCLUSIVE
    return {**base, "effect": diff, "ci_low": lo, "ci_high": hi,
            "outcome": outcome.value}


def evaluate_rule(rule: dict, trials: list[Trial]) -> dict:
    """The pre-registered decision with optional co-primary endpoints.

    ``rule["co_primary"]`` is a list of further rules (metric, direction, type,
    min_effect | margin; treatment/control/alpha/pairing default to the main rule's).
    Intersection-union logic, so no alpha correction is needed: supported only if
    every endpoint is supported; unsupported if any endpoint is unsupported;
    otherwise inconclusive (or partially_supported if all are at least partial).
    """
    main = evaluate_decision(rule, trials)
    subs = rule.get("co_primary") or []
    if not subs:
        return main
    inherit = {k: rule[k] for k in ("treatment", "control", "alpha", "pairing") if k in rule}
    parts = [main] + [evaluate_decision({**inherit, **s}, trials) for s in subs]
    outs = [p["outcome"] for p in parts]
    if all(o == Outcome.SUPPORTED.value for o in outs):
        outcome = Outcome.SUPPORTED
    elif any(o == Outcome.UNSUPPORTED.value for o in outs):
        outcome = Outcome.UNSUPPORTED
    elif all(o in (Outcome.SUPPORTED.value, Outcome.PARTIALLY_SUPPORTED.value) for o in outs):
        outcome = Outcome.PARTIALLY_SUPPORTED
    else:
        outcome = Outcome.INCONCLUSIVE
    return {**main, "outcome": outcome.value, "endpoints": parts,
            "combination": "intersection-union (all co-primary endpoints must hold)"}


def holm(p_values: list[float], alpha: float) -> list[tuple[float, bool]]:
    """Holm-Bonferroni: (adjusted p, rejected at alpha) for each p, in input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return [(adjusted[i], adjusted[i] <= alpha) for i in range(m)]


def required_seeds(sd: float, effect: float, alpha: float = 0.05, power: float = 0.8,
                   max_n: int = 1000) -> int | None:
    """Smallest number of paired seeds for a two-sided t test at ``alpha`` to detect a
    true mean difference ``effect`` with probability ``power`` given per-seed SD ``sd``
    (approximation: t_{1-a/2,n-1} + t_{power,n-1} <= effect*sqrt(n)/sd)."""
    if effect <= 0 or sd < 0:
        return None
    if sd == 0:
        return 3
    for n in range(3, max_n + 1):
        if (t_quantile(1 - alpha / 2, n - 1) + t_quantile(power, n - 1)) * sd / math.sqrt(n) <= effect:
            return n
    return None


_OPS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


_AGG = {"mean": statistics.fmean, "median": statistics.median, "min": min, "max": max}


def evaluate_requirements(reqs: list[dict], summary: dict,
                          trials: list[Trial] | None = None) -> list[dict]:
    """Evaluate checks on per-condition aggregates, or -- with ``relative_to`` -- on the
    aggregate of per-seed differences (condition - relative_to) over seeds valid in both."""
    results = []
    for r in reqs:
        agg = r.get("aggregate", "mean")
        if r.get("relative_to"):
            pairs = paired_values(trials or [], r["condition"], r["relative_to"], r["metric"])
            label = f"{agg}(paired {r['condition']}-{r['relative_to']} {r['metric']})"
            if not pairs:
                results.append({"id": r["id"], "passed": False, "observed": None,
                                "reason": f"no paired data for {label}"})
                continue
            observed = _AGG[agg]([a - b for _, a, b in pairs])
            results.append({"id": r["id"], "passed": bool(_OPS[r["op"]](observed, r["value"])),
                            "observed": observed, "n_pairs": len(pairs),
                            "expected": f"{label} {r['op']} {r['value']}"})
            continue
        stats = summary.get(r["condition"], {}).get(r["metric"])
        if stats is None:
            results.append({"id": r["id"], "passed": False, "observed": None,
                            "reason": f"no data for {r['condition']}.{r['metric']}"})
            continue
        observed = stats[agg]
        results.append({"id": r["id"], "passed": bool(_OPS[r["op"]](observed, r["value"])),
                        "observed": observed,
                        "expected": f"{agg}({r['condition']}.{r['metric']}) {r['op']} {r['value']}"})
    return results


def contrasts(protocol: dict, trials: list[Trial]) -> list[dict]:
    """Secondary (non-decisive) comparisons of every non-control condition vs control."""
    rule = {k: v for k, v in protocol["decision_rule"].items() if k != "co_primary"}
    out = []
    for cond in protocol["conditions"]:
        if cond["name"] == rule["control"] or cond["name"] == rule["treatment"]:
            continue
        r = {**rule, "treatment": cond["name"]}
        res = evaluate_decision(r, trials)
        res["role"] = cond["role"]
        res["decisive"] = False
        out.append(res)
    # Multiplicity: Holm across the secondary contrasts that produced a p-value.
    tested = [c for c in out if "p_value" in c]
    for c, (adj, rej) in zip(tested, holm([c["p_value"] for c in tested],
                                          rule.get("alpha", 0.05))):
        c["p_holm"], c["holm_significant"] = adj, rej
    return out
