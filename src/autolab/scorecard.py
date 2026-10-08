"""Agent scorecards (D60, master prompt sections 10 and 20).

Evidence for choosing models: per agent (and per model it ran on) the lab aggregates, from the
ledger only,

* activity -- calls, completed, errors, success rate, protocol rejections, stages served;
* cost and time -- controller-measured wall time, and tokens / cost where the backend reports
  them (Claude CLI and the OpenAI API do; Codex and Gemini CLIs do not, so those stay unknown,
  never estimated);
* quality -- for authors of code, the adversarial reviews of their work (passed / failed and the
  findings by severity they caused); for reviewers, the findings they raised.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .store import Store

AUTHOR_STAGES = ("implement", "redesign", "build", "rebuild")
SEVERITIES = ("critical", "major", "minor", "note")


def _agent(task: dict) -> str:
    return task.get("agent") or task.get("role") or "unknown"


def scorecards(store: Store) -> list[dict]:
    tasks = store.query("task")
    by_id = {t.id: t for t in tasks}
    cards: dict[str, dict] = defaultdict(lambda: {
        "calls": 0, "completed": 0, "errors": 0, "other": 0, "protocol_rejections": 0,
        "wall_s": 0.0, "timed_calls": 0, "usage_calls": 0, "input_tokens": 0,
        "output_tokens": 0, "cache_read_tokens": 0, "cost_usd": 0.0,
        "stages": Counter(), "models": Counter(),
        "reviews_of_my_code": {"passed": 0, "failed": 0},
        "findings_caused": Counter(), "findings_raised": Counter()})
    for t in tasks:
        d = t.data
        c = cards[_agent(d)]
        c["calls"] += 1
        status = d.get("status")
        c["completed" if status == "complete" else "errors" if status == "error" else "other"] += 1
        c["protocol_rejections"] += len(d.get("rejections") or [])
        c["stages"][d.get("stage")] += 1
        model = (d.get("usage") or {}).get("model") or (d.get("backend") or {}).get("model")
        c["models"][model or "default"] += 1
        if isinstance(d.get("wall_s"), (int, float)):
            c["wall_s"] += d["wall_s"]
            c["timed_calls"] += 1
        u = d.get("usage")
        if u:
            c["usage_calls"] += 1
            for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cost_usd"):
                if isinstance(u.get(k), (int, float)):
                    c[k] += u[k]
    # Quality: each adversarial code review is credited to the author of the reviewed code (the
    # latest engineer call of that engineering task before the review) and to the reviewer.
    author_tasks: dict[str, list] = defaultdict(list)
    for t in tasks:
        if t.data.get("stage") in AUTHOR_STAGES and t.data.get("status") == "complete":
            author_tasks[t.data.get("project")].append(t)
    for rev in store.query("review"):
        r = rev.data
        if r.get("review_type") != "code_review":
            continue
        findings = Counter(f.get("severity") for f in r.get("findings", []) if isinstance(f, dict))
        reviewer = by_id.get((r.get("refs") or {}).get("task"))
        if reviewer:
            cards[_agent(reviewer.data)]["findings_raised"].update(findings)
        earlier = [t for t in author_tasks.get(r.get("project"), [])
                   if t.created_at <= rev.created_at]
        if earlier:
            author = cards[_agent(max(earlier, key=lambda t: t.created_at).data)]
            author["reviews_of_my_code"]["passed" if r.get("passed") else "failed"] += 1
            author["findings_caused"].update(findings)
    out = []
    for name, c in sorted(cards.items()):
        out.append({
            "agent": name, "calls": c["calls"], "completed": c["completed"], "errors": c["errors"],
            "other": c["other"],
            "success_rate": round(c["completed"] / c["calls"], 3) if c["calls"] else None,
            "protocol_rejections": c["protocol_rejections"],
            "avg_wall_s": round(c["wall_s"] / c["timed_calls"], 1) if c["timed_calls"] else None,
            "total_wall_s": round(c["wall_s"], 1),
            "usage_reported_calls": c["usage_calls"],
            "input_tokens": c["input_tokens"] if c["usage_calls"] else None,
            "output_tokens": c["output_tokens"] if c["usage_calls"] else None,
            "cache_read_tokens": c["cache_read_tokens"] if c["usage_calls"] else None,
            "cost_usd": round(c["cost_usd"], 4) if c["usage_calls"] else None,
            "stages": dict(c["stages"]), "models": dict(c["models"]),
            "reviews_of_my_code": c["reviews_of_my_code"],
            "findings_caused": {s: c["findings_caused"].get(s, 0) for s in SEVERITIES},
            "findings_raised": {s: c["findings_raised"].get(s, 0) for s in SEVERITIES},
        })
    return out


def totals(cards: list[dict]) -> dict:
    """Lab-wide observability numbers (unknown usage stays unknown, never zero-filled)."""
    known = [c for c in cards if c["usage_reported_calls"]]
    return {"calls": sum(c["calls"] for c in cards),
            "errors": sum(c["errors"] for c in cards),
            "wall_s": round(sum(c["total_wall_s"] for c in cards), 1),
            "usage_reported_calls": sum(c["usage_reported_calls"] for c in cards),
            "input_tokens": sum(c["input_tokens"] or 0 for c in known) if known else None,
            "output_tokens": sum(c["output_tokens"] or 0 for c in known) if known else None,
            "cost_usd": round(sum(c["cost_usd"] or 0 for c in known), 4) if known else None}
