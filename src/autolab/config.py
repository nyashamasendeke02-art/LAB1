"""Lab configuration (``lab.toml``)."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

DEFAULT_TOML = """\
# Autonomous Research Lab configuration.
[lab]
name = "autolab"

# Role -> backend. backends: "codex-cli", "claude-cli", "openai-api".
# The scientist (ChatGPT) defaults to the Codex CLI in read-only mode, which
# authenticates with your ChatGPT login. Use backend = "openai-api" with
# model = "..." and OPENAI_API_KEY in the environment to call the API instead.
[agents.scientist]
backend = "codex-cli"
# model = ""

[agents.engineer]
backend = "claude-cli"
# model = ""

[agents.verifier]
backend = "codex-cli"
# model = ""

[limits]
max_stage_retries = 2        # transient failures per state before HALTED
max_patch_attempts = 3       # engineering patches before forced REDESIGN
max_redesigns = 2            # redesigns before escalating to research DESIGN
max_design_iterations = 4    # research DESIGN re-entries per cycle before HALTED
max_cycles = 3               # research cycles (question -> report) per project
max_trials_without_approval = 200
test_timeout_s = 900

[gates]
# Human approval is ALWAYS required for protocols marked protected = true.
confirmatory_protocol_freeze = true   # human approves pre-registration
merge_to_main = false                 # human approves every merge
compute_budget = true                 # trials > max_trials_without_approval

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
