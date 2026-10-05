"""Shared vocabularies: evidence taxonomy, roles, outcomes, experiment kinds.

The evidence taxonomy mirrors the project-wide CLAUDE.md. Labels are never
silently upgraded: :func:`check_label_change` is used whenever a stored claim's
label changes, and the change must carry a justification.
"""

from __future__ import annotations

from enum import Enum


class Evidence(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    SOURCE_CLAIM = "SOURCE_CLAIM"
    HYPOTHESIS = "HYPOTHESIS"
    ENGINEERING_DECISION = "ENGINEERING_DECISION"
    EXPERIMENTAL_RESULT = "EXPERIMENTAL_RESULT"
    INFERENCE = "INFERENCE"
    OPEN_QUESTION = "OPEN_QUESTION"


class Role(str, Enum):
    SCIENTIST = "scientist"  # ChatGPT
    ENGINEER = "engineer"  # Claude
    VERIFIER = "verifier"  # Codex
    CONTROLLER = "controller"
    HUMAN = "human"


class Outcome(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class ExperimentKind(str, Enum):
    EXPLORATORY = "exploratory"
    CONFIRMATORY = "confirmatory"


# Labels that require an attached source / evidence reference.
_NEEDS_SOURCE = {Evidence.ESTABLISHED, Evidence.SOURCE_CLAIM}
_NEEDS_RUN = {Evidence.EXPERIMENTAL_RESULT}


def validate_claim(claim: dict, known_run_ids: set[str] | None = None) -> list[str]:
    """Return a list of problems with a research claim (empty == valid).

    * every claim needs a recognised label and a statement;
    * ESTABLISHED / SOURCE_CLAIM need at least one source;
    * EXPERIMENTAL_RESULT must cite a run id that the controller actually
      recorded -- an agent cannot assert an experimental result that the
      lab never produced.
    """
    errors: list[str] = []
    label = claim.get("type")
    try:
        ev = Evidence(label)
    except ValueError:
        return [f"unknown evidence label {label!r}"]
    if not str(claim.get("statement", "")).strip():
        errors.append("claim has empty statement")
    if ev in _NEEDS_SOURCE and not claim.get("sources"):
        errors.append(f"{ev.value} claim requires 'sources'")
    if ev in _NEEDS_RUN:
        runs = claim.get("run_ids") or []
        if not runs:
            errors.append("EXPERIMENTAL_RESULT claim requires 'run_ids'")
        elif known_run_ids is not None:
            missing = [r for r in runs if r not in known_run_ids]
            if missing:
                errors.append(f"EXPERIMENTAL_RESULT cites unknown runs {missing}")
    return errors


def check_label_change(old: str, new: str, justification: str | None) -> None:
    """Refuse silent re-labelling of a claim."""
    if old != new and not (justification and justification.strip()):
        raise ValueError(
            f"evidence label change {old} -> {new} requires an explicit justification"
        )
