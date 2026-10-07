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


class AgentBackend(ABC):
    name: str = "backend"
    model: str | None = None

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

    def __init__(self, handlers: dict[str, Handler | list[Handler]], model: str = "script"):
        self.handlers = handlers
        self.model = model
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
        cmd = ["claude", "-p", "--output-format", "json", *self.HERMETIC]
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
        proc = _run(self.command(task), cwd=task.workdir, stdin=prompt, timeout=self.timeout,
                    env={**os.environ, **self.HERMETIC_ENV})
        return self.parse_output(proc.returncode, proc.stdout, proc.stderr)

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
        if "output_text" in data:
            return data["output_text"]
        texts = [c.get("text", "") for item in data.get("output", [])
                 for c in item.get("content", []) or [] if c.get("type") == "output_text"]
        return "\n".join(texts)


def _make_single_backend(spec: dict) -> AgentBackend:
    kind = spec.get("backend")
    if kind == "claude-cli":
        return ClaudeCLIBackend(model=spec.get("model"), timeout=spec.get("timeout", 1800))
    if kind == "codex-cli":
        return CodexCLIBackend(model=spec.get("model"), timeout=spec.get("timeout", 1800))
    if kind in ("gemini-cli", "gemini", "agy-cli"):
        return GeminiCLIBackend(model=spec.get("model"), timeout=spec.get("timeout", 1800),
                                effort=spec.get("effort"))
    if kind == "openai-api":
        return OpenAIBackend(model=spec["model"], api_key_env=spec.get("api_key_env", "OPENAI_API_KEY"))
    raise ValueError(f"unknown backend {kind!r}")


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
            cmd += ["--mode", "accept-edits", "--dangerously-skip-permissions"]
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
            return self.backup.invoke(task, prompt)

        try:
            self.active = self.primary
            return self.primary.invoke(task, prompt)
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
                return self.backup.invoke(task, prompt)
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


class Agent:
    def __init__(self, role: Role, backend: AgentBackend, max_protocol_retries: int = 2):
        self.role = role
        self.backend = backend
        self.max_protocol_retries = max_protocol_retries

    def run(self, task: TaskPacket) -> AgentResult:
        if task.role != self.role:
            raise ValueError(f"task for {task.role} sent to {self.role}")
        base_prompt = build_prompt(self.role, task.stage, task.to_dict())
        prompt = base_prompt
        raws: list[str] = []
        rejections: list[str] = []
        for attempt in range(1, self.max_protocol_retries + 2):
            raw = self.backend.invoke(task, prompt)
            raws.append(raw)
            try:
                completion = validate_completion(task.stage, extract_json(raw))
                return AgentResult(completion, base_prompt, raws, attempt, rejections)
            except ProtocolError as exc:
                rejections.append(str(exc))
                prompt = (base_prompt + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED BY THE "
                          f"CONTROLLER: {exc}\nReturn a corrected JSON object only.")
        err = ProtocolError(f"{self.role.value}/{task.stage}: {rejections[-1]}")
        # Keep the evidence: the controller stores rejected responses as artifacts.
        err.prompt, err.raw_responses, err.rejections = base_prompt, raws, rejections
        raise err
