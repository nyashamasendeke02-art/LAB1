"""Loopback-only web dashboard for one Autolab lab (``autolab ui LAB``).

Architecture (D49):

* ``ThreadingHTTPServer``; every handler thread opens its own :class:`Lab` (SQLite
  connections are per thread), so a live event stream never blocks API calls.
* Static single-page app (``web/index.html``, ``app.js``, ``app.css``) served with a strict
  Content-Security-Policy (no inline script or style); the per-process write token is
  delivered in a ``<meta>`` tag.
* JSON API under ``/api`` and a Server-Sent Events stream (``/api/stream``) that announces
  ledger and queue-log changes, so the page updates without polling.
* Read-mostly: the only writes are creating a project and recording a human gate decision,
  both through the controller/Gates APIs, refused while an agent call is in flight (the
  controller's tamper check would otherwise HALT the project).
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

from .controller import Controller, Lab
from .gates import GateError, Gates

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
ENG_PIPELINE = ["SPEC", "IMPLEMENTING", "TESTING", "ADVERSARIAL_REVIEW", "MERGE", "MERGED"]
TASK_KEY = re.compile(r"^\s*(G\d+-\d+[a-z]?)\b")
GATE_REF = re.compile(r"^Gate (\d+)$")
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
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                        return
                    self._json(HTTPStatus.OK, result)
                except (ValueError, GateError) as exc:
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

    def _project_summary(self, rec) -> dict:
        d = rec.data
        objective = d.get("objective", "")
        key = TASK_KEY.match(objective)
        history = self.store.history(rec.id)
        gates = [int(m.group(1)) for r in d.get("mandate_refs", []) if (m := GATE_REF.match(r))]
        return {"id": rec.id, "kind": d.get("kind", "research"), "key": key.group(1) if key else None,
                "title": _title(objective), "objective": objective, "state": d.get("state", "UNKNOWN"),
                "cycle": d.get("cycle", 0), "blocked_on": d.get("blocked_on"),
                "halt_reason": d.get("halt_reason"), "mandate_refs": d.get("mandate_refs", []),
                "gate": gates[0] if gates else None, "eng": self._eng(rec),
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
    def agents(self) -> list[dict]:
        tasks = self._tasks()
        by_id = {rec.id: rec for rec in tasks}
        active = {}
        for event in self._open_dispatches(set(by_id)):
            role = event["data"].get("role", "unknown")
            if role not in active or event["seq"] > active[role]["seq"]:
                active[role] = event
        configured = self.lab.config.get("agents", {})
        out = []
        for role in ("scientist", "engineer", "verifier", "reviewer"):
            settings = configured.get(role) or {}
            if role == "reviewer" and not settings.get("backend"):
                continue
            mine = sorted((r for r in tasks if r.data.get("role") == role),
                          key=lambda r: r.created_at, reverse=True)
            latest = mine[0] if mine else None
            err = latest.data.get("error") if latest and latest.data.get("status") == "error" else None
            counts = Counter(r.data.get("status") for r in mine)
            act = active.get(role)
            out.append({
                "role": role, "backend": settings.get("backend", "unknown"),
                "model": settings.get("model") or None,
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
        superseded = {p["key"] for p in projects if p["key"] and p["state"] != "HALTED"}
        alerts = []
        for a in agents:
            if a["status"] == "blocked":
                kind = a["error_kind"] or "error"
                alerts.append({"level": "warn" if kind in ("usage_limit", "network") else "error",
                               "title": f"{a['role'].title()} blocked: {kind.replace('_', ' ')}",
                               "detail": a["error_message"] or ""})
        for p in projects:
            if p["state"] == "HALTED" and p["key"] not in superseded:
                alerts.append({"level": "error", "title": f"{p['id']} halted",
                               "detail": (p["halt_reason"] or "")[:240], "project": p["id"]})
        if approvals:
            alerts.append({"level": "info",
                           "title": f"{len(approvals)} approval(s) awaiting a decision",
                           "detail": ", ".join(a["id"] for a in approvals)})
        active = [p for p in projects if p["state"] not in ("COMPLETE", "HALTED")]
        states = Counter(p["state"] for p in projects)
        unresolved_halts = [p for p in projects if p["state"] == "HALTED" and p["key"] not in superseded]
        return {
            "lab": self.root.name, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "counts": {"projects": len(projects), "active": len(active),
                       "complete": states.get("COMPLETE", 0), "halted": len(unresolved_halts),
                       "halted_total": states.get("HALTED", 0),
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
            raise ValueError("kind must be 'research' or 'engineering'")
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
        return (self.store.head(), log)

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
