"""Research memory: typed views over the store, lineage tracing, exports.

Every record may carry ``refs`` (name -> id | [ids]). :func:`trace` follows
refs transitively so any result can be walked back to the exact protocol
version, commit, run configuration, raw data artifacts and agent tasks that
produced it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .store import Record, Store

KINDS = [
    "project", "problem", "background", "claim", "question", "hypothesis",
    "requirements", "design", "protocol", "eng_task", "review", "run", "result",
    "challenge", "conclusion", "failure", "report", "future_question", "task",
    "approval", "cycle", "delivery", "programme", "observation", "triage",
]


def _ref_ids(refs: dict) -> list[str]:
    out = []
    for v in (refs or {}).values():
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str))
    return out


def trace(store: Store, record_id: str, max_depth: int = 12) -> dict:
    """Return a lineage tree rooted at ``record_id``."""
    seen: set[str] = set()

    def node(rid: str, depth: int) -> dict:
        if not store.exists(rid):
            return {"id": rid, "missing": True}
        rec = store.get(rid)
        out = {"id": rid, "kind": rec.kind, "version": rec.version,
               "hash": rec.content_hash}
        for key in ("commit", "freeze_hash", "statement", "question", "outcome",
                    "branch", "artifact", "env_hash", "status", "kind_label"):
            if key in rec.data:
                out[key] = rec.data[key]
        if "_freeze_hash" in rec.data:
            out["freeze_hash"] = rec.data["_freeze_hash"]
        if rid in seen:
            out["seen"] = True
            return out
        if depth >= max_depth:
            return out
        seen.add(rid)
        kids = [node(r, depth + 1) for r in _ref_ids(rec.data.get("refs", {}))
                if not r.startswith("sha256:")]
        arts = [r for r in _ref_ids(rec.data.get("refs", {})) if r.startswith("sha256:")]
        if kids:
            out["derived_from"] = kids
        if arts:
            out["artifacts"] = arts
        return out

    return node(record_id, 0)


def format_trace(tree: dict, indent: int = 0) -> str:
    pad = "  " * indent
    extra = ", ".join(f"{k}={str(tree[k])[:60]}" for k in
                      ("commit", "freeze_hash", "outcome", "status", "branch")
                      if k in tree)
    line = f"{pad}- {tree['id']} [{tree.get('kind', '?')} v{tree.get('version', '?')}]"
    if extra:
        line += f" {extra}"
    if tree.get("seen"):
        return line + " (see above)"
    lines = [line]
    for a in tree.get("artifacts", []):
        lines.append(f"{pad}    artifact {a[:20]}...")
    for k in tree.get("derived_from", []):
        lines.append(format_trace(k, indent + 1))
    return "\n".join(lines)


def _md_list(recs: list[Record], fmt) -> str:
    return "\n".join(fmt(r) for r in recs) if recs else "_none_"


def export_markdown(store: Store, out_dir: str | Path) -> list[Path]:
    """Write human-readable state files (regenerated; the DB is authoritative)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []

    def w(name: str, text: str) -> None:
        p = out / name
        p.write_text(text, encoding="utf-8")
        written.append(p)

    projects = store.query("project")
    lines = ["# Current State", "", "_Generated from the lab database. Do not edit._", ""]
    for p in projects:
        d = p.data
        lines += [f"## {p.id} [{d.get('kind', 'research')}]: {d['objective']}", "",
                  f"- state: **{d['state']}**",
                  f"- mandate refs: {', '.join(d.get('mandate_refs', [])) or '-'}",
                  f"- cycle: {d.get('cycle', 1)}",
                  f"- blocked on: {d.get('blocked_on') or '-'}",
                  f"- halted reason: {d.get('halt_reason') or '-'}", ""]
        cur = d.get("current", {})
        if cur:
            lines.append("Current pointers: " + ", ".join(f"{k}={v}" for k, v in cur.items()))
            lines.append("")
    w("CURRENT.md", "\n".join(lines))

    w("HYPOTHESES.md", "# Hypotheses\n\n" + _md_list(
        store.query("hypothesis"),
        lambda r: f"- **{r.id}** [{r.data.get('status')}] ({r.data.get('label', 'HYPOTHESIS')}) "
                  f"{r.data['statement']}"))
    w("CONCLUSIONS.md", "# Conclusions\n\n" + _md_list(
        store.query("conclusion"),
        lambda r: f"- **{r.id}** {r.data['hypothesis']}: **{r.data['outcome']}** "
                  f"({r.data['label']}, {r.data['experiment_kind']}, "
                  f"confidence={r.data['confidence']}) result={r.data['refs']['result']}"))
    w("FAILURES.md", "# Failures (retained, never deleted)\n\n" + _md_list(
        store.query("failure"),
        lambda r: f"- **{r.id}** [{r.data['category']}] {r.data['summary']}"))
    w("OPEN_QUESTIONS.md", "# Open / Future Questions\n\n" + _md_list(
        store.query("future_question"),
        lambda r: f"- **{r.id}** (p{r.data.get('priority', '-')}, {r.data.get('status')}) "
                  f"{r.data['question']}"))
    w("DECISIONS.md", "# Approval Decisions\n\n" + _md_list(
        store.query("approval"),
        lambda r: f"- **{r.id}** {r.data['gate']} on {r.data['subject']}: "
                  f"**{r.data['status']}** by {r.data.get('decided_by', '-')}"
                  f"{' (delegated by ' + r.data['delegated_by'] + ')' if r.data.get('delegated_by') else ''}"
                  f" {r.data.get('note', '')}"))
    w("DELIVERIES.md", "# Engineering Deliveries\n\n" + _md_list(
        store.query("delivery"),
        lambda r: f"- **{r.id}** {', '.join(r.data.get('mandate_refs', [])) or '-'}: "
                  f"commit {r.data['commit'][:10]}, review {r.data['review']}: "
                  f"{r.data['spec'][:120]}"))
    prog = ["# Programmes (hierarchical coordination)", ""]
    for g in store.query("programme"):
        d = g.data
        prog += [f"## {g.id}: {d['objective']}", "", f"- state: **{d['state']}**",
                 f"- reviews: {d.get('reviews', 0)}",
                 f"- halted reason: {d.get('halt_reason') or '-'}", ""]
        for key in d.get("order", []):
            it = d["items"][key]
            pad = "  " if it.get("parent") else ""
            spec = f", {it['specialty']}" if it.get("specialty") else ""
            prog.append(f"{pad}- `{key}` [{it['kind']}{spec}] **{it['status']}** "
                        f"{', '.join(it.get('projects', []))} {it['objective'][:100]}")
        prog.append("")
    w("PROGRAMMES.md", "\n".join(prog) if len(prog) > 2 else "# Programmes\n\n_none_")
    w("EXPERIMENTS.md", "# Experiment Runs\n\n" + _md_list(
        store.query("run"),
        lambda r: f"- **{r.id}** protocol={r.data['refs']['protocol']} "
                  f"v{r.data['protocol_version']} kind={r.data['experiment_kind']} "
                  f"commit={r.data['commit'][:10]} trials={r.data['n_trials']} "
                  f"failed={r.data['n_failed']}"))
    return written


def dump_json(store: Store, path: str | Path) -> Path:
    """Full JSON export (all versions of all records + ledger)."""
    data = {"records": {}, "events": store.events()}
    for kind in KINDS:
        for rec in store.query(kind):
            data["records"][rec.id] = [
                {"version": h.version, "kind": h.kind, "data": h.data,
                 "author": h.author, "reason": h.reason, "created_at": h.created_at,
                 "hash": h.content_hash}
                for h in store.history(rec.id)]
    p = Path(path)
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return p
