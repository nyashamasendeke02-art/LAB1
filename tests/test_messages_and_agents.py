import json

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
    with pytest.raises(ProtocolError):
        agent.run(TaskPacket("TASK-1", Role.SCIENTIST, "research_question", "obj"))


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
    claude = ClaudeCLIBackend()
    cmd = claude.command(TaskPacket("T", Role.ENGINEER, "implement", "o", writable=True))
    assert "--dangerously-skip-permissions" not in cmd
    assert "Bash(git:*)" in cmd[cmd.index("--disallowedTools") + 1]
    ro_cmd = claude.command(TaskPacket("T", Role.ENGINEER, "solution_design", "o"))
    assert "Edit" not in ro_cmd[ro_cmd.index("--allowedTools") + 1]


def test_openai_backend_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(BackendError):
        OpenAIBackend(model="m").invoke(TaskPacket("T", Role.SCIENTIST, "design", "o"), "p")


def test_make_backend():
    assert isinstance(make_backend({"backend": "claude-cli"}), ClaudeCLIBackend)
    assert isinstance(make_backend({"backend": "codex-cli"}), CodexCLIBackend)
    with pytest.raises(ValueError):
        make_backend({"backend": "gpt-telepathy"})
