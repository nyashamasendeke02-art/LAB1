"""Loopback-only web dashboard for one Autolab lab (``autolab ui LAB``).

Architecture (D49):

* ``ThreadingHTTPServer``; every handler thread opens its own :class:`Lab` (SQLite
  connections are per thread), so a live event stream never blocks API calls.
* Static single-page app (``web/index.html``, ``app.js``, ``app.css``) served with a strict
  Content-Security-Policy (no inline script or style); the per-process write token is
  delivered in a ``<meta>`` tag.
* JSON API under ``/api`` and a Server-Sent Events stream (``/api/stream``) that announces
  ledger and queue-log changes, so the page updates without polling.
* Read-mostly: the writes are creating a project, recording a human gate decision and editing
  the agent registry (agents.toml: agents, models, stage allocation, D52), all refused while an
  agent call is in flight (the controller's tamper check would otherwise HALT the project).
* No hardcoded lab vocabulary: states, pipelines, tones, stages, roles, backends, project kinds
  and milestone patterns come from ``/api/meta`` (state machines, registry, lab config).
* Security: binds to loopback only, checks the ``Host`` header (DNS rebinding), requires the
  token and a same-origin ``Origin`` for writes, no CORS.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .controller import Controller, Lab
from .gates import GateError, Gates
from .coordination import PROGRAMME_STATES, PROGRAMME_TRANSITIONS, Coordinator
from .knowledge import INDEXED_KINDS, Knowledge
from .registry import BACKENDS, ORGANISATION, ROLE_AGENTS, STAGES, Registry, RegistryError
from .state_machines import (ENGINEERING_PIPELINE, ENGINEERING_PIPELINE_ALIAS, RESEARCH_DONE,
                             RESEARCH_TERMINAL, STATE_TONES, EngineeringState, ResearchState)
from .taxonomy import Role

WEB_DIR = Path(__file__).with_name("web")
ASSETS = {"/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/assets/app.css": ("app.css", "text/css; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
FAVICON = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><linearGradient '
           b'id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6ea8ff"/><stop offset="1" '
           b'stop-color="#b495ff"/></linearGradient></defs><rect width="32" height="32" rx="8" fill="url(#g)"/>'
           b'<text x="16" y="22" font-family="Segoe UI,Arial" font-size="17" font-weight="800" '
           b'text-anchor="middle" fill="#fff">A</text></svg>')
ENG_PIPELINE = [s.value for s in ENGINEERING_PIPELINE]
PROJECT_KINDS = [
    {"value": "research", "label": "Research: investigate a question", "needs_acceptance": False},
    {"value": "engineering", "label": "Engineering: build to a spec", "needs_acceptance": True},
]
# Tones of record statuses and verdicts (state-machine tones come from state_machines.py).
STATUS_TONES = {"approved": "ok", "complete": "ok", "completed": "ok", "pass": "ok",
                "upheld": "ok", "supported": "ok", "rejected": "bad", "error": "bad",
                "fail": "bad", "failed": "bad", "timeout": "bad", "challenged": "warn",
                "needs_review": "warn", "pending": "warn", "blocked": "warn",
                "usage_limit": "warn", "network": "warn", "working": "info",
                "inconclusive": "warn", "unsupported": "info",
                # programme states and work-item statuses (D54)
                "PLANNING": "info", "RUNNING": "info", "REVIEWING": "review", "done": "ok",
                "halted": "bad", "dropped": "warn", "split": "info", "running": "info"}
_USAGE = re.compile(r"hit your (?:\w+ )?limit|usage limit|rate[ _-]?limit|quota|\b429\b", re.I)
_NETWORK = re.compile(r"no response from api|econnreset|connection (?:dropped|reset|refused|"
                      r"aborted)|overloaded|service unavailable|\b50[0234]\b|\b529\b", re.I)
_TIMEOUT = re.compile(r"timed out after", re.I)
STALE_DISPATCH_S = 7200  # agent calls are capped at 30 min; older open dispatches were abandoned


def _parse_ts(value: object) -> dt.datetime | None:
    try:
        ts = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)


def classify_error(text: str | None) -> str | None:
    """Short label for an agent error: usage_limit, network, timeout or error."""
    if not text:
        return None
    if _USAGE.search(text):
        return "usage_limit"
    if _NETWORK.search(text):
        return "network"
    if _TIMEOUT.search(text):
        return "timeout"
    return "error"


def readable_error(text: str | None, limit: int = 300) -> str | None:
    """The human-readable part of an agent error (CLI errors bury it after JSON schemas)."""
    if not text:
        return None
    flat = str(text).replace("\\n", "\n")  # stderr captured as a repr keeps literal "\n"
    found = re.findall(r"ERROR: ([^\n{][^\n]*)", flat)
    if not found:
        found = re.findall(r"is_error=\w+\): ([^\n]+)", flat)
    msg = found[-1] if found else flat.strip().splitlines()[-1] if flat.strip() else flat
    return msg.strip().strip("'\"")[:limit]


def _title(objective: str) -> str:
    text = " ".join(str(objective or "").split())
    m = re.match(r"^(.{1,160}?[.!?])(\s|$)", text)
    return m.group(1) if m else text[:160]


class DashboardServer:
    """Serve the lab dashboard on a loopback interface."""

    def __init__(self, lab: Lab, host: str = "127.0.0.1", port: int = 8765,
                 run_log: str | Path | None = None):
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("host must be a loopback IP address such as 127.0.0.1") from exc
        if not address.is_loopback:
            raise ValueError("the Autolab dashboard can only bind to a loopback address")
        self.root = Path(lab.root)
        self._local = threading.local()
        self._local.lab = lab
        self.token = secrets.token_urlsafe(32)
        if run_log is None:
            guess = self.root.parent / f"{self.root.name}-run.log"
            run_log = guess if guess.exists() else None
        self.run_log = Path(run_log) if run_log else None
        index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.index = index.replace("__AUTOLAB_TOKEN__", self.token).encode("utf-8")
        self._verify_cache: tuple[str, dict] | None = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AutolabDashboard/2.0"
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args) -> None:
                if "/api/" not in (str(args[0]) if args else ""):
                    print(f"[autolab-ui] {self.address_string()} {fmt % args}")

            def _headers(self, status: HTTPStatus, content_type: str, length: int | None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                if length is not None:
                    self.send_header("Content-Length", str(length))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                self.send_header("Content-Security-Policy", CSP)
                self.end_headers()

            def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
                self._headers(status, content_type, len(body))
                self.wfile.write(body)

            def _json(self, status: HTTPStatus, value: object) -> None:
                self._send(status, json.dumps(value, ensure_ascii=False, default=str)
                           .encode("utf-8"), "application/json; charset=utf-8")

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
                return not origin or origin == f"http://{self.headers.get('Host', '')}"

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if not self._host_ok():
                    self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "unexpected Host"})
                    return
                parts = urlsplit(self.path)
                route, query = parts.path, parse_qs(parts.query)
                try:
                    if route == "/favicon.ico":
                        self._send(HTTPStatus.OK, FAVICON, "image/svg+xml")
                    elif route in ("/", "/index.html"):
                        self._send(HTTPStatus.OK, owner.index, "text/html; charset=utf-8")
                    elif route in ASSETS:
                        name, ctype = ASSETS[route]
                        self._send(HTTPStatus.OK, (WEB_DIR / name).read_bytes(), ctype)
                    elif route == "/api/stream":
                        owner._stream(self)
                    elif route == "/api/overview":
                        self._json(HTTPStatus.OK, owner.overview())
                    elif route == "/api/projects":
                        self._json(HTTPStatus.OK, owner.projects())
                    elif route.startswith("/api/projects/"):
                        self._json(HTTPStatus.OK, owner.project(
                            unquote(route.removeprefix("/api/projects/"))))
                    elif route == "/api/approvals":
                        self._json(HTTPStatus.OK, owner.approvals())
                    elif route.startswith("/api/approvals/"):
                        self._json(HTTPStatus.OK, owner.approval(
                            unquote(route.removeprefix("/api/approvals/"))))
                    elif route == "/api/meta":
                        self._json(HTTPStatus.OK, owner.meta())
                    elif route == "/api/programmes":
                        self._json(HTTPStatus.OK, owner.programmes())
                    elif route.startswith("/api/programmes/"):
                        self._json(HTTPStatus.OK, owner.programme(
                            unquote(route.removeprefix("/api/programmes/"))))
                    elif route == "/api/knowledge":
                        self._json(HTTPStatus.OK, owner.knowledge())
                    elif route == "/api/knowledge/search":
                        self._json(HTTPStatus.OK, owner.knowledge_search(query))
                    elif route == "/api/knowledge/node":
                        self._json(HTTPStatus.OK, owner.knowledge_node(query))
                    elif route == "/api/registry":
                        self._json(HTTPStatus.OK, owner.registry_state())
                    elif route == "/api/agents":
                        self._json(HTTPStatus.OK, owner.agents())
                    elif route.startswith("/api/tasks/"):
                        self._json(HTTPStatus.OK, owner.task(
                            unquote(route.removeprefix("/api/tasks/"))))
                    elif route == "/api/activity":
                        limit = int((query.get("limit") or ["120"])[0])
                        self._json(HTTPStatus.OK, owner.activity(max(1, min(limit, 1000))))
                    elif route == "/api/state":  # v1 compatibility
                        self._json(HTTPStatus.OK, owner.state())
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "record not found"})
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                except ValueError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except Exception as exc:
                    print(f"[autolab-ui] GET {route} failed: {type(exc).__name__}: {exc}")
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if not self._host_ok() or not self._authorized():
                    self._json(HTTPStatus.FORBIDDEN, {"error": "request rejected"})
                    return
                route = urlsplit(self.path).path
                try:
                    data = self._read_json()
                    if route == "/api/projects":
                        result = owner.create_project(data)
                    elif route.startswith("/api/approvals/"):
                        result = owner.decide(unquote(route.removeprefix("/api/approvals/")), data)
                    elif route == "/api/programmes":
                        result = owner.create_programme(data)
                    elif route == "/api/knowledge/spawn":
                        result = owner.spawn_from_question(data)
                    elif route == "/api/allocation":
                        result = owner.allocate(data)
                    elif route == "/api/agents/preset":
                        result = owner.apply_preset(data)
                    elif route.startswith("/api/agents/") and route.endswith("/remove"):
                        result = owner.remove_agent(unquote(
                            route.removeprefix("/api/agents/").removesuffix("/remove")))
                    elif route.startswith("/api/agents/"):
                        result = owner.save_agent(unquote(route.removeprefix("/api/agents/")),
                                                  data)
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                        return
                    self._json(HTTPStatus.OK, result)
                except (ValueError, GateError, RegistryError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "record not found"})
                except Exception as exc:
                    print(f"[autolab-ui] POST {route} failed: {type(exc).__name__}: {exc}")
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            address_family = socket.AF_INET6 if address.version == 6 else socket.AF_INET

        self.httpd = Server((host, port), Handler)
        self.httpd.timeout = 1
        bound = self.httpd.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{bound}", f"localhost:{bound}", f"[::1]:{bound}",
                              f"{host}:{bound}" if address.version == 4 else f"[{host}]:{bound}"}

    # ------------------------------------------------------------ lab access
    @property
    def lab(self) -> Lab:
        lab = getattr(self._local, "lab", None)
        if lab is None:
            lab = self._local.lab = Lab(self.root)
        return lab

    @property
    def store(self):
        return self.lab.store

    # ------------------------------------------------------------ helpers
    def _tasks(self) -> list:
        return self.store.query("task")

    def _open_dispatches(self, done: set[str] | None = None) -> list[dict]:
        if done is None:
            done = {rec.id for rec in self._tasks()}
        now = dt.datetime.now(dt.timezone.utc)
        out = []
        for event in self.store.events(etype="task.dispatched"):
            if event["subject"] in done:
                continue
            ts = _parse_ts(event["ts"])
            if ts and (now - ts).total_seconds() <= STALE_DISPATCH_S:
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

    def _eng(self, project) -> dict | None:
        eng_id = (project.data.get("current") or {}).get("eng_task")
        if not eng_id:
            return None
        try:
            eng = self.store.get(eng_id)
        except KeyError:
            return None
        d = eng.data
        return {"id": eng.id, "state": d.get("state"), "patch_attempts": d.get("patch_attempts", 0),
                "redesigns": d.get("redesigns", 0), "review_round": d.get("review_round", 0),
                "test_runs": len(d.get("test_runs", [])), "branch": d.get("branch"),
                "head": d.get("head")}

    def _patterns(self) -> tuple[re.Pattern, re.Pattern]:
        ui = self.lab.config.get("ui", {})
        return (re.compile(ui.get("task_key_pattern") or r"(?!x)x"),
                re.compile(ui.get("milestone_ref_pattern") or r"(?!x)x"))

    def _project_summary(self, rec) -> dict:
        d = rec.data
        objective = d.get("objective", "")
        task_key, milestone_ref = self._patterns()
        key = task_key.match(objective)
        history = self.store.history(rec.id)
        gates = [int(m.group(1)) for r in d.get("mandate_refs", [])
                 if (m := milestone_ref.match(r))]
        return {"id": rec.id, "kind": d.get("kind", "research"), "key": key.group(1) if key else None,
                "title": _title(objective), "objective": objective, "state": d.get("state", "UNKNOWN"),
                "cycle": d.get("cycle", 0), "blocked_on": d.get("blocked_on"),
                "halt_reason": d.get("halt_reason"), "mandate_refs": d.get("mandate_refs", []),
                "gate": gates[0] if gates else None, "eng": self._eng(rec),
                "origin": d.get("origin"),
                "created_at": history[0].created_at if history else rec.created_at,
                "updated_at": rec.created_at}

    def _verify(self) -> dict:
        head = self.store.head()
        if self._verify_cache and self._verify_cache[0] == head:
            return self._verify_cache[1]
        try:
            n = self.store.verify_chain()
            result = {"ok": True, "events": n, "head": head}
        except Exception as exc:  # ChainError
            result = {"ok": False, "error": str(exc)[:300], "head": head}
        self._verify_cache = (head, result)
        return result

    def _queue(self) -> dict:
        if not self.run_log or not self.run_log.exists():
            return {"log": None, "running": None, "lines": []}
        raw = self.run_log.read_bytes()[-24000:].decode("utf-8", errors="replace")
        lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
        started = max((i for i, ln in enumerate(lines) if "=== queue started" in ln), default=-1)
        exited = max((i for i, ln in enumerate(lines) if "=== queue exited" in ln), default=-1)
        last_result = next((ln for ln in reversed(lines) if ln.startswith("QUEUE ")), None)
        return {"log": str(self.run_log), "running": started > exited if started >= 0 else None,
                "last_result": last_result, "lines": [ln[:400] for ln in lines[-40:]],
                "modified": dt.datetime.fromtimestamp(self.run_log.stat().st_mtime,
                                                      dt.timezone.utc).isoformat()}

    # ------------------------------------------------------------ API
    def registry(self) -> Registry:
        return Registry(self.lab.config, self.root)

    def agents(self) -> list[dict]:
        tasks = self._tasks()
        by_id = {rec.id: rec for rec in tasks}
        # Tasks recorded before D52 carry no agent name: they belong to their role's agent.
        agent_of = lambda d: d.get("agent") or d.get("role", "unknown")  # noqa: E731
        active = {}
        for event in self._open_dispatches(set(by_id)):
            name = agent_of(event["data"])
            if name not in active or event["seq"] > active[name]["seq"]:
                active[name] = event
        reg = self.registry()
        effective = reg.describe()["effective"]
        out = []
        for name, settings in sorted(reg.agents.items(),
                                     key=lambda kv: (kv[0] not in ROLE_AGENTS, kv[0])):
            role = next((s.role.value for s in STAGES if effective[s.name] == name),
                        name if name in ROLE_AGENTS else None)
            mine = sorted((r for r in tasks if agent_of(r.data) == name),
                          key=lambda r: r.created_at, reverse=True)
            latest = mine[0] if mine else None
            err = latest.data.get("error") if latest and latest.data.get("status") == "error" else None
            counts = Counter(r.data.get("status") for r in mine)
            act = active.get(name)
            out.append({
                "name": name, "title": settings.get("title") or name.replace("_", " ").title(),
                "charter": settings.get("charter", ""), "role": role,
                "default_for_role": name if name in ROLE_AGENTS else None,
                "stages": sorted(s for s, n in effective.items() if n == name),
                "backend": settings.get("backend") or None,
                "model": settings.get("model") or None,
                "backup_backend": settings.get("backup_backend") or None,
                "backup_model": settings.get("backup_model") or None,
                "spec": {k: v for k, v in settings.items() if k != "stages"},
                "status": "working" if act else ("blocked" if err else "idle"),
                "error_kind": classify_error(err), "error": err[-600:] if err else None,
                "error_message": readable_error(err),
                "active": ({"task": act["subject"], "stage": act["data"].get("stage"),
                            "project": act["data"].get("project"), "since": act["ts"]}
                           if act else None),
                "last_task": ({"id": latest.id, "stage": latest.data.get("stage"),
                               "status": latest.data.get("status"),
                               "summary": latest.data.get("summary", ""),
                               "at": latest.created_at} if latest else None),
                "calls": len(mine), "completed": counts.get("complete", 0) + counts.get("completed", 0),
                "errors": counts.get("error", 0),
                "recent": [{"id": r.id, "stage": r.data.get("stage"), "status": r.data.get("status"),
                            "project": r.data.get("project"), "at": r.created_at,
                            "error_kind": classify_error(r.data.get("error"))}
                           for r in mine[:12]],
            })
        return out

    def projects(self) -> list[dict]:
        return [self._project_summary(r) for r in reversed(self.store.query("project"))]

    def overview(self) -> dict:
        projects = self.projects()
        approvals = self.approvals()
        agents = self.agents()
        gates: dict[int, list] = {}
        for p in projects:
            if p["gate"] is not None and p["kind"] == "engineering":
                gates.setdefault(p["gate"], []).append(
                    {"key": p["key"] or p["id"], "project": p["id"], "state": p["state"],
                     "eng_state": (p["eng"] or {}).get("state"), "title": p["title"]})
        board = []
        for g in sorted(gates):
            latest: dict[str, dict] = {}
            for t in sorted(gates[g], key=lambda t: t["project"]):
                latest[t["key"]] = t  # the newest project for each task key wins
            board.append({"gate": g, "tasks": sorted(latest.values(), key=lambda t: t["key"])})
        superseded = {p["key"] for p in projects
                      if p["key"] and p["state"] != ResearchState.HALTED.value}
        alerts = []
        for a in agents:
            if a["status"] == "blocked" and a["stages"]:  # unallocated agents do no work
                kind = a["error_kind"] or "error"
                alerts.append({"level": "warn" if kind in ("usage_limit", "network") else "error",
                               "title": f"{a['title']} blocked: {kind.replace('_', ' ')}",
                               "detail": a["error_message"] or ""})
        for p in projects:
            if p["state"] == ResearchState.HALTED.value and p["key"] not in superseded:
                alerts.append({"level": "error", "title": f"{p['id']} halted",
                               "detail": (p["halt_reason"] or "")[:240], "project": p["id"]})
        if approvals:
            alerts.append({"level": "info",
                           "title": f"{len(approvals)} approval(s) awaiting a decision",
                           "detail": ", ".join(a["id"] for a in approvals)})
        terminal = {s.value for s in RESEARCH_TERMINAL}
        active = [p for p in projects if p["state"] not in terminal]
        states = Counter(p["state"] for p in projects)
        halted = ResearchState.HALTED.value
        unresolved_halts = [p for p in projects if p["state"] == halted and p["key"] not in superseded]
        return {
            "lab": self.root.name, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "counts": {"projects": len(projects), "active": len(active),
                       "complete": sum(states.get(s.value, 0) for s in RESEARCH_DONE),
                       "halted": len(unresolved_halts),
                       "halted_total": states.get(halted, 0),
                       "approvals": len(approvals),
                       "deliveries": len(self.store.query("delivery")),
                       "agents_working": sum(a["status"] == "working" for a in agents)},
            "ledger": self._verify(), "queue": self._queue(), "gates": board,
            "active": active, "approvals": approvals, "agents": agents, "alerts": alerts,
            "activity": self.activity(14), "pipeline": ENG_PIPELINE,
        }

    def project(self, project_id: str) -> dict:
        rec = self.store.get(project_id)
        if rec.kind != "project":
            raise KeyError(project_id)
        summary = self._project_summary(rec)

        def mine(kind: str) -> list:
            return [r for r in self.store.query(kind) if r.data.get("project") == rec.id]

        eng_history = [{"eng": eng.id, **h} for eng in mine("eng_task")
                       for h in eng.data.get("history", [])]
        reviews = [{"id": r.id, "type": r.data.get("review_type"), "verdict": r.data.get("verdict"),
                    "passed": r.data.get("passed"), "round": r.data.get("round"),
                    "commit": r.data.get("commit"), "at": r.created_at,
                    "tests_passed": r.data.get("tests_passed"),
                    "findings": r.data.get("findings", [])} for r in mine("review")]
        failures = [{"id": r.id, "category": r.data.get("category"), "summary": r.data.get("summary"),
                     "state": r.data.get("state"), "at": r.created_at} for r in mine("failure")]
        tasks = [{"id": r.id, "role": r.data.get("role"), "stage": r.data.get("stage"),
                  "agent": r.data.get("agent") or r.data.get("role"),
                  "model": (r.data.get("backend") or {}).get("model"),
                  "status": r.data.get("status"), "at": r.created_at,
                  "summary": r.data.get("summary", ""),
                  "error_kind": classify_error(r.data.get("error"))} for r in mine("task")]
        deliveries = [{"id": r.id, "commit": r.data.get("commit"), "at": r.created_at}
                      for r in mine("delivery")]
        approvals = [{"id": r.id, "gate": r.data.get("gate"), "status": r.data.get("status"),
                      "decided_by": r.data.get("decided_by"), "note": r.data.get("note"),
                      "at": r.created_at} for r in mine("approval")]
        by_time = lambda rows: sorted(rows, key=lambda r: r["at"], reverse=True)  # noqa: E731
        return {**summary, "acceptance_criteria": rec.data.get("acceptance_criteria", []),
                "pipeline": ENG_PIPELINE, "eng_history": eng_history,
                "reviews": by_time(reviews), "failures": by_time(failures), "tasks": by_time(tasks),
                "deliveries": deliveries, "approvals": approvals,
                "events": self.store.events(subject=project_id)[-40:]}

    def meta(self) -> dict:
        """Everything the dashboard needs to know about this lab's vocabulary."""
        ui = self.lab.config.get("ui", {})
        tones = {**STATUS_TONES, **{k.value: v for k, v in STATE_TONES.items()}}
        return {
            "version": __version__, "lab": self.root.name,
            "research_states": [s.value for s in ResearchState],
            "engineering_states": [s.value for s in EngineeringState],
            "research_terminal": [s.value for s in RESEARCH_TERMINAL],
            "research_done": [s.value for s in RESEARCH_DONE],
            "engineering_pipeline": ENG_PIPELINE,
            "pipeline_alias": {k.value: v.value for k, v in ENGINEERING_PIPELINE_ALIAS.items()},
            "tones": tones, "project_kinds": PROJECT_KINDS,
            "roles": [{"value": r.value, "default_agent": r.value} for r in Role],
            "stages": [{"name": st.name, "role": st.role.value, "plane": st.plane,
                        "writable": st.writable, "reads_files": st.reads_files,
                        "label": st.label} for st in STAGES],
            "planes": list(dict.fromkeys(st.plane for st in STAGES)),
            "programme_states": list(PROGRAMME_STATES),
            "programme_terminal": [s for s in PROGRAMME_STATES if not PROGRAMME_TRANSITIONS[s]],
            "specialties": list((self.lab.config.get("coordination") or {}).get("specialties", [])),
            "backends": [{"name": n, **caps} for n, caps in BACKENDS.items()],
            "presets": [{"name": "organisation",
                         "agents": [{"name": n, "title": v[0], "role": v[1].value,
                                     "stages": v[3]} for n, v in ORGANISATION.items()]}],
            "ui": {"milestone_label": ui.get("milestone_label") or "Milestone",
                   "milestones_enabled": bool(ui.get("milestone_ref_pattern")),
                   "refresh_fallback_s": int(ui.get("refresh_fallback_s") or 30)},
        }

    def registry_state(self) -> dict:
        reg = self.registry()
        return {**reg.describe(), "known_models": sorted(
            {m for spec in reg.agents.values() for m in (spec.get("model"), spec.get("backup_model"))
             if m} | {t.data.get("backend", {}).get("model") for t in self._tasks()
                      if (t.data.get("backend") or {}).get("model")} - {"script"})}

    def save_agent(self, name: str, data: dict) -> dict:
        self._ensure_idle()
        spec = data.get("spec")
        if not isinstance(spec, dict):
            raise ValueError("body needs a spec object")
        self.registry().upsert(name, {k: v for k, v in spec.items() if v not in (None, "")})
        return self.registry_state()

    def remove_agent(self, name: str) -> dict:
        self._ensure_idle()
        self.registry().remove(name)
        return self.registry_state()

    def allocate(self, data: dict) -> dict:
        self._ensure_idle()
        changes = data.get("allocation")
        if not isinstance(changes, dict):
            raise ValueError("body needs an allocation object {stage: agent}")
        self.registry().allocate(changes)
        return self.registry_state()

    def apply_preset(self, data: dict) -> dict:
        self._ensure_idle()
        created = self.registry().apply_preset(str(data.get("name") or "organisation"))
        return {**self.registry_state(), "created": created}

    # ------------------------------------------------------------ programmes (D54)
    def _coordinator(self) -> Coordinator:
        return Coordinator(Controller(self.lab, agents={}))

    def programmes(self) -> list[dict]:
        co = self._coordinator()
        out = []
        for rec in reversed(self.store.query("programme")):
            d = rec.data
            counts = Counter(it["status"] for it in d.get("items", {}).values())
            out.append({"id": rec.id, "objective": d["objective"], "title": _title(d["objective"]),
                        "state": d["state"], "reviews": d.get("reviews", 0),
                        "halt_reason": d.get("halt_reason"), "blocked_on": d.get("blocked_on"),
                        "items": len(d.get("items", {})), "status_counts": dict(counts),
                        "updated_at": rec.created_at})
        return out

    def programme(self, prg: str) -> dict:
        co = self._coordinator()
        rec = co.programme(prg)
        d = rec.data
        st = co.status(prg)
        history = self.store.history(prg)
        tasks = [{"id": t.id, "stage": t.data.get("stage"), "agent": t.data.get("agent"),
                  "status": t.data.get("status"), "at": t.created_at}
                 for t in self.store.query("task") if t.data.get("project") == prg]
        for it in st["items"]:
            full = d["items"][it["key"]]
            it["projects"] = full.get("projects", [])
            it["drop_reason"] = full.get("drop_reason")
            it["architecture_notes"] = full.get("architecture_notes")
            it["rationale"] = full.get("rationale")
        return {"id": rec.id, **st, "title": _title(d["objective"]),
                "halt_reason": d.get("halt_reason"), "blocked_on": d.get("blocked_on"),
                "plan_summary": d.get("plan_summary"),
                "success_criteria": d.get("success_criteria", []),
                "decisions": d.get("decisions", []), "director_calls": tasks,
                "created_at": history[0].created_at if history else rec.created_at,
                "updated_at": rec.created_at, "events": self.store.events(subject=prg)[-30:]}

    def create_programme(self, data: dict) -> dict:
        self._ensure_idle()
        objective = data.get("objective")
        refs = data.get("refs", [])
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 4000:
            raise ValueError("objective must contain 1–4000 characters")
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
            raise ValueError("refs must be a list of strings")
        return {"id": self._coordinator().new_programme(objective.strip(), refs)}

    # ------------------------------------------------------------ knowledge (K1)
    def _knowledge(self) -> Knowledge:
        kn = getattr(self._local, "knowledge", None)
        if kn is None:
            kn = self._local.knowledge = Knowledge(self.root.name, self.store, self.root,
                                                   self.lab.config)
        return kn

    def knowledge(self) -> dict:
        kn = self._knowledge()
        g = kn.graph()
        conclusions = sorted((n for n in g.nodes.values() if n.kind == "conclusion"),
                             key=lambda n: n.created_at, reverse=True)
        return {"stats": g.stats(), "problems": kn.problems, "kinds": list(INDEXED_KINDS),
                "open_questions": [{**n.brief(), "priority": n.data.get("priority"),
                                    "question": n.data.get("question", ""),
                                    "rationale": n.data.get("rationale", "")}
                                   for n in g.open_questions()],
                "conclusions": [n.brief() for n in conclusions[:20]]}

    def knowledge_search(self, query: dict) -> list[dict]:
        text = (query.get("q") or [""])[0]
        if len(text) > 1000:
            raise ValueError("query is limited to 1000 characters")
        kinds = tuple(k for k in query.get("kind", []) if k in INDEXED_KINDS) or None
        hits = self._knowledge().graph().search(text, k=40, kinds=kinds)
        return [{**n.brief(), "score": round(score, 3)} for score, n in hits]

    def knowledge_node(self, query: dict) -> dict:
        g = self._knowledge().graph()
        node = g.resolve_source((query.get("id") or [""])[0])
        if node is None:
            raise KeyError("node")
        nb = g.neighbours(node.id)
        brief = lambda nid: g.nodes[nid].brief(200)  # noqa: E731
        return {**node.brief(6000), "out": [{"relation": r, **brief(d)} for r, d in nb["out"]],
                "in": [{"relation": r, **brief(src)} for src, r in nb["in"]]}

    def spawn_from_question(self, data: dict) -> dict:
        self._ensure_idle()
        source = data.get("source")
        if not isinstance(source, str) or not source.startswith("lab:"):
            raise ValueError("source must be 'lab:<lab>/<FQ id>'")
        project_id = Controller(self.lab, agents={}).new_project_from_question(source)
        self._local.knowledge = None  # the question's status changed
        return {"id": project_id}

    def approvals(self) -> list[dict]:
        gates = Gates(self.store, self.lab.config["gates"].get("delegation"))
        return [{"id": r.id, "gate": r.data.get("gate"), "subject": r.data.get("subject"),
                 "summary": r.data.get("summary"), "project": r.data.get("project"),
                 "files": (r.data.get("details") or {}).get("files", []), "at": r.created_at}
                for r in gates.pending()]

    def approval(self, approval_id: str) -> dict:
        rec = self.store.get(approval_id)
        if rec.kind != "approval":
            raise KeyError(approval_id)
        details = rec.data.get("details") or {}
        return {"id": rec.id, "gate": rec.data.get("gate"), "subject": rec.data.get("subject"),
                "summary": rec.data.get("summary"), "project": rec.data.get("project"),
                "status": rec.data.get("status"), "decided_by": rec.data.get("decided_by"),
                "note": rec.data.get("note"), "files": details.get("files", []),
                "diff": str(details.get("diff", ""))[:400_000],
                "details": {k: v for k, v in details.items() if k not in ("diff", "files")},
                "at": rec.created_at}

    def task(self, task_id: str) -> dict:
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
            record = self.store.get(task_id)
            result = {"status": record.data.get("status"), "summary": record.data.get("summary"),
                      "error": record.data.get("error"), "attempts": record.data.get("attempts"),
                      "rejections": record.data.get("rejections", []),
                      "backend": record.data.get("backend"),
                      "agent": record.data.get("agent") or record.data.get("role"),
                      "error_kind": classify_error(record.data.get("error"))}
        except KeyError:
            result = {"status": "working"}
        return {"id": task_id, "packet": packet, "completion": completion, "result": result}

    def activity(self, limit: int = 120) -> list[dict]:
        out = []
        for e in self.store.events()[-limit:][::-1]:
            data = e.get("data") or {}
            brief = ((data.get("to") and f"{data.get('from', '?')} → {data.get('to')}")
                     or data.get("reason") or data.get("stage") or data.get("gate")
                     or data.get("kind") or "")
            out.append({"seq": e["seq"], "ts": e["ts"], "type": e["type"], "actor": e["actor"],
                        "subject": e["subject"], "brief": str(brief)[:200]})
        return out

    def state(self) -> dict:  # v1 API, kept for compatibility
        return {"lab": self.root.name, "projects": self.projects(), "approvals": self.approvals(),
                "agents": self.agents()}

    def create_project(self, data: dict) -> dict:
        self._ensure_idle()
        kind = data.get("kind", "research")
        objective = data.get("objective")
        refs = data.get("refs", [])
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 4000:
            raise ValueError("objective must contain 1–4000 characters")
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("refs must be a list of strings")
        controller = Controller(self.lab, agents={})
        if kind == "research":
            project_id = controller.new_project(objective.strip(), refs)
        elif kind == "engineering":
            acceptance = data.get("acceptance", [])
            if (not isinstance(acceptance, list) or not acceptance
                    or any(not isinstance(item, str) or not item.strip() for item in acceptance)):
                raise ValueError("engineering projects need acceptance criteria")
            project_id = controller.new_engineering_project(
                objective.strip(), [item.strip() for item in acceptance], refs)
        else:
            raise ValueError("kind must be one of "
                             + ", ".join(repr(k["value"]) for k in PROJECT_KINDS))
        return {"id": project_id}

    def decide(self, approval_id: str, data: dict) -> dict:
        self._ensure_idle()
        approved = data.get("approved")
        note = data.get("note", "")
        if not isinstance(approved, bool) or not isinstance(note, str) or len(note) > 2000:
            raise ValueError("decision needs a boolean and a note of at most 2000 characters")
        if not note.strip():
            raise ValueError("a decision needs a note: say what you checked")
        rec = Gates(self.store, self.lab.config["gates"].get("delegation")).decide(
            approval_id, approved, by="human", note=note.strip())
        return {"id": rec.id, "status": rec.data["status"]}

    # ------------------------------------------------------------ live stream
    def _fingerprint(self) -> tuple:
        log = None
        if self.run_log and self.run_log.exists():
            st = self.run_log.stat()
            log = (st.st_size, st.st_mtime_ns)
        reg = self.root / "agents.toml"
        return (self.store.head(), log, reg.stat().st_mtime_ns if reg.exists() else None)

    def _stream(self, handler: BaseHTTPRequestHandler, max_seconds: float = 3600,
                interval: float = 1.0) -> None:
        handler._headers(HTTPStatus.OK, "text/event-stream; charset=utf-8", None)
        handler.close_connection = True
        last, start, beat = None, time.monotonic(), time.monotonic()
        handler.wfile.write(b"retry: 3000\n\n")
        while time.monotonic() - start < max_seconds:
            fp = self._fingerprint()
            if fp != last:
                payload = json.dumps({"ledger": str(fp[0])[:16], "log": fp[1] is not None})
                handler.wfile.write(f"event: change\ndata: {payload}\n\n".encode())
                handler.wfile.flush()
                last = fp
            elif time.monotonic() - beat > 15:
                handler.wfile.write(b": heartbeat\n\n")
                handler.wfile.flush()
                beat = time.monotonic()
            time.sleep(interval)

    def serve_forever(self) -> None:
        address, port = self.httpd.server_address[:2]
        printable = f"[{address}]" if ":" in address else address
        print(f"Autolab dashboard for {self.root} at http://{printable}:{port}/")
        print("Loopback only. Press Ctrl+C to stop.")
        try:
            self.httpd.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            print("\nStopping Autolab dashboard.")
        finally:
            self.httpd.server_close()
