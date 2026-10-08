"""Research <-> engineering feedback loop (D55, master prompt section 12).

    engineering / experiment failure  ->  observation (automatic, controller)
    open observations                 ->  observation_triage (a research agent)
                                          research_question | engineering_fix | noise
    research_question                 ->  future_question (origin: engineering_failure)
                                          -> knowledge plane open questions -> new projects /
                                             programme reviews

The controller records an ``observation`` for every failure in OBSERVED_FAILURES (failed tests,
failed adversarial reviews, escalations, failed smoke tests, rejected validations, failed or
invalid experiment runs, infeasible designs). Triage is an ordinary audited stage call on a
``triage`` record; the controller checks that every observation in the batch is answered and
creates the questions itself, with provenance back to the observation and the failure.
"""

from __future__ import annotations

from .store import Record, Store
from .taxonomy import Role

OBSERVED_FAILURES = frozenset({
    "tests_failed", "review_failed", "approach_inadequate", "smoke_test_failed",
    "validation_rejected", "run_failed", "invalid_experiment", "design_infeasible"})
VERDICTS = ("research_question", "engineering_fix", "noise")
STATUS_BY_VERDICT = {"research_question": "question_raised", "engineering_fix": "engineering_fix",
                     "noise": "dismissed"}


def record_observation(store: Store, failure: Record, project: dict) -> Record:
    obs = store.create("observation", {
        "kind": "engineering" if project.get("kind") == "engineering"
                or failure.data["state"] == "ENGINEERING" else "experiment",
        "category": failure.data["category"], "summary": failure.data["summary"],
        "project": failure.data["project"], "project_objective": project.get("objective", "")[:600],
        "specialty": project.get("specialty"), "programme": project.get("programme"),
        "state": failure.data["state"], "status": "open",
        "refs": {"failure": failure.id, **{k: v for k, v in failure.data.get("refs", {}).items()
                                           if isinstance(v, str)}}},
        prefix="OBS", reason=f"observation from failure {failure.id}")
    store.append_event("controller", "ObservationCreated", obs.id,
                       {"failure": failure.id, "category": failure.data["category"],
                        "project": failure.data["project"]})
    return obs


def open_observations(store: Store, projects: set[str] | None = None) -> list[Record]:
    return [o for o in store.query("observation", status="open")
            if projects is None or o.data.get("project") in projects]


def triage(ctl, observations: list[Record], scope: str, max_batch: int = 30) -> dict:
    """Have a research agent triage ``observations``; returns {triage, questions, counts}."""
    batch = observations[:max_batch]
    if not batch:
        return {"triage": None, "questions": [], "counts": {}}
    store = ctl.store
    trg = store.create("triage", {
        "kind": "triage", "objective": f"Triage {len(batch)} engineering/experiment observations "
                                       f"({scope}) into research questions",
        "cycle": 1, "scope": scope, "observations": [o.id for o in batch], "refs": {}},
        prefix="TRG", reason=f"observation triage: {scope}")
    obs_ctx = []
    for o in batch:
        fail = store.get(o.data["refs"]["failure"])
        obs_ctx.append({"id": o.id, "kind": o.data["kind"], "category": o.data["category"],
                        "project": o.data["project"], "project_objective": o.data["project_objective"],
                        "specialty": o.data.get("specialty"), "state": o.data["state"],
                        "summary": o.data["summary"],
                        "evidence": str((fail.data.get("details") or {}).get("feedback", ""))[-1500:]})
    payload, tid = ctl._call(trg.id, Role.SCIENTIST, "observation_triage",
                             {"observations": obs_ctx})
    ids = {o.id for o in batch}
    answered = {t["observation"] for t in payload["triage"]}
    errs = []
    if answered - ids:
        errs.append(f"triage answers unknown observations {sorted(answered - ids)}")
    if ids - answered:
        errs.append(f"triage leaves observations unanswered {sorted(ids - answered)}")
    missing_q = [t["observation"] for t in payload["triage"]
                 if t["verdict"] == "research_question" and not (t.get("question") or "").strip()]
    if missing_q:
        errs.append(f"research_question verdicts need a question: {missing_q}")
    if errs:
        store.update(trg.id, {"status": "rejected", "errors": errs},
                     reason="triage rejected by controller")
        raise ValueError("triage rejected by controller: " + "; ".join(errs))
    by_id = {o.id: o for o in batch}
    questions = []
    for t in payload["triage"]:
        o = by_id[t["observation"]]
        refs = {"observation": o.id, "failure": o.data["refs"]["failure"], "triage": trg.id,
                "task": tid}
        if t["verdict"] == "research_question":
            fq = store.create("future_question", {
                "question": t["question"].strip(), "rationale": t["rationale"],
                "priority": int(t.get("priority", 2)), "status": "open",
                "origin": "engineering_failure", "project": o.data["project"], "refs": refs},
                prefix="FQ", author="scientist", reason=f"research question from {o.id}")
            store.append_event("controller", "ResearchQuestionCreated", fq.id,
                               {"observation": o.id, "origin": "engineering_failure"})
            questions.append(fq.id)
            refs["future_question"] = fq.id
        store.update(o.id, {"status": STATUS_BY_VERDICT[t["verdict"]], "verdict": t["verdict"],
                            "triage_rationale": t["rationale"],
                            "refs": {**o.data["refs"], **{k: v for k, v in refs.items()
                                                          if k in ("triage", "future_question")}}},
                     reason=f"triaged by {trg.id}: {t['verdict']}")
    counts = {v: sum(1 for t in payload["triage"] if t["verdict"] == v) for v in VERDICTS}
    store.update(trg.id, {"status": "complete", "patterns": payload.get("patterns", []),
                          "counts": counts, "questions": questions,
                          "refs": {"task": tid, "questions": questions}},
                 reason=f"triage complete: {counts}")
    return {"triage": trg.id, "questions": questions, "counts": counts,
            "patterns": payload.get("patterns", [])}
