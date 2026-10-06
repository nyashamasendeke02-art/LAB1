"""Autopilot helpers (D39): directive parsing and usage-limit detection."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "autopilot", Path(__file__).resolve().parents[1] / "scripts" / "autopilot.py")
ap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ap)


def test_parse_directive_continue_with_retry():
    kind, detail, retry = ap.parse_directive("review done\nAUTOPILOT: CONTINUE RETRY=G1-4,G1-5")
    assert kind == "CONTINUE" and retry == ["G1-4", "G1-5"]


def test_parse_directive_uses_last_line_and_defaults_to_human():
    assert ap.parse_directive("AUTOPILOT: CONTINUE\n...\nAUTOPILOT: DONE gate 1")[0] == "DONE"
    assert ap.parse_directive("AUTOPILOT: NEEDS_HUMAN hardware")[:2] == ("NEEDS_HUMAN", "hardware")
    assert ap.parse_directive("no directive")[0] == "NEEDS_HUMAN"


def test_usage_limit_text():
    assert ap.is_usage_limit("You've hit your session limit · resets 2:30am")
    assert ap.is_usage_limit("API Error: 429 Too Many Requests")
    assert not ap.is_usage_limit("tests failed")
