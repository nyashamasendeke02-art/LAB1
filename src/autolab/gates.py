"""Safety and approval gates.

A gate is a named checkpoint where the controller must obtain an explicit
human decision. Requests and decisions are versioned records plus ledger
events; only actor ``human`` can decide. Agents cannot approve anything.

Delegation: the human may delegate named gates to a named delegate in lab.toml
(``[gates.delegation] delegate = "claude-code", gates = [...]``). A delegated
decision is recorded as ``decided_by=<delegate>, delegated_by="human"``, never
as the human. Agent role names can never be delegates.
"""

from __future__ import annotations

from .store import Record, Store

PROTECTED_EXPERIMENT = "protected_experiment"
CONFIRMATORY_FREEZE = "confirmatory_protocol_freeze"
MERGE_TO_MAIN = "merge_to_main"
COMPUTE_BUDGET = "compute_budget"
REVIEW_PREFIX = "review:"  # path-based review gates, e.g. "review:safety"

AGENT_ROLES = {"scientist", "engineer", "verifier", "controller"}


class GateError(Exception):
    pass


class Gates:
    def __init__(self, store: Store, delegation: dict | None = None):
        self.store = store
        delegation = delegation or {}
        self.delegate = delegation.get("delegate") or None
        if self.delegate in AGENT_ROLES:
            raise GateError(f"agent role {self.delegate!r} cannot be a gate delegate")
        self.delegated = set(delegation.get("gates", []))

    def may_decide(self, gate: str, by: str) -> bool:
        if by == "human":
            return True
        return bool(self.delegate) and by == self.delegate and (
            gate in self.delegated or "*" in self.delegated)

    def find(self, gate: str, subject: str) -> Record | None:
        hits = [r for r in self.store.query("approval", gate=gate, subject=subject)]
        return hits[-1] if hits else None

    def request(self, gate: str, subject: str, summary: str, details: dict | None = None,
                project: str | None = None) -> Record:
        existing = self.find(gate, subject)
        if existing and existing.data["status"] == "pending":
            return existing
        rec = self.store.create("approval", {
            "gate": gate, "subject": subject, "summary": summary,
            "details": details or {}, "status": "pending", "project": project,
            "refs": {"subject": subject},
        }, prefix="APR", reason=f"approval requested for {gate}")
        self.store.append_event("controller", "gate.requested", rec.id,
                                {"gate": gate, "subject": subject})
        return rec

    def decide(self, approval_id: str, approved: bool, by: str = "human",
               note: str = "") -> Record:
        rec = self.store.get(approval_id)
        if not self.may_decide(rec.data["gate"], by):
            raise GateError(f"{by!r} may not decide {rec.data['gate']} gates (only the human, "
                            f"or a delegate the human named for this gate in lab.toml)")
        if rec.data["status"] != "pending":
            raise GateError(f"{approval_id} already {rec.data['status']}")
        if by != "human" and not note.strip():
            raise GateError("a delegated decision needs a rationale (--note)")
        status = "approved" if approved else "rejected"
        extra = {} if by == "human" else {"delegated_by": "human"}
        new = self.store.update(approval_id, {"status": status, "decided_by": by,
                                              "note": note, **extra},
                                author=by, reason=f"{status}: {note or 'no note'}")
        self.store.append_event(by, f"gate.{status}", approval_id,
                                {"gate": rec.data["gate"], "subject": rec.data["subject"],
                                 **extra})
        return new

    def pending(self) -> list[Record]:
        return self.store.query("approval", status="pending")
