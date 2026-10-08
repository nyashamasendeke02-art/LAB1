"""D55: research <-> engineering feedback loop (master prompt s.12): engineering failure ->
observation -> triage -> research question -> new project, with provenance at every step."""

import pytest

from autolab.coordination import COMPLETE, Coordinator
from autolab.feedback import OBSERVED_FAILURES, open_observations, triage

import scenario
from scenario import make, ok

OBJECTIVE = "Investigate whether treat can produce higher score"


@pytest.fixture
def failed_once(tmp_path):
    """A research project whose first implementation fails the controller's tests."""
    lab, ctl = make(tmp_path, eng__implement=[scenario.implement_failing, scenario.implement])
    pid = ctl.new_project(OBJECTIVE)
    assert ctl.run(pid)[-1].after == "COMPLETE"
    return lab, ctl, pid


def answer_all(verdict_for):
    def h(t):
        return ok({"triage": [
            {"observation": o["id"], "verdict": verdict_for(o), "rationale": "checked the evidence",
             **({"question": f"Why does {o['category']} occur for this design?", "priority": 1}
                if verdict_for(o) == "research_question" else {})}
            for o in t.context["observations"]], "patterns": ["first build forgot the tests"]})
    return h


def test_engineering_failures_become_observations(failed_once):
    lab, ctl, pid = failed_once
    fails = [f for f in lab.store.query("failure") if f.data["category"] in OBSERVED_FAILURES]
    obs = lab.store.query("observation")
    assert fails and len(obs) == len(fails)
    o = obs[0]
    assert o.data["status"] == "open" and o.data["category"] == "tests_failed"
    assert o.data["refs"]["failure"] == fails[0].id and o.data["project"] == pid
    assert o.data["project_objective"] == OBJECTIVE
    assert any(e["type"] == "ObservationCreated" and e["subject"] == o.id
               for e in lab.store.events())
    # stage errors (crashes, outages) are not observations
    assert all(lab.store.get(x.data["refs"]["failure"]).data["category"] != "stage_error"
               for x in obs)


def test_triage_turns_observations_into_research_questions(failed_once, tmp_path):
    lab, ctl, pid = failed_once
    obs = open_observations(lab.store)
    ctl2 = scenario.Controller(lab, scenario.agents(
        sci__observation_triage=answer_all(lambda o: "research_question")))
    out = triage(ctl2, obs, "test")
    assert out["counts"]["research_question"] == len(obs) and len(out["questions"]) == len(obs)
    fq = lab.store.get(out["questions"][0])
    assert fq.data["origin"] == "engineering_failure" and fq.data["status"] == "open"
    o = lab.store.get(fq.data["refs"]["observation"])
    assert o.data["status"] == "question_raised" and o.data["refs"]["future_question"] == fq.id
    assert fq.data["refs"]["failure"] == o.data["refs"]["failure"]
    assert open_observations(lab.store) == []
    assert any(e["type"] == "ResearchQuestionCreated" and e["subject"] == fq.id
               for e in lab.store.events())
    trg = lab.store.get(out["triage"]).data
    assert trg["status"] == "complete" and trg["patterns"] == ["first build forgot the tests"]
    # the question is knowledge: searchable, and a new project can be spawned from it
    g = ctl2.knowledge.graph()
    assert any(n.kind == "observation" for n in g.nodes.values())
    src = f"lab:lab/{fq.id}"
    assert g.resolve_source(src).status == "open"
    new = ctl2.new_project_from_question(src)
    assert lab.store.get(new).data["origin"]["question"] == fq.id
    assert lab.store.get(fq.id).data["status"] == "spawned"


def test_triage_noise_and_fixes_raise_no_questions(failed_once):
    lab, ctl, _ = failed_once
    ctl2 = scenario.Controller(lab, scenario.agents(
        sci__observation_triage=answer_all(lambda o: "engineering_fix")))
    out = triage(ctl2, open_observations(lab.store), "test")
    assert out["questions"] == [] and out["counts"]["engineering_fix"] >= 1
    assert all(o.data["status"] == "engineering_fix" for o in lab.store.query("observation"))


def test_triage_must_answer_every_observation(failed_once):
    lab, ctl, _ = failed_once
    obs = open_observations(lab.store)

    def partial(t):
        return ok({"triage": [{"observation": "OBS-9999", "verdict": "noise",
                               "rationale": "made up"}]})

    def no_question(t):
        return ok({"triage": [{"observation": o["id"], "verdict": "research_question",
                               "rationale": "r"} for o in t.context["observations"]]})

    for handler, msg in ((partial, "unanswered"), (no_question, "need a question")):
        ctl2 = scenario.Controller(lab, scenario.agents(sci__observation_triage=handler))
        with pytest.raises(ValueError, match=msg):
            triage(ctl2, obs, "test")
    assert all(o.data["status"] == "open" for o in lab.store.query("observation"))
    assert triage(ctl, [], "empty")["triage"] is None


def test_programme_review_sees_questions_from_engineering_failures(tmp_path):
    seen = {}

    def review(t):
        seen.update(t.context)
        return ok({"decision": "complete", "assessment": "R1 answered"})

    plan = {"key": "R1", "kind": "research", "objective": OBJECTIVE, "rationale": "core"}
    lab, ctl = make(tmp_path, eng__implement=[scenario.implement_failing, scenario.implement],
                    sci__programme_plan=lambda t: ok({"plan_summary": "one item",
                                                      "items": [plan]}),
                    sci__programme_review=review,
                    sci__observation_triage=answer_all(lambda o: "research_question"))
    co = Coordinator(ctl)
    prg = co.new_programme("Answer R1")
    assert co.run(prg)[-1].after == COMPLETE
    qs = seen["programme_status"]["research_questions_from_engineering"]
    assert qs and qs[0]["observation"].startswith("OBS-")
    triaged = [t for t in lab.store.query("task") if t.data["stage"] == "observation_triage"]
    assert len(triaged) == 1
