"""Agent backends and the protocol-enforcing Agent wrapper.

Backends only turn a prompt into text. :class:`Agent` builds the prompt,
calls the backend, extracts JSON, validates it against the stage schema and
retries with the validation error on protocol violations.

Default role -> backend mapping (configurable in lab.toml):
    scientist -> ChatGPT  (CodexCLIBackend read-only, or OpenAIBackend)
    engineer  -> Claude   (ClaudeCLIBackend, writes in its worktree)
    verifier  -> Codex    (CodexCLIBackend workspace-write in its worktree)
"""

from __future__ import annotations

import re
import time

import json
import os
import shutil
import sys
import tempfile
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .messages import ProtocolError, TaskPacket, extract_json, validate_completion
from .procs import ProcResult, run_tree
from .prompts import build_prompt
from .taxonomy import Role


class BackendError(Exception):
    pass


_USAGE_LIMIT = re.compile(
    r"hit your (?:\w+ )?limit|usage limit|rate[ _-]?limit|quota exceeded|too many requests"
    r"|upgrade to plus|try again at|\b429\b", re.IGNORECASE)


_TRANSIENT_NETWORK = re.compile(
    r"no response from api|econnreset|connection (?:dropped|reset|refused|aborted|error)"
    r"|network (?:error|is unreachable)|overloaded|service unavailable|bad gateway|gateway timeout"
    r"|internal server error|\b(?:500|502|503|504|529)\b", re.IGNORECASE)


def agent_wait_kind(exc: BaseException) -> str | None:
    """'usage_limit' or 'network' for transient agent errors that should be waited out and
    retried without counting as a stage failure; None otherwise (a real failure)."""
    if not isinstance(exc, BackendError):
        return None
    text = str(exc)
    if _USAGE_LIMIT.search(text):
        return "usage_limit"
    if _TRANSIENT_NETWORK.search(text):
        return "network"
    return None


def is_usage_limit(exc: BaseException) -> bool:
    """True for agent quota/rate-limit errors: transient, wait and retry, not a stage failure."""
    return isinstance(exc, BackendError) and bool(_USAGE_LIMIT.search(str(exc)))


def _clip_input(value, limit: int = 600) -> dict | str:
    """A tool input for the log: long text fields (file contents, edits) are replaced by their
    size so the log shows what was done without copying code into it."""
    if not isinstance(value, dict):
        return str(value)[:limit]
    out = {}
    for k, v in value.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = f"<{len(v)} chars>"
        else:
            out[k] = v if isinstance(v, (int, float, bool)) or v is None else str(v)[:200]
    return out


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                "cost_usd", "api_duration_s", "turns")


def add_usage(total: dict | None, part: dict | None) -> dict | None:
    """Sum two usage dicts field by field (None = unknown)."""
    if not part:
        return total
    out = dict(total or {})
    for k in USAGE_FIELDS:
        if part.get(k) is not None:
            out[k] = round((out.get(k) or 0) + part[k], 6)
    if part.get("model"):
        out["model"] = part["model"]
    return out


class AgentBackend(ABC):
    name: str = "backend"
    model: str | None = None
    # Usage reported by the last invoke() (tokens, cost, time), when the backend reports it;
    # None means the backend does not report usage (never estimated).
    last_usage: dict | None = None
    # Tool calls made during the last invoke() (D64), or None when the backend cannot report
    # them (never invented).
    last_tool_calls: list | None = None

    @abstractmethod
    def invoke(self, task: TaskPacket, prompt: str) -> str:
        """Return the agent's raw final answer text."""

    def describe(self) -> dict:
        return {"backend": self.name, "model": self.model}


# ------------------------------------------------------------------ scripted
Handler = Callable[[TaskPacket], "dict | str"]


class ScriptedBackend(AgentBackend):
    """Deterministic backend for tests and dry runs.

    ``handlers`` maps stage -> callable(task) returning a completion dict (or
    raw text). A handler may write files into ``task.workdir`` to simulate an
    agent editing code. A list of handlers is consumed one per call (the last
    one repeats), which lets tests script "fail, then succeed" sequences.
    """

    name = "scripted"

    def __init__(self, handlers: dict[str, Handler | list[Handler]], model: str = "script",
                 usage: dict | None = None):
        self.handlers = handlers
        self.model = model
        self.usage = usage  # reported per call, to test accounting
        self.tool_calls: list | None = None  # reported per call, to test tool logging
        self.calls: list[tuple[str, str]] = []
        self._idx: dict[str, int] = {}

    def invoke(self, task: TaskPacket, prompt: str) -> str:
        self.calls.append((task.stage, task.task_id))
        h = self.handlers.get(task.stage)
        if h is None:
            raise BackendError(f"scripted backend has no handler for stage {task.stage!r}")
        if isinstance(h, list):
            i = self._idx.get(task.stage, 0)
            self._idx[task.stage] = i + 1
            h = h[min(i, len(h) - 1)]
        out = h(task)
        self.last_usage = dict(self.usage) if self.usage else None
        self.last_tool_calls = list(self.tool_calls) if self.tool_calls is not None else None
        return out if isinstance(out, str) else json.dumps(out)


# --------------------------------------------------------------- subprocess
def _run(cmd: list[str], *, cwd: str | None, stdin: str, timeout: float,
         env: dict | None = None) -> ProcResult:
    """Run an agent CLI; on timeout its whole process tree is killed (no orphans)."""
    exe = shutil.which(cmd[0])
    if exe is None:
        raise BackendError(f"{cmd[0]!r} not found on PATH")
    proc = run_tree([exe, *cmd[1:]], cwd=cwd, input=stdin, timeout=timeout, env=env)
    if proc.timed_out:
        raise BackendError(f"{cmd[0]} timed out after {timeout}s (process tree killed)")
    return proc


class ClaudeCLIBackend(AgentBackend):
    """Claude Code in headless mode (``claude -p``), run inside the worktree.

    Hermetic: no user/project/local settings (so no plugins, hooks or CLAUDE.md
    from parent directories), no MCP servers, no skills and no auto-memory. The
    task packet is the agent's only context.
    """

    HERMETIC = ["--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
                "--settings", '{"autoMemoryEnabled": false}']
    HERMETIC_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}

    name = "claude-cli"

    def __init__(self, model: str | None = None, timeout: float = 1800,
                 allowed_tools: list[str] | None = None):
        self.model = model
        self.timeout = timeout
        self.allowed_tools = allowed_tools or [
            "Read", "Glob", "Grep", "Edit", "Write",
            "Bash(python:*)", "Bash(pytest:*)", "Bash(python -m pytest:*)",
        ]

    def command(self, task: TaskPacket) -> list[str]:
        # stream-json (needs --verbose with -p) carries every tool call and permission decision;
        # its final "result" line is the same object the json format returns (D64).
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", *self.HERMETIC]
        if task.writable:
            cmd += ["--permission-mode", "acceptEdits",
                    "--allowedTools", ",".join(self.allowed_tools)]
        else:
            cmd += ["--allowedTools", "Read,Glob,Grep"]
        cmd += ["--disallowedTools", "Bash(git:*)"]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def invoke(self, task: TaskPacket, prompt: str) -> str:
        self.last_usage, self.last_tool_calls = None, None
        proc = _run(self.command(task), cwd=task.workdir, stdin=prompt, timeout=self.timeout,
                    env={**os.environ, **self.HERMETIC_ENV})
        result, self.last_tool_calls = self.parse_stream(proc.stdout)
        stdout = json.dumps(result) if result is not None else proc.stdout
        self.last_usage = self.usage_of(stdout)
        return self.parse_output(proc.returncode, stdout, proc.stderr)

    @staticmethod
    def parse_stream(stdout: str) -> tuple[dict | None, list | None]:
        """(final result object, tool calls) from stream-json output. A single JSON object
        (the plain json format) gives (that object, None): tool calls unknown, not empty."""
        text = (stdout or "").strip()
        try:
            whole = json.loads(text)
            if isinstance(whole, dict):
                return whole, None
        except json.JSONDecodeError:
            pass
        result, calls, by_id = None, [], {}
        for line in text.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            kind = ev.get("type")
            if kind == "result":
                result = ev
            elif kind in ("assistant", "user"):
                for c in (ev.get("message") or {}).get("content") or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_use":
                        call = {"id": c.get("id"), "tool": c.get("name"),
                                "input": _clip_input(c.get("input")), "ok": None,
                                "denied": False, "error": None, "result_chars": None}
                        by_id[c.get("id")] = call
                        calls.append(call)
                    elif c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                        call = by_id[c["tool_use_id"]]
                        content = c.get("content")
                        body = content if isinstance(content, str) else json.dumps(content)
                        call["ok"] = not c.get("is_error")
                        call["result_chars"] = len(body or "")
                        if c.get("is_error"):
                            call["error"] = (body or "")[:300]
            elif kind == "system" and ev.get("subtype") == "permission_denied":
                call = by_id.get(ev.get("tool_use_id"))
                if call:
                    call["denied"] = True
        if result is None and not calls:
            return None, None
        for d in (result or {}).get("permission_denials") or []:
            if d.get("tool_use_id") in by_id:
                by_id[d["tool_use_id"]]["denied"] = True
        return result, calls

    @staticmethod
    def usage_of(stdout: str) -> dict | None:
        """Tokens, cost and time from Claude Code's JSON result (also on errors)."""
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        u = data.get("usage") or {}
        models = list((data.get("modelUsage") or {}).keys())
        out = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
               "cache_read_tokens": u.get("cache_read_input_tokens"),
               "cache_write_tokens": u.get("cache_creation_input_tokens"),
               "cost_usd": data.get("total_cost_usd"),
               "api_duration_s": (data["duration_api_ms"] / 1000
                                  if isinstance(data.get("duration_api_ms"), (int, float)) else None),
               "turns": data.get("num_turns"), "model": models[0] if len(models) == 1 else None}
        return out if any(v is not None for k, v in out.items() if k != "model") else None

    @staticmethod
    def parse_output(returncode: int, stdout: str, stderr: str) -> str:
        """Claude Code reports errors (usage limits, API errors) as JSON on stdout."""
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            if returncode != 0 or data.get("is_error"):
                detail = (data.get("result") or data.get("api_error_status")
                          or data.get("subtype") or "")
                raise BackendError(f"claude exited {returncode} (is_error="
                                   f"{data.get('is_error')}): {str(detail)[:2000]} "
                                   f"{stderr[-1000:]}".strip())
            return data.get("result", "")
        if returncode != 0:
            raise BackendError(f"claude exited {returncode}: stderr={stderr[-1500:]!r} "
                               f"stdout={stdout[-1500:]!r}")
        return stdout


class CodexCLIBackend(AgentBackend):
    """OpenAI Codex CLI (``codex exec``). Also usable as the ChatGPT scientist
    in read-only mode, authenticated by the user's ChatGPT login."""

    name = "codex-cli"

    # Hermetic: ignore ~/.codex/config.toml and exec-policy rules; no plugins, apps,
    # browser/computer use or memories. The task packet is the only context.
    HERMETIC = ["--ignore-user-config", "--ignore-rules",
                *[a for f in ("plugins", "apps", "browser_use", "browser_use_external",
                              "in_app_browser", "computer_use", "memories")
                  for a in ("--disable", f)]]

    def __init__(self, model: str | None = None, timeout: float = 1800,
                 sandbox_when_writable: str = "workspace-write"):
        self.model = model
        self.timeout = timeout
        self.sandbox_when_writable = sandbox_when_writable

    def command(self, task: TaskPacket, out_file: str) -> list[str]:
        sandbox = self.sandbox_when_writable if task.writable else "read-only"
        cmd = ["codex", "exec", "--sandbox", sandbox, "--skip-git-repo-check",
               "--ephemeral", "--color", "never", *self.HERMETIC, "-o", out_file]
        if task.writable and sys.platform == "win32":
            # --ignore-user-config also drops [windows] sandbox; without it Windows
            # degrades workspace-write to read-only with shell commands rejected.
            cmd += ["-c", 'windows.sandbox="elevated"']
        if task.workdir:
            cmd += ["-C", task.workdir]
        if self.model:
            cmd += ["-m", self.model]
        cmd.append("-")
        return cmd

    def invoke(self, task: TaskPacket, prompt: str) -> str:
        with tempfile.TemporaryDirectory() as td:
            out_file = os.path.join(td, "last_message.txt")
            proc = _run(self.command(task, out_file), cwd=task.workdir or td,
                        stdin=prompt, timeout=self.timeout)
            if proc.returncode != 0:
                raise BackendError(f"codex exited {proc.returncode}: stderr="
                                   f"{proc.stderr[-1500:]!r} stdout={proc.stdout[-1500:]!r}")
            if os.path.exists(out_file):
                return Path(out_file).read_text(encoding="utf-8")
            return proc.stdout


class OpenAIBackend(AgentBackend):
    """ChatGPT via the OpenAI Responses API (no tools, no workspace)."""

    name = "openai-api"

    def __init__(self, model: str, api_key_env: str = "OPENAI_API_KEY",
                 base_url: str = "https://api.openai.com/v1", timeout: float = 600):
        self.model = model
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def invoke(self, task: TaskPacket, prompt: str) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise BackendError(f"environment variable {self.api_key_env} is not set")
        body = json.dumps({"model": self.model, "input": prompt}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/responses", data=body, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except Exception as exc:  # network errors become backend errors
            raise BackendError(f"OpenAI request failed: {exc}") from None
        u = data.get("usage") or {}
        self.last_usage = {"input_tokens": u.get("input_tokens"),
                           "output_tokens": u.get("output_tokens"),
                           "model": data.get("model")} if u else None
        if "output_text" in data:
            return data["output_text"]
        texts = [c.get("text", "") for item in data.get("output", [])
                 for c in item.get("content", []) or [] if c.get("type") == "output_text"]
        return "\n".join(texts)


# Backend factories by name; capabilities (for allocation checks and the UI) are declared in
# registry.BACKENDS under the same names.
BACKEND_ALIASES = {"gemini": "gemini-cli", "agy-cli": "gemini-cli"}
BACKEND_FACTORIES: dict[str, Callable[[dict], "AgentBackend"]] = {
    "claude-cli": lambda s: ClaudeCLIBackend(model=s.get("model") or None,
                                             timeout=s.get("timeout", 1800)),
    "codex-cli": lambda s: CodexCLIBackend(model=s.get("model") or None,
                                           timeout=s.get("timeout", 1800)),
    "gemini-cli": lambda s: GeminiCLIBackend(model=s.get("model") or None,
                                             timeout=s.get("timeout", 1800),
                                             effort=s.get("effort") or None),
    "openai-api": lambda s: OpenAIBackend(model=s["model"],
                                          api_key_env=s.get("api_key_env") or "OPENAI_API_KEY",
                                          timeout=s.get("timeout", 600)),
}


def _make_single_backend(spec: dict) -> AgentBackend:
    kind = BACKEND_ALIASES.get(spec.get("backend"), spec.get("backend"))
    factory = BACKEND_FACTORIES.get(kind)
    if factory is None:
        raise ValueError(f"unknown backend {kind!r}")
    return factory(spec)


class GeminiCLIBackend(AgentBackend):
    """Google Gemini / Antigravity CLI (``agy``) in headless mode.

    Hermetic: slash commands disabled; mode is 'accept-edits' for writable tasks
    and 'plan' (read-only) for read-only tasks.
    """

    HERMETIC = ["--disable-slash-commands"]

    name = "gemini-cli"

    def __init__(self, model: str | None = None, timeout: float = 1800,
                 effort: str | None = None):
        self.model = model
        self.timeout = timeout
        self.effort = effort

    def command(self, task: TaskPacket) -> list[str]:
        cmd = ["agy", "--output-format", "json", *self.HERMETIC]
        if task.writable:
            # agy has no per-tool allowlist: headless edits need auto-approval, so the
            # terminal sandbox must contain what the auto-approved tools can do.
            cmd += ["--mode", "accept-edits", "--dangerously-skip-permissions", "--sandbox"]
        else:
            cmd += ["--mode", "plan"]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        return cmd

    def invoke(self, task: TaskPacket, prompt: str) -> str:
        with tempfile.TemporaryDirectory() as td:
            workdir = task.workdir or td
            proc = _run(self.command(task), cwd=workdir, stdin=prompt, timeout=self.timeout)
            return self.parse_output(proc.returncode, proc.stdout, proc.stderr)

    @staticmethod
    def parse_output(returncode: int, stdout: str, stderr: str) -> str:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            if returncode != 0 or data.get("status") in ("ERROR", "FAILED"):
                detail = data.get("error") or data.get("response") or stderr
                raise BackendError(f"gemini exited {returncode}: {str(detail)[:2000]}".strip())
            return data.get("response", "")
        if returncode != 0:
            raise BackendError(f"gemini exited {returncode}: stderr={stderr[-1500:]!r} "
                               f"stdout={stdout[-1500:]!r}")
        return stdout


class FallbackBackend(AgentBackend):
    """Wraps a primary backend and automatically falls back to a backup backend on usage limits.

    If the primary hits a usage limit, quota exhaustion or rate limit, it switches
    to the backup backend and sets a cooldown timer on the primary so subsequent calls
    do not waste time waiting for a known-exhausted quota. Once the cooldown expires,
    it automatically attempts the primary backend again.
    """

    def __init__(self, primary: AgentBackend, backup: AgentBackend, cooldown_s: float = 900.0):
        self.primary = primary
        self.backup = backup
        self.cooldown_s = cooldown_s
        self._primary_limited_until: float = 0.0
        self.active: AgentBackend = primary
        self.name = primary.name
        self.model = primary.model

    def describe(self) -> dict:
        desc = self.active.describe()
        desc["primary_backend"] = self.primary.name
        desc["backup_backend"] = self.backup.name
        return desc

    def invoke(self, task: TaskPacket, prompt: str) -> str:
        now = time.time()
        if now < self._primary_limited_until:
            self.active = self.backup
            out = self.backup.invoke(task, prompt)
            self.last_usage = self.backup.last_usage
            self.last_tool_calls = self.backup.last_tool_calls
            return out

        try:
            self.active = self.primary
            out = self.primary.invoke(task, prompt)
            self.last_usage = self.primary.last_usage
            self.last_tool_calls = self.primary.last_tool_calls
            return out
        except BackendError as exc:
            if is_usage_limit(exc) or any(phrase in str(exc).lower() for phrase in (
                "usage limit", "rate limit", "upgrade to plus", "quota exceeded", "too many requests", "429"
            )):
                self._primary_limited_until = time.time() + self.cooldown_s
                sys.stderr.write(
                    f"\n[autolab] Primary backend {self.primary.name} usage limit hit: {exc}\n"
                    f"[autolab] Automatically falling back to backup backend {self.backup.name}...\n"
                )
                self.active = self.backup
                out = self.backup.invoke(task, prompt)
                self.last_usage = self.backup.last_usage
                self.last_tool_calls = self.backup.last_tool_calls
                return out
            raise


def make_backend(spec: dict) -> AgentBackend:
    primary = _make_single_backend(spec)
    backup_kind = spec.get("backup_backend") or spec.get("backup")
    if backup_kind:
        backup_spec = {
            "backend": backup_kind,
            "model": spec.get("backup_model"),
            "timeout": spec.get("backup_timeout", spec.get("timeout", 1800)),
            "effort": spec.get("backup_effort"),
        }
        backup = _make_single_backend(backup_spec)
        cooldown_s = float(spec.get("backup_cooldown_s", 900.0))
        return FallbackBackend(primary, backup, cooldown_s=cooldown_s)
    return primary


# --------------------------------------------------------------------- agent
@dataclass
class AgentResult:
    completion: dict
    prompt: str
    raw_responses: list[str]
    attempts: int
    rejections: list[str]
    usage: dict | None = None
    tool_calls: list | None = None


class Agent:
    def __init__(self, role: Role, backend: AgentBackend, max_protocol_retries: int = 2,
                 persona: dict | None = None):
        self.role = role
        self.backend = backend
        self.max_protocol_retries = max_protocol_retries
        self.persona = persona  # {"name", "title", "charter"} of the allocated agent

    def run(self, task: TaskPacket) -> AgentResult:
        if task.role != self.role:
            raise ValueError(f"task for {task.role} sent to {self.role}")
        base_prompt = build_prompt(self.role, task.stage, task.to_dict(), self.persona)
        prompt = base_prompt
        raws: list[str] = []
        rejections: list[str] = []
        usage: dict | None = None
        tools: list | None = None

        def collect(attempt: int) -> list | None:
            got = getattr(self.backend, "last_tool_calls", None)
            if got is None:
                return tools
            return (tools or []) + [{**c, "attempt": attempt} for c in got]

        for attempt in range(1, self.max_protocol_retries + 2):
            try:
                raw = self.backend.invoke(task, prompt)
            except Exception as exc:
                exc.usage = add_usage(usage, getattr(self.backend, "last_usage", None))
                exc.tool_calls = collect(attempt)
                raise
            usage = add_usage(usage, getattr(self.backend, "last_usage", None))
            tools = collect(attempt)
            raws.append(raw)
            try:
                completion = validate_completion(task.stage, extract_json(raw))
                return AgentResult(completion, base_prompt, raws, attempt, rejections, usage,
                                   tools)
            except ProtocolError as exc:
                rejections.append(str(exc))
                prompt = (base_prompt + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED BY THE "
                          f"CONTROLLER: {exc}\nReturn a corrected JSON object only.")
        err = ProtocolError(f"{self.role.value}/{task.stage}: {rejections[-1]}")
        # Keep the evidence: the controller stores rejected responses as artifacts.
        err.prompt, err.raw_responses, err.rejections = base_prompt, raws, rejections
        err.usage = usage
        err.tool_calls = tools
        raise err
