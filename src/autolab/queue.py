"""Task queue: run a list of engineering tasks in order, unattended.

A queue file is TOML with one ``[[task]]`` table per task::

    [[task]]
    id = "G1-2"
    spec = "..."             # the engineering spec (the project objective)
    accept = ["...", "..."]  # acceptance criteria
    refs = ["Gate 1"]        # mandate refs (optional)

Each task is matched to an existing project by its exact spec. COMPLETE tasks are
skipped and unfinished ones are continued; a missing task is submitted. The queue stops
at the first project that HALTs or waits on an approval gate, so nothing is retried or
approved behind anyone's back.
"""

from __future__ import annotations

import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .state_machines import ResearchState as R


@dataclass
class QueueOutcome:
    status: str               # "done" | "blocked" | "halted"
    task_id: str | None = None
    project: str | None = None
    detail: str = ""


def load_queue(path: str | Path) -> list[dict]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    tasks = data.get("task", [])
    seen = set()
    for t in tasks:
        for key in ("id", "spec", "accept"):
            if not t.get(key):
                raise ValueError(f"queue task {t.get('id', '?')!r} is missing {key!r}")
        if t["id"] in seen:
            raise ValueError(f"duplicate queue task id {t['id']!r}")
        seen.add(t["id"])
        t.setdefault("refs", [])
    return tasks


def run_queue(ctl, tasks: list[dict], *, author: str = "claude-code",
              on_step: Callable | None = None,
              log: Callable[[str], None] = print) -> QueueOutcome:
    store = ctl.store
    for t in tasks:
        matches = [p for p in store.query("project") if p.data.get("objective") == t["spec"]]
        latest = matches[-1] if matches else None
        if latest is not None and latest.data["state"] == R.COMPLETE.value:
            log(f"--- {t['id']} already COMPLETE ({latest.id}) ---")
            continue
        if latest is not None and latest.data["state"] == R.HALTED.value:
            return QueueOutcome("halted", t["id"], latest.id,
                                f"previously HALTED: {latest.data.get('halt_reason')}")
        if latest is None:
            pid = ctl.new_engineering_project(t["spec"], list(t["accept"]), list(t["refs"]),
                                              author=author)
            log(f"--- {t['id']} submitted {time.strftime('%Y-%m-%d %H:%M:%S')} as {pid} ---")
        else:
            pid = latest.id
            log(f"--- {t['id']} continuing {pid} ---")
        steps = ctl.run(pid, on_step=on_step)
        last = steps[-1] if steps else None
        state = ctl.project(pid).data["state"]
        if state == R.COMPLETE.value:
            continue
        if last is not None and last.blocked_on:
            return QueueOutcome("blocked", t["id"], pid, f"awaiting approval {last.blocked_on}")
        if state == R.HALTED.value:
            return QueueOutcome("halted", t["id"], pid, ctl.project(pid).data.get("halt_reason") or "")
        return QueueOutcome("halted", t["id"], pid, f"stopped in {state} (step limit)")
    return QueueOutcome("done")
