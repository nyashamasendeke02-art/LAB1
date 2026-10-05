"""Research and engineering state machines.

The two machines are deliberately separate: "the software works" (engineering
state MERGED) says nothing about "the hypothesis holds" (research outcome).
Transitions are whitelisted; anything else raises :class:`IllegalTransition`.
"""

from __future__ import annotations

from enum import Enum


class IllegalTransition(Exception):
    pass


class ResearchState(str, Enum):
    DEFINE_PROBLEM = "DEFINE_PROBLEM"
    BACKGROUND_RESEARCH = "BACKGROUND_RESEARCH"
    RESEARCH_QUESTION = "RESEARCH_QUESTION"
    HYPOTHESIS = "HYPOTHESIS"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"  # Brainstorm, Evaluate and Choose Solution
    SCIENTIFIC_REVIEW = "SCIENTIFIC_REVIEW"
    PROTOCOL_FREEZE = "PROTOCOL_FREEZE"
    ENGINEERING = "ENGINEERING"  # delegates to EngineeringState machine
    SCIENTIFIC_VALIDATION = "SCIENTIFIC_VALIDATION"
    RUN_EXPERIMENT = "RUN_EXPERIMENT"
    ANALYZE = "ANALYZE"  # collect data + analyse
    CHALLENGE = "CHALLENGE"
    EVALUATE = "EVALUATE"  # meets requirements?
    COMMUNICATE = "COMMUNICATE"
    NEXT_QUESTION = "NEXT_QUESTION"
    COMPLETE = "COMPLETE"
    HALTED = "HALTED"  # needs human intervention


R = ResearchState
RESEARCH_TRANSITIONS: dict[ResearchState, set[ResearchState]] = {
    R.DEFINE_PROBLEM: {R.BACKGROUND_RESEARCH},
    R.BACKGROUND_RESEARCH: {R.RESEARCH_QUESTION, R.DEFINE_PROBLEM},
    R.RESEARCH_QUESTION: {R.HYPOTHESIS, R.BACKGROUND_RESEARCH},
    R.HYPOTHESIS: {R.REQUIREMENTS, R.RESEARCH_QUESTION},
    R.REQUIREMENTS: {R.DESIGN, R.HYPOTHESIS},
    R.DESIGN: {R.SCIENTIFIC_REVIEW, R.REQUIREMENTS},
    R.SCIENTIFIC_REVIEW: {R.PROTOCOL_FREEZE, R.DESIGN},
    R.PROTOCOL_FREEZE: {R.ENGINEERING, R.DESIGN},
    R.ENGINEERING: {R.SCIENTIFIC_VALIDATION, R.DESIGN},
    R.SCIENTIFIC_VALIDATION: {R.RUN_EXPERIMENT, R.ENGINEERING, R.DESIGN},
    R.RUN_EXPERIMENT: {R.ANALYZE, R.DESIGN},
    R.ANALYZE: {R.CHALLENGE},
    R.CHALLENGE: {R.EVALUATE},
    R.EVALUATE: {R.COMMUNICATE, R.DESIGN},
    R.COMMUNICATE: {R.NEXT_QUESTION},
    R.NEXT_QUESTION: {R.RESEARCH_QUESTION, R.DEFINE_PROBLEM, R.COMPLETE},
    R.COMPLETE: set(),
    R.HALTED: set(),  # leaving HALTED is a human action (resume), see Controller
}
# Any non-terminal state may halt.
for _s in list(RESEARCH_TRANSITIONS):
    if _s not in (R.COMPLETE, R.HALTED):
        RESEARCH_TRANSITIONS[_s].add(R.HALTED)


class EngineeringState(str, Enum):
    SPEC = "SPEC"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    ADVERSARIAL_REVIEW = "ADVERSARIAL_REVIEW"
    REDESIGN = "REDESIGN"
    MERGE = "MERGE"
    MERGED = "MERGED"
    ESCALATED = "ESCALATED"  # approach inadequate -> research DESIGN


E = EngineeringState
ENGINEERING_TRANSITIONS: dict[EngineeringState, set[EngineeringState]] = {
    E.SPEC: {E.IMPLEMENTING},
    E.IMPLEMENTING: {E.TESTING, E.IMPLEMENTING, E.REDESIGN, E.ESCALATED},
    E.TESTING: {E.ADVERSARIAL_REVIEW, E.IMPLEMENTING, E.REDESIGN, E.ESCALATED},
    E.ADVERSARIAL_REVIEW: {E.MERGE, E.IMPLEMENTING, E.REDESIGN, E.ESCALATED},
    E.REDESIGN: {E.IMPLEMENTING, E.ESCALATED},
    E.MERGE: {E.MERGED, E.IMPLEMENTING, E.REDESIGN, E.ESCALATED},
    E.MERGED: set(),
    E.ESCALATED: set(),
}


def check(machine: dict, current: Enum, target: Enum) -> None:
    if target not in machine.get(current, set()):
        raise IllegalTransition(f"{current.value} -> {target.value} is not allowed")


def check_research(current: ResearchState, target: ResearchState) -> None:
    check(RESEARCH_TRANSITIONS, current, target)


def check_engineering(current: EngineeringState, target: EngineeringState) -> None:
    check(ENGINEERING_TRANSITIONS, current, target)
