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
