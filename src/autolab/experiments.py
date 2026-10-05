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
import random
import shlex
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

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


def run_trial(entrypoint: str, workdir: Path, out_dir: Path, condition: dict,
              seed: int, required_metrics: list[str], timeout_s: float) -> Trial:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(entrypoint) + [
        "--condition", condition["name"], "--seed", str(seed),
        "--out", str(out_dir), "--params", json.dumps(condition.get("params", {}),
                                                     sort_keys=True),
    ]
    env = {**os.environ, "PYTHONHASHSEED": str(seed), "AUTOLAB_SEED": str(seed)}
    t0 = time.perf_counter()
    error = None
    try:
        proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s, env=env)
        rc, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        rc, stdout, stderr = -1, exc.stdout or "", exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
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
            missing = [m for m in required_metrics if not _finite_number(metrics.get(m))]
            if missing:
                error = f"missing/non-finite metrics: {missing}"
        except FileNotFoundError:
            error = "entrypoint did not write metrics.json"
        except (ValueError, json.JSONDecodeError) as exc:
            error = f"invalid metrics.json: {exc}"
    elif error is None:
        error = f"exit code {rc}"
    return Trial(condition["name"], condition["role"], seed, rc, round(dur, 4),
                 metrics, str(out_dir), error)


def run_protocol(protocol: dict, workdir: Path, out_root: Path,
                 seeds: list[int] | None = None,
                 conditions: list[str] | None = None) -> RunOutput:
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
                                        cond, seed, required, timeout))
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


def bootstrap_mean_diff(t: list[float], c: list[float], n_boot: int, alpha: float,
                        seed: int) -> tuple[float, float, float]:
    rng = random.Random(seed)
    diff = statistics.fmean(t) - statistics.fmean(c)
    boots = []
    for _ in range(n_boot):
        bt = [t[rng.randrange(len(t))] for _ in t]
        bc = [c[rng.randrange(len(c))] for _ in c]
        boots.append(statistics.fmean(bt) - statistics.fmean(bc))
    boots.sort()
    lo = boots[int(math.floor((alpha / 2) * (n_boot - 1)))]
    hi = boots[int(math.ceil((1 - alpha / 2) * (n_boot - 1)))]
    return diff, lo, hi


def paired_values(trials: list[Trial], treatment: str, control: str,
                  metric: str) -> list[tuple[int, float, float]]:
    """(seed, treatment, control) for seeds where BOTH arms produced a valid value."""
    def by_seed(cond):
        return {t.seed: float(t.metrics[metric]) for t in trials
                if t.ok and t.condition == cond and metric in t.metrics}
    tv, cv = by_seed(treatment), by_seed(control)
    return [(s, tv[s], cv[s]) for s in sorted(tv.keys() & cv.keys())]


def bootstrap_paired_diff(diffs: list[float], n_boot: int, alpha: float,
                          seed: int) -> tuple[float, float, float]:
    """Percentile bootstrap CI of the mean of per-seed differences."""
    rng = random.Random(seed)
    mean = statistics.fmean(diffs)
    boots = sorted(statistics.fmean([diffs[rng.randrange(len(diffs))] for _ in diffs])
                   for _ in range(n_boot))
    lo = boots[int(math.floor((alpha / 2) * (n_boot - 1)))]
    hi = boots[int(math.ceil((1 - alpha / 2) * (n_boot - 1)))]
    return mean, lo, hi


def evaluate_decision(rule: dict, trials: list[Trial], seed: int = 0) -> dict:
    """Apply the pre-registered decision rule.

    effect is oriented so that positive == the hypothesised direction.
    * supported:           CI_low > 0 and effect >= min_effect
    * partially_supported: CI_low > 0 but effect < min_effect
    * unsupported:         CI_high < min_effect (a meaningful effect is excluded)
    * inconclusive:        otherwise, or < 2 valid trials in either arm

    ``rule["pairing"] == "paired"`` bootstraps per-seed differences over seeds
    valid in both arms (seed-matched designs); default "unpaired" resamples
    each arm independently.
    """
    alpha = rule.get("alpha", 0.05)
    n_boot = rule.get("n_boot", 5000)
    t = values(trials, rule["treatment"], rule["metric"])
    c = values(trials, rule["control"], rule["metric"])
    base = {"metric": rule["metric"], "treatment": rule["treatment"],
            "control": rule["control"], "n_treatment": len(t), "n_control": len(c),
            "min_effect": rule["min_effect"], "alpha": alpha, "direction": rule["direction"]}
    pairing = rule.get("pairing", "unpaired")
    base["pairing"] = pairing
    if pairing == "paired":
        pairs = paired_values(trials, rule["treatment"], rule["control"], rule["metric"])
        base["n_pairs"] = len(pairs)
        if len(pairs) < 2:
            return {**base, "outcome": Outcome.INCONCLUSIVE.value,
                    "reason": "fewer than 2 seeds valid in both arms"}
        diff, lo, hi = bootstrap_paired_diff([a - b for _, a, b in pairs], n_boot, alpha, seed)
    else:
        if len(t) < 2 or len(c) < 2:
            return {**base, "outcome": Outcome.INCONCLUSIVE.value,
                    "reason": "fewer than 2 valid trials in an arm"}
        diff, lo, hi = bootstrap_mean_diff(t, c, n_boot, alpha, seed)
    if rule["direction"] == "less":
        diff, lo, hi = -diff, -hi, -lo
    if lo > 0 and diff >= rule["min_effect"]:
        outcome = Outcome.SUPPORTED
    elif lo > 0:
        outcome = Outcome.PARTIALLY_SUPPORTED
    elif hi < rule["min_effect"]:
        outcome = Outcome.UNSUPPORTED
    else:
        outcome = Outcome.INCONCLUSIVE
    return {**base, "effect": diff, "ci_low": lo, "ci_high": hi,
            "outcome": outcome.value}


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


def contrasts(protocol: dict, trials: list[Trial], seed: int = 0) -> list[dict]:
    """Secondary (non-decisive) comparisons of every non-control condition vs control."""
    rule = protocol["decision_rule"]
    out = []
    for cond in protocol["conditions"]:
        if cond["name"] == rule["control"] or cond["name"] == rule["treatment"]:
            continue
        r = {**rule, "treatment": cond["name"]}
        res = evaluate_decision(r, trials, seed)
        res["role"] = cond["role"]
        res["decisive"] = False
        out.append(res)
    return out
