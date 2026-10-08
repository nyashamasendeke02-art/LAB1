# Experiment architecture

Status labels: **done** = implemented and tested; **partial** = implemented with a known gap; **gap** = not built. Statements are ENGINEERING_DECISIONs about the code in `src/autolab/` unless labelled otherwise.

## Experiment model

* **Protocol** = pre-registration: kind (exploratory | confirmatory),
  `protected`, entrypoint, conditions (baseline, intervention, ablation,
  null, transfer, robustness), seeds, primary/secondary metrics, decision
  rule (optionally `pairing: paired` for seed-matched designs), budget, and
  machine-checkable `validity_checks` / `success_checks` bound to the
  protocol's own conditions and metrics. The REQUIREMENTS stage states
  validity criteria in prose (conditions don't exist yet); DESIGN translates
  them into checks, which are therefore frozen as part of the pre-registration.
* Frozen before any implementation. Changes go only through
  `autolab halt` + `autolab amend` (human-only): recorded with a justification
  and a new freeze hash, committed to the repo. A confirmatory protocol amended
  after data collection is downgraded to exploratory, and resuming re-enters
  ENGINEERING so the implementation is re-verified.
* **Entrypoint contract:** `<entrypoint> --condition N --seed S --out DIR
  --params JSON` writes `DIR/metrics.json`; `--params` is `fixed_params` merged with the
  condition's `params`. The interpreter is pinned to the
  recorded `sys.executable`; `PYTHONHASHSEED` is set to the seed.
* **Smoke test:** a seed outside the protocol seeds, so confirmatory data is
  never peeked at, and it is not counted as data.
* **Run:** every condition × seed. Raw stdout/stderr/metrics are hashed and
  made read-only. The manifest links protocol version + freeze hash, commit,
  environment snapshot (Python, platform, installed packages), and command.
* **Analysis** (controller, deterministic; Student t / Welch t CIs, >= 3 seeds): the
  pre-registered decision rule gives supported / partially_supported /
  unsupported / inconclusive. Secondary contrasts (ablations, null) are
  reported but are not decisive. Validity checks are evaluated
  mechanically. The scientist interprets (INFERENCE) but cannot change the
  outcome.

### Research domains: AI, LLMs, agents, software and code (D51)

The method is the same in every domain; what changes is the unit of analysis and the
external resources a trial uses.

| Need | Mechanism |
|---|---|
| Benchmarks: replication comes from items, not seeds | `decision_rule.unit = "item"`, frozen `n_items`; the entrypoint also writes `DIR/items.json` (`[{"id", <metrics>}]`). Per-item values are averaged over seeds within an arm and a paired t interval is taken over per-item differences. >= 1 seed; power is counted in items. |
| Instrument must not drop items | automatic validity check `AUTO-ITEM-COVERAGE` |
| Fresh data for confirmation | automatic validity check `AUTO-FRESH-ITEMS`: a confirmatory study cannot reuse items already analysed for the hypothesis (pilot on a dev split, confirm on held-out items) |
| API rate/usage limits, network blips | the entrypoint exits with 75; the trial is re-run from an empty directory with exponential backoff (`limits.max_trial_retries`, `trial_retry_wait_s`), not counted as failed |
| Slow I/O-bound trials | `budget.max_parallel` concurrent trials (results keep their order) |
| Spend | `budget.max_cost_usd` (needs a `cost_usd` metric; no new trial starts once reached); `compute_budget` gate when smoke-test cost x seeds > `limits.max_cost_usd_without_approval` |
| Pinned evaluation data | `protocol.data_paths` (repo-relative) hashed into the manifest; missing data fails the smoke test; trials must not download data or models |
| Transcripts | every file under the trial directory, subfolders included, is hashed and made read-only |
| Models, decoding settings, prompts, judges | frozen in `fixed_params` / condition `params` (see `DOMAIN_GUIDANCE` in `prompts.py`) |

Limits: cost is reported by the experiment code, not measured by the controller; there is no
GPU scheduler; the scientist has no web access, so background sources stay unverified.
