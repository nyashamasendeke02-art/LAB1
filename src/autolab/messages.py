"""Agent communication protocol.

Every interaction is a *TaskPacket* (controller -> agent) answered by a
*Completion* (agent -> controller). Both are JSON, schema-validated, stored
as artifacts and linked in the ledger. The controller never acts on free
text: the stage-specific ``payload`` must validate against
``STAGE_SCHEMAS[stage]`` or the completion is rejected.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import jsonschema

from .taxonomy import Evidence, Role

_str = {"type": "string"}
_nstr = {"type": "string", "minLength": 1}
_strs = {"type": "array", "items": {"type": "string"}}
_num = {"type": "number"}
_sev = {"enum": ["critical", "major", "minor"]}
_issue = {
    "type": "object",
    "required": ["severity", "description"],
    "properties": {"severity": _sev, "description": _nstr, "location": _str},
}

CLAIM_SCHEMA = {
    "type": "object",
    "required": ["type", "statement"],
    "properties": {
        "type": {"enum": [e.value for e in Evidence]},
        "statement": _nstr,
        "sources": _strs,
        "run_ids": _strs,
    },
}

# Protocol objects are closed (additionalProperties: false): a misspelled or
# misplaced key must be rejected, never silently dropped in favour of a default.
REQUIREMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "description", "metric", "condition", "op", "value"],
    "properties": {
        "id": _nstr,
        "description": _nstr,
        "metric": _nstr,
        "condition": _nstr,
        "op": {"enum": [">", ">=", "<", "<=", "==", "!="]},
        "value": _num,
        "aggregate": {"enum": ["mean", "median", "min", "max"]},
        "relative_to": _nstr,
    },
}

PROTOCOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "kind", "entrypoint", "conditions", "seeds", "metrics",
                 "decision_rule"],
    "properties": {
        "title": _nstr,
        "kind": {"enum": ["exploratory", "confirmatory"]},
        "protected": {"type": "boolean"},
        "entrypoint": _nstr,
        "conditions": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "role"],
                "properties": {
                    "name": {"type": "string", "pattern": "^[A-Za-z0-9_\\-]+$"},
                    "role": {"enum": ["baseline", "intervention", "ablation", "null",
                                      "transfer", "robustness"]},
                    "params": {"type": "object"},
                },
            },
        },
        "seeds": {"type": "array", "minItems": 1, "items": {"type": "integer"}},
        "metrics": {
            "type": "object",
            "additionalProperties": False,
            "required": ["primary"],
            "properties": {"primary": _nstr, "secondary": _strs},
        },
        "decision_rule": {
            "type": "object",
            "additionalProperties": False,
            "required": ["metric", "treatment", "control", "direction"],
            "properties": {
                "metric": _nstr,
                "treatment": _nstr,
                "control": _nstr,
                "direction": {"enum": ["greater", "less"]},
                "type": {"enum": ["superiority", "non_inferiority"]},
                "min_effect": {"type": "number", "minimum": 0},
                "margin": {"type": "number", "exclusiveMinimum": 0},
                "co_primary": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["metric", "direction"],
                    "properties": {
                        "metric": _nstr, "treatment": _nstr, "control": _nstr,
                        "direction": {"enum": ["greater", "less"]},
                        "type": {"enum": ["superiority", "non_inferiority"]},
                        "min_effect": {"type": "number", "minimum": 0},
                        "margin": {"type": "number", "exclusiveMinimum": 0}}}},
                "alpha": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
                "pairing": {"enum": ["paired", "unpaired"]},
                "unit": {"enum": ["seed", "item"]},
            },
        },
        "n_items": {"type": "integer", "minimum": 2},
        "data_paths": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "budget": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"timeout_s": _num, "max_runs": {"type": "integer"},
                           "max_parallel": {"type": "integer", "minimum": 1, "maximum": 64},
                           "max_cost_usd": {"type": "number", "exclusiveMinimum": 0}},
        },
        "fixed_params": {"type": "object"},
        "validity_checks": {"type": "array", "items": REQUIREMENT_SCHEMA},
        "success_checks": {"type": "array", "items": REQUIREMENT_SCHEMA},
        "transfer_tests": _strs,
        "robustness_tests": _strs,
        "mandate_refs": _strs,
    },
}


def _obj(required: list[str], props: dict) -> dict:
    return {"type": "object", "required": required, "properties": props}


STAGE_SCHEMAS: dict[str, dict] = {
    "define_problem": _obj(
        ["problem_statement", "scope"],
        {"problem_statement": _nstr, "scope": _nstr, "out_of_scope": _strs,
         "success_notion": _str},
    ),
    "background_research": _obj(
        ["findings"],
        {"findings": {"type": "array", "items": CLAIM_SCHEMA},
         "known_methods": _strs, "gaps": _strs},
    ),
    "research_question": _obj(["question", "rationale"],
                              {"question": _nstr, "rationale": _nstr}),
    "hypothesis": _obj(
        ["hypotheses"],
        {"hypotheses": {
            "type": "array", "minItems": 1,
            "items": _obj(["statement", "prediction", "null_hypothesis"],
                          {"statement": _nstr, "prediction": _nstr,
                           "null_hypothesis": _nstr, "falsification": _str}),
        }},
    ),
    "requirements": _obj(
        ["validity_criteria", "engineering"],
        {"validity_criteria": {"type": "array", "minItems": 1, "items": _nstr},
         "success_criteria": _strs,
         "engineering": _strs},
    ),
    "design": _obj(
        ["options", "chosen", "rationale", "protocol"],
        {"options": {"type": "array", "minItems": 1,
                     "items": _obj(["name", "description"],
                                   {"name": _nstr, "description": _nstr,
                                    "pros": _strs, "cons": _strs})},
         "chosen": _nstr, "rationale": _nstr, "protocol": PROTOCOL_SCHEMA},
    ),
    "solution_design": _obj(
        ["solution_design", "feasible"],
        {"solution_design": _nstr, "feasible": {"type": "boolean"},
         "files": _strs, "risks": _strs},
    ),
    "scientific_review": _obj(
        ["verdict", "issues"],
        {"verdict": {"enum": ["approve", "revise"]},
         "issues": {"type": "array", "items": _issue},
         "required_changes": _strs},
    ),
    "implement": _obj(
        ["summary"],
        {"summary": _nstr, "files_changed": _strs, "tests_added": _strs,
         "design_notes": _str},
    ),
    "build": _obj(
        ["summary"],
        {"summary": _nstr, "files_changed": _strs, "tests_added": _strs,
         "design_notes": _str, "mandate_refs": _strs},
    ),
    "rebuild": _obj(
        ["summary", "architecture_change"],
        {"summary": _nstr, "architecture_change": _nstr, "files_changed": _strs,
         "tests_added": _strs},
    ),
    "redesign": _obj(
        ["summary", "architecture_change"],
        {"summary": _nstr, "architecture_change": _nstr, "files_changed": _strs,
         "tests_added": _strs},
    ),
    "verify": _obj(
        ["verdict", "findings", "reproducibility_ok", "protocol_compliance_ok"],
        {"verdict": {"enum": ["pass", "fail"]},
         "findings": {"type": "array", "items": _issue},
         "tests_added": _strs,
         "reproducibility_ok": {"type": "boolean"},
         "protocol_compliance_ok": {"type": "boolean"}},
    ),
    "scientific_validation": _obj(
        ["verdict", "issues"],
        {"verdict": {"enum": ["approve", "reject"]},
         "issues": {"type": "array", "items": _issue},
         "send_back_to": {"enum": ["engineering", "design"]}},
    ),
    "interpret": _obj(
        ["interpretation", "alternative_explanations", "limitations"],
        {"interpretation": _nstr, "alternative_explanations": _strs,
         "limitations": _strs},
    ),
    "challenge": _obj(
        ["verdict", "issues", "alternative_explanations"],
        {"verdict": {"enum": ["upheld", "challenged"]},
         "issues": {"type": "array", "items": _issue},
         "alternative_explanations": _strs, "requested_controls": _strs},
    ),
    "communicate": _obj(["summary"], {"summary": _nstr, "audience_notes": _str}),
    "next_question": _obj(
        ["questions", "continue"],
        {"questions": {"type": "array",
                       "items": _obj(["question", "rationale"],
                                     {"question": _nstr, "rationale": _nstr,
                                      "priority": {"type": "integer"}})},
         "continue": {"type": "boolean"}},
    ),
}

COMPLETION_SCHEMA = {
    "type": "object",
    "required": ["status", "summary", "payload"],
    "properties": {
        "status": {"enum": ["complete", "blocked", "needs_review", "failed"]},
        "summary": _str,
        "payload": {"type": "object"},
        "research_claims": {"type": "array", "items": CLAIM_SCHEMA},
        "risks": _strs,
        "next_action": _str,
    },
}


class ProtocolError(Exception):
    """An agent response violated the communication protocol."""


@dataclass
class TaskPacket:
    task_id: str
    role: Role
    stage: str
    objective: str
    context: dict = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    workdir: str | None = None
    writable: bool = False
    attempt: int = 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["role"] = self.role.value
        d["output_schema"] = completion_schema_for(self.stage)
        return d


def completion_schema_for(stage: str) -> dict:
    schema = json.loads(json.dumps(COMPLETION_SCHEMA))
    schema["properties"]["payload"] = STAGE_SCHEMAS[stage]
    return schema


def validate_completion(stage: str, completion: Any) -> dict:
    if not isinstance(completion, dict):
        raise ProtocolError("completion must be a JSON object")
    try:
        jsonschema.validate(completion, completion_schema_for(stage))
    except jsonschema.ValidationError as exc:
        path = "/".join(str(p) for p in exc.absolute_path)
        raise ProtocolError(f"stage {stage}: {exc.message} at /{path}") from None
    return completion


def validate_protocol(protocol: dict) -> list[str]:
    """Schema + semantic checks for an experiment protocol."""
    errors: list[str] = []
    try:
        jsonschema.validate(protocol, PROTOCOL_SCHEMA)
    except jsonschema.ValidationError as exc:
        return [exc.message]
    names = [c["name"] for c in protocol["conditions"]]
    if len(set(names)) != len(names):
        errors.append("condition names must be unique")
    roles = {c["role"] for c in protocol["conditions"]}
    if "baseline" not in roles:
        errors.append("protocol needs a baseline condition")
    if "intervention" not in roles:
        errors.append("protocol needs an intervention condition")
    rule = protocol["decision_rule"]
    for key in ("treatment", "control"):
        if rule[key] not in names:
            errors.append(f"decision_rule.{key}={rule[key]!r} is not a condition")
    metrics = {protocol["metrics"]["primary"], *protocol["metrics"].get("secondary", [])}
    for label, r in [("decision_rule", rule)] + [
            (f"decision_rule.co_primary[{i}]", r) for i, r in enumerate(rule.get("co_primary", []))]:
        if r.get("type", "superiority") == "non_inferiority":
            if not r.get("margin"):
                errors.append(f"{label}: a non_inferiority rule needs margin > 0")
        elif not r.get("min_effect") or r["min_effect"] <= 0:
            errors.append(f"{label}: min_effect must be > 0 (smallest effect size of interest);"
                          " with 0 an 'unsupported' outcome is unreachable and null results can"
                          " only ever be 'inconclusive'")
        for key in ("treatment", "control"):
            if key in r and r[key] not in names:
                errors.append(f"{label}.{key}={r[key]!r} is not a condition")
        if label != "decision_rule" and r["metric"] not in metrics:
            errors.append(f"{label}: metric {r['metric']!r} is not a declared metric")
    if rule["metric"] != protocol["metrics"]["primary"]:
        errors.append("decision_rule.metric must be the pre-specified primary metric")
    for key in ("validity_checks", "success_checks"):
        for chk in protocol.get(key, []):
            if chk["condition"] not in names:
                errors.append(f"{key} {chk['id']}: condition {chk['condition']!r} is not one of "
                              f"{sorted(names)}")
            if chk.get("relative_to") and chk["relative_to"] not in names:
                errors.append(f"{key} {chk['id']}: relative_to {chk['relative_to']!r} is not a "
                              f"condition")
            if chk["metric"] not in metrics:
                errors.append(f"{key} {chk['id']}: metric {chk['metric']!r} is not a declared "
                              f"metric {sorted(metrics)}")
    if not protocol.get("validity_checks"):
        errors.append("protocol needs >= 1 validity_check (instrument sanity check)")
    fixed = set(protocol.get("fixed_params", {}))
    for c in protocol["conditions"]:
        clash = sorted(fixed & set(c.get("params", {})))
        if clash:
            errors.append(f"condition {c['name']!r} overrides fixed_params {clash}; a parameter "
                          f"is either fixed for all conditions or set per condition")
    if len(set(protocol["seeds"])) != len(protocol["seeds"]):
        errors.append("seeds must be unique")
    if rule.get("unit", "seed") == "item":
        # Replication comes from the evaluation items; seeds are repeated samples.
        if rule.get("pairing") == "unpaired":
            errors.append("decision_rule.unit='item' is always paired by item; remove "
                          "pairing='unpaired'")
        if "n_items" not in protocol:
            errors.append("decision_rule.unit='item' needs n_items (the frozen number of "
                          "evaluation items every trial reports in items.json)")
    elif len(protocol["seeds"]) < 3:
        errors.append("protocols need >= 3 seeds (confidence intervals need replication)")
    if protocol.get("budget", {}).get("max_cost_usd") is not None and "cost_usd" not in metrics:
        errors.append("budget.max_cost_usd needs 'cost_usd' declared as a metric (each trial "
                      "reports its spend in metrics.json)")
    for dp in protocol.get("data_paths", []):
        if dp.startswith(("/", "\\")) or ":" in dp or ".." in dp.replace("\\", "/").split("/"):
            errors.append(f"data_paths entry {dp!r} must be a relative path inside the repo")
    return errors


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def extract_json(text: str) -> dict:
    """Pull the final JSON object out of an LLM response.

    Preference order: whole text is JSON; last fenced ```json block; last
    balanced top-level ``{...}`` in the text.
    """
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    blocks = _FENCE.findall(text)
    for block in reversed(blocks):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    # last balanced object
    end = text.rfind("}")
    while end != -1:
        depth = 0
        for i in range(end, -1, -1):
            ch = text[i]
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[i:end + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        end = text.rfind("}", 0, end)
    raise ProtocolError("no JSON object found in agent response")
