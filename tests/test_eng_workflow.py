"""D56: engineering workflow -- approved machine-readable architecture before code; security and
performance reviews before integration; release manifest with every delivery."""

import json

from scenario import FAST_CONFIG, make, ok
from test_p0_lab_upgrades import build_ok, verify_spec

ENG_CONFIG = FAST_CONFIG.replace(
    'architecture_stage = false   # D56 stages are tested in test_eng_workflow.py\n'
    'pre_merge_reviews = []',
    'architecture_stage = true\narchitecture_rounds = 2\n'
    'pre_merge_reviews = ["security", "performance"]')
assert ENG_CONFIG != FAST_CONFIG

ARCH = {"architecture_summary": "one contracts module",
        "components": [{"name": "msg", "responsibility": "versioned messages",
                        "files": ["src/contracts/msg.py"], "interfaces": ["VERSION: int"]}],
        "test_strategy": "unit test the VERSION constant",
        "implementation_plan": [{"step": "add msg.py with VERSION", "files": ["src/contracts/msg.py"],
                                 "tests": ["tests/test_msg.py"]}],
        "requirements_trace": {"VERSION constant exists": ["msg"]}}
APPROVE = {"verdict": "approve", "issues": []}
REVISE = {"verdict": "revise", "issues": [{"severity": "major",
                                           "description": "no error handling for bad versions"}],
          "required_changes": ["validate VERSION"]}
PASS = {"verdict": "pass", "findings": [], "summary": "no issues"}


def seq(*payloads):
    calls = []

    def h(t):
        calls.append(t)
        return ok(payloads[min(len(calls) - 1, len(payloads) - 1)])
    h.calls = calls
    return h


def eng_lab(tmp_path, **over):
    handlers = {"eng__build": build_ok, "ver__verify": verify_spec,
                "eng__architecture": seq(ARCH), "ver__architecture_critique": seq(APPROVE),
                "ver__security_review": seq(PASS), "ver__performance_review": seq(PASS)}
    handlers.update(over)
    lab, ctl = make(tmp_path, config=ENG_CONFIG, **handlers)
    return lab, ctl, handlers


def stages(lab, pid):
    return [t.data["stage"] for t in lab.store.query("task") if t.data["project"] == pid]


def test_full_engineering_workflow_with_release_manifest(tmp_path):
    lab, ctl, h = eng_lab(tmp_path)
    builds = []
    orig = h["eng__build"]
    ctl.injected["engineer"].handlers["build"] = lambda t: (builds.append(t), orig(t))[1]
    pid = ctl.new_engineering_project("Versioned message contract module",
                                      ["VERSION constant exists"], ["REQ-LOG"])
    steps = ctl.run(pid)
    assert steps[-1].after == "COMPLETE", steps[-1]
    assert stages(lab, pid) == ["architecture", "architecture_critique", "build", "verify",
                                "security_review", "performance_review"]
    # the approved architecture reached the implementer
    assert builds[0].context["approved_architecture"]["components"][0]["name"] == "msg"
    # security and performance read the exact candidate, read-only
    sec = h["ver__security_review"].calls[0]
    assert sec.writable is False and "src/contracts/msg.py" in sec.context["changed_files"]
    dlv = lab.store.query("delivery")[0].data
    manifest = json.loads(lab.artifacts.get_text(dlv["refs"]["release"][7:]))
    assert manifest["commit"] == dlv["commit"] == lab.repo.rev("main")
    types = {r["type"] for r in manifest["reviews"]}
    assert {"architecture_critique", "code_review", "security_review",
            "performance_review"} <= types, types
    assert set(dlv["quality"]["pre_merge_reviews"]) == {"security", "performance"}
    assert manifest["architecture"].startswith("sha256:")
    events = [e["type"] for e in lab.store.events()]
    for etype in ("ArchitectureCreated", "ArchitectureApproved", "SecurityReviewCompleted",
                  "PerformanceReviewCompleted", "ReleaseProduced"):
        assert etype in events, etype


def test_architecture_revision_round(tmp_path):
    arch = seq(ARCH, {**ARCH, "architecture_summary": "with validation"})
    lab, ctl, _ = eng_lab(tmp_path, eng__architecture=arch,
                          ver__architecture_critique=seq(REVISE, APPROVE))
    pid = ctl.new_engineering_project("contract module", ["VERSION constant exists"])
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert len(arch.calls) == 2
    second = arch.calls[1].context
    assert second["critique_to_address"]["required_changes"] == ["validate VERSION"]
    assert second["previous_architecture"]["architecture_summary"] == "one contracts module"
    eng = lab.store.query("eng_task")[0].data
    assert eng["architecture"]["spec"]["architecture_summary"] == "with validation"


def test_no_code_without_an_approved_architecture(tmp_path):
    lab, ctl, h = eng_lab(tmp_path, ver__architecture_critique=seq(REVISE))
    pid = ctl.new_engineering_project("contract module", ["VERSION constant exists"])
    steps = ctl.run(pid)
    assert steps[-1].after == "HALTED"
    assert "architecture not approved" in lab.store.get(pid).data["halt_reason"]
    assert "build" not in stages(lab, pid)
    eng = lab.store.query("eng_task")[0].data
    assert eng["state"] == "SPEC" and not eng.get("worktree")
    assert lab.store.query("failure", category="architecture_rejected")


def test_blocking_security_finding_returns_to_patching(tmp_path):
    fail = {"verdict": "fail", "summary": "secret in code",
            "findings": [{"severity": "critical", "description": "API key committed"}]}
    sec = seq(fail, PASS)
    lab, ctl, _ = eng_lab(tmp_path, ver__security_review=sec)
    pid = ctl.new_engineering_project("contract module", ["VERSION constant exists"])
    assert ctl.run(pid)[-1].after == "COMPLETE"
    assert len(sec.calls) == 2
    assert stages(lab, pid).count("build") == 2  # patched after the security failure
    fails = lab.store.query("failure", category="security_review_failed")
    assert fails and "API key committed" in fails[0].data["summary"]


def test_research_track_is_unchanged(tmp_path):
    import scenario
    lab, ctl, h = eng_lab(tmp_path, ver__verify=scenario.verify_pass)
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    s = stages(lab, pid)
    assert not {"architecture", "architecture_critique", "security_review",
                "performance_review"} & set(s)
