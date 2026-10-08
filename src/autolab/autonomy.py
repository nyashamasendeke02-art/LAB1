"""Autonomy levels (D58, master prompt section 21).

Each lab declares the highest level its agents may work at (``[lab] autonomy_level``) and each
project may be given a lower one. Levels map onto mechanisms the controller already enforces:

    0  human performs task          no agent is called for the project
    1  agent suggests               plan-only research: agents propose, nothing is built or run
    2  agent executes with approval every merge and every experiment run needs a human approval
    3  agent executes autonomously  gates as configured in [gates]
    4  agent plans multi-step work  programmes (Research / Engineering Director) are allowed
    5  autonomous R&D loop          gate decisions may be delegated ([gates.delegation])
"""

from __future__ import annotations

LEVELS = {
    0: "Human performs task",
    1: "Agent suggests",
    2: "Agent executes with approval",
    3: "Agent executes autonomously",
    4: "Agent plans and executes multi-step work",
    5: "Research/engineering loop operates autonomously",
}
DEFAULT_LEVEL = 3


class AutonomyError(ValueError):
    pass


def _valid(level) -> int:
    if isinstance(level, bool) or not isinstance(level, int) or level not in LEVELS:
        raise AutonomyError(f"autonomy level must be one of {sorted(LEVELS)}, got {level!r}")
    return level


def lab_level(cfg: dict) -> int:
    return _valid(cfg.get("lab", {}).get("autonomy_level", DEFAULT_LEVEL))


def resolve_level(cfg: dict, requested: int | None) -> int:
    """The level for a new project: the request, capped by the lab's maximum."""
    cap = lab_level(cfg)
    if requested is None:
        return cap
    requested = _valid(requested)
    if requested > cap:
        raise AutonomyError(f"autonomy level {requested} exceeds this lab's maximum {cap} "
                            f"([lab] autonomy_level)")
    return requested


def project_level(cfg: dict, project: dict) -> int:
    """A project's effective level (never above the lab's current maximum)."""
    return min(lab_level(cfg), int(project.get("autonomy_level", lab_level(cfg))))


def delegation(cfg: dict) -> dict:
    """Gate delegation is honoured only at level 5; below it only the human decides."""
    return (cfg.get("gates", {}).get("delegation") or {}) if lab_level(cfg) >= 5 else {}
