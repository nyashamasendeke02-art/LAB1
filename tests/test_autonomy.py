"""Unattended operation (D35): agent usage limits wait instead of failing; task queues."""

from pathlib import Path

from autolab.agents import BackendError, is_usage_limit
from autolab.queue import load_queue, run_queue

from scenario import make
from test_p0_lab_upgrades import REVIEW_CONFIG, build_ok, verify_spec

LIMIT_MSG = ("claude exited 1 (is_error=True): You've hit your session limit · "
             "resets 3:10pm (America/Los_Angeles)")


def test_usage_limit_detection():
    assert is_usage_limit(BackendError(LIMIT_MSG))
    assert is_usage_limit(BackendError("codex exited 1: stderr='429 Too Many Requests'"))
    assert not is_usage_limit(BackendError("claude exited 1: stderr='segfault'"))
    assert not is_usage_limit(ValueError("usage limit"))  # only agent backend errors


def test_usage_limit_waits_without_counting_a_retry(tmp_path):
    calls = {"n": 0}

    def build(t):
        calls["n"] += 1
        if calls["n"] <= 4:  # more than max_stage_retries would allow
            raise BackendError(LIMIT_MSG)
        return build_ok(t)

    lab, ctl = make(tmp_path, eng__build=build, ver__verify=verify_spec)
    slept = []
    ctl.sleep = slept.append
    pid = ctl.new_engineering_project("contract module", ["tests pass"])
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE", steps[-1]
    assert slept == [900.0] * 4
    fails = [f for f in lab.store.query("failure") if f.data.get("category") == "usage_limit"]
    assert len(fails) == 4


def test_usage_limit_halts_after_max_wait(tmp_path):
    def build(t):
        raise BackendError(LIMIT_MSG)

    lab, ctl = make(tmp_path, eng__build=build)
    ctl.limits = {**ctl.limits, "usage_limit_wait_s": 100, "usage_limit_max_wait_s": 250}
    slept = []
    ctl.sleep = slept.append
    pid = ctl.new_engineering_project("contract module", ["tests pass"])
    steps = ctl.run(pid)
    assert slept == [100.0, 100.0]
    assert steps[-1].after == "HALTED"
    assert "usage limit" in ctl.project(pid).data["halt_reason"]


QUEUE = '''
[[task]]
id = "T1"
spec = "contract module"
accept = ["tests pass"]
refs = ["Gate 0"]

[[task]]
id = "T2"
spec = "safety kernel"
accept = ["limits enforced"]
'''


def test_queue_runs_in_order_skips_done_and_stops_at_gates(tmp_path):
    def build(t):
        out = build_ok(t)
        if t.objective == "safety kernel":
            (Path(t.workdir) / "src" / "safety").mkdir(parents=True, exist_ok=True)
            (Path(t.workdir) / "src" / "safety" / "kernel.py").write_text("LIMIT = 1.0\n")
        return out

    lab, ctl = make(tmp_path, config=REVIEW_CONFIG, eng__build=build, ver__verify=verify_spec)
    qfile = tmp_path / "q.toml"
    qfile.write_text(QUEUE, encoding="utf-8")
    tasks = load_queue(qfile)
    logs = []
    out = run_queue(ctl, tasks, log=logs.append)
    assert out.status == "blocked" and out.task_id == "T2", out
    projects = lab.store.query("project")
    assert [p.data["objective"] for p in projects] == ["contract module", "safety kernel"]
    assert projects[0].data["state"] == "COMPLETE"
    assert lab.store.history(projects[0].id)[0].author == "claude-code"
    # re-running skips the finished task and does not resubmit the blocked one
    out2 = run_queue(ctl, tasks, log=logs.append)
    assert out2.status == "blocked" and len(lab.store.query("project")) == 2
    assert any("T1 already COMPLETE" in line for line in logs)


def test_queue_stops_on_a_previously_halted_task(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_engineering_project("contract module", ["tests pass"])
    ctl.halt(pid, "test")
    qfile = tmp_path / "q.toml"
    qfile.write_text(QUEUE, encoding="utf-8")
    out = run_queue(ctl, load_queue(qfile), log=lambda s: None)
    assert out.status == "halted" and out.project == pid
    assert len(lab.store.query("project")) == 1


def test_queue_retry_resubmits_a_halted_task_once(tmp_path):
    lab, ctl = make(tmp_path, eng__build=build_ok, ver__verify=verify_spec)
    pid = ctl.new_engineering_project("contract module", ["tests pass"])
    ctl.halt(pid, "backend misconfigured")
    qfile = tmp_path / "q.toml"
    qfile.write_text(QUEUE.split("[[task]]")[0] + "[[task]]" + QUEUE.split("[[task]]")[1],
                     encoding="utf-8")
    out = run_queue(ctl, load_queue(qfile), log=lambda s: None, retry={"T1"})
    assert out.status == "done"
    projects = lab.store.query("project")
    assert [p.data["state"] for p in projects] == ["HALTED", "COMPLETE"]


def test_network_errors_wait_briefly_and_are_not_failures(tmp_path):
    from autolab.agents import agent_wait_kind
    assert agent_wait_kind(BackendError("API Error: Connection dropped (ECONNRESET)")) == "network"
    assert agent_wait_kind(BackendError("API Error: No response from API (waited 3m)")) == "network"
    assert agent_wait_kind(BackendError("503 Service Unavailable")) == "network"
    assert agent_wait_kind(BackendError(LIMIT_MSG)) == "usage_limit"
    assert agent_wait_kind(BackendError("claude timed out after 1800s")) is None
    calls = {"n": 0}

    def build(t):
        calls["n"] += 1
        if calls["n"] <= 4:
            raise BackendError("claude exited 1: API Error: Connection dropped (ECONNRESET)")
        return build_ok(t)

    lab, ctl = make(tmp_path, eng__build=build, ver__verify=verify_spec)
    slept = []
    ctl.sleep = slept.append
    pid = ctl.new_engineering_project("contract module", ["tests pass"])
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert slept == [120.0] * 4
    assert len([f for f in lab.store.query("failure") if f.data["category"] == "network"]) == 4
