"""Cycle report generation (controller-authored, traceable)."""

from __future__ import annotations

from .memory import format_trace, trace
from .store import Store


def _fmt(x) -> str:
    if isinstance(x, float):
        return f"{x:.6g}"
    return str(x)


def build_report(store: Store, project_id: str, cycle: int, cur: dict,
                 scientist_summary: str) -> str:
    proj = store.get(project_id)
    q = store.get(cur["question"]).data
    hyp = store.get(cur["hypothesis"])
    prot = store.get(cur["protocol"])
    run = store.get(cur["run"])
    res = store.get(cur["result"])
    chl = store.get(cur["challenge"]).data
    con = store.get(cur["conclusion"])
    interp = store.get(cur["interpretation"]).data if cur.get("interpretation") else {}
    p = prot.data["protocol"]
    d = res.data["decision"]

    lines = [
        f"# Research report — {project_id}, cycle {cycle}",
        "",
        f"**Objective:** {proj.data['objective']}",
        "",
        f"**Research question** ({cur['question']}): {q['question']}",
        "",
        f"**Hypothesis** ({hyp.id}, label HYPOTHESIS): {hyp.data['statement']}",
        f"- prediction: {hyp.data['prediction']}",
        f"- null: {hyp.data['null_hypothesis']}",
        "",
        "## Outcome (computed by the controller from the pre-registered rule)",
        "",
        f"- **{d['outcome'].upper()}** — {con.data['experiment_kind']} experiment, "
        f"confidence: {con.data['confidence']}",
        f"- effect ({d['direction']}, {d['treatment']} vs {d['control']} on {d['metric']}): "
        f"{_fmt(d.get('effect', 'n/a'))}, {int((1 - d['alpha']) * 100)}% CI "
        f"[{_fmt(d.get('ci_low', 'n/a'))}, {_fmt(d.get('ci_high', 'n/a'))}], "
        f"min effect {d['min_effect']}",
        f"- n = {d['n_treatment']} / {d['n_control']} seeds",
        "",
        "> Labels: the outcome above is an EXPERIMENTAL_RESULT for this protocol, "
        "commit and environment only. It is not proof of the hypothesis"
        + (" and, being exploratory, is hypothesis-generating only." if
           con.data["experiment_kind"] == "exploratory" else "."),
        "",
        "## Method",
        "",
        f"- protocol {prot.id} v{prot.version} (freeze hash `{prot.data.get('_freeze_hash', '')[:16]}`), "
        f"kind={p['kind']}, protected={p.get('protected', False)}",
        f"- amendments: {len(prot.data.get('_amendments', []))}",
        f"- conditions: " + ", ".join(f"{c['name']} ({c['role']})" for c in p["conditions"]),
        f"- seeds: {p['seeds']}",
        f"- implementation commit: `{run.data['commit']}`",
        f"- run {run.id}: {run.data['n_trials']} trials, {run.data['n_failed']} failed, "
        f"env hash `{run.data['env_hash'][:16]}`",
        "",
        "## Results by condition",
        "",
        "| condition | metric | n | mean | std |",
        "|---|---|---|---|---|",
    ]
    for cond, stats in res.data["summary"].items():
        for metric, s in stats.items():
            if isinstance(s, dict):
                lines.append(f"| {cond} | {metric} | {s['n']} | {_fmt(s['mean'])} | {_fmt(s['std'])} |")
    lines += ["", "### Secondary contrasts (not decisive)", ""]
    for c in res.data["contrasts"]:
        lines.append(f"- {c['treatment']} ({c['role']}) vs {c['control']}: {c['outcome']}, "
                     f"effect {_fmt(c.get('effect', 'n/a'))}")
    lines += ["", "### Experimental validity checks", ""]
    for v in res.data["validity"]:
        lines.append(f"- {v['id']}: {'PASS' if v['passed'] else 'FAIL'} "
                     f"(observed {_fmt(v['observed'])}; {v.get('expected', v.get('reason', ''))})")
    lines += ["", "## Interpretation (INFERENCE — scientist)", "",
              interp.get("interpretation", "_none_"), "",
              "Alternative explanations:"]
    lines += [f"- {a}" for a in interp.get("alternative_explanations", [])] or ["- _none given_"]
    lines += ["", "Limitations:"]
    lines += [f"- {a}" for a in interp.get("limitations", [])] or ["- _none given_"]
    lines += ["", f"## Adversarial challenge (verifier): **{chl['verdict']}**", ""]
    lines += [f"- [{i['severity']}] {i['description']}" for i in chl["issues"]] or ["- no issues raised"]
    lines += [f"- alt: {a}" for a in chl.get("alternative_explanations", [])]
    lines += ["", "## Scientist summary", "", scientist_summary, "",
              "## Provenance trace", "", "```", format_trace(trace(store, con.id)), "```", ""]
    return "\n".join(lines)


def research_plan_markdown(store: Store, project_id: str, cur: dict) -> str:
    """The saved artifact of plan-only research (/research)."""
    proj = store.get(project_id).data
    get = lambda key: store.get(cur[key]).data if cur.get(key) else {}  # noqa: E731
    prb, bkg, q, req = get("problem"), get("background"), get("question"), get("requirements")
    hyp, prot = get("hypothesis"), get("protocol")
    p = prot.get("protocol", {})
    claims = [store.get(c).data for c in (bkg.get("refs") or {}).get("claims", [])]
    reviews = [r.data for r in store.query("review", project=project_id)
               if r.data.get("review_type") == "scientific_review"]
    design = store.get(prot["refs"]["design"]).data if prot.get("refs", {}).get("design") else {}
    lines = [f"# Research plan: {proj['objective']}", "",
             f"_Project {project_id} (plan-only research). Generated from the lab ledger; "
             f"every item is traceable by its record id._", "",
             "## 1. Problem", "", _fmt(prb.get("problem_statement")), "",
             f"- scope: {_fmt(prb.get('scope'))}",
             f"- out of scope: {_fmt(prb.get('out_of_scope'))}",
             f"- success: {_fmt(prb.get('success_notion'))}", "",
             "## 2. Literature and knowledge", ""]
    for c in claims:
        ver = "verified" if c.get("sources_verified") else "unverified"
        lines.append(f"- [{c.get('label')}] {c.get('statement')} "
                     f"(sources: {', '.join(c.get('sources', [])) or '-'}; {ver})")
    lines += ["", "## 3. State of the art and gaps", "",
              "Known methods:", *[f"- {m}" for m in bkg.get("known_methods", [])], "",
              "Gaps:", *[f"- {g}" for g in bkg.get("gaps", [])], "",
              "## 4. Research question", "", _fmt(q.get("question")), "",
              f"Rationale: {_fmt(q.get('rationale'))}", "",
              "## 5. Hypothesis", "", f"- statement: {_fmt(hyp.get('statement'))}",
              f"- prediction: {_fmt(hyp.get('prediction'))}",
              f"- null: {_fmt(hyp.get('null_hypothesis'))}",
              f"- falsification: {_fmt(hyp.get('falsification'))}", "",
              "## 6. Requirements", "",
              "Validity criteria:", *[f"- {v}" for v in req.get("validity_criteria", [])], "",
              "Engineering requirements:", *[f"- {v}" for v in req.get("engineering", [])], "",
              "## 7. Experiment proposals", ""]
    for o in design.get("options", []):
        mark = " (chosen)" if o.get("name") == design.get("chosen") else ""
        lines.append(f"- **{o.get('name')}**{mark}: {o.get('description')}")
    lines += ["", f"Rationale: {_fmt(design.get('rationale'))}", "",
              "## 8. Proposed protocol", "", f"- title: {_fmt(p.get('title'))} ({_fmt(p.get('kind'))})",
              f"- conditions: {', '.join(c['name'] + ' (' + c['role'] + ')' for c in p.get('conditions', []))}",
              f"- primary metric: {_fmt((p.get('metrics') or {}).get('primary'))}",
              f"- decision rule: {_fmt(p.get('decision_rule'))}",
              f"- seeds: {_fmt(p.get('seeds'))}", "",
              "## 9. Scientific review", ""]
    for r in reviews:
        lines.append(f"- verdict **{r.get('verdict')}**: "
                     + "; ".join(f"[{i.get('severity')}] {i.get('description')}"
                                 for i in r.get("issues", [])))
    lines += ["", "## 10. Next step", "",
              "Run this plan as a full research project (`autolab project`), or refine it."]
    return "\n".join(lines) + "\n"
