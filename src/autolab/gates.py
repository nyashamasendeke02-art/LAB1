"""Safety and approval gates.

A gate is a named checkpoint where the controller must obtain an explicit
human decision. Requests and decisions are versioned records plus ledger
events; only actor ``human`` can decide. Agents cannot approve anything.
"""

from __future__ import annotations

from .store import Record, Store

PROTECTED_EXPERIMENT = "protected_experiment"
CONFIRMATORY_FREEZE = "confirmatory_protocol_freeze"
MERGE_TO_MAIN = "merge_to_main"
COMPUTE_BUDGET = "compute_budget"


class GateError(Exception):
    pass


class Gates:
    def __init__(self, store: Store):
        self.store = store

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
        if by != "human":
            raise GateError("only the human researcher can decide approval gates")
        rec = self.store.get(approval_id)
        if rec.data["status"] != "pending":
            raise GateError(f"{approval_id} already {rec.data['status']}")
        status = "approved" if approved else "rejected"
        new = self.store.update(approval_id, {"status": status, "decided_by": by,
                                              "note": note},
                                author=by, reason=f"{status}: {note or 'no note'}")
        self.store.append_event(by, f"gate.{status}", approval_id,
                                {"gate": rec.data["gate"], "subject": rec.data["subject"]})
        return new

    def pending(self) -> list[Record]:
        return self.store.query("approval", status="pending")
