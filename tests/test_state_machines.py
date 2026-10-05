import pytest

from autolab.state_machines import (ENGINEERING_TRANSITIONS, RESEARCH_TRANSITIONS,
                                    EngineeringState as E, IllegalTransition,
                                    ResearchState as R, check_engineering, check_research)


def test_happy_path_is_legal():
    path = [R.DEFINE_PROBLEM, R.BACKGROUND_RESEARCH, R.RESEARCH_QUESTION, R.HYPOTHESIS,
            R.REQUIREMENTS, R.DESIGN, R.SCIENTIFIC_REVIEW, R.PROTOCOL_FREEZE, R.ENGINEERING,
            R.SCIENTIFIC_VALIDATION, R.RUN_EXPERIMENT, R.ANALYZE, R.CHALLENGE, R.EVALUATE,
            R.COMMUNICATE, R.NEXT_QUESTION, R.RESEARCH_QUESTION]
    for a, b in zip(path, path[1:]):
        check_research(a, b)


@pytest.mark.parametrize("a,b", [
    (R.DESIGN, R.RUN_EXPERIMENT),          # cannot skip review/freeze/engineering
    (R.ENGINEERING, R.RUN_EXPERIMENT),     # cannot skip scientific validation
    (R.ANALYZE, R.COMMUNICATE),            # cannot skip challenge/evaluate
    (R.RUN_EXPERIMENT, R.ENGINEERING),     # protocol/code fixed once data collected
    (R.COMPLETE, R.DESIGN),
    (R.HALTED, R.DESIGN),                  # only a human resume leaves HALTED
])
def test_illegal_research_transitions(a, b):
    with pytest.raises(IllegalTransition):
        check_research(a, b)


def test_failure_loops_back_to_design():
    check_research(R.EVALUATE, R.DESIGN)
    check_research(R.SCIENTIFIC_REVIEW, R.DESIGN)
    check_research(R.ENGINEERING, R.DESIGN)


def test_every_nonterminal_can_halt():
    for s, targets in RESEARCH_TRANSITIONS.items():
        if s not in (R.COMPLETE, R.HALTED):
            assert R.HALTED in targets


def test_engineering_machine():
    for a, b in [(E.SPEC, E.IMPLEMENTING), (E.IMPLEMENTING, E.TESTING),
                 (E.TESTING, E.ADVERSARIAL_REVIEW), (E.ADVERSARIAL_REVIEW, E.MERGE),
                 (E.MERGE, E.MERGED), (E.TESTING, E.REDESIGN), (E.REDESIGN, E.IMPLEMENTING),
                 (E.ADVERSARIAL_REVIEW, E.ESCALATED)]:
        check_engineering(a, b)
    with pytest.raises(IllegalTransition):
        check_engineering(E.IMPLEMENTING, E.MERGE)  # no merge without test + review
    with pytest.raises(IllegalTransition):
        check_engineering(E.TESTING, E.MERGE)
    assert ENGINEERING_TRANSITIONS[E.MERGED] == set()
