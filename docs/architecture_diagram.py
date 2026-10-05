"""Generate docs/architecture.svg (and docs/architecture.png via headless Edge/Chrome).

    python docs/architecture_diagram.py

The diagram mirrors docs/ARCHITECTURE.md; update both together.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

W, H = 1800, 1262
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
MONO = "Consolas, Menlo, monospace"
INK, MUTED = "#1f2937", "#5b6472"

C = {  # (fill, stroke)
    "human": ("#fff4e0", "#d98a00"),
    "ctl": ("#eef4ff", "#3565c9"),
    "sci": ("#e8f6ee", "#2e8f57"),
    "eng": ("#fdeee5", "#cf6a32"),
    "ver": ("#efeaff", "#6a4fd0"),
    "store": ("#f3f4f6", "#6b7280"),
    "halt": ("#fdecec", "#c43c3c"),
}
GATE = "#e0a100"

out: list[str] = []


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def rect(x, y, w, h, fill, stroke, rx=12, sw=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
               f'stroke="{stroke}" stroke-width="{sw}"{d}/>')


def text(x, y, s, size=13, weight=400, anchor="start", fill=INK, family=FONT, italic=False):
    st = ' font-style="italic"' if italic else ""
    out.append(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
               f'font-weight="{weight}" text-anchor="{anchor}" fill="{fill}"{st}>{esc(s)}</text>')


def lead_text(x, y, lead, rest, size=13):
    out.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="{INK}">'
               f'<tspan font-weight="700">{esc(lead)}</tspan>{esc(rest)}</text>')


def lines(x, y, items, size=12.5, lh=17, **kw):
    for i, s in enumerate(items):
        text(x, y + i * lh, s, size=size, **kw)
    return y + len(items) * lh


def wrap(s, width):
    return textwrap.wrap(s, width)


def gate(x, y):
    out.append(f'<circle cx="{x}" cy="{y}" r="10" fill="{GATE}" stroke="#fff" stroke-width="2"/>')
    text(x, y + 4.5, "G", size=12, weight=800, anchor="middle", fill="#fff")


def pill(cx, cy, w, h, label, stroke, size=11.5, gated=False, fill="#ffffff"):
    rect(cx - w / 2, cy - h / 2, w, h, fill, stroke, rx=h / 2 if h < 30 else 10, sw=1.8)
    parts = label.split("\n")
    y0 = cy - (len(parts) - 1) * (size + 2) / 2 + size * 0.36
    for i, p in enumerate(parts):
        text(cx, y0 + i * (size + 2), p, size=size, weight=700, anchor="middle")
    if gated:
        gate(cx + w / 2 - 4, cy - h / 2 + 2)


def arrow(x1, y1, x2, y2, color=INK, dash=None, both=False, sw=1.6):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m0 = ' marker-start="url(#a0)"' if both else ""
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
               f'stroke-width="{sw}"{d} marker-end="url(#a1)"{m0}/>')


def path_arrow(d, color=INK, dash=None, sw=1.6):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da} '
               f'marker-end="url(#a1)"/>')


def label_bg(x, y, s, size=11.5, fill=MUTED, weight=600):
    w = len(s) * size * 0.56 + 10
    out.append(f'<rect x="{x - w / 2}" y="{y - size}" width="{w}" height="{size + 6}" rx="4" '
               f'fill="{C["ctl"][0]}"/>')
    text(x, y, s, size=size, anchor="middle", fill=fill, weight=weight)


def build() -> str:
    out.clear()
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
               f'viewBox="0 0 {W} {H}">')
    out.append('<defs>'
               '<marker id="a1" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
               'fill="context-stroke"/></marker>'
               '<marker id="a0" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
               'fill="context-stroke"/></marker></defs>')
    rect(0, 0, W, H, "#ffffff", "#ffffff", rx=0, sw=0)

    # ---------------------------------------------------------------- title
    text(40, 44, "Autonomous Research Lab (autolab v0.2.0): architecture", size=26, weight=800)
    text(40, 72, "The controller owns all state · agents propose · the controller records, "
                 "verifies and transitions · the human approves and has final authority",
         size=14, fill=MUTED)

    # ---------------------------------------------------------------- human
    rect(40, 100, 1320, 62, *C["human"])
    text(60, 127, "HUMAN RESEARCHER: final authority", size=16, weight=800)
    text(60, 149, "submits the objective · approves or rejects gates · halt / amend frozen protocol "
                  "/ resume · accepts major conclusions", size=13, fill=MUTED)
    arrow(700, 162, 700, 198, C["human"][1], both=True)
    text(712, 186, "autolab CLI", size=12, weight=600, fill=C["human"][1])

    rect(1420, 100, 340, 62, *C["store"], sw=1.5)
    text(1436, 124, "Lab instance  labs/<name>/", size=13, weight=700)
    text(1436, 145, "lab.toml · .autolab/lab.db · repo/ · worktrees/", size=11.5,
         family=MONO, fill=MUTED)
    text(1436, 158, "runs/ · reports/ · project_state/", size=11.5, family=MONO, fill=MUTED)

    # ----------------------------------------------------------- controller
    rect(40, 200, 1320, 820, *C["ctl"], sw=2.5)
    text(60, 234, "CONTROLLER  (controller.py)", size=20, weight=800, fill=C["ctl"][1])
    text(60, 256, "one state-machine action per step() · records everything, then at most one "
                  "transition · any process can resume a project from the DB after a crash",
         size=13, fill=MUTED)
    text(60, 292, "RESEARCH STATE MACHINE  (state_machines.py · whitelisted transitions)",
         size=13, weight=800, fill=C["ctl"][1])

    cx = [131 + 160 * i for i in range(8)]
    pw, ph = 132, 48
    r1, r2, r3 = 340, 460, 548
    row1 = ["DEFINE\nPROBLEM", "BACKGROUND\nRESEARCH", "RESEARCH\nQUESTION", "HYPOTHESIS",
            "REQUIREMENTS", "DESIGN", "SCIENTIFIC\nREVIEW", "PROTOCOL\nFREEZE"]
    for i, lab in enumerate(row1):
        pill(cx[i], r1, pw, ph, lab, C["ctl"][1], gated=(i == 7))
    for i in range(7):
        both = i == 5
        arrow(cx[i] + pw / 2 + 2, r1, cx[i + 1] - pw / 2 - 2, r1, both=both)
    text((cx[5] + cx[6]) / 2, 305, "approve / revise", size=11, anchor="middle", fill=MUTED,
         weight=600)

    row2 = {7: "ENGINEERING", 6: "SCIENTIFIC\nVALIDATION", 5: "RUN\nEXPERIMENT", 4: "ANALYZE",
            3: "CHALLENGE", 2: "EVALUATE", 1: "COMMUNICATE", 0: "NEXT\nQUESTION"}
    for i, lab in row2.items():
        pill(cx[i], r2, pw, ph, lab, C["ctl"][1], gated=(i == 5),
             fill="#fff7ef" if i == 7 else "#ffffff")
    for i in range(7, 0, -1):
        arrow(cx[i] - pw / 2 - 2, r2, cx[i - 1] + pw / 2 + 2, r2)
    text((cx[2] + cx[1]) / 2, r2 + 40, "valid", size=11, anchor="middle", fill=MUTED, weight=600)

    # freeze -> engineering
    arrow(cx[7], r1 + ph / 2 + 2, cx[7], r2 - ph / 2 - 2)
    text(cx[7] + 8, 404, "frozen", size=11, fill=MUTED, weight=600)
    # back edges in the gap between rows
    top2, bot1 = r2 - ph / 2 - 2, r1 + ph / 2 + 2
    arrow(cx[2] + 20, top2, cx[5] - 26, bot1, "#8a5a00", dash="6 4")
    label_bg((cx[2] + cx[5]) / 2, 402, "invalid / inconclusive → redesign", fill="#8a5a00")
    arrow(cx[7] - 40, top2, cx[5] + 26, bot1, "#8a5a00", dash="6 4")
    label_bg((cx[7] + cx[5]) / 2 - 10, 402, "escalated", fill="#8a5a00")
    arrow(cx[0] + 20, top2, cx[2] - 20, bot1, C["ctl"][1], dash="6 4")
    label_bg((cx[0] + cx[2]) / 2, 402, "next cycle", fill=C["ctl"][1])

    # terminal states
    pill(cx[0], r3, pw, 36, "COMPLETE", "#2e8f57", fill="#e8f6ee")
    arrow(cx[0], r2 + ph / 2 + 2, cx[0], r3 - 20)
    rect(222, 528, 420, 42, *C["halt"], rx=10, sw=1.6)
    text(236, 545, "HALTED ← any non-terminal state", size=12, weight=800, fill=C["halt"][1])
    text(236, 562, "retries / budgets exhausted, integrity violation; exit only by human resume",
         size=11, fill=MUTED)
    rect(660, 528, 610, 42, "#fffaf0", GATE, rx=10, sw=1.6)
    gate(678, 549)
    text(696, 545, "Human approval gates (agents can never approve):", size=12, weight=800)
    text(696, 562, "confirmatory pre-registration · protected experiment · compute budget · "
                   "merge (optional)", size=11, fill=MUTED)

    # ------------------------------------------------- engineering machine
    rect(700, 600, 640, 192, "#fff7ef", C["eng"][1], rx=10, sw=1.6)
    arrow(1290, r2 + ph / 2 + 2, 1290, 598, C["eng"][1], dash="2 4")
    text(1297, 590, "delegates", size=11, fill=C["eng"][1], weight=600)
    text(716, 622, "ENGINEERING STATE MACHINE  (one per ENG task)", size=13, weight=800,
         fill=C["eng"][1])
    ex = [758 + 106 * i for i in range(6)]
    elabels = ["SPEC", "IMPLEMENTING", "TESTING", "ADVERSARIAL\nREVIEW", "MERGE", "MERGED"]
    for i, lab in enumerate(elabels):
        pill(ex[i], 660, 92, 40, lab, C["eng"][1], size=10.5, gated=(i == 4))
    for i in range(5):
        arrow(ex[i] + 47, 660, ex[i + 1] - 47, 660)
    path_arrow(f"M {ex[3]} 681 C {ex[3]} 712, {ex[1]} 712, {ex[1]} 682", "#8a5a00", dash="6 4")
    text(ex[2], 724, "tests or review fail → patch", size=11.5, anchor="middle",
         fill="#8a5a00", weight=600)
    text(716, 752, "≥ 3 failed patches → REDESIGN: fresh branch from main + full failure history",
         size=12)
    text(716, 772, "≥ 2 redesigns → ESCALATED → research DESIGN (approach inadequate)", size=12)

    # ------------------------------------------------------- mechanisms
    rect(60, 600, 620, 400, "#ffffff", C["ctl"][1], rx=10, sw=1.4)
    text(76, 624, "CONTROLLER MECHANISMS", size=13, weight=800, fill=C["ctl"][1])
    mech = [
        ("Agent dispatch: ", "builds the TaskPacket, extracts the JSON answer, validates it "
         "against the stage schema; up to 2 protocol retries; rejected answers are stored."),
        ("Integrity check: ", "after every agent call, main HEAD and clean tree, ledger chain "
         "and lab.toml must be unchanged, otherwise HALT (never retried)."),
        ("Commits, path policy, merge: ", "the controller commits for agents; edits to protected "
         "paths are reverted. Merge needs controller tests, the verifier's tests passing in a "
         "hermetic run, and a verifier pass with no critical/major finding."),
        ("Experiment engine: ", "detached checkout of the merged commit; smoke test on a "
         "non-protocol seed; then every condition × seed with --params = fixed_params + condition "
         "params; raw data hashed and made read-only."),
        ("Analysis: ", "the pre-registered decision rule with Student / Welch t intervals and "
         "validity checks gives the outcome before any agent interprets it; looks per hypothesis "
         "are counted."),
        ("Processes: ", "agents, tests and trials run in kill-on-close job objects, "
         "so no orphaned processes."),
    ]
    y = 650
    for lead, rest in mech:
        ls = wrap(lead + rest, 84)
        lead_text(76, y, lead, ls[0][len(lead):], size=13)
        y = lines(76, y + 18, ls[1:], size=13, lh=18) + 9

    # ------------------------------------------------ communication protocol
    rect(700, 806, 640, 194, "#ffffff", C["ctl"][1], rx=10, sw=1.4)
    text(716, 828, "AGENT COMMUNICATION PROTOCOL  (messages.py · prompts.py)", size=13,
         weight=800, fill=C["ctl"][1])
    rect(714, 840, 294, 112, "#f7f9ff", "#9fb3e0", rx=8, sw=1.2)
    text(726, 858, "TaskPacket  (controller → agent)", size=12.5, weight=800)
    lines(726, 876, ["task_id · role · stage", "objective (neutral if blinded)",
                     "context: explicit; no conversation memory",
                     "constraints · acceptance_criteria",
                     "workdir · writable · output_schema"], size=11.5, lh=15)
    arrow(1010, 896, 1032, 896, both=True)
    rect(1034, 840, 294, 112, "#f7f9ff", "#9fb3e0", rx=8, sw=1.2)
    text(1046, 858, "Completion  (agent → controller)", size=12.5, weight=800)
    lines(1046, 876, ["status: complete | blocked | needs_review | failed",
                      "summary · risks[]",
                      "payload: validated against STAGE_SCHEMAS",
                      "research_claims[]: each labelled",
                      "invalid → rejected, retried, stored"], size=11.5, lh=15)
    lines(716, 972, ["Evidence labels: ESTABLISHED · SOURCE_CLAIM · HYPOTHESIS · "
                     "ENGINEERING_DECISION · EXPERIMENTAL_RESULT",
                     "(must cite a run the controller recorded) · INFERENCE · OPEN_QUESTION"],
          size=11.5, lh=15, fill=MUTED)

    # ------------------------------------------------------------- agents
    def agent(y, h, key, name, vendor, cmd, body):
        f, s = C[key]
        rect(1420, y, 340, h, f, s)
        text(1436, y + 26, name, size=16, weight=800, fill=s)
        text(1744, y + 26, vendor, size=13, weight=700, anchor="end", fill=s)
        text(1436, y + 46, cmd, size=11.5, family=MONO, fill=INK)
        yy = y + 68
        for lead, rest in body:
            ls = wrap(lead + rest, 46)
            lead_text(1436, yy, lead, ls[0][len(lead):], size=12.5)
            yy = lines(1436, yy + 17, ls[1:], size=12.5, lh=17) + 4
        arrow(1362, y + h / 2, 1418, y + h / 2, s, both=True)
        text(1390, y + h / 2 - 7, "JSON", size=10, weight=700, anchor="middle", fill=s)

    agent(200, 212, "sci", "SCIENTIST", "ChatGPT", "codex exec --sandbox read-only", [
        ("Writes: ", "nothing"),
        ("Stages: ", "define problem · background research · research question · hypothesis "
         "· requirements · design (options + protocol) · scientific review · scientific "
         "validation (reads the merged code) · interpret · communicate · next question"),
    ])
    agent(430, 205, "eng", "ENGINEER", "Claude", "claude -p · acceptEdits · no git", [
        ("Worktree: ", "eng/<ENG>-d<n>, branched from main"),
        ("May write: ", "anything except protocols/ and tests/verification/"),
        ("Stages: ", "solution design (read-only) · implement · redesign"),
        ("Blinded: ", "no hypothesis, decision rule or earlier results"),
    ])
    agent(653, 215, "ver", "VERIFIER", "Codex", "codex exec --sandbox workspace-write", [
        ("Worktree: ", "verify/<ENG>-r<n>, from the engineer's head"),
        ("May write: ", "tests/verification/* only"),
        ("verify: ", "adversarial code review + at least 1 independent pytest (blinded)"),
        ("challenge: ", "read-only attack on results and raw data"),
    ])
    rect(1420, 886, 340, 134, "#fafafa", "#9aa1ad", rx=10, sw=1.4, dash="5 4")
    text(1436, 908, "All agent CLIs are hermetic", size=13, weight=800)
    lines(1436, 928, ["claude: no settings, MCP, skills, auto-memory",
                      "codex: --ignore-user-config, --ignore-rules;",
                      "  plugins, apps, memories disabled",
                      "the task packet is the only context",
                      "agents never touch the DB, never run git,",
                      "  never decide transitions"], size=11.5, lh=15, fill=MUTED)

    # ------------------------------------------------------------ storage
    arrow(700, 1022, 700, 1058, C["store"][1], both=True)
    text(712, 1046, "records · ledger events · commits · artifacts", size=12, weight=600,
         fill=C["store"][1])
    arrow(1590, 1022, 1590, 1058, C["store"][1], dash="2 4")
    text(1600, 1046, "files in own worktree only", size=11, weight=600, fill=C["store"][1])
    boxes = [
        ("STORE", "store.py · SQLite .autolab/lab.db",
         "Versioned, immutable records (SQL triggers block UPDATE and DELETE) · sha256 "
         "hash-chained event ledger · frozen protocols; amendments carry a justification and "
         "a new freeze hash"),
        ("ARTIFACTS", "content-addressed (sha256)",
         "Read-only files: prompts, raw agent responses (including rejected ones), completions, "
         "test logs, raw trial data, run manifests, reports"),
        ("MEMORY & REPORTS", "memory.py · report.py",
         "project_state/*.md regenerated every step · lineage trace: conclusion → result → run → "
         "commit → frozen protocol → design → hypothesis → agent tasks · reports/"),
        ("GIT", "worktrees.py · repo/",
         "main changes only through controller --no-ff merges with provenance trailers · one "
         "worktree and branch per agent task; branches never deleted · ledger head anchored "
         "in commits"),
    ]
    for i, (name, sub, body) in enumerate(boxes):
        x = 40 + i * 435
        rect(x, 1060, 415, 138, *C["store"])
        text(x + 16, 1086, name, size=15, weight=800)
        text(x + 16, 1105, sub, size=11.5, family=MONO, fill=MUTED)
        lines(x + 16, 1128, wrap(body, 60), size=12.5, lh=17)

    # ------------------------------------------------------------- legend
    lx, ly = 40, 1230
    text(lx, ly + 4, "Legend", size=13, weight=800)
    lx += 70
    for key, name in (("human", "Human"), ("ctl", "Controller"), ("sci", "Scientist (ChatGPT)"),
                      ("eng", "Engineer (Claude)"), ("ver", "Verifier (Codex)"),
                      ("store", "Storage")):
        rect(lx, ly - 9, 22, 16, *C[key], rx=4, sw=1.5)
        text(lx + 30, ly + 4, name, size=12.5)
        lx += 58 + len(name) * 6.6
    gate(lx + 8, ly)
    text(lx + 24, ly + 4, "human approval gate", size=12.5)
    lx += 175
    arrow(lx, ly, lx + 40, ly, "#8a5a00", dash="6 4")
    text(lx + 48, ly + 4, "loop back / redesign", size=12.5)
    lx += 200
    arrow(lx, ly, lx + 40, ly, C["store"][1], dash="2 4")
    text(lx + 48, ly + 4, "delegation / file access", size=12.5)
    text(W - 40, ly + 4, "source: docs/architecture_diagram.py", size=11, anchor="end",
         fill=MUTED)
    out.append("</svg>")
    return "\n".join(out)


def find_browser() -> str | None:
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(c).exists():
            return c
    return shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("msedge")


def main() -> int:
    here = Path(__file__).resolve().parent
    svg = here / "architecture.svg"
    svg.write_bytes(build().encode("utf-8"))
    print(f"wrote {svg}")
    browser = find_browser()
    if not browser:
        print("no Edge/Chrome found; PNG not rendered", file=sys.stderr)
        return 1
    png = here / "architecture.png"
    png.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", f"--window-size={W},{H}",
                        f"--user-data-dir={profile}", f"--screenshot={png}", svg.as_uri()],
                       check=True, capture_output=True, timeout=120)
        # Edge's launcher can return before the headless process has written the file.
        deadline = time.monotonic() + 60
        while not png.exists() and time.monotonic() < deadline:
            time.sleep(0.5)
    if not png.exists():
        print("browser did not write the PNG", file=sys.stderr)
        return 1
    print(f"wrote {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
