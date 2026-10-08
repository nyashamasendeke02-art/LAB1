"""D64: tool-call logging (master prompt s.18): every tool an agent used is logged, attributable,
observable; denied calls raise an event. Fixture: real Claude Code stream-json output
(2026-10-08, anonymised) where the agent read a file and was denied `git status`."""

import json
from pathlib import Path

from autolab.agents import ClaudeCLIBackend, _clip_input
from autolab.messages import TaskPacket
from autolab.scorecard import scorecards
from autolab.taxonomy import Role

from scenario import make

FIXTURE = Path(__file__).with_name("data") / "claude_stream_tools.jsonl"


def test_real_stream_is_parsed():
    result, calls = ClaudeCLIBackend.parse_stream(FIXTURE.read_text(encoding="utf-8"))
    assert result["type"] == "result" and result["result"] == "banana"
    assert [(c["tool"], c["ok"], c["denied"]) for c in calls] == [("Read", True, False),
                                                                ("Bash", False, True)]
    assert calls[0]["result_chars"] > 0 and "denied" in calls[1]["error"]
    assert calls[1]["input"]["command"] == "git status"
    # the final answer goes through the unchanged json parser
    assert ClaudeCLIBackend.parse_output(0, json.dumps(result), "") == "banana"
    usage = ClaudeCLIBackend.usage_of(json.dumps(result))
    assert usage["cost_usd"] > 0 and usage["output_tokens"] > 0


def test_stream_fallbacks():
    obj = {"type": "result", "result": "x", "is_error": False}
    assert ClaudeCLIBackend.parse_stream(json.dumps(obj)) == (obj, None)  # plain json: unknown
    assert ClaudeCLIBackend.parse_stream("not json at all") == (None, None)
    assert ClaudeCLIBackend.parse_stream("") == (None, None)


def test_command_streams_events_and_inputs_are_clipped():
    cmd = ClaudeCLIBackend().command(TaskPacket("T", Role.ENGINEER, "implement", "o", writable=True))
    i = cmd.index("--output-format")
    assert cmd[i + 1] == "stream-json" and "--verbose" in cmd
    clipped = _clip_input({"file_path": "a.py", "content": "x" * 5000, "replace_all": False})
    assert clipped == {"file_path": "a.py", "content": "<5000 chars>", "replace_all": False}


def test_controller_logs_tools_per_task_and_scorecards(tmp_path):
    lab, ctl = make(tmp_path)
    eng = ctl.injected["engineer"]
    eng.tool_calls = [{"id": "t1", "tool": "Edit", "input": {"file_path": "x.py"}, "ok": True,
                       "denied": False, "error": None, "result_chars": 10},
                      {"id": "t2", "tool": "Bash", "input": {"command": "git push"}, "ok": False,
                       "denied": True, "error": "denied", "result_chars": 5}]
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    impl = next(t for t in lab.store.query("task") if t.data["stage"] == "implement")
    tools = impl.data["tools"]
    assert tools["logged"] and tools["count"] == 2 and tools["by_tool"] == {"Edit": 1, "Bash": 1}
    assert tools["denied"] == [{"tool": "Bash", "input": {"command": "git push"}}]
    assert lab.artifacts.has(tools["artifact"][7:])
    lines = (lab.handoffs / impl.id / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["tool"] for x in lines] == ["Edit", "Bash"]
    assert any(e["type"] == "ToolPermissionDenied" and e["subject"] == impl.id
               for e in lab.store.events())
    sci = next(t for t in lab.store.query("task") if t.data["stage"] == "design")
    assert sci.data["tools"] == {"logged": False}  # backend did not report: not invented
    cards = {c["agent"]: c for c in scorecards(lab.store)}
    assert cards["engineer"]["tool_calls"] >= 2 and cards["engineer"]["tool_denied"] >= 1
    assert cards["scientist"]["tool_calls"] is None


def test_task_api_returns_the_tool_trail(tmp_path):
    from autolab.web import DashboardServer
    lab, ctl = make(tmp_path)
    ctl.injected["engineer"].tool_calls = [{"id": "t1", "tool": "Read", "input": {"file_path": "a"},
                                            "ok": True, "denied": False, "error": None,
                                            "result_chars": 3}]
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    ctl.run(pid)
    impl = next(t for t in lab.store.query("task") if t.data["stage"] == "implement")
    srv = DashboardServer(lab, "127.0.0.1", 0)
    try:
        assert srv.task(impl.id)["tool_calls"][0]["tool"] == "Read"
        design = next(t for t in lab.store.query("task") if t.data["stage"] == "design")
        assert srv.task(design.id)["tool_calls"] is None
    finally:
        srv.httpd.server_close()
