"""K1: knowledge plane -- graph over ledgers, retrieval into research stages, verified lab
sources, and the feedback loop from open questions to new projects (also across labs)."""

import json
import sqlite3

import pytest

from autolab import demo
from autolab.controller import Controller, Lab
from autolab.knowledge import KnowledgeGraph, tokens
from autolab.store import Store

import scenario
from scenario import FAST_CONFIG, agents, make, ok

OBJECTIVE = "Investigate whether treat can produce higher score"


def packets(lab, pid, stage):
    out = []
    for t in lab.store.query("task"):
        if t.data["project"] == pid and t.data["stage"] == stage:
            out.append(json.loads((lab.handoffs / t.id / "task.json").read_text(encoding="utf-8")))
    return out


@pytest.fixture
def finished(tmp_path):
    """A lab whose first project ran to COMPLETE (conclusion + open questions)."""
    lab, ctl = make(tmp_path)
    pid = ctl.new_project(OBJECTIVE)
    assert ctl.run(pid)[-1].after == "COMPLETE"
    return lab, ctl, pid


def test_tokens_keep_compounds_and_parts():
    assert tokens("Heavy-ball beats G1-6 in the test") == [
        "heavy-ball", "heavy", "ball", "beats", "g1-6", "g1", "test"]


def test_readonly_store_refuses_writes(finished):
    lab, _, _ = finished
    ro = Store.open_readonly(lab.state_dir / "lab.db")
    assert ro.query("conclusion")
    with pytest.raises(sqlite3.OperationalError):
        ro.create("note", {"x": 1}, prefix="N")
    with pytest.raises(FileNotFoundError):
        Store.open_readonly(lab.state_dir / "missing.db")


def test_graph_nodes_edges_and_search(finished):
    lab, _, pid = finished
    g = KnowledgeGraph({"lab": lab.store})
    con = lab.store.query("conclusion")[0]
    node = g.nodes[f"lab:{con.id}"]
    assert node.kind == "conclusion" and node.status == "supported"
    assert "tested treat vs base on score" in node.text
    out = set(g.neighbours(node.id)["out"])  # typed relations (D59)
    con_refs = lab.store.get(con.id).data["refs"]
    assert ("supports", f"lab:{con_refs['hypothesis']}") in out
    assert ("derived_from", f"lab:{con_refs['result']}") in out
    assert ("derived_from", f"lab:{con_refs['protocol']}") in out
    assert all(n.status != "stage_error" for n in g.nodes.values())  # noise not indexed
    hits = g.search("treat score", k=50)
    assert hits and any(n.kind == "conclusion" for _, n in hits)
    from autolab.knowledge import INDEXED_KINDS
    # every record belongs to the one project; derived entities (metric:score, agents) do not
    assert g.search("treat score", kinds=INDEXED_KINDS, exclude_project=("lab", pid)) == []
    assert {n.entity for _, n in g.search("treat score", exclude_project=("lab", pid))} <= {
        "Metric", "Agent", "Model", "Dataset", "Paper", "CodeArtifact", "Architecture"}
    assert g.resolve_source(f"lab:lab/{con.id}") is node
    assert g.resolve_source("lab:lab/CON-9999") is None
    assert [n.kind for n in g.open_questions()] == ["future_question"] * len(g.open_questions())


def test_second_project_receives_prior_knowledge_but_engineers_do_not(finished):
    lab, ctl, first = finished
    second = ctl.new_project("Investigate whether a larger treat effect raises the score further")
    assert ctl.run(second)[-1].after == "COMPLETE"
    con = lab.store.query("conclusion", project=first)[0]
    # the knowledge stages that occur in a research project (programme and triage stages
    # are tested in test_coordination.py / test_feedback.py)
    project_stages = [s for s in Controller.KNOWLEDGE_STAGES
                      if not s.startswith("programme_") and s != "observation_triage"]
    assert project_stages == ["define_problem", "background_research", "research_question",
                              "hypothesis", "design"]
    for stage in project_stages:
        pk = packets(lab, second, stage)
        assert pk, stage
        items = pk[0]["context"]["lab_knowledge"]["items"]
        assert all(i["project"] != second for i in items)
        assert any(i["source"] == f"lab:lab/{con.id}" for i in items), stage
    for stage in ("solution_design", "implement", "verify", "requirements", "interpret"):
        for pk in packets(lab, second, stage):
            assert "lab_knowledge" not in pk["context"], stage
    # the first project had nothing earlier to learn from
    assert all("lab_knowledge" not in pk["context"]
               for pk in packets(lab, first, "define_problem"))


def test_claims_citing_lab_records_are_verified(finished):
    lab, ctl, first = finished
    con = lab.store.query("conclusion", project=first)[0]

    def background(t):
        return ok({"findings": [
            {"type": "SOURCE_CLAIM", "statement": "treat beat base earlier",
             "sources": [f"lab:lab/{con.id}"]},
            {"type": "SOURCE_CLAIM", "statement": "an invented lab record",
             "sources": ["lab:lab/CON-0999"]},
            {"type": "SOURCE_CLAIM", "statement": "an external paper",
             "sources": ["https://example.org/paper"]}]})

    ctl2 = Controller(lab, agents(sci__background_research=background))
    second = ctl2.new_project("Investigate whether treat helps again")
    ctl2.run(second)
    claims = {c.data["statement"]: c.data for c in lab.store.query("claim", project=second)}
    assert claims["treat beat base earlier"]["sources_verified"] is True
    assert claims["treat beat base earlier"]["verification"] == "lab-ledger"
    assert claims["an invented lab record"]["sources_verified"] is False
    assert claims["an external paper"]["sources_verified"] is False


def test_spawn_project_from_open_question(finished):
    lab, ctl, first = finished
    fq = ctl.knowledge.graph().open_questions()[0]
    new = ctl.new_project_from_question(fq.brief()["source"])
    proj = lab.store.get(new).data
    assert proj["objective"] == fq.data["question"] and proj["state"] == "DEFINE_PROBLEM"
    assert proj["origin"]["question"] == fq.record_id and proj["origin"]["project"] == first
    rec = lab.store.get(fq.record_id).data
    assert rec["status"] == "spawned" and rec["refs"]["spawned_project"] == new
    with pytest.raises(ValueError, match="not open"):
        ctl.new_project_from_question(fq.brief()["source"])
    con = lab.store.query("conclusion")[0]
    with pytest.raises(ValueError, match="not a future question"):
        ctl.new_project_from_question(f"lab:lab/{con.id}")


def test_knowledge_flows_across_labs_read_only(finished, tmp_path):
    lab, _, first = finished
    head = lab.store.head()
    config = FAST_CONFIG + '\n[knowledge]\ninclude_labs = ["../lab"]\ncontext_items = 4\n'
    other = Lab.init(tmp_path / "other", config_text=config)
    ctl = Controller(other, agents())
    assert ctl.knowledge.problems == []
    assert ctl.knowledge.graph().stats()["labs"] == ["lab", "other"]
    pid = ctl.new_project(OBJECTIVE)
    ctl.run(pid)
    items = packets(other, pid, "define_problem")[0]["context"]["lab_knowledge"]["items"]
    assert any(i["source"].startswith("lab:lab/CON-") for i in items)
    fq = next(n for n in ctl.knowledge.graph().open_questions() if n.lab == "lab")
    spawned = ctl.new_project_from_question(fq.brief()["source"])
    assert other.store.get(spawned).data["origin"]["lab"] == "lab"
    assert Store.open_readonly(lab.state_dir / "lab.db").head() == head  # untouched
    assert lab.store.get(fq.record_id).data["status"] == "open"


def test_missing_included_lab_is_reported_not_fatal(tmp_path):
    config = FAST_CONFIG + '\n[knowledge]\ninclude_labs = ["../nowhere"]\n'
    lab = Lab.init(tmp_path / "lab", config_text=config)
    ctl = Controller(lab, agents())
    assert ctl.knowledge.problems and "nowhere" in ctl.knowledge.problems[0]
    assert ctl.knowledge.graph().stats()["labs"] == ["lab"]


def test_knowledge_can_be_disabled(tmp_path):
    lab, ctl = make(tmp_path, config=FAST_CONFIG + "\n[knowledge]\nenabled = false\n")
    first = ctl.new_project(OBJECTIVE)
    ctl.run(first)
    second = ctl.new_project(OBJECTIVE)
    ctl.run(second)
    assert all("lab_knowledge" not in pk["context"]
               for pk in packets(lab, second, "define_problem"))


def test_entity_types_and_typed_relations(finished):
    """Master prompt s.8: entities and named relationships, derived from the records."""
    lab, _, pid = finished
    g = KnowledgeGraph({"lab": lab.store})
    st = g.stats()
    for entity in ("ResearchQuestion", "Hypothesis", "Claim", "Method", "Experiment",
                   "ExperimentRun", "Result", "Requirement", "Metric", "Agent", "Model",
                   "CodeArtifact"):
        assert st["by_entity"].get(entity), entity
    con = lab.store.query("conclusion")[0]
    hyp = con.data["refs"]["hypothesis"]
    assert (f"lab:{con.id}", "supports", f"lab:{hyp}") in g.edges
    fq = lab.store.query("future_question")[0]
    assert (f"lab:{con.id}", "motivates", f"lab:{fq.id}") in g.edges
    prot, run = con.data["refs"]["protocol"], con.data["refs"]["run"]
    assert (f"lab:{prot}", "tested_by", f"lab:{run}") in g.edges
    assert (f"lab:{prot}", "uses", "lab:metric:score") in g.edges
    assert ("lab:agent:scientist", "uses", "lab:model:s") in g.edges
    assert any(s == "lab:agent:scientist" and r == "produces" for s, r, _ in g.edges)
    assert set(st["by_relation"]) <= set(__import__("autolab.knowledge",
                                                     fromlist=["RELATIONS"]).RELATIONS)


def test_unsupported_conclusion_contradicts_its_hypothesis(tmp_path):
    lab, ctl = make(tmp_path, sci__design=scenario.design(effect=0.0))
    pid = ctl.new_project(OBJECTIVE)
    ctl.run(pid)
    con = lab.store.query("conclusion")[0]
    assert con.data["outcome"] == "unsupported"
    g = KnowledgeGraph({"lab": lab.store})
    assert (f"lab:{con.id}", "contradicts", f"lab:{con.data['refs']['hypothesis']}") in g.edges
