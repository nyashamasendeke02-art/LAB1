"""Engineering workflow stages (D56, master prompt sections 11, 27 and 30).

Engineering-track projects follow:

    requirements (spec + acceptance criteria)
      -> architecture            machine-readable: components, interfaces, data flows, decisions,
                                 risks, test strategy, implementation plan     (Systems Architect)
      -> architecture critique   a different agent approves or asks for revision   (critic)
      -> implementation -> testing -> adversarial review (existing engineering machine)
      -> security review -> performance review                   (Security / Performance agents)
      -> integration (merge, review gates) -> evaluation + release manifest (delivery)

"No major implementation should proceed without a machine-readable architecture and
requirements specification": until the critique approves, no worktree exists and no code is
written; if the critique still asks for revision after ``architecture_rounds``, the project
HALTs for a human. A critical or major security/performance finding sends the work back to the
patch loop like any failed review. Stages are configurable in ``[engineering]``.
"""

from __future__ import annotations

import json

from .store import Record, canonical
from .taxonomy import Role

BLOCKING = ("critical", "major")


class EngineeringWorkflowMixin:
    """Mixed into Controller; uses its _call, _scratch_checkout, repo, store, cfg."""

    # ------------------------------------------------------------------ config
    def _wf(self) -> dict:
        e = self.cfg["engineering"]
        return {"architecture": bool(e.get("architecture_stage", True)),
                "rounds": int(e.get("architecture_rounds", 2)),
                "reviews": list(e.get("pre_merge_reviews", ["security", "performance"]))}

    def _event(self, etype: str, subject: str, data: dict) -> None:
        self.store.append_event("controller", etype, subject, data)

    # ------------------------------------------------------------------ architecture
    def _architecture_step(self, pid: str, eng: Record) -> str | None:
        """One architecture/critique action, or None once the architecture is approved
        (or the stage is disabled / not an engineering-track project)."""
        if not (self._is_engineering(pid) and self._wf()["architecture"]):
            return None
        arch = eng.data.get("architecture") or {}
        if arch.get("status") == "approved":
            return None
        proj = self.project(pid).data
        wt = self._scratch_checkout(f"arch-{eng.id}", self.repo.rev("main"))
        try:
            if arch.get("status") in (None, "revise"):
                ctx = {"engineering_spec": proj["objective"],
                       "acceptance_criteria": proj["acceptance_criteria"],
                       "mandate_refs": proj.get("mandate_refs", []),
                       "specialty": proj.get("specialty")}
                if arch.get("status") == "revise":
                    ctx["previous_architecture"] = arch.get("spec")
                    ctx["critique_to_address"] = arch.get("critique")
                payload, tid = self._call(pid, Role.ENGINEER, "architecture", ctx, workdir=wt)
                rounds = arch.get("rounds", 0) + 1
                sha = self.lab.artifacts.put_text(canonical(payload))
                arch = {"status": "proposed", "spec": payload, "rounds": rounds,
                        "artifact": "sha256:" + sha, "task": tid,
                        "history": arch.get("history", []) + [{"round": rounds, "task": tid}]}
                self.store.update(eng.id, {"architecture": arch},
                                  reason=f"architecture proposed (round {rounds})")
                self._event("ArchitectureCreated", eng.id, {"round": rounds, "task": tid,
                                                            "artifact": arch["artifact"]})
                return f"architecture proposed (round {rounds})"
            # status == "proposed": critique by a different agent
            payload, tid = self._call(pid, Role.VERIFIER, "architecture_critique", {
                "engineering_spec": proj["objective"],
                "acceptance_criteria": proj["acceptance_criteria"],
                "architecture": arch["spec"]}, workdir=wt)
        finally:
            self.repo.remove_worktree(wt)
        blocking = [i for i in payload["issues"] if i["severity"] in BLOCKING]
        approved = payload["verdict"] == "approve" and not blocking
        rev = self.store.create("review", {
            "review_type": "architecture_critique", **payload, "approved": approved,
            "round": arch["rounds"], "project": pid,
            "refs": {"eng_task": eng.id, "task": tid}},
            prefix="REV", author="verifier", reason="architecture critique")
        arch = {**arch, "critique": payload, "critique_review": rev.id,
                "status": "approved" if approved else "revise"}
        self.store.update(eng.id, {"architecture": arch},
                          reason=f"architecture {'approved' if approved else 'needs revision'}")
        if approved:
            self._event("ArchitectureApproved", eng.id, {"review": rev.id,
                                                         "round": arch["rounds"]})
            return f"architecture approved ({rev.id})"
        if arch["rounds"] >= self._wf()["rounds"]:
            self._failure(pid, "architecture_rejected",
                          f"architecture not approved after {arch['rounds']} rounds: "
                          + "; ".join(i["description"] for i in payload["issues"])[:400],
                          {"eng_task": eng.id, "review": rev.id})
            self._halt(pid, f"{eng.id}: architecture not approved after {arch['rounds']} rounds; "
                            f"no implementation without an approved architecture (human "
                            f"direction required)")
            return "architecture rejected"
        return f"architecture revision requested ({rev.id})"

    def _architecture_context(self, eng: Record) -> dict:
        arch = eng.data.get("architecture") or {}
        if arch.get("status") != "approved":
            return {}
        return {"approved_architecture": arch["spec"],
                "architecture_rule": "Implement the approved architecture; if it must change, "
                                     "say so in design_notes and why."}

    # ------------------------------------------------------------------ quality reviews
    def _quality_review_step(self, pid: str, eng: Record, head: str) -> str | None:
        """Run the next pending pre-merge review (security, performance) on ``head``; None
        when all have passed for this head. A blocking finding returns the patch loop note."""
        if not self._is_engineering(pid):
            return None
        done = eng.data.get("quality_reviews", {}).get(head, {})
        pending = [r for r in self._wf()["reviews"] if r not in done]
        if not pending:
            return None
        kind = pending[0]
        proj = self.project(pid).data
        wt = self._scratch_checkout(f"{kind}-{eng.id}", head)
        try:
            payload, tid = self._call(pid, Role.VERIFIER, f"{kind}_review", {
                "engineering_spec": proj["objective"],
                "acceptance_criteria": proj["acceptance_criteria"],
                "changed_files": self.repo.changed_files(eng.data["base"], head),
                "diff": self.repo.diff(eng.data["base"], head)[-20000:],
                **self._architecture_context(eng)}, workdir=wt)
        finally:
            self.repo.remove_worktree(wt)
        blocking = [f for f in payload["findings"] if f["severity"] in BLOCKING]
        passed = payload["verdict"] == "pass" and not blocking
        rev = self.store.create("review", {
            "review_type": f"{kind}_review", **payload, "passed": passed, "commit": head,
            "project": pid, "refs": {"eng_task": eng.id, "task": tid}},
            prefix="REV", author="verifier", reason=f"{kind} review")
        self._event(f"{kind.title()}ReviewCompleted", eng.id,
                    {"review": rev.id, "passed": passed, "commit": head})
        qr = dict(eng.data.get("quality_reviews", {}))
        qr[head] = {**done, kind: {"review": rev.id, "passed": passed}}
        eng = self.store.update(eng.id, {"quality_reviews": qr},
                                reason=f"{kind} review {'passed' if passed else 'failed'}")
        if passed:
            return f"{kind} review passed ({rev.id})"
        lines = [f"[{f['severity']}] {f['description']}" for f in payload["findings"]]
        return self._eng_fail(pid, eng, f"{kind.title()} review {rev.id} failed:\n"
                              + "\n".join(lines), f"{kind}_review_failed")

    # ------------------------------------------------------------------ release
    def _release_manifest(self, pid: str, eng: Record) -> tuple[str, dict]:
        """A verifiable release record for an engineering delivery (evaluation of system
        quality + provenance): spec, architecture, every review, tests, commit."""
        proj = self.project(pid).data
        head = self.repo.rev(eng.data["merge_candidate"]) if eng.data.get("merge_candidate") \
            else eng.data["merge_commit"]
        reviews = [r for r in self.store.query("review", project=pid)
                   if r.data.get("refs", {}).get("eng_task") == eng.id]
        quality = {
            "tests": [t for t in eng.data.get("test_runs", [])][-3:],
            "adversarial_review": eng.data.get("last_review"),
            "pre_merge_reviews": eng.data.get("quality_reviews", {}).get(head, {}),
            "architecture_review": (eng.data.get("architecture") or {}).get("critique_review"),
            "patch_attempts": eng.data.get("patch_attempts", 0),
            "redesigns": eng.data.get("redesigns", 0),
            "findings_by_severity": {
                sev: sum(1 for r in reviews for f in r.data.get("findings", []) + r.data.get("issues", [])
                         if isinstance(f, dict) and f.get("severity") == sev)
                for sev in ("critical", "major", "minor", "note")},
        }
        manifest = {
            "release_of": pid, "spec": proj["objective"],
            "acceptance_criteria": proj["acceptance_criteria"],
            "specialty": proj.get("specialty"), "mandate_refs": proj.get("mandate_refs", []),
            "commit": eng.data["merge_commit"],
            "architecture": (eng.data.get("architecture") or {}).get("artifact"),
            "reviews": [{"id": r.id, "type": r.data.get("review_type"),
                         "verdict": r.data.get("verdict")} for r in reviews],
            "quality": quality, "ledger_head": self.store.head(),
        }
        sha = self.lab.artifacts.put_text(json.dumps(manifest, indent=2, sort_keys=True,
                                                     default=str))
        return "sha256:" + sha, quality
