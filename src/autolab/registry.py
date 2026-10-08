"""Agent registry and stage allocation (D52).

The lab separates two things:

* **Permissions** belong to the *stage*. Every stage has a fixed role (scientist: read-only,
  engineer: writable worktree, verifier: tests only) and the controller builds the task packet
  (workdir, writable flag, blinding, path policies) from that role. No configuration can widen
  them.
* **Who does the work** is configuration. Any number of named agents -- each a backend
  (claude-cli, codex-cli, gemini-cli, openai-api, ...) plus a model and an optional charter --
  can be allocated to stages. A stage without an allocation runs on the agent named after its
  role (``scientist``, ``engineer``, ``verifier``), so labs without allocations behave as before.

Agents and allocations come from ``lab.toml`` (``[agents.<name>]``, ``[allocation]``) overlaid
by ``agents.toml`` in the lab root, which the web UI and ``autolab agents`` edit. The controller
hashes ``agents.toml`` in its tamper check, so an agent cannot reallocate stages to itself.
"""

from __future__ import annotations

import copy
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .taxonomy import Role

AGENTS_FILE = "agents.toml"
ROLE_AGENTS = tuple(r.value for r in Role)
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


@dataclass(frozen=True)
class Stage:
    name: str
    role: Role
    plane: str          # research | engineering | experimentation | knowledge
    writable: bool      # the task may write files (needs a backend with workspace tools)
    reads_files: bool   # the task gets a read-only checkout to inspect
    label: str


STAGES: tuple[Stage, ...] = (
    Stage("define_problem", Role.SCIENTIST, "research", False, False, "Define the problem"),
    Stage("background_research", Role.SCIENTIST, "research", False, False,
          "Literature and background"),
    Stage("research_question", Role.SCIENTIST, "research", False, False,
          "Research gap and question"),
    Stage("hypothesis", Role.SCIENTIST, "research", False, False, "Hypotheses"),
    Stage("requirements", Role.SCIENTIST, "research", False, False,
          "Validity and engineering requirements"),
    Stage("design", Role.SCIENTIST, "research", False, False, "Experiment design"),
    Stage("scientific_review", Role.SCIENTIST, "research", False, False,
          "Scientific review of the design"),
    Stage("solution_design", Role.ENGINEER, "engineering", False, True,
          "Feasibility and software design"),
    Stage("implement", Role.ENGINEER, "engineering", True, True, "Implementation"),
    Stage("redesign", Role.ENGINEER, "engineering", True, True, "Redesign after failures"),
    Stage("build", Role.ENGINEER, "engineering", True, True, "Engineering build"),
    Stage("rebuild", Role.ENGINEER, "engineering", True, True, "Engineering rebuild"),
    Stage("verify", Role.VERIFIER, "engineering", True, True,
          "Adversarial review and independent tests"),
    Stage("scientific_validation", Role.SCIENTIST, "experimentation", False, True,
          "Pre-run validation of the implementation"),
    Stage("interpret", Role.SCIENTIST, "experimentation", False, False,
          "Interpretation of results"),
    Stage("challenge", Role.VERIFIER, "experimentation", False, True,
          "Adversarial challenge of results"),
    Stage("communicate", Role.SCIENTIST, "knowledge", False, False, "Report"),
    Stage("next_question", Role.SCIENTIST, "research", False, False, "Next research question"),
)
STAGE_BY_NAME = {s.name: s for s in STAGES}

# Backend capabilities (what a backend can do inside a task). Factories live in agents.py.
BACKENDS: dict[str, dict] = {
    "claude-cli": {"label": "Claude Code CLI (claude -p)", "tools": True,
                   "options": ["model", "timeout"]},
    "codex-cli": {"label": "OpenAI Codex CLI (codex exec)", "tools": True,
                  "options": ["model", "timeout"]},
    "gemini-cli": {"label": "Gemini / Antigravity CLI (agy)", "tools": True,
                   "options": ["model", "timeout", "effort"]},
    "openai-api": {"label": "OpenAI Responses API (no file access)", "tools": False,
                   "options": ["model", "api_key_env", "timeout"], "model_required": True},
}
AGENT_KEYS = {"title", "charter", "backend", "model", "timeout", "effort", "api_key_env",
              "backup_backend", "backup_model", "backup_effort", "backup_cooldown_s",
              "stages"}  # "stages": legacy [agents.reviewer] allocation

# The research and engineering organisation from the lab's master prompt, mapped onto the
# stages the controller runs. Applied with `autolab agents preset LAB organisation`.
ORGANISATION = {
    "research_director": ("Research Director", Role.SCIENTIST,
                          "You coordinate the research programme: turn the objective into a "
                          "well-scoped problem, monitor progress across cycles and choose the "
                          "next direction from evidence, not enthusiasm.",
                          ["define_problem", "next_question"]),
    "literature": ("Literature Agent", Role.SCIENTIST,
                   "You survey existing knowledge: methods, claims, limitations and the state of "
                   "the art, with relationships between works. Never invent sources.",
                   ["background_research"]),
    "research_gap": ("Research Gap Agent", Role.SCIENTIST,
                     "You compare existing approaches, find contradictions, limitations and "
                     "unexplored areas, and turn the most valuable gap into one answerable "
                     "question.", ["research_question"]),
    "hypothesis": ("Hypothesis Agent", Role.SCIENTIST,
                   "You formulate falsifiable hypotheses with explicit assumptions and "
                   "measurable predictions, ranked by value and testability.", ["hypothesis"]),
    "requirements": ("Requirements Agent", Role.SCIENTIST,
                     "You turn research intent into validity criteria, functional and "
                     "non-functional requirements and acceptance criteria.", ["requirements"]),
    "experiment_designer": ("Experiment Designer", Role.SCIENTIST,
                            "You design controlled experiments: baselines, controls, ablations, "
                            "metrics, datasets and variables, as an executable protocol.",
                            ["design"]),
    "scientific_critic": ("Scientific Critic", Role.SCIENTIST,
                          "You challenge assumptions, find methodological weaknesses, "
                          "confounds and unsupported claims, and say which extra experiment "
                          "would settle the question.",
                          ["scientific_review", "scientific_validation"]),
    "research_synthesizer": ("Research Synthesizer", Role.SCIENTIST,
                             "You combine results into knowledge: interpret within the "
                             "pre-registered outcome, note emerging patterns and report "
                             "honestly with evidence labels.", ["interpret", "communicate"]),
    "systems_architect": ("Systems Architect", Role.ENGINEER,
                          "You assess feasibility and design the software: components, "
                          "interfaces, data flows and risks, before any code is written.",
                          ["solution_design"]),
    "engineer": ("Implementation Engineer", Role.ENGINEER, "",
                 ["implement", "redesign", "build", "rebuild"]),
    "verifier": ("Verification Engineer", Role.VERIFIER, "", ["verify", "challenge"]),
}


class RegistryError(ValueError):
    pass


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON string escapes are valid TOML
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in v) + "]"
    raise RegistryError(f"cannot store {type(v).__name__} in {AGENTS_FILE}")


def dump_toml(agents: dict, allocation: dict) -> str:
    out = ["# Agents and stage allocation for this lab (autolab agents / web UI).",
           "# Permissions are fixed by each stage's role; this file only chooses who works.", ""]
    for name in sorted(agents):
        out.append(f"[agents.{name}]")
        out += [f"{k} = {_toml_value(v)}" for k, v in sorted(agents[name].items())
                if v not in (None, "")]
        out.append("")
    out.append("[allocation]")
    out += [f"{k} = {_toml_value(v)}" for k, v in sorted(allocation.items())]
    return "\n".join(out) + "\n"


class Registry:
    """Effective agents and allocation for one lab."""

    def __init__(self, base_cfg: dict, lab_root: str | Path | None = None):
        self.base_agents = copy.deepcopy(base_cfg.get("agents", {}))
        self.base_allocation = dict(base_cfg.get("allocation", {}) or {})
        self.path = Path(lab_root) / AGENTS_FILE if lab_root else None
        self._mtime: int | None = -1
        self.agents: dict[str, dict] = {}
        self.allocation: dict[str, str] = {}
        self.reload()

    # ------------------------------------------------------------------ loading
    def _overlay(self) -> dict:
        if self.path and self.path.exists():
            return tomllib.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def reload(self, force: bool = False) -> bool:
        """Re-read agents.toml if it changed. Returns True when the registry changed."""
        mtime = self.path.stat().st_mtime_ns if self.path and self.path.exists() else None
        if not force and mtime == self._mtime:
            return False
        over = self._overlay()
        agents = copy.deepcopy(self.base_agents)
        for name, spec in (over.get("agents") or {}).items():
            agents[name] = spec  # an overlay entry replaces the whole agent
        allocation = dict(self.base_allocation)
        rv = agents.get("reviewer") or {}
        if rv.get("backend"):  # legacy [agents.reviewer] stages = [...]
            for st in rv.get("stages", ["scientific_review"]):
                allocation.setdefault(st, "reviewer")
        allocation.update(over.get("allocation") or {})
        self.agents = {n: s for n, s in agents.items() if isinstance(s, dict)
                       and (s.get("backend") or n in ROLE_AGENTS)}
        self.allocation = {k: v for k, v in allocation.items() if v}
        self._mtime = mtime
        return True

    # ------------------------------------------------------------------ queries
    def resolve(self, stage: str, role: Role) -> str:
        """Name of the agent that performs ``stage`` (falls back to the role's agent)."""
        name = self.allocation.get(stage)
        if name and name in self.agents:
            return name
        return role.value

    def spec(self, name: str) -> dict:
        return self.agents.get(name, {})

    def problems(self) -> list[str]:
        """Configuration errors (empty when every allocation is usable)."""
        errs = []
        for stage, name in self.allocation.items():
            st = STAGE_BY_NAME.get(stage)
            if st is None:
                errs.append(f"allocation: unknown stage {stage!r}")
                continue
            if name not in self.agents:
                errs.append(f"allocation: {stage} -> unknown agent {name!r}")
                continue
            errs += [f"{stage}: {e}" for e in stage_fit(st, self.agents[name])]
        for name, spec in self.agents.items():
            if spec.get("backend") and spec["backend"] not in BACKENDS:
                errs.append(f"agent {name}: unknown backend {spec['backend']!r}")
        return errs

    def describe(self) -> dict:
        return {"agents": self.agents, "allocation": self.allocation,
                "effective": {s.name: self.resolve(s.name, s.role) for s in STAGES},
                "problems": self.problems(), "file": str(self.path) if self.path else None}

    # ------------------------------------------------------------------ editing
    def _write(self, agents_over: dict, allocation_over: dict) -> None:
        if self.path is None:
            raise RegistryError("registry has no lab root to write to")
        trial = Registry({"agents": self.base_agents, "allocation": self.base_allocation})
        trial.agents = {**{n: s for n, s in self.agents.items()}, **agents_over}
        merged_alloc = {**self.allocation, **allocation_over}
        trial.allocation = {k: v for k, v in merged_alloc.items() if v}
        errs = trial.problems()
        if errs:
            raise RegistryError("; ".join(errs))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(dump_toml(agents_over, {k: v for k, v in allocation_over.items()}),
                       encoding="utf-8", newline="\n")
        tmp.replace(self.path)
        self.reload(force=True)

    def overlay(self) -> tuple[dict, dict]:
        over = self._overlay()
        return dict(over.get("agents") or {}), dict(over.get("allocation") or {})

    def upsert(self, name: str, spec: dict) -> None:
        validate_agent(name, spec)
        agents, alloc = self.overlay()
        agents[name] = {k: v for k, v in spec.items() if v not in (None, "")}
        self._write(agents, alloc)

    def remove(self, name: str) -> None:
        if name in ROLE_AGENTS:
            raise RegistryError(f"{name!r} is a role's default agent and cannot be removed")
        agents, alloc = self.overlay()
        if name in self.base_agents:
            raise RegistryError(f"{name!r} is defined in lab.toml; edit it there")
        if name not in agents:
            raise RegistryError(f"no agent {name!r}")
        used = sorted(s for s, n in self.allocation.items() if n == name)
        if used:
            raise RegistryError(f"{name!r} is allocated to {used}; reallocate first")
        del agents[name]
        self._write(agents, alloc)

    def allocate(self, changes: dict) -> None:
        """``{stage: agent name | ""}``; an empty name returns the stage to its role agent."""
        agents, alloc = self.overlay()
        for stage, name in changes.items():
            if stage not in STAGE_BY_NAME:
                raise RegistryError(f"unknown stage {stage!r}")
            if not isinstance(name, str):
                raise RegistryError(f"allocation for {stage} must be an agent name")
            alloc[stage] = name  # "" overrides a lab.toml allocation back to the role agent
        self._write(agents, alloc)

    def apply_preset(self, preset: str = "organisation") -> list[str]:
        """Create the master-prompt organisation, every agent inheriting the backend and model
        of its role's current agent (change them afterwards per agent)."""
        if preset != "organisation":
            raise RegistryError(f"unknown preset {preset!r} (available: organisation)")
        agents, alloc = self.overlay()
        created = []
        for name, (title, role, charter, stages) in ORGANISATION.items():
            base = {k: v for k, v in self.spec(role.value).items() if k != "stages"}
            spec = {**base, "title": title}
            if charter:
                spec["charter"] = charter
            if name in ROLE_AGENTS:
                spec = {**self.spec(name), **{k: v for k, v in spec.items()
                                              if k in ("title", "charter")}}
            agents[name] = spec
            for st in stages:
                alloc[st] = name
            created.append(name)
        self._write(agents, alloc)
        return created


def validate_agent(name: str, spec: dict) -> None:
    if not NAME.match(name or ""):
        raise RegistryError("agent names are lowercase letters, digits, '_' or '-' "
                            "(start with a letter, at most 48 characters)")
    if not isinstance(spec, dict):
        raise RegistryError("agent spec must be an object")
    unknown = sorted(set(spec) - AGENT_KEYS)
    if unknown:
        raise RegistryError(f"unknown agent fields {unknown}")
    backend = spec.get("backend")
    if backend not in BACKENDS:
        raise RegistryError(f"backend must be one of {sorted(BACKENDS)}")
    if BACKENDS[backend].get("model_required") and not spec.get("model"):
        raise RegistryError(f"backend {backend} needs a model")
    if spec.get("backup_backend") and spec["backup_backend"] not in BACKENDS:
        raise RegistryError(f"backup_backend must be one of {sorted(BACKENDS)}")
    for key in ("title", "charter", "model", "effort", "api_key_env", "backup_model"):
        if key in spec and not isinstance(spec[key], str):
            raise RegistryError(f"{key} must be text")
    if "charter" in spec and len(spec["charter"]) > 4000:
        raise RegistryError("charter is limited to 4000 characters")
    for key in ("timeout", "backup_cooldown_s"):
        if key in spec and (isinstance(spec[key], bool)
                            or not isinstance(spec[key], (int, float)) or spec[key] <= 0):
            raise RegistryError(f"{key} must be a positive number")


def stage_fit(stage: Stage, spec: dict) -> list[str]:
    """Why an agent cannot perform a stage (empty if it can)."""
    caps = BACKENDS.get(spec.get("backend", ""), {})
    errs = []
    if stage.writable and not caps.get("tools"):
        errs.append(f"backend {spec.get('backend')!r} has no workspace tools and cannot "
                    f"perform a writing stage")
    if stage.writable and spec.get("backup_backend") and \
            not BACKENDS.get(spec["backup_backend"], {}).get("tools"):
        errs.append(f"backup backend {spec['backup_backend']!r} cannot perform a writing stage")
    return errs
