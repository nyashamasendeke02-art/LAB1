"""Git repository / worktree strategy.

* ``repo/`` holds the research code; branch ``main`` is the integration
  branch and is only ever changed by the controller's merge step.
* Every agent task gets its own worktree + branch:
    - engineer:  ``eng/<TASK>-d<design>``     (writable, branched from main)
    - verifier:  ``verify/<TASK>-r<round>``   (branched from the engineer's
      commit; may only add files under ``tests/verification/``)
    - scientist: no worktree, or a detached read-only checkout.
* Agents never run git. The controller commits their changes with author
  identity and provenance trailers, then enforces path policies on the diff.
* Branches are never deleted: failed implementations stay inspectable.
"""

from __future__ import annotations

import fnmatch
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

CONTROLLER_NAME = "autolab-controller"
CONTROLLER_EMAIL = "controller@autolab.local"


class GitError(Exception):
    pass


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


@dataclass(frozen=True)
class AgentIdentity:
    name: str
    email: str

    @property
    def author(self) -> str:
        return f"{self.name} <{self.email}>"


class GitRepo:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ----------------------------------------------------------- creation
    @classmethod
    def init(cls, path: str | Path, files: dict[str, str] | None = None) -> "GitRepo":
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        _git(path, "init", "-b", "main")
        _git(path, "config", "user.name", CONTROLLER_NAME)
        _git(path, "config", "user.email", CONTROLLER_EMAIL)
        _git(path, "config", "core.autocrlf", "false")
        files = files or {"README.md": "# Research code\n"}
        for rel, content in files.items():
            p = path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-m", "Initial research repository\n\nAutolab-Task: INIT")
        return cls(path)

    # ------------------------------------------------------------- queries
    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        return _git(cwd or self.path, *args, check=check)

    def rev(self, ref: str = "HEAD", cwd: Path | None = None) -> str:
        return self.git("rev-parse", ref, cwd=cwd)

    def branch_exists(self, name: str) -> bool:
        return bool(self.git("branch", "--list", name))

    def changed_files(self, base: str, head: str) -> list[str]:
        out = self.git("diff", "--name-only", f"{base}..{head}")
        return [line for line in out.splitlines() if line]

    def diff(self, base: str, head: str) -> str:
        return self.git("diff", f"{base}..{head}")

    def is_clean(self, cwd: Path | None = None) -> bool:
        return self.git("status", "--porcelain", cwd=cwd) == ""

    def commit_message(self, ref: str) -> str:
        return self.git("log", "-1", "--format=%B", ref)

    # ----------------------------------------------------------- worktrees
    def add_worktree(self, path: str | Path, branch: str, base: str) -> Path:
        path = Path(path)
        if path.exists():
            raise GitError(f"worktree path {path} already exists")
        if self.branch_exists(branch):
            self.git("worktree", "add", str(path), branch)
        else:
            self.git("worktree", "add", "-b", branch, str(path), base)
        return path

    def add_detached_worktree(self, path: str | Path, commit: str) -> Path:
        path = Path(path)
        self.git("worktree", "add", "--detach", str(path), commit)
        return path

    def remove_worktree(self, path: str | Path) -> None:
        """Remove the checkout only. The branch (and its history) is kept."""
        path = Path(path)
        if path.exists():
            self.git("worktree", "remove", "--force", str(path), check=False)
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        self.git("worktree", "prune", check=False)

    # -------------------------------------------------------------- commits
    def commit_all(self, worktree: Path, message: str, author: AgentIdentity,
                   trailers: dict[str, str]) -> str | None:
        """Commit every change in ``worktree``. Returns sha, or None if no change."""
        self.git("add", "-A", cwd=worktree)
        if self.git("diff", "--cached", "--name-only", cwd=worktree) == "":
            return None
        body = message.rstrip() + "\n\n" + "\n".join(f"{k}: {v}" for k, v in trailers.items())
        self.git("commit", "--author", author.author, "-m", body, cwd=worktree)
        return self.rev("HEAD", cwd=worktree)

    def checkout_paths_from(self, worktree: Path, ref: str, pathspec: str) -> bool:
        """Bring ``pathspec`` from ``ref`` into the worktree index (if it exists there)."""
        listed = self.git("ls-tree", "-r", "--name-only", ref, "--", pathspec, cwd=worktree)
        if not listed:
            return False
        self.git("checkout", ref, "--", pathspec, cwd=worktree)
        return True

    # ---------------------------------------------------------------- merge
    def merge_into_main(self, branch: str, message: str, trailers: dict[str, str]) -> str:
        """--no-ff merge of ``branch`` into main inside the controller checkout."""
        current = self.git("rev-parse", "--abbrev-ref", "HEAD")
        if current != "main":
            raise GitError(f"controller checkout must be on main (is {current})")
        if not self.is_clean():
            raise GitError("controller checkout is dirty; refusing to merge")
        body = message.rstrip() + "\n\n" + "\n".join(f"{k}: {v}" for k, v in trailers.items())
        proc = subprocess.run(["git", "merge", "--no-ff", "-m", body, branch],
                              cwd=str(self.path), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=str(self.path),
                           capture_output=True)
            raise GitError(f"merge of {branch} failed (aborted): {proc.stdout}{proc.stderr}")
        return self.rev("HEAD")


def path_violations(changed: list[str], allowed: list[str] | None,
                    forbidden: list[str]) -> list[str]:
    """Return changed paths that break the role's path policy.

    ``allowed=None`` means "anything not forbidden".
    """
    bad = []
    for f in changed:
        if any(fnmatch.fnmatch(f, pat) for pat in forbidden):
            bad.append(f)
        elif allowed is not None and not any(fnmatch.fnmatch(f, pat) for pat in allowed):
            bad.append(f)
    return bad
