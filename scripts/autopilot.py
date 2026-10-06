"""Autopilot: keep the robolab lab moving unattended (D39).

    python scripts/autopilot.py            # run (foreground; see start_autopilot.cmd)
    python scripts/autopilot.py --once     # one cycle, for testing

Loop:
1. Run the active task queue (`autolab queue`, file named in docs/gates/ACTIVE_QUEUE).
   Agent usage limits inside the lab are already waited out by the controller (D35).
2. When the queue stops (approval gate, HALT, or all done), start a headless Claude Code
   session in LAB1 that follows PROJECT_STATE.md: real gate reviews, fixes, new queues.
   Its last line is a directive: ``AUTOPILOT: CONTINUE [RETRY=G1-4,G1-5]``,
   ``AUTOPILOT: NEEDS_HUMAN <reason>`` or ``AUTOPILOT: DONE``.
3. If Claude Code itself hits its usage/session limit, wait and retry until it resets.
4. Stop on NEEDS_HUMAN, DONE, or when the same stop repeats (no progress), and say why
   in labs/autopilot.log and labs/AUTOPILOT_STATUS.txt.

Only one autopilot runs at a time (labs/autopilot.lock). It never starts a second queue
while one is already running.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "labs" / "robolab"
LOG = ROOT / "labs" / "autopilot.log"
STATUS = ROOT / "labs" / "AUTOPILOT_STATUS.txt"
LOCK = ROOT / "labs" / "autopilot.lock"
RUN_LOG = ROOT / "labs" / "robolab-run.log"
ACTIVE_QUEUE = ROOT / "docs" / "gates" / "ACTIVE_QUEUE"
AUTOLAB = ROOT / ".venv" / "Scripts" / "autolab.exe"

LIMIT_WAIT_S = 15 * 60
LIMIT_MAX_WAIT_S = 7 * 24 * 3600   # weekly limits exist; give up after a week
CLAUDE_TIMEOUT_S = 3 * 3600
EXTERNAL_POLL_S = 60
MAX_SAME_STOP = 2

_USAGE_LIMIT = re.compile(
    r"hit your (?:\w+ )?limit|usage limit|rate[ _-]?limit|quota exceeded|too many requests"
    r"|\b429\b|overloaded", re.IGNORECASE)
_DIRECTIVE = re.compile(r"AUTOPILOT:\s*(CONTINUE|NEEDS_HUMAN|DONE)\b(.*)$", re.MULTILINE)

ALLOWED_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]

PROMPT = """AUTOPILOT RUN (unattended; no human is watching; follow your memory and CLAUDE.md rules).
The robolab task queue stopped. Queue file: {queue}. Last queue result:
{result}

Do the project manager's job exactly as in PROJECT_STATE.md ("In Progress" resume steps):
- Approval gate: do a REAL review as delegate claude-code (read the diff, run the tests on the
  branch, fault-inject for safety/contract changes), then approve or reject with the evidence in
  the note (`.venv/Scripts/autolab.exe approve labs/robolab APR-xxxx --as claude-code --note ...`).
  Fold any follow-up into a not-yet-submitted queue task or a new task in the queue file.
- HALTED task: find the cause in the log and records, fix it (lab config, autolab code with tests,
  or the task spec), record a FAILURES/DECISIONS entry, and ask for a retry.
- Queue finished: plan the next step from PROJECT_STATE.md and docs/PROJECT_PLAN.md; write the
  next queue file and put its repo-relative path in docs/gates/ACTIVE_QUEUE, or say DONE if the
  next step needs a research project you cannot queue.
- Do NOT run `autolab queue` or `autolab run` yourself; the autopilot restarts the queue.
- Update PROJECT_STATE.md and project_state/DECISIONS.md, commit in LAB1, and push LAB1 and
  labs/robolab/repo to origin (authorised, D38).
- Anything that needs the human (hardware, money, accounts, new remotes or publishing, deleting
  research artifacts, accepting a major scientific conclusion): add it to PROJECT_STATE.md human
  tasks and stop.

End your reply with exactly one line:
AUTOPILOT: CONTINUE            (queue can restart)
AUTOPILOT: CONTINUE RETRY=ID[,ID]   (restart and re-submit these HALTED task ids)
AUTOPILOT: NEEDS_HUMAN <reason>
AUTOPILOT: DONE <reason>
"""


# ------------------------------------------------------------------ helpers
def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"{now()}  {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def set_status(msg: str) -> None:
    STATUS.write_text(f"{now()}  {msg}\n", encoding="utf-8")


def is_usage_limit(text: str) -> bool:
    return bool(_USAGE_LIMIT.search(text or ""))


def parse_directive(text: str) -> tuple[str, str, list[str]]:
    """Return (kind, detail, retry_ids) from Claude's final AUTOPILOT line."""
    matches = list(_DIRECTIVE.finditer(text or ""))
    if not matches:
        return "NEEDS_HUMAN", "no AUTOPILOT directive in the reply", []
    kind, rest = matches[-1].group(1), matches[-1].group(2).strip()
    retry: list[str] = []
    m = re.search(r"RETRY=([\w\-,]+)", rest)
    if kind == "CONTINUE" and m:
        retry = [r for r in m.group(1).split(",") if r]
    return kind, rest, retry


def active_queue() -> str:
    if ACTIVE_QUEUE.exists():
        q = ACTIVE_QUEUE.read_text(encoding="utf-8").strip()
        if q:
            return q
    return "docs/gates/gate1_queue.toml"


def external_queue_running() -> bool:
    """True if an `autolab queue`/`autolab run` started elsewhere is still running."""
    pattern = r'autolab(\.exe)?"?\s+(queue|run)\s'
    if os.name != "nt":
        out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
        return any(re.search(pattern, line) for line in out.splitlines())
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'autolab|python' "
          f"-and $_.CommandLine -match '{pattern}' }} | ForEach-Object {{ $_.ProcessId }}")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True).stdout
    return any(tok.isdigit() for tok in out.split())


# ------------------------------------------------------------------ steps
def run_queue(retry: list[str]) -> tuple[int, str]:
    queue = active_queue()
    cmd = [str(AUTOLAB), "queue", str(LAB), queue] + [x for r in retry for x in ("--retry", r)]
    log(f"queue start: {queue} retry={retry or '-'}")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    last = ""
    with RUN_LOG.open("a", encoding="utf-8") as out:
        out.write(f"=== queue started {now()} (autopilot) ===\n")
        out.flush()
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace")
        for line in proc.stdout:
            out.write(line)
            out.flush()
            if line.startswith("QUEUE "):
                last = line.strip()
        code = proc.wait()
        out.write(f"=== queue exited {code} {now()} ===\n")
    log(f"queue exit {code}: {last[:300]}")
    return code, last


def run_claude(prompt: str) -> tuple[bool, str]:
    """Run headless Claude Code in LAB1. Returns (usage_limited, reply_text)."""
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS]
    exe = "claude.cmd" if os.name == "nt" else "claude"
    cmd[0] = exe
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=CLAUDE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, "AUTOPILOT: NEEDS_HUMAN claude session timed out"
    raw = proc.stdout or ""
    try:
        data = json.loads(raw.strip().splitlines()[-1]) if raw.strip() else {}
    except (json.JSONDecodeError, IndexError):
        data = {}
    text = str(data.get("result", "")) if data else raw
    err_blob = f"{text}\n{proc.stderr}\n{raw[-2000:]}"
    if (proc.returncode != 0 or data.get("is_error")) and is_usage_limit(err_blob):
        return True, err_blob[-500:]
    if proc.returncode != 0 and not text:
        text = f"AUTOPILOT: NEEDS_HUMAN claude exited {proc.returncode}: {proc.stderr[-300:]}"
    return False, text


def claude_with_wait(prompt: str) -> str:
    waited = 0
    while True:
        limited, text = run_claude(prompt)
        if not limited:
            return text
        if waited >= LIMIT_MAX_WAIT_S:
            return "AUTOPILOT: NEEDS_HUMAN Claude usage limit persisted for a week"
        set_status(f"waiting for the Claude usage limit to reset (waited {waited // 60} min)")
        log(f"claude usage limit; sleeping {LIMIT_WAIT_S // 60} min: {text[-160:]!r}")
        time.sleep(LIMIT_WAIT_S)
        waited += LIMIT_WAIT_S


# ------------------------------------------------------------------ main loop
def cycle(state: dict) -> str | None:
    """One autopilot cycle. Returns a stop reason, or None to keep going."""
    while external_queue_running():
        set_status("a queue started elsewhere is running; waiting for it")
        time.sleep(EXTERNAL_POLL_S)
    set_status(f"running queue {active_queue()}")
    code, last = run_queue(state.pop("retry", []))
    if last and last == state.get("last_stop"):
        state["same"] = state.get("same", 0) + 1
    else:
        state["same"], state["last_stop"] = 0, last
    if state["same"] >= MAX_SAME_STOP:
        return f"no progress: the queue stopped the same way {state['same'] + 1} times: {last}"
    set_status(f"queue stopped ({last or code}); Claude Code is handling it")
    reply = claude_with_wait(PROMPT.format(queue=active_queue(), result=last or f"exit {code}"))
    with (ROOT / "labs" / "autopilot-replies.log").open("a", encoding="utf-8") as fh:
        fh.write(f"===== {now()} =====
{reply}
")
    kind, detail, retry = parse_directive(reply)
    log(f"claude directive: {kind} {detail[:200]}")
    if kind == "CONTINUE":
        state["retry"] = retry
        return None
    return f"{kind}: {detail}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run a single cycle")
    a = ap.parse_args()
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        print(f"another autopilot holds {LOCK} (delete it if no autopilot is running)")
        return 1
    try:
        log("autopilot started")
        state: dict = {}
        while True:
            reason = cycle(state)
            if reason:
                set_status(f"STOPPED: {reason}")
                log(f"autopilot stopped: {reason}")
                return 0
            if a.once:
                set_status("one cycle done (--once)")
                return 0
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
