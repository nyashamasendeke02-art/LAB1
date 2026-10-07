"""Loopback-only web dashboard for a single Autolab lab."""

from __future__ import annotations

import ipaddress
import datetime as dt
import json
import re
import secrets
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .controller import Controller, Lab
from .gates import Gates, GateError


class DashboardServer:
    """Serve project status and human approval actions on a loopback interface."""

    def __init__(self, lab: Lab, host: str = "127.0.0.1", port: int = 8765):
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("host must be a loopback IP address such as 127.0.0.1") from exc
        if not address.is_loopback:
            raise ValueError("the Autolab dashboard can only bind to a loopback address")
        self.lab = lab
        self.controller = Controller(lab, agents={})
        self.token = secrets.token_urlsafe(32)
        dashboard = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
        self.dashboard = dashboard.replace("__AUTOLAB_TOKEN__", self.token).encode("utf-8")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AutolabDashboard/1.0"

            def log_message(self, fmt: str, *args) -> None:
                print(f"[autolab-ui] {self.address_string()} {fmt % args}")

            def _send(self, status: HTTPStatus, body: bytes,
                      content_type: str = "application/json; charset=utf-8") -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                 "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
                                 "base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: HTTPStatus, value: object) -> None:
                self._send(status, json.dumps(value, ensure_ascii=False, default=str)
                           .encode("utf-8"))

            def _read_json(self) -> dict:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ValueError("invalid Content-Length") from exc
                if length < 1 or length > 64_000:
                    raise ValueError("request body must be between 1 and 64000 bytes")
                try:
                    data = json.loads(self.rfile.read(length))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ValueError("request body must be valid JSON") from exc
                if not isinstance(data, dict):
                    raise ValueError("request JSON must be an object")
                return data

            def _host_ok(self) -> bool:
                # DNS-rebinding guard: a page on another hostname that resolves to
                # loopback must not be able to read the token or call the API.
                return self.headers.get("Host", "") in owner.allowed_hosts

            def _authorized(self) -> bool:
                if not secrets.compare_digest(self.headers.get("X-Autolab-Token", ""),
                                              owner.token):
                    return False
                origin = self.headers.get("Origin")
                if origin and origin != f"http://{self.headers.get('Host', '')}":
                    return False
                return True

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if not self._host_ok():
                    self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "unexpected Host"})
                    return
                route = urlsplit(self.path).path
                if route == "/":
                    self._send(HTTPStatus.OK, owner.dashboard,
                               "text/html; charset=utf-8")
                elif route == "/api/state":
                    self._json(HTTPStatus.OK, owner._state())
                elif route.startswith("/api/projects/"):
                    project_id = unquote(route.removeprefix("/api/projects/"))
                    try:
                        self._json(HTTPStatus.OK, owner._project(project_id))
                    except KeyError:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "project not found"})
                elif route.startswith("/api/tasks/"):
                    task_id = unquote(route.removeprefix("/api/tasks/"))
                    try:
                        self._json(HTTPStatus.OK, owner._task(task_id))
                    except KeyError:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "task not found"})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if not self._host_ok() or not self._authorized():
                    self._json(HTTPStatus.FORBIDDEN, {"error": "request rejected"})
                    return
                route = urlsplit(self.path).path
                try:
                    data = self._read_json()
                    if route == "/api/projects":
                        result = owner._create_project(data)
                    elif route.startswith("/api/approvals/"):
                        approval_id = unquote(route.removeprefix("/api/approvals/"))
                        result = owner._decide(approval_id, data)
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                        return
                    self._json(HTTPStatus.OK, result)
                except (ValueError, GateError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "record not found"})
                except Exception as exc:
                    print(f"[autolab-ui] request failed: {type(exc).__name__}: {exc}")
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                               {"error": "internal server error"})

        if address.version == 6:
            class IPv6HTTPServer(HTTPServer):
                address_family = socket.AF_INET6
            self.httpd = IPv6HTTPServer((host, port), Handler)
        else:
            self.httpd = HTTPServer((host, port), Handler)
        self.httpd.timeout = 1
        bound_port = self.httpd.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{bound_port}", f"localhost:{bound_port}",
                              f"[::1]:{bound_port}"}
        if address.version == 4:
            self.allowed_hosts.add(f"{host}:{bound_port}")
        else:
            self.allowed_hosts.add(f"[{host}]:{bound_port}")

    def _state(self) -> dict:
        projects = []
        for rec in reversed(self.lab.store.query("project")):
            data = rec.data
            projects.append({
                "id": rec.id,
                "kind": data.get("kind", "research"),
                "objective": data.get("objective", ""),
                "state": data.get("state", "UNKNOWN"),
                "cycle": data.get("cycle", 0),
                "blocked_on": data.get("blocked_on"),
                "halt_reason": data.get("halt_reason"),
                "mandate_refs": data.get("mandate_refs", []),
                "updated_at": rec.created_at,
            })
        approvals = [{
            "id": rec.id,
            "gate": rec.data.get("gate"),
            "subject": rec.data.get("subject"),
            "summary": rec.data.get("summary"),
            "details": rec.data.get("details", {}),
            "project": rec.data.get("project"),
        } for rec in Gates(self.lab.store, self.lab.config["gates"].get("delegation")).pending()]
        task_records = self.lab.store.query("task")
        task_by_id = {rec.id: rec for rec in task_records}
        active_calls = self._open_dispatches(set(task_by_id))
        active_by_role = {}
        for event in active_calls:
            role = event["data"].get("role", "unknown")
            if role not in active_by_role or event["seq"] > active_by_role[role]["seq"]:
                active_by_role[role] = event

        agent_roles = []
        configured = self.lab.config.get("agents", {})
        for role in ("scientist", "engineer", "verifier", "reviewer"):
            settings = configured.get(role) or {}
            if role == "reviewer" and not settings.get("backend"):
                continue
            recent = sorted((rec for rec in task_records if rec.data.get("role") == role),
                            key=lambda rec: rec.created_at, reverse=True)
            active = active_by_role.get(role)
            latest = recent[0] if recent else None
            agent_roles.append({
                "role": role,
                "backend": settings.get("backend", "unknown"),
                "model": settings.get("model") or None,
                "status": "working" if active else
                          ("last_error" if latest and latest.data.get("status") == "error"
                           else "idle"),
                "active": ({"task": active["subject"],
                            "stage": active["data"].get("stage"),
                            "project": active["data"].get("project"),
                            "backend": active["data"].get("backend"),
                            "model": active["data"].get("model"),
                            "since": active["ts"]} if active else None),
                "last_task": ({"id": latest.id, "stage": latest.data.get("stage"),
                               "status": latest.data.get("status"),
                               "summary": latest.data.get("summary", ""),
                               "error": latest.data.get("error"),
                               "created_at": latest.created_at} if latest else None),
                "review_stages": settings.get("stages", []) if role == "reviewer" else [],
            })

        recent_tasks = [{
            "id": rec.id,
            "role": rec.data.get("role"),
            "stage": rec.data.get("stage"),
            "status": rec.data.get("status"),
            "project": rec.data.get("project"),
            "backend": rec.data.get("backend", {}),
            "summary": rec.data.get("summary", ""),
            "error": rec.data.get("error"),
            "attempts": rec.data.get("attempts"),
            "rejections": rec.data.get("rejections", []),
            "created_at": rec.created_at,
        } for rec in sorted(task_records, key=lambda item: item.created_at, reverse=True)[:16]]

        priorities = [{
            "id": rec.id,
            "question": rec.data.get("question", ""),
            "rationale": rec.data.get("rationale", ""),
            "priority": rec.data.get("priority"),
            "status": rec.data.get("status", "open"),
            "project": rec.data.get("project"),
        } for rec in sorted(self.lab.store.query("future_question"),
                            key=lambda item: (item.data.get("priority", 99), item.id))]

        protocols = []
        for rec in sorted(self.lab.store.query("protocol"),
                          key=lambda item: item.created_at, reverse=True):
            protocol = rec.data.get("protocol", {})
            protocols.append({
                "id": rec.id,
                "version": rec.version,
                "project": rec.data.get("project"),
                "title": protocol.get("title", "Untitled protocol"),
                "status": rec.data.get("status", "draft"),
                "frozen": rec.frozen,
                "freeze_hash": rec.data.get("_freeze_hash"),
                "kind": protocol.get("kind"),
                "seeds": protocol.get("seeds", []),
                "conditions": protocol.get("conditions", []),
                "metrics": protocol.get("metrics", {}),
                "decision_rule": protocol.get("decision_rule", {}),
                "validity_checks": protocol.get("validity_checks", []),
                "success_checks": protocol.get("success_checks", []),
            })
        return {"lab": self.lab.root.name, "projects": projects, "approvals": approvals,
                "agents": agent_roles, "agent_tasks": recent_tasks,
                "priorities": priorities, "protocols": protocols}

    def _project(self, project_id: str) -> dict:
        rec = self.lab.store.get(project_id)
        if rec.kind != "project":
            raise KeyError(project_id)
        events = self.lab.store.events(subject=project_id)
        return {"id": rec.id, "kind": rec.data.get("kind", "research"),
                "objective": rec.data.get("objective", ""),
                "state": rec.data.get("state", "UNKNOWN"),
                "cycle": rec.data.get("cycle", 0),
                "current": rec.data.get("current", {}),
                "blocked_on": rec.data.get("blocked_on"),
                "halt_reason": rec.data.get("halt_reason"),
                "mandate_refs": rec.data.get("mandate_refs", []),
                "acceptance_criteria": rec.data.get("acceptance_criteria", []),
                "events": events[-12:]}

    def _task(self, task_id: str) -> dict:
        if not re.fullmatch(r"TASK-[0-9]+", task_id):
            raise KeyError(task_id)
        handoff = self.lab.handoffs / task_id
        packet_path = handoff / "task.json"
        if not packet_path.is_file():
            raise KeyError(task_id)
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        completion_path = handoff / "completion.json"
        completion = (json.loads(completion_path.read_text(encoding="utf-8"))
                      if completion_path.is_file() else None)
        try:
            record = self.lab.store.get(task_id)
            result = {"status": record.data.get("status"),
                      "summary": record.data.get("summary"),
                      "error": record.data.get("error"),
                      "attempts": record.data.get("attempts"),
                      "rejections": record.data.get("rejections", [])}
        except KeyError:
            result = {"status": "working"}
        return {"id": task_id, "packet": packet, "completion": completion, "result": result}

    # Agent calls are capped at 30 min (agent timeout); a dispatch with no task record
    # after this long was abandoned by a stopped controller, not still running.
    STALE_DISPATCH_S = 7200

    def _open_dispatches(self, done: set[str] | None = None) -> list[dict]:
        if done is None:
            done = {rec.id for rec in self.lab.store.query("task")}
        now = dt.datetime.now(dt.timezone.utc)
        out = []
        for event in self.lab.store.events(etype="task.dispatched"):
            if event["subject"] in done:
                continue
            try:
                ts = dt.datetime.fromisoformat(str(event["ts"]).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
            if (now - ts).total_seconds() <= self.STALE_DISPATCH_S:
                out.append(event)
        return out

    def _agent_call_in_flight(self) -> bool:
        return bool(self._open_dispatches())

    def _ensure_idle(self) -> None:
        # The controller treats any ledger change during an agent call as possible
        # tampering and HALTs the project, so the dashboard writes only between calls.
        if self._agent_call_in_flight():
            raise ValueError("an agent call is in progress; try again when it finishes "
                             "(a ledger change now would trip the lab's tamper check)")

    def _create_project(self, data: dict) -> dict:
        self._ensure_idle()
        kind = data.get("kind", "research")
        objective = data.get("objective")
        refs = data.get("refs", [])
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 4000:
            raise ValueError("objective must contain 1–4000 characters")
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("refs must be a list of strings")
        if kind == "research":
            project_id = self.controller.new_project(objective.strip(), refs)
        elif kind == "engineering":
            acceptance = data.get("acceptance", [])
            if (not isinstance(acceptance, list) or not acceptance
                    or any(not isinstance(item, str) or not item.strip()
                           for item in acceptance)):
                raise ValueError("engineering projects need acceptance criteria")
            project_id = self.controller.new_engineering_project(
                objective.strip(), [item.strip() for item in acceptance], refs)
        else:
            raise ValueError("kind must be 'research' or 'engineering'")
        return {"id": project_id}

    def _decide(self, approval_id: str, data: dict) -> dict:
        self._ensure_idle()
        approved = data.get("approved")
        note = data.get("note", "")
        if not isinstance(approved, bool) or not isinstance(note, str) or len(note) > 2000:
            raise ValueError("decision needs a boolean and a note of at most 2000 characters")
        rec = Gates(self.lab.store, self.lab.config["gates"].get("delegation")).decide(
            approval_id, approved, by="human", note=note)
        return {"id": rec.id, "status": rec.data["status"]}

    def serve_forever(self) -> None:
        address, port = self.httpd.server_address[:2]
        printable_address = f"[{address}]" if ":" in address else address
        print(f"Autolab dashboard for {self.lab.root} at http://{printable_address}:{port}/")
        print("Loopback only. Press Ctrl+C to stop.")
        try:
            self.httpd.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            print("\nStopping Autolab dashboard.")
        finally:
            self.httpd.server_close()
