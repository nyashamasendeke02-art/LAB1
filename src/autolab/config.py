"""Lab configuration (``lab.toml``)."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

DEFAULT_TOML = """\
# Autonomous Research Lab configuration.
[lab]
name = "autolab"
# Optional: a file in the research repo given to the scientist as the lab charter
# (e.g. "docs/MANDATE.md").
charter = ""

# Role -> backend. backends: "codex-cli", "claude-cli", "gemini-cli", "openai-api".
# Optional backup_backend and backup_model provide automatic fallback when primary limits hit.
# The scientist (ChatGPT) defaults to the Codex CLI in read-only mode, which
# authenticates with your ChatGPT login. Use backend = "openai-api" with
# model = "..." and OPENAI_API_KEY in the environment to call the API instead.
[agents.scientist]
backend = "codex-cli"
# backup_backend = "gemini-cli"
# model = ""

[agents.engineer]
backend = "claude-cli"
# model = ""

[agents.verifier]
backend = "codex-cli"
# model = ""

# Optional independent reviewer: these stages run on this backend instead of the role's
# own (e.g. a different model family from the designing scientist). Empty = disabled.
[agents.reviewer]
backend = ""
stages = ["scientific_review"]

[limits]
max_stage_retries = 2        # transient failures per state before HALTED
max_patch_attempts = 3       # engineering patches before forced REDESIGN
max_redesigns = 2            # redesigns before escalating to research DESIGN
max_design_iterations = 4    # research DESIGN re-entries per cycle before HALTED
max_cycles = 3               # research cycles (question -> report) per project
max_trials_without_approval = 200
test_timeout_s = 900
max_trial_output_mb = 25     # raw output cap per trial (telemetry policy)
require_pilot_for_confirmatory = false   # true: confirmatory only after an exploratory pilot
usage_limit_wait_s = 900     # agent usage/rate limit: wait this long, then retry (no retry counted)
usage_limit_max_wait_s = 43200   # total wait per run before HALTED
network_wait_s = 120        # API/network blip (no response, ECONNRESET, 5xx): wait, retry
network_max_wait_s = 3600   # total network wait per run before HALTED
max_trial_retries = 6       # trial exit 75 (transient: API rate/usage limit, network): re-run
trial_retry_wait_s = 60     # first wait before a re-run; doubles per attempt (max 16x)
max_cost_usd_without_approval = 20.0   # projected spend (smoke cost x seeds) needing the
                                       # compute_budget gate

[gates]
# Human approval is ALWAYS required for protocols marked protected = true.
confirmatory_protocol_freeze = true   # human approves pre-registration
merge_to_main = false                 # human approves every merge
compute_budget = true                 # trials > max_trials_without_approval
# Path-based review gates: merges that change matching files need a decision.
review_paths = []   # e.g. [{pattern = "src/safety/*", gate = "safety"}]

# Gates the human delegates to a named (non-agent) decider. Decisions are recorded
# as decided_by=<delegate>, delegated_by="human".
[gates.delegation]
delegate = ""
gates = []

[engineering]
test_command = "python -m pytest -q"
protected_paths = ["protocols/*", "tests/verification/*"]
verifier_allowed_paths = ["tests/verification/*"]
"""

_DEFAULTS = tomllib.loads(DEFAULT_TOML)


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    cfg = copy.deepcopy(_DEFAULTS)
    if path and Path(path).exists():
        cfg = _merge(cfg, tomllib.loads(Path(path).read_text(encoding="utf-8")))
    if overrides:
        cfg = _merge(cfg, overrides)
    return cfg
