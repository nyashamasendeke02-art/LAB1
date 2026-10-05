"""Create labs/robolab: the AI Robotics Lab instance (docs/PROJECT_PLAN.md, decision D21).

    python scripts/init_robolab.py

The research repo is the robot-brain codebase in the mandate layout; the mandate digest is
the lab charter given to the scientist; safety/contract merges need review; gates are
delegated to claude-code (recorded as such, never as the human).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autolab.controller import DEFAULT_REPO_FILES, Lab  # noqa: E402

PACKAGES = ["contracts", "state", "world_model", "system1", "system2", "awareness", "memory",
            "skills", "learning", "safety", "simulation", "robot"]

CONFIG = """\
# AI Robotics Lab (robolab). See LAB1/docs/PROJECT_PLAN.md and decisions D20-D22.
[lab]
name = "robolab"
charter = "docs/MANDATE.md"

[agents.scientist]
backend = "codex-cli"

[agents.engineer]
backend = "claude-cli"

[agents.verifier]
backend = "codex-cli"

[limits]
max_stage_retries = 2
max_patch_attempts = 3
max_redesigns = 2
max_design_iterations = 4
max_cycles = 1                 # one research cycle per experiment project
max_trials_without_approval = 200
test_timeout_s = 900
max_trial_output_mb = 25

[gates]
confirmatory_protocol_freeze = true
merge_to_main = false
compute_budget = true
review_paths = [
  {pattern = "src/safety/*", gate = "safety"},
  {pattern = "src/contracts/*", gate = "contracts"},
]

# D21: the human delegated gate decisions to Claude Code; they are recorded as
# decided_by = "claude-code", delegated_by = "human".
[gates.delegation]
delegate = "claude-code"
gates = ["*"]

[engineering]
test_command = "python -m pytest -q -p no:cacheprovider"
protected_paths = ["protocols/*", "tests/verification/*", "docs/MANDATE.md"]
verifier_allowed_paths = ["tests/verification/*"]
"""

AGENTS = DEFAULT_REPO_FILES["AGENTS.md"] + """
## AI Robotics Lab rules (docs/MANDATE.md is the mandate)

- Layout: `src/<package>` for contracts, state, world_model, system1, system2, awareness,
  memory, skills, learning, safety, simulation, robot; `tests/`; `experiments/` (entrypoints);
  `configs/`. Import packages by name (`from contracts import ...`); `src` is on sys.path.
- Order of work: contract -> tests -> implementation -> integration. No undocumented
  contracts; schema changes bump the schema version.
- Every actuator command passes the Safety Kernel. Never weaken a safety limit, a test or a
  metric to make something pass.
- Pure Python + NumPy. Every random draw uses an explicitly passed numpy Generator (no
  global RNG). Simulation and evaluation are deterministic given the seed.
- Experiences/telemetry are immutable once written; never silently drop data.
- Do not edit docs/MANDATE.md (controller-owned).
"""

CONFTEST = """\
# Make the src-layout packages importable in tests (the controller's hermetic verification
# run puts src/ on sys.path itself).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
"""

README = """\
# robolab: AI Robotics Lab research code

Modular robot brain under the AI Robotics Lab mandate (docs/MANDATE.md): World Model,
System 1, System 2, Awareness Harness, memory/skills, continual learning, and a
deterministic Safety Kernel, all in simulation first.

`main` changes only through autolab controller merges (engineering track for gate work,
research track for experiments). Every component is earned by an experiment against its
ablation.
"""


def main() -> int:
    target = ROOT / "labs" / "robolab"
    files = {
        "README.md": README,
        "AGENTS.md": AGENTS,
        "conftest.py": CONFTEST,
        "docs/MANDATE.md": (ROOT / "docs" / "MANDATE.md").read_text(encoding="utf-8"),
        "experiments/README.md": "Experiment entrypoints (one per frozen protocol).\n",
        "configs/README.md": "Versioned configuration files.\n",
        "tests/__init__.py": "",
        # L9: checked against the interpreter before any data is collected.
        "requirements.lock": "numpy==2.5.3\npytest==9.1.1\n",
    }
    for pkg in PACKAGES:
        files[f"src/{pkg}/__init__.py"] = f'"""{pkg} (see docs/MANDATE.md)."""\n'
    lab = Lab.init(target, config_text=CONFIG, repo_files=files)
    print(f"robolab initialised at {lab.root} (main {lab.repo.rev('main')[:10]})")
    lab.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
