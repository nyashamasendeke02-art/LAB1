"""Sandbox profiles (D62, master prompt section 19).

Every stage and every experiment trial runs under a named profile. A profile states its
filesystem, network, tool, compute, execution and secrets policy, and says honestly which parts
the lab enforces (``enforced``) and which it cannot on this platform (``not_enforced``).

Secrets are enforced for code the lab executes itself (experiment trials and the controller's
test runs): the environment is scrubbed of credential-like variables, and a trial receives only
the secrets its frozen protocol declares (``protocol.secrets``). Agent CLIs keep their own
authentication (they log in through their own config, not the lab's environment).
"""

from __future__ import annotations

import re

from .taxonomy import Role

SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|SESSION)",
                         re.IGNORECASE)
# Variables code needs to run that merely look secret-like.
KEEP = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
                  "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
                  "PROGRAMDATA", "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "AUTOLAB_SEED",
                  "SESSIONNAME"})

PROFILES = {
    "ResearchSandbox": {
        "filesystem": "none, or a read-only checkout (validation, challenge)",
        "network": "the agent CLI's own model API only",
        "tools": "read-only tools (Read, Glob, Grep / codex read-only / agy plan mode)",
        "compute": "agent timeout (default 1800 s)", "execution": "no code execution",
        "secrets": "none from the lab",
        "enforced": ["filesystem", "tools", "execution", "compute"],
        "not_enforced": ["network"]},
    "CodingSandbox": {
        "filesystem": "own git worktree; protected paths (protocols, verification tests) reverted",
        "network": "the agent CLI's own model API only",
        "tools": "edit + python/pytest allowlist; git denied (claude); workspace-write sandbox "
                 "(codex); terminal sandbox (agy)",
        "compute": "agent timeout; controller test timeout", "execution": "tests in the worktree",
        "secrets": "test runs get a scrubbed environment",
        "enforced": ["filesystem (policy + tamper check)", "tools", "secrets (test runs)",
                     "compute"],
        "not_enforced": ["network", "OS-level isolation of engineer-run code"]},
    "TestingSandbox": {
        "filesystem": "verification worktree; only tests/verification/* may change",
        "network": "the agent CLI's own model API only",
        "tools": "as CodingSandbox", "compute": "agent timeout; hermetic test run",
        "execution": "verification tests, hermetic (no conftest, controller ini)",
        "secrets": "scrubbed environment for controller test runs",
        "enforced": ["filesystem (path policy)", "tools", "secrets (test runs)", "compute"],
        "not_enforced": ["network"]},
    "SimulationSandbox": {
        "filesystem": "detached read-only checkout of the exact commit; writes only to the trial "
                      "output directory (size-capped)",
        "network": "not blocked; protocols must pin data in data_paths and not download",
        "tools": "the protocol entrypoint only", "compute": "per-trial timeout, output cap, "
        "max_parallel, spend cap, CPU/memory accounting",
        "execution": "pinned interpreter, lock-file check, seeded",
        "secrets": "only the variables listed in protocol.secrets (frozen)",
        "enforced": ["filesystem (checkout + output cap)", "compute", "execution", "secrets"],
        "not_enforced": ["network", "OS-level isolation (no containers on this machine)"]},
    "DeploymentSandbox": {
        "status": "unavailable: there is no deployment plane yet (ROADMAP)",
        "enforced": ["no stage can deploy"], "not_enforced": []},
    "RobotSandbox": {
        "status": "unavailable: physical hardware is blocked until Gate 7's human safety review; "
                  "simulated bodies run in SimulationSandbox",
        "enforced": ["no stage can command hardware"], "not_enforced": []},
}
PROFILE_OF_ROLE = {Role.SCIENTIST: "ResearchSandbox", Role.ENGINEER: "CodingSandbox",
                   Role.VERIFIER: "TestingSandbox"}


def profile_for(role: Role, writable: bool) -> str:
    """Engineer/verifier stages that cannot write run read-only, like research."""
    return PROFILE_OF_ROLE[role] if writable or role == Role.SCIENTIST else "ResearchSandbox"


def scrubbed_env(env: dict, allowed_secrets: list[str] | tuple[str, ...] = ()) -> dict:
    """``env`` without credential-like variables, except those explicitly allowed."""
    allowed = set(allowed_secrets)
    return {k: v for k, v in env.items()
            if k in allowed or k.upper() in KEEP or not SECRET_NAME.search(k)}
