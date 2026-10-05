import json
import sys

import pytest

from autolab.agents import (Agent, ClaudeCLIBackend, CodexCLIBackend, OpenAIBackend,
                            BackendError, ScriptedBackend, make_backend)
from autolab.messages import (ProtocolError, TaskPacket, extract_json, validate_completion,
                              validate_protocol)
from autolab.taxonomy import Role, check_label_change, validate_claim

from scenario import protocol


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('blah\n```json\n{"a": 2}\n```\nmore') == {"a": 2}
    assert extract_json('I think {"x": {"y": 3}} is the answer') == {"x": {"y": 3}}
    with pytest.raises(ProtocolError):
        extract_json("no json here")


def test_completion_validation():
    good = {"status": "complete", "summary": "s",
            "payload": {"question": "q?", "rationale": "r"}}
    validate_completion("research_question", good)
    bad = {**good, "payload": {"question": "q?"}}
    with pytest.raises(ProtocolError):
        validate_completion("research_question", bad)
    with pytest.raises(ProtocolError):
        validate_completion("research_question", {**good, "status": "done"})


def test_protocol_semantic_checks():
    assert validate_protocol(protocol()) == []
    p = protocol()
    p["conditions"][1]["role"] = "ablation"
    assert any("intervention" in e for e in validate_protocol(p))
    p = protocol()
    p["decision_rule"]["metric"] = "other"
    assert any("primary metric" in e for e in validate_protocol(p))
    assert any(">= 3 seeds" in e for e in validate_protocol(protocol("confirmatory", seeds=(1, 2))))
    assert any(">= 3 seeds" in e for e in validate_protocol(protocol(seeds=(1, 2))))


def test_protocol_rejects_unknown_or_misplaced_keys():
    """R7 regression: a misplaced key must not be silently dropped in favour of a default."""
    p = protocol()
    p["pairing"] = "paired"  # belongs inside decision_rule
    assert any("pairing" in e for e in validate_protocol(p))
    p = protocol()
    p["decision_rule"]["alhpa"] = 0.01
    assert validate_protocol(p)
    p = protocol()
    p["conditions"][0]["param"] = {"effect": 1}
    assert validate_protocol(p)


def test_condition_params_may_not_override_fixed_params():
    p = protocol()
    p["fixed_params"] = {"noise": 0.1, "lr": 0.5}
    assert any("overrides fixed_params ['noise']" in e for e in validate_protocol(p))
    p["fixed_params"] = {"lr": 0.5}
    assert validate_protocol(p) == []


def test_claim_taxonomy_enforcement():
    assert validate_claim({"type": "HYPOTHESIS", "statement": "x"}) == []
    assert validate_claim({"type": "SOURCE_CLAIM", "statement": "x"})  # needs sources
    assert validate_claim({"type": "EXPERIMENTAL_RESULT", "statement": "x",
                           "run_ids": ["RUN-9"]}, known_run_ids={"RUN-1"})
    assert validate_claim({"type": "PROVEN", "statement": "x"})
    with pytest.raises(ValueError):
        check_label_change("HYPOTHESIS", "ESTABLISHED", None)
    check_label_change("HYPOTHESIS", "ESTABLISHED", "replicated in RUN-3, RUN-4")


def test_agent_retries_on_protocol_violation():
    responses = ["not json", json.dumps({"status": "complete", "summary": "",
                                         "payload": {"question": "q", "rationale": "r"}})]
    backend = ScriptedBackend({"research_question": [lambda t: responses[0],
                                                     lambda t: responses[1]]})
    agent = Agent(Role.SCIENTIST, backend)
    res = agent.run(TaskPacket("TASK-1", Role.SCIENTIST, "research_question", "obj"))
    assert res.attempts == 2 and res.completion["payload"]["question"] == "q"


def test_agent_gives_up_after_retries():
    agent = Agent(Role.SCIENTIST, ScriptedBackend({"research_question": lambda t: "junk"}),
                  max_protocol_retries=1)
    with pytest.raises(ProtocolError) as exc:
        agent.run(TaskPacket("TASK-1", Role.SCIENTIST, "research_question", "obj"))
    # R8: the rejected responses travel with the error so the controller can store them
    assert exc.value.raw_responses == ["junk", "junk"] and len(exc.value.rejections) == 2


def test_agent_rejects_wrong_role():
    agent = Agent(Role.ENGINEER, ScriptedBackend({}))
    with pytest.raises(ValueError):
        agent.run(TaskPacket("TASK-1", Role.SCIENTIST, "research_question", "obj"))


def test_cli_backend_commands_are_sandboxed():
    t_ro = TaskPacket("T", Role.SCIENTIST, "design", "o", workdir="/w", writable=False)
    t_rw = TaskPacket("T", Role.VERIFIER, "verify", "o", workdir="/w", writable=True)
    codex = CodexCLIBackend(model="m")
    ro = codex.command(t_ro, "out.txt")
    assert ro[ro.index("--sandbox") + 1] == "read-only"
    rw = codex.command(t_rw, "out.txt")
    assert rw[rw.index("--sandbox") + 1] == "workspace-write"
    assert "--dangerously-bypass-approvals-and-sandbox" not in rw
    # Hermetic mode drops the user's [windows] sandbox setting; restore only that.
    elevated = 'windows.sandbox="elevated"'
    assert (elevated in rw) == (sys.platform == "win32") and elevated not in ro
    claude = ClaudeCLIBackend()
    cmd = claude.command(TaskPacket("T", Role.ENGINEER, "implement", "o", writable=True))
    assert "--dangerously-skip-permissions" not in cmd
    assert "Bash(git:*)" in cmd[cmd.index("--disallowedTools") + 1]
    ro_cmd = claude.command(TaskPacket("T", Role.ENGINEER, "solution_design", "o"))
    assert "Edit" not in ro_cmd[ro_cmd.index("--allowedTools") + 1]


def test_cli_backends_are_hermetic():
    """R5 regression: agents must not inherit the user's CLAUDE.md, memory, plugins,
    skills, MCP servers or codex config; the task packet is their only context."""
    for writable in (False, True):
        cmd = ClaudeCLIBackend().command(TaskPacket("T", Role.ENGINEER, "implement", "o",
                                                    writable=writable))
        assert cmd[cmd.index("--setting-sources") + 1] == ""
        assert "--strict-mcp-config" in cmd and "--mcp-config" not in cmd
        assert "--disable-slash-commands" in cmd
        assert json.loads(cmd[cmd.index("--settings") + 1]) == {"autoMemoryEnabled": False}
    assert ClaudeCLIBackend.HERMETIC_ENV == {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    cmd = CodexCLIBackend().command(TaskPacket("T", Role.SCIENTIST, "design", "o"), "out.txt")
    assert "--ignore-user-config" in cmd and "--ignore-rules" in cmd
    disabled = {cmd[i + 1] for i, a in enumerate(cmd) if a == "--disable"}
    assert {"plugins", "apps", "memories", "browser_use", "computer_use"} <= disabled


def test_openai_backend_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(BackendError):
        OpenAIBackend(model="m").invoke(TaskPacket("T", Role.SCIENTIST, "design", "o"), "p")


def test_make_backend():
    assert isinstance(make_backend({"backend": "claude-cli"}), ClaudeCLIBackend)
    assert isinstance(make_backend({"backend": "codex-cli"}), CodexCLIBackend)
    with pytest.raises(ValueError):
        make_backend({"backend": "gpt-telepathy"})


def test_validity_checks_must_bind_to_protocol_conditions_and_metrics():
    p = protocol()
    p["validity_checks"][0]["condition"] = "each paired seed, easy vs random"  # prose (pilot-001)
    p["validity_checks"].append({"id": "V2", "description": "d", "metric": "derived_diff",
                                 "condition": "base", "op": ">", "value": 0})
    errs = validate_protocol(p)
    assert any("V1" in e and "condition" in e for e in errs)
    assert any("V2" in e and "metric" in e for e in errs)
    p = protocol()
    p["validity_checks"] = []
    assert any("validity_check" in e for e in validate_protocol(p))


def test_requirements_stage_is_prose_only():
    validate_completion("requirements", {"status": "complete", "summary": "", "payload": {
        "validity_criteria": ["baseline learns"], "engineering": ["tests"]}})
    with pytest.raises(ProtocolError):
        validate_completion("requirements", {"status": "complete", "summary": "", "payload": {
            "validity_criteria": [], "engineering": []}})


def test_claude_errors_reported_on_stdout_are_surfaced():
    limit = json.dumps({"is_error": True, "result": "Usage limit reached", "subtype": "error"})
    with pytest.raises(BackendError, match="Usage limit reached"):
        ClaudeCLIBackend.parse_output(1, limit, "")
    with pytest.raises(BackendError, match="Usage limit reached"):
        ClaudeCLIBackend.parse_output(0, limit, "")  # exit 0 but is_error
    with pytest.raises(BackendError, match="boom"):
        ClaudeCLIBackend.parse_output(1, "not json", "boom")
    ok = json.dumps({"is_error": False, "result": "{\"a\": 1}"})
    assert ClaudeCLIBackend.parse_output(0, ok, "") == '{"a": 1}'


def test_min_effect_must_be_positive_so_null_is_concludable():
    p = protocol()
    p["decision_rule"]["min_effect"] = 0
    assert any("min_effect must be > 0" in e for e in validate_protocol(p))


def test_relative_to_must_name_a_condition():
    p = protocol()
    p["validity_checks"].append({"id": "R", "description": "d", "metric": "score",
                                 "condition": "treat", "relative_to": "ghost", "op": ">",
                                 "value": 0})
    assert any("relative_to" in e for e in validate_protocol(p))
    p["validity_checks"][-1]["relative_to"] = "base"
    p["fixed_params"] = {"lr": 0.01}
    assert validate_protocol(p) == []


def test_non_inferiority_and_co_primary_rules_validate():
    p = protocol()
    p["metrics"]["secondary"] = ["calls"]
    p["decision_rule"] = {"metric": "score", "treatment": "treat", "control": "base",
                          "direction": "greater", "type": "non_inferiority", "margin": 0.2,
                          "co_primary": [{"metric": "calls", "direction": "less",
                                          "min_effect": 1}]}
    assert validate_protocol(p) == []
    p["decision_rule"].pop("margin")
    p["decision_rule"]["co_primary"].append({"metric": "ghost", "direction": "less",
                                             "min_effect": 1, "control": "nobody"})
    errs = validate_protocol(p)
    assert any("margin" in e for e in errs)
    assert any("ghost" in e for e in errs) and any("nobody" in e for e in errs)


def test_design_and_review_prompts_state_the_fixed_analysis():
    from autolab.prompts import ANALYSIS_METHOD, ENTRYPOINT_CONTRACT, STAGES
    assert ANALYSIS_METHOD in STAGES["scientific_review"]
    assert ANALYSIS_METHOD in STAGES["design"]
    assert ENTRYPOINT_CONTRACT in STAGES["scientific_review"]
    assert "Welch" in ANALYSIS_METHOD and "non-inferiority" in ANALYSIS_METHOD.lower()
