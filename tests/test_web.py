"""Local dashboard (`autolab ui`): loopback only, Host/token/Origin checks, safe writes."""

import http.client
import json
import re
import threading

import pytest

from autolab.controller import Lab
from autolab.gates import Gates
from autolab.web import DashboardServer

from scenario import FAST_CONFIG


@pytest.fixture
def ui(tmp_path):
    # SQLite connections are per-thread: the server thread opens its own Lab, as
    # `autolab ui` does in its single thread; the test inspects through another.
    Lab.init(tmp_path / "lab", config_text=FAST_CONFIG)
    ready, holder = threading.Event(), {}

    def serve():
        holder["server"] = DashboardServer(Lab(tmp_path / "lab"), "127.0.0.1", 0)
        ready.set()
        holder["server"].httpd.serve_forever(poll_interval=0.05)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(10)
    server = holder["server"]
    yield Lab(tmp_path / "lab"), server
    server.httpd.shutdown()
    server.httpd.server_close()


def call(server, method, path, body=None, host=None, token=None, origin=None):
    port = server.httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Autolab-Token"] = token
    if origin:
        headers["Origin"] = origin
    conn.request(method, path, None if body is None else json.dumps(body), headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_refuses_non_loopback_bind(tmp_path):
    lab = Lab.init(tmp_path / "lab", config_text=FAST_CONFIG)
    with pytest.raises(ValueError):
        DashboardServer(lab, "0.0.0.0", 0)


def test_page_and_state(ui):
    lab, server = ui
    status, page = call(server, "GET", "/")
    assert status == 200 and server.token.encode() in page
    status, body = call(server, "GET", "/api/state")
    state = json.loads(body)
    assert status == 200 and state["projects"] == [] and state["approvals"] == []
    assert {a["role"] for a in state["agents"]} >= {"scientist", "engineer", "verifier"}


def test_dns_rebinding_host_is_rejected(ui):
    lab, server = ui
    port = server.httpd.server_address[1]
    status, _ = call(server, "GET", "/", host=f"evil.example:{port}")
    assert status == 421
    status, _ = call(server, "POST", "/api/projects", {"objective": "x"},
                     host=f"evil.example:{port}", token=server.token,
                     origin=f"http://evil.example:{port}")
    assert status in (403, 421)
    assert lab.store.query("project") == []


def test_writes_need_token_and_same_origin(ui):
    lab, server = ui
    port = server.httpd.server_address[1]
    body = {"kind": "research", "objective": "Investigate whether X can produce Y"}
    assert call(server, "POST", "/api/projects", body)[0] == 403
    assert call(server, "POST", "/api/projects", body, token=server.token,
                origin="http://other.example")[0] == 403
    status, data = call(server, "POST", "/api/projects", body, token=server.token,
                        origin=f"http://127.0.0.1:{port}")
    assert status == 200 and re.fullmatch(r"PRJ-\d{4}", json.loads(data)["id"])
    rec = lab.store.history(json.loads(data)["id"])[0]
    assert rec.author == "human"


def test_engineering_project_needs_acceptance(ui):
    lab, server = ui
    status, _ = call(server, "POST", "/api/projects",
                     {"kind": "engineering", "objective": "spec", "acceptance": []},
                     token=server.token)
    assert status == 400 and lab.store.query("project") == []


def test_human_decision_is_recorded(ui):
    lab, server = ui
    apr = Gates(lab.store).request("review:safety", "ENG-0001@abc", "safety review")
    status, data = call(server, "POST", f"/api/approvals/{apr.id}",
                        {"approved": True, "note": "read the diff"}, token=server.token)
    assert status == 200 and json.loads(data)["status"] == "approved"
    rec = lab.store.get(apr.id)
    assert rec.data["decided_by"] == "human" and rec.data["note"] == "read the diff"


def test_no_writes_while_an_agent_call_is_in_flight(ui):
    lab, server = ui
    apr = Gates(lab.store).request("review:safety", "ENG-0001@abc", "safety review")
    lab.store.append_event("controller", "task.dispatched", "TASK-0001",
                           {"role": "engineer", "stage": "build", "project": "PRJ-0001"})
    status, data = call(server, "POST", f"/api/approvals/{apr.id}",
                        {"approved": True, "note": "x"}, token=server.token)
    assert status == 400 and b"agent call is in progress" in data
    assert lab.store.get(apr.id).data["status"] == "pending"
    state = json.loads(call(server, "GET", "/api/state")[1])
    assert any(a["role"] == "engineer" and a["status"] == "working" for a in state["agents"])


def test_task_detail_rejects_path_tricks(ui):
    lab, server = ui
    assert call(server, "GET", "/api/tasks/..%2F..%2Flab.toml")[0] == 404
    assert call(server, "GET", "/api/tasks/TASK-0001")[0] == 404


def test_assets_are_served_with_a_strict_csp(ui):
    lab, server = ui
    port = server.httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    for path, ctype in (("/", "text/html"), ("/assets/app.js", "text/javascript"),
                        ("/assets/app.css", "text/css")):
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 200 and resp.getheader("Content-Type").startswith(ctype)
        csp = resp.getheader("Content-Security-Policy")
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    conn.close()


def test_overview_projects_and_detail(ui):
    lab, server = ui
    body = {"kind": "engineering", "objective": "G2-1 World Model. Build it.",
            "acceptance": ["tests pass"], "refs": ["Gate 2"]}
    pid = json.loads(call(server, "POST", "/api/projects", body, token=server.token)[1])["id"]
    o = json.loads(call(server, "GET", "/api/overview")[1])
    assert o["counts"]["projects"] == 1 and o["ledger"]["ok"] is True
    assert o["gates"] == [{"gate": 2, "tasks": [{"key": "G2-1", "project": pid, "state": "ENGINEERING",
                                                   "eng_state": "SPEC", "title": "G2-1 World Model."}]}]
    detail = json.loads(call(server, "GET", f"/api/projects/{pid}")[1])
    assert detail["key"] == "G2-1" and detail["acceptance_criteria"] == ["tests pass"]
    assert call(server, "GET", "/api/projects/PRJ-9999")[0] == 404
    assert json.loads(call(server, "GET", "/api/activity?limit=5")[1])


def test_decision_needs_a_note(ui):
    lab, server = ui
    apr = Gates(lab.store).request("review:safety", "ENG-0001@abc", "safety review")
    status, data = call(server, "POST", f"/api/approvals/{apr.id}",
                        {"approved": True, "note": "  "}, token=server.token)
    assert status == 400 and b"note" in data
    assert lab.store.get(apr.id).data["status"] == "pending"
    detail = json.loads(call(server, "GET", f"/api/approvals/{apr.id}")[1])
    assert detail["status"] == "pending" and detail["diff"] == ""


def test_live_stream_announces_ledger_changes(ui):
    lab, server = ui
    port = server.httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/api/stream", headers={"Host": f"127.0.0.1:{port}"})
    resp = conn.getresponse()
    assert resp.getheader("Content-Type").startswith("text/event-stream")
    def next_change() -> bytes:
        for _ in range(40):  # retry line, events, heartbeats
            line = resp.fp.readline()
            if line.startswith(b"event: change"):
                return resp.fp.readline()  # its data line
        raise AssertionError("no change event")

    first = next_change()  # initial state
    Gates(lab.store).request("review:safety", "ENG-0002@abc", "another review")
    second = next_change()  # pushed because the ledger head moved
    assert first != second and b'"ledger"' in second
    conn.close()


def test_readable_error_and_favicon(ui):
    from autolab.web import classify_error, readable_error
    raw = ("BackendError: codex exited 1: stderr='...schema...\n```\n\nERROR: You've hit your usage "
           "limit. Upgrade to Plus to continue using Codex, or try again at Nov 3rd, 2026 9:58 AM.\n'")
    assert readable_error(raw).startswith("You've hit your usage limit.")
    assert classify_error(raw) == "usage_limit"
    assert classify_error("claude timed out after 1800s") == "timeout"
    assert classify_error("API Error: Connection dropped (ECONNRESET)") == "network"
    lab, server = ui
    status, body = call(server, "GET", "/favicon.ico")
    assert status == 200 and body.startswith(b"<svg")


def test_meta_publishes_the_lab_vocabulary(ui):
    lab, server = ui
    meta = json.loads(call(server, "GET", "/api/meta")[1])
    from autolab.registry import BACKENDS, STAGES
    from autolab.state_machines import ResearchState
    assert meta["research_states"] == [s.value for s in ResearchState]
    assert {s["name"] for s in meta["stages"]} == {s.name for s in STAGES}
    assert {b["name"] for b in meta["backends"]} == set(BACKENDS)
    assert meta["tones"]["HALTED"] == "bad" and "COMPLETE" in meta["research_done"]
    assert [k["value"] for k in meta["project_kinds"]] == ["research", "engineering"]
    assert meta["ui"]["milestone_label"] == "Gate"


def test_agents_and_allocation_are_editable_through_the_api(ui):
    lab, server = ui
    port = server.httpd.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    spec = {"spec": {"backend": "gemini-cli", "model": "some-model", "title": "Critic"}}
    assert call(server, "POST", "/api/agents/critic", spec)[0] == 403  # token required
    status, data = call(server, "POST", "/api/agents/critic", spec, token=server.token,
                        origin=origin)
    assert status == 200 and "critic" in json.loads(data)["agents"]
    status, data = call(server, "POST", "/api/allocation",
                        {"allocation": {"scientific_review": "critic"}}, token=server.token)
    assert status == 200 and json.loads(data)["effective"]["scientific_review"] == "critic"
    agents = json.loads(call(server, "GET", "/api/agents")[1])
    critic = next(a for a in agents if a["name"] == "critic")
    assert critic["stages"] == ["scientific_review"] and critic["model"] == "some-model"
    # an API-only backend cannot take a writing stage
    call(server, "POST", "/api/agents/apionly", {"spec": {"backend": "openai-api", "model": "x"}},
         token=server.token)
    status, data = call(server, "POST", "/api/allocation", {"allocation": {"implement": "apionly"}},
                        token=server.token)
    assert status == 400 and b"writing stage" in data
    status, data = call(server, "POST", "/api/agents/preset", {"name": "organisation"},
                        token=server.token)
    assert status == 200 and "literature" in json.loads(data)["created"]
    assert (lab.root / "agents.toml").exists()
    status, _ = call(server, "POST", "/api/agents/engineer/remove", {}, token=server.token)
    assert status == 400


def test_registry_edits_refused_while_an_agent_call_is_in_flight(ui):
    lab, server = ui
    lab.store.append_event("controller", "task.dispatched", "TASK-0001",
                           {"role": "engineer", "stage": "build", "project": "PRJ-0001"})
    status, data = call(server, "POST", "/api/agents/critic",
                        {"spec": {"backend": "claude-cli"}}, token=server.token)
    assert status == 400 and b"agent call is in progress" in data
    assert not (lab.root / "agents.toml").exists()


def test_knowledge_api_search_node_and_spawn(ui):
    lab, server = ui
    hyp = lab.store.create("hypothesis", {"statement": "momentum lowers iterations",
                                          "project": "PRJ-0001", "status": "supported",
                                          "refs": {}}, prefix="HYP")
    con = lab.store.create("conclusion", {
        "hypothesis": hyp.id, "statement": "momentum lowers iterations", "outcome": "supported",
        "label": "EXPERIMENTAL_RESULT", "experiment_kind": "exploratory",
        "confidence": "preliminary (exploratory)", "project": "PRJ-0001",
        "refs": {"hypothesis": hyp.id, "result": "RES-0001"}}, prefix="CON")
    fq = lab.store.create("future_question", {"question": "Does momentum help on noisy losses?",
                                              "priority": 1, "status": "open",
                                              "project": "PRJ-0001",
                                              "refs": {"conclusion": con.id}}, prefix="FQ")
    k = json.loads(call(server, "GET", "/api/knowledge")[1])
    assert k["stats"]["nodes"] == 3 and k["open_questions"][0]["source"] == f"lab:lab/{fq.id}"
    hits = json.loads(call(server, "GET", "/api/knowledge/search?q=momentum&kind=conclusion")[1])
    assert [h["source"] for h in hits] == [f"lab:lab/{con.id}"]
    node = json.loads(call(server, "GET", f"/api/knowledge/node?id=lab:lab/{con.id}")[1])
    assert node["out"][0]["relation"] == "supports"  # typed relations (D59)
    assert node["out"][0]["source"].endswith(hyp.id)
    assert any(e["relation"] == "motivates" and e["source"].endswith(fq.id) for e in node["out"])
    assert call(server, "GET", "/api/knowledge/node?id=lab:lab/CON-9999")[0] == 404
    assert call(server, "POST", "/api/knowledge/spawn", {"source": f"lab:lab/{fq.id}"})[0] == 403
    status, data = call(server, "POST", "/api/knowledge/spawn", {"source": f"lab:lab/{fq.id}"},
                        token=server.token)
    assert status == 200
    pid = json.loads(data)["id"]
    assert lab.store.get(pid).data["origin"]["question"] == fq.id
    assert lab.store.get(fq.id).data["status"] == "spawned"
    detail = json.loads(call(server, "GET", f"/api/projects/{pid}")[1])
    assert detail["origin"]["source"] == f"lab:lab/{fq.id}"


def test_programmes_api(ui):
    lab, server = ui
    assert call(server, "POST", "/api/programmes", {"objective": "Build X"})[0] == 403
    status, data = call(server, "POST", "/api/programmes",
                        {"objective": "Answer R1 and build E1", "refs": ["Gate 2"]},
                        token=server.token)
    assert status == 200
    prg = json.loads(data)["id"]
    assert prg.startswith("PRG-")
    listing = json.loads(call(server, "GET", "/api/programmes")[1])
    assert listing[0]["id"] == prg and listing[0]["state"] == "PLANNING"
    detail = json.loads(call(server, "GET", f"/api/programmes/{prg}")[1])
    assert detail["objective"] == "Answer R1 and build E1" and detail["items"] == []
    assert call(server, "GET", "/api/programmes/PRJ-0001")[0] == 404
    meta = json.loads(call(server, "GET", "/api/meta")[1])
    assert meta["programme_terminal"] == ["COMPLETE", "HALTED"]
    assert "ml" in meta["specialties"] and "coordination" in meta["planes"]
    assert call(server, "POST", "/api/programmes", {"objective": ""}, token=server.token)[0] == 400


def test_research_view_meta_charts_and_activity_paging(tmp_path):
    """D63: research content, research pipeline + state labels, usage per day, paging."""
    from scenario import make
    lab, ctl = make(tmp_path)
    ctl.injected["scientist"].usage = {"input_tokens": 10, "output_tokens": 2, "cost_usd": 0.01}
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    ctl.run(pid)
    srv = DashboardServer(lab, "127.0.0.1", 0)
    try:
        r = srv.project(pid)["research"]
        assert r["problem"]["problem_statement"] and r["questions"] and r["hypotheses"]
        assert any(h["current"] for h in r["hypotheses"])
        assert r["designs"][0]["chosen"] and r["protocols"][-1]["frozen"]
        assert r["results"][0]["decision"]["ci_low"] is not None
        assert r["conclusions"][0]["outcome"] == "supported" and r["reports"][0]["text"]
        meta = srv.meta()
        assert meta["research_pipeline"][0] == "DEFINE_PROBLEM"
        assert meta["research_pipeline"][-1] == "COMPLETE"
        assert meta["state_labels"]["ADVERSARIAL_REVIEW"] == "Independent review"
        usage = srv.overview()["usage"]
        assert usage["by_day"][0]["cost_usd"] > 0 and usage["by_agent"]
        newest = srv.activity(5)
        older = srv.activity(5, before=newest[-1]["seq"])
        assert older and all(e["seq"] < newest[-1]["seq"] for e in older)
        assert srv.project(ctl.new_engineering_project("x", ["y"]))["research"] is None
    finally:
        srv.httpd.server_close()
