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

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .messages import ProtocolError, TaskPacket, extract_json, validate_completion
from .prompts import build_prompt
from .taxonomy import Role


class BackendError(Exception):
    pass


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
def _run(cmd: list[str], *, cwd: str | None, stdin: str, timeout: float) -> subprocess.CompletedProcess:
    exe = shutil.which(cmd[0])
    if exe is None:
        raise BackendError(f"{cmd[0]!r} not found on PATH")
    try:
        return subprocess.run([exe, *cmd[1:]], cwd=cwd, input=stdin, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BackendError(f"{cmd[0]} timed out after {timeout}s") from None


class ClaudeCLIBackend(AgentBackend):
    """Claude Code in headless mode (``claude -p``), run inside the worktree."""

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
        cmd = ["claude", "-p", "--output-format", "json"]
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
        proc = _run(self.command(task), cwd=task.workdir, stdin=prompt, timeout=self.timeout)
        if proc.returncode != 0:
            raise BackendError(f"claude exited {proc.returncode}: {proc.stderr[-2000:]}")
        try:
            return json.loads(proc.stdout).get("result", "")
        except json.JSONDecodeError:
            return proc.stdout


class CodexCLIBackend(AgentBackend):
    """OpenAI Codex CLI (``codex exec``). Also usable as the ChatGPT scientist
    in read-only mode, authenticated by the user's ChatGPT login."""

    name = "codex-cli"

    def __init__(self, model: str | None = None, timeout: float = 1800,
                 sandbox_when_writable: str = "workspace-write"):
        self.model = model
        self.timeout = timeout
        self.sandbox_when_writable = sandbox_when_writable

    def command(self, task: TaskPacket, out_file: str) -> list[str]:
        sandbox = self.sandbox_when_writable if task.writable else "read-only"
        cmd = ["codex", "exec", "--sandbox", sandbox, "--skip-git-repo-check",
               "--ephemeral", "--color", "never", "-o", out_file]
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
                raise BackendError(f"codex exited {proc.returncode}: {proc.stderr[-2000:]}")
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


def make_backend(spec: dict) -> AgentBackend:
    kind = spec.get("backend")
    if kind == "claude-cli":
        return ClaudeCLIBackend(model=spec.get("model"), timeout=spec.get("timeout", 1800))
    if kind == "codex-cli":
        return CodexCLIBackend(model=spec.get("model"), timeout=spec.get("timeout", 1800))
    if kind == "openai-api":
        return OpenAIBackend(model=spec["model"], api_key_env=spec.get("api_key_env", "OPENAI_API_KEY"))
    raise ValueError(f"unknown backend {kind!r}")


# --------------------------------------------------------------------- agent
@dataclass
class AgentResult:
    completion: dict
    prompt: str
    raw_responses: list[str]
    attempts: int


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
        last_err = None
        for attempt in range(1, self.max_protocol_retries + 2):
            raw = self.backend.invoke(task, prompt)
            raws.append(raw)
            try:
                completion = validate_completion(task.stage, extract_json(raw))
                return AgentResult(completion, base_prompt, raws, attempt)
            except ProtocolError as exc:
                last_err = exc
                prompt = (base_prompt + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED BY THE "
                          f"CONTROLLER: {exc}\nReturn a corrected JSON object only.")
        raise ProtocolError(f"{self.role.value}/{task.stage}: {last_err}")
