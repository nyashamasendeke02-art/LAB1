"""D60: observability (tokens, cost, time per agent call) and agent scorecards."""

import json

from autolab.agents import Agent, ClaudeCLIBackend, ScriptedBackend, add_usage
from autolab.controller import Controller
from autolab.messages import TaskPacket
from autolab.scorecard import scorecards, totals
from autolab.taxonomy import Role

import scenario
from scenario import make, ok

# The shape Claude Code's `claude -p --output-format json` returned on 2026-10-08 (trimmed).
CLAUDE_JSON = {
    "type": "result", "subtype": "success", "is_error": False, "result": "OK",
    "duration_ms": 1398, "duration_api_ms": 1241, "num_turns": 1, "total_cost_usd": 0.0074183,
    "usage": {"input_tokens": 9, "cache_creation_input_tokens": 2800,
              "cache_read_input_tokens": 16093, "output_tokens": 40},
    "modelUsage": {"claude-haiku-4-5-20251001": {"inputTokens": 9, "outputTokens": 40,
                                                  "costUSD": 0.0074183}}}


def test_claude_usage_is_parsed_from_real_output():
    u = ClaudeCLIBackend.usage_of(json.dumps(CLAUDE_JSON))
    assert u == {"input_tokens": 9, "output_tokens": 40, "cache_read_tokens": 16093,
                 "cache_write_tokens": 2800, "cost_usd": 0.0074183, "api_duration_s": 1.241,
                 "turns": 1, "model": "claude-haiku-4-5-20251001"}
    assert ClaudeCLIBackend.usage_of("not json") is None
    assert ClaudeCLIBackend.usage_of(json.dumps({"result": "x"})) is None  # unknown, not zero


def test_usage_is_summed_across_protocol_retries():
    calls = {"n": 0}

    def flaky(t):
        calls["n"] += 1
        return "no json here" if calls["n"] == 1 else ok({"problem_statement": "p", "scope": "s"})

    backend = ScriptedBackend({"define_problem": flaky}, "m",
                              usage={"input_tokens": 100, "output_tokens": 10, "cost_usd": 0.5})
    res = Agent(Role.SCIENTIST, backend).run(TaskPacket("T", Role.SCIENTIST, "define_problem", "o"))
    assert res.attempts == 2 and res.usage["input_tokens"] == 200 and res.usage["cost_usd"] == 1.0
    assert add_usage(None, None) is None


def test_task_records_and_scorecards(tmp_path):
    def verify_with_finding(t):
        out = scenario.verify_pass(t)
        out["payload"]["findings"] = [{"severity": "minor", "description": "naming"}]
        return out

    lab, ctl = make(tmp_path, ver__verify=verify_with_finding)
    usage = {"input_tokens": 1000, "output_tokens": 100, "cost_usd": 0.01}
    for backend in ctl.injected.values():
        backend.usage = usage if backend.model == "s" else None  # only the scientist reports
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    tasks = lab.store.query("task")
    assert all(isinstance(t.data["wall_s"], float) for t in tasks)
    sci = [t for t in tasks if t.data["role"] == "scientist"]
    assert all(t.data["usage"]["input_tokens"] == 1000 for t in sci)
    assert all(t.data["usage"] is None for t in tasks if t.data["role"] != "scientist")
    cards = {c["agent"]: c for c in scorecards(lab.store)}
    s = cards["scientist"]
    assert s["input_tokens"] == 1000 * len(sci) and s["cost_usd"] == round(0.01 * len(sci), 4)
    assert s["success_rate"] == 1.0 and s["avg_wall_s"] is not None
    assert cards["engineer"]["input_tokens"] is None and cards["engineer"]["cost_usd"] is None
    # review credited to the code's author and to the reviewer
    assert cards["engineer"]["reviews_of_my_code"] == {"passed": 1, "failed": 0}
    assert cards["engineer"]["findings_caused"]["minor"] == 1
    assert cards["verifier"]["findings_raised"]["minor"] == 1
    t = totals(list(cards.values()))
    assert t["usage_reported_calls"] == len(sci) and t["cost_usd"] == round(0.01 * len(sci), 4)


def test_scorecard_reaches_the_dashboard(tmp_path):
    from autolab.web import DashboardServer
    lab, ctl = make(tmp_path)
    ctl.injected["scientist"].usage = {"input_tokens": 5, "output_tokens": 1, "cost_usd": 0.002}
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    ctl.run(pid)
    srv = DashboardServer(lab, "127.0.0.1", 0)
    try:
        agents = {a["name"]: a for a in srv.agents()}
        assert agents["scientist"]["scorecard"]["cost_usd"] > 0
        assert srv.overview()["usage"]["cost_usd"] > 0
    finally:
        srv.httpd.server_close()
