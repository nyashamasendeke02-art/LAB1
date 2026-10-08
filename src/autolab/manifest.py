"""Project manifest and structure (D61, master prompt sections 15 and 16).

Export: a project's ledger records become an executable, machine-readable folder::

    <out>/<project-id>/
      project.yaml                    the manifest (s.16 schema + provenance)
      research/question.md, research/hypotheses/<HYP>.md, research/literature/claims.md
      requirements/requirements.yaml  architecture/architecture.yaml (engineering track)
      agents/agents.yaml              who did what, on which model
      experiments/<PROT>.yaml         frozen or proposed protocols
      datasets/datasets.yaml          pinned data (paths + sha256) used by runs
      models/models.yaml              models used by agents
      results/<RES>.yaml, results/conclusions.yaml
      evaluations/reviews.yaml        scientific, code, architecture, security, performance
      papers/papers.yaml              external sources cited by claims (verification status)
      src/SOURCE.md                   the exact commits holding the code (the repo is the source)
      documentation/                  the lab's reports for the project

The ledger stays authoritative: every file names the record ids it came from, and the manifest
carries the ledger head it was exported at.

Import: ``project.yaml`` (the s.16 example shape, plus optional autonomy_level / mode /
engineering fields) creates a project; its questions, hypotheses, metrics and domains are given
to the research stages as a starting brief (``project_manifest`` in their context).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import jsonschema
import yaml

MANIFEST_SCHEMA = {
    "type": "object", "required": ["project"],
    "properties": {
        "project": {"type": "object", "required": ["name"],
                    "properties": {"id": {"type": "string"},
                                   "name": {"type": "string", "minLength": 1},
                                   "autonomy_level": {"type": "integer", "minimum": 0, "maximum": 5},
                                   "mode": {"enum": ["full", "plan"]},
                                   "mandate_refs": {"type": "array", "items": {"type": "string"}}}},
        "research": {"type": "object", "properties": {
            "questions": {"type": "array", "items": {"type": "object", "required": ["statement"],
                                                     "properties": {"statement": {"type": "string"}}}},
            "hypotheses": {"type": "array", "items": {"type": "object", "required": ["statement"],
                                                      "properties": {"statement": {"type": "string"}}}}}},
        "domains": {"type": "array", "items": {"type": "string"}},
        "experiments": {"type": "array"},
        "evaluation": {"type": "object",
                       "properties": {"metrics": {"type": "array", "items": {"type": "string"}}}},
        "engineering": {"type": "object", "required": ["spec", "acceptance_criteria"],
                        "properties": {"spec": {"type": "string", "minLength": 1},
                                       "acceptance_criteria": {"type": "array", "minItems": 1,
                                                               "items": {"type": "string"}},
                                       "specialty": {"type": "string"}}},
    },
}


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
                    encoding="utf-8", newline="\n")


def _md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "project"


def _clean(d: dict) -> dict:
    """Record data without internal keys (frozen flags) for export."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def export_project(lab, pid: str, out_root: Path) -> Path:
    store = lab.store
    proj = store.get(pid)
    if proj.kind != "project":
        raise KeyError(pid)
    d = proj.data
    mine = lambda kind: [r for r in store.query(kind) if r.data.get("project") == pid]  # noqa: E731
    out = Path(out_root) / pid
    if out.exists():
        shutil.rmtree(out)
    questions, hyps = mine("question"), mine("hypothesis")
    protocols, results, cons = mine("protocol"), mine("result"), mine("conclusion")
    runs, claims = mine("run"), mine("claim")
    # ---- research
    for q in questions:
        _md(out / "research" / "question.md",
            f"# {q.id}\n\n{q.data.get('question', '')}\n\nRationale: {q.data.get('rationale', '')}\n")
    for h in hyps:
        hd = h.data
        _md(out / "research" / "hypotheses" / f"{h.id}.md",
            f"# {h.id} ({hd.get('status', 'open')})\n\n{hd.get('statement', '')}\n\n"
            f"- prediction: {hd.get('prediction', '')}\n- null: {hd.get('null_hypothesis', '')}\n"
            f"- falsification: {hd.get('falsification', '')}\n")
    if claims:
        _md(out / "research" / "literature" / "claims.md", "# Claims\n\n" + "\n".join(
            f"- **{c.id}** [{c.data.get('label')}] {c.data.get('statement')} "
            f"(sources: {', '.join(c.data.get('sources', [])) or '-'}; "
            f"{'verified' if c.data.get('sources_verified') else 'unverified'})" for c in claims))
    reqs = mine("requirements")
    if reqs:
        _dump(out / "requirements" / "requirements.yaml",
              [{"id": r.id, **{k: v for k, v in _clean(r.data).items() if k not in ("refs", "project")}}
               for r in reqs])
    # ---- engineering
    engs = mine("eng_task")
    archs = [{"eng_task": e.id, **(e.data.get("architecture") or {}).get("spec", {})}
             for e in engs if (e.data.get("architecture") or {}).get("status") == "approved"]
    if archs:
        _dump(out / "architecture" / "architecture.yaml", archs)
    # ---- experiments, data, results
    for p in protocols:
        _dump(out / "experiments" / f"{p.id}.yaml",
              {"id": p.id, "version": p.version, "status": p.data.get("status"),
               "freeze_hash": p.data.get("_freeze_hash"), **p.data.get("protocol", {})})
    datasets = {path: h for r in runs for path, h in (r.data.get("data") or {}).items()}
    if datasets:
        _dump(out / "datasets" / "datasets.yaml",
              [{"path": k, "sha256": v} for k, v in sorted(datasets.items())])
    for r in results:
        _dump(out / "results" / f"{r.id}.yaml",
              {"id": r.id, "outcome": r.data.get("outcome"), "decision": r.data.get("decision"),
               "validity": r.data.get("validity"), "run": (r.data.get("refs") or {}).get("run")})
    if cons:
        _dump(out / "results" / "conclusions.yaml",
              [{"id": c.id, "statement": c.data.get("statement"), "outcome": c.data.get("outcome"),
                "label": c.data.get("label"), "confidence": c.data.get("confidence"),
                "caveats": c.data.get("caveats", [])} for c in cons])
    reviews = mine("review")
    if reviews:
        _dump(out / "evaluations" / "reviews.yaml",
              [{"id": r.id, "type": r.data.get("review_type"),
                "verdict": r.data.get("verdict"), "passed": r.data.get("passed"),
                "approved": r.data.get("approved"),
                "findings": r.data.get("findings") or r.data.get("issues") or []} for r in reviews])
    # ---- agents and models
    tasks = mine("task")
    agents: dict[str, dict] = {}
    for t in tasks:
        name = t.data.get("agent") or t.data.get("role")
        a = agents.setdefault(name, {"agent": name, "role": t.data.get("role"),
                                     "stages": set(), "models": set(), "calls": 0})
        a["calls"] += 1
        a["stages"].add(t.data.get("stage"))
        model = (t.data.get("backend") or {}).get("model")
        if model:
            a["models"].add(model)
    agent_list = [{**a, "stages": sorted(a["stages"]), "models": sorted(a["models"])}
                  for a in agents.values()]
    if agent_list:
        _dump(out / "agents" / "agents.yaml", agent_list)
        _dump(out / "models" / "models.yaml",
              sorted({m for a in agent_list for m in a["models"]}))
    papers = sorted({s for c in claims for s in c.data.get("sources", [])
                     if isinstance(s, str) and not s.startswith("lab:")})
    if papers:
        _dump(out / "papers" / "papers.yaml", [{"source": s, "verified": False} for s in papers])
    commits = [{"what": "experiment code", "commit": r.data.get("commit"), "run": r.id} for r in runs]
    commits += [{"what": "delivery", "commit": x.data.get("commit"), "delivery": x.id}
                for x in mine("delivery")]
    _md(out / "src" / "SOURCE.md", "# Source\n\nThe code lives in the lab's research repository "
        "(`repo/`); these commits hold it:\n\n" + ("\n".join(
            f"- {c['what']}: `{c['commit']}` ({c.get('run') or c.get('delivery')})" for c in commits)
            or "- (no code merged yet)"))
    for rep in mine("report"):
        src = lab.root / rep.data.get("path", "")
        if src.is_file():
            (out / "documentation").mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out / "documentation" / src.name)
    # ---- manifest (s.16 shape + provenance)
    metrics = sorted({m for p in protocols for m in
                      [(p.data.get("protocol") or {}).get("metrics", {}).get("primary"),
                       *(p.data.get("protocol") or {}).get("metrics", {}).get("secondary", [])] if m})
    manifest = {
        "project": {"id": _slug(d.get("objective", pid)), "ledger_id": pid,
                    "name": d.get("objective", ""), "kind": d.get("kind", "research"),
                    "mode": d.get("mode", "full"), "state": d.get("state"),
                    "autonomy_level": d.get("autonomy_level"),
                    "mandate_refs": d.get("mandate_refs", [])},
        "research": {"questions": [{"id": q.id, "statement": q.data.get("question", "")}
                                   for q in questions],
                     "hypotheses": [{"id": h.id, "statement": h.data.get("statement", ""),
                                     "status": h.data.get("status")} for h in hyps]},
        "domains": d.get("domains", []),
        "experiments": [{"id": c["name"], "role": c["role"], "protocol": p.id}
                        for p in protocols for c in (p.data.get("protocol") or {}).get("conditions", [])],
        "evaluation": {"metrics": metrics,
                       "outcomes": [{"conclusion": c.id, "outcome": c.data.get("outcome")}
                                    for c in cons]},
        "provenance": {"lab": lab.root.name, "ledger_head": store.head(),
                       "exported_from": "autolab ledger (authoritative)"},
    }
    if d.get("kind") == "engineering":
        manifest["engineering"] = {"spec": d.get("objective"),
                                   "acceptance_criteria": d.get("acceptance_criteria", []),
                                   "specialty": d.get("specialty")}
    _dump(out / "project.yaml", manifest)
    return out


def load_manifest(path: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        jsonschema.validate(data, MANIFEST_SCHEMA)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path)
        raise ValueError(f"project.yaml invalid at /{where}: {exc.message}") from None
    return data


def import_project(ctl, path: Path, author: str = "human") -> str:
    """Create a project from project.yaml; its research content becomes a starting brief."""
    m = load_manifest(path)
    p = m["project"]
    seed = {"questions": [q["statement"] for q in m.get("research", {}).get("questions", [])],
            "hypotheses": [h["statement"] for h in m.get("research", {}).get("hypotheses", [])],
            "metrics": m.get("evaluation", {}).get("metrics", []),
            "domains": m.get("domains", []),
            "experiments": m.get("experiments", []), "source": str(path)}
    refs = p.get("mandate_refs", [])
    if "engineering" in m:
        e = m["engineering"]
        pid = ctl.new_engineering_project(e["spec"], e["acceptance_criteria"], refs, author=author,
                                          specialty=e.get("specialty"),
                                          autonomy_level=p.get("autonomy_level"))
    else:
        objective = p["name"] if not seed["questions"] else f"{p['name']}: {seed['questions'][0]}"
        pid = ctl.new_project(objective, refs, author=author, mode=p.get("mode", "full"),
                              autonomy_level=p.get("autonomy_level"))
    ctl.store.update(pid, {"manifest_seed": seed, "domains": seed["domains"]},
                     author=author, reason=f"created from manifest {path}")
    return pid
