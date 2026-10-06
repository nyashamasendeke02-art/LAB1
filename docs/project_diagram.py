"""Generate docs/project.svg (and docs/project.png via headless Edge/Chrome).

    python docs/project_diagram.py

Whole-project schematic: people and control, the programme (gates), the autolab lab,
the robolab robot brain, and records/backup. Status as of the date in the subtitle;
update with PROJECT_STATE.md.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

W, H = 2000, 1450
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
INK, MUTED = "#1f2937", "#5b6472"

L = {  # (fill, stroke)
    "people": ("#fff4e0", "#d98a00"),
    "prog": ("#f1ebff", "#7a5cc9"),
    "lab": ("#e8f1fd", "#3b78c4"),
    "brain": ("#eaf6ec", "#3f9a55"),
    "safe": ("#fde8e8", "#c43c3c"),
    "adapt": ("#fff1e0", "#d98a2b"),
    "rec": ("#eef0f3", "#7b8594"),
}
STATUS = {
    "PASSED": ("#2e8f57", "#fff"), "BUILT": ("#2e8f57", "#fff"),
    "IN PROGRESS": ("#e0a100", "#fff"), "NEXT": ("#e0a100", "#fff"),
    "INTERFACE": ("#5a9bd8", "#fff"), "PLANNED": ("#9aa3af", "#fff"),
    "LATER": ("#c9ced6", INK), "HUMAN": ("#d98a00", "#fff"), "OPTIONAL": ("#c9ced6", INK),
    "RUNNING": ("#2e8f57", "#fff"), "TODO": ("#c43c3c", "#fff"),
}
BLUE, RED, GREEN, ORANGE, PURPLE = "#2f6fd0", "#c43c3c", "#2e8f57", "#d98a2b", "#7a5cc9"

out: list[str] = []


def esc(s):
    return html.escape(s, quote=True)


def rect(x, y, w, h, fill, stroke, rx=12, sw=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
               f'stroke="{stroke}" stroke-width="{sw}"{d}/>')


def text(x, y, s, size=13, weight=400, anchor="start", fill=INK, italic=False):
    st = ' font-style="italic"' if italic else ""
    out.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
               f'font-weight="{weight}" text-anchor="{anchor}" fill="{fill}"{st}>{esc(s)}</text>')


def badge(x_right, y, label):
    fill, ink = STATUS[label.split(" ·")[0]]
    w = len(label) * 6.4 + 14
    rect(x_right - w, y, w, 18, fill, fill, rx=9, sw=1)
    text(x_right - w / 2, y + 13, label, size=10.5, weight=700, anchor="middle", fill=ink)


def card(x, y, w, h, title, sub, key, status=None, ts=15, ss=12.2, lh=16):
    rect(x, y, w, h, "#ffffff", L[key][1], rx=10, sw=1.6)
    text(x + 12, y + 24, title, size=ts, weight=700)
    for i, s in enumerate(sub):
        text(x + 12, y + 44 + i * lh, s, size=ss, fill=MUTED)
    if status:
        badge(x + w - 8, y + 8, status)


def band(x, y, w, h, key, title, note=None):
    rect(x, y, w, h, L[key][0], L[key][1], rx=14, sw=2.2)
    text(x + 16, y + 27, title, size=18.5, weight=700)
    if note:
        text(x + w - 16, y + 27, note, size=12.5, fill=MUTED, italic=True, anchor="end")


def line(points, color, dash=None, sw=2.2, start=False, end=True):
    d = "M " + " L ".join(f"{px},{py}" for px, py in points)
    da = f' stroke-dasharray="{dash}"' if dash else ""
    m = (f' marker-end="url(#m{color[1:]})"' if end else "") + \
        (f' marker-start="url(#s{color[1:]})"' if start else "")
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da}{m}/>')


def tag(x, y, s, color):
    w = len(s) * 6.3 + 10
    rect(x - w / 2, y - 12, w, 17, "#ffffff", color, rx=4, sw=1)
    text(x, y + 1, s, size=10.5, weight=700, anchor="middle", fill=color)


def pill(x, y, w, h, title, sub, key, status=None):
    rect(x, y, w, h, "#ffffff", L[key][1], rx=9, sw=1.4)
    text(x + w / 2, y + 22, title, size=13.5, weight=700, anchor="middle")
    if sub:
        text(x + w / 2, y + 40, sub, size=11.5, anchor="middle", fill=MUTED)
    if status:
        fill, ink = STATUS[status.split(" ·")[0]]
        bw = len(status) * 6.2 + 12
        rect(x + w / 2 - bw / 2, y + h - 22, bw, 16, fill, fill, rx=8, sw=1)
        text(x + w / 2, y + h - 10, status, size=10, weight=700, anchor="middle", fill=ink)


def build() -> str:
    out.clear()
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
               f'viewBox="0 0 {W} {H}">')
    out.append("<defs>")
    for c in (BLUE, RED, GREEN, ORANGE, PURPLE, INK, MUTED):
        k = c[1:]
        out.append(f'<marker id="m{k}" markerUnits="userSpaceOnUse" markerWidth="12" '
                   f'markerHeight="12" refX="10" refY="6" orient="auto">'
                   f'<path d="M0,0 L12,6 L0,12 z" fill="{c}"/></marker>')
        out.append(f'<marker id="s{k}" markerUnits="userSpaceOnUse" markerWidth="12" '
                   f'markerHeight="12" refX="2" refY="6" orient="auto">'
                   f'<path d="M12,0 L0,6 L12,12 z" fill="{c}"/></marker>')
    out.append("</defs>")
    rect(0, 0, W, H, "#ffffff", "#ffffff", rx=0, sw=0)
    text(W / 2, 46, "LAB1 – Whole Project Schematic", size=32, weight=800, anchor="middle")
    text(W / 2, 72, "An autonomous research lab building and testing a generalised robot brain "
         "(one brain for any body described by a Model Hardware Standard) · status 2026-10-06",
         size=13.5, anchor="middle", fill=MUTED)

    # ---------------------------------------------------------- left: people & control
    band(30, 95, 310, 905, "people", "People & Control")
    card(45, 140, 280, 150, "You (human)", [
        "direction, goals, north star", "hardware safety sign-off",
        "money, accounts, publishing", "accept major conclusions"], "people", "HUMAN")
    card(45, 330, 280, 150, "Claude Code (PM)", [
        "architecture, requirements", "task specs and queues",
        "real gate reviews (delegated)", "decisions D1–D41, fixes"], "people")
    card(45, 520, 280, 150, "Autopilot", [
        "scripts/autopilot.py", "runs the active task queue",
        "on stop: starts Claude Code", "waits out usage limits"], "people", "BUILT")
    card(45, 710, 280, 150, "Mandate", [
        "AI_Robotics_Full_Documentation", "H1–H5 · E1–E6 · gates 0–8",
        "+ north star D28 (MHS)", "every component earned"], "people")
    card(45, 885, 280, 100, "Licence", ["Apache-2.0 (D40)", "robolab: task G1-8"], "people")
    line([(185, 290), (185, 328)], ORANGE)
    tag(232, 312, "delegates", ORANGE)
    line([(185, 518), (185, 482)], ORANGE)
    tag(232, 500, "on stop", ORANGE)

    # ---------------------------------------------------------- right: records
    band(1660, 95, 310, 905, "rec", "Records & Backup")
    card(1675, 140, 280, 150, "GitHub (private)", [
        "LAB1: lab, docs, decisions", "robolab: brain code,",
        "all branches + provenance", "pushed after each commit"], "rec", "BUILT")
    card(1675, 330, 280, 150, "Lab ledger", [
        "hash-chained event log", "records, artifacts, raw runs",
        "tamper-evident", "(backup to git: TODO)"], "rec", "TODO")
    card(1675, 520, 280, 150, "Project records", [
        "PROJECT_STATE.md", "DECISIONS · FAILURES",
        "OPEN_QUESTIONS", "per-cycle reports"], "rec")
    card(1675, 710, 280, 150, "Design documents", [
        "ROBOT_BRAIN_ARCHITECTURE", "REQUIREMENTS (REQ-*, SW-*)",
        "PROJECT_PLAN · gate specs", "schematics (this one)"], "rec")
    card(1675, 885, 280, 100, "Telemetry & runs", ["per-cycle JSONL, latency", "trial metrics, raw data"],
         "rec")

    # ---------------------------------------------------------- centre top: programme
    X0, XW = 370, 1260
    band(X0, 95, XW, 175, "prog", "Programme: gates and experiments",
         "each brain component must beat its ablation")
    gates = [("Gate 0", "contracts, safety", "", "PASSED"),
             ("Gate 1", "simulation, MHS", "G1-1..G1-8", "IN PROGRESS"),
             ("Gate 2", "World Model", "WM-1, WM-2", "PLANNED"),
             ("Gate 3", "System 1", "E1 milestone", "PLANNED"),
             ("Gate 4", "Awareness", "E3a, E4", "PLANNED"),
             ("Gate 5", "System 2 (LLM)", "E2, E3", "PLANNED"),
             ("Gate 6", "memory, learning", "E5, E6", "PLANNED"),
             ("Gate 7", "hardware", "you decide", "HUMAN"),
             ("Gate 8", "synthesis", "you accept", "HUMAN")]
    gw = 128
    for i, (g, s1, s2, st) in enumerate(gates):
        gx = X0 + 15 + i * (gw + 10)
        rect(gx, 140, gw, 115, "#ffffff", L["prog"][1], rx=9, sw=1.4)
        text(gx + gw / 2, 162, g, size=14.5, weight=800, anchor="middle")
        text(gx + gw / 2, 181, s1, size=11.5, anchor="middle", fill=MUTED)
        text(gx + gw / 2, 198, s2, size=11.5, anchor="middle", fill=MUTED, italic=True)
        fill, ink = STATUS[st]
        bw = len(st) * 6.2 + 12
        rect(gx + gw / 2 - bw / 2, 226, bw, 17, fill, fill, rx=8, sw=1)
        text(gx + gw / 2, 239, st, size=10, weight=700, anchor="middle", fill=ink)
        if i < len(gates) - 1:
            line([(gx + gw, 197), (gx + gw + 8, 197)], PURPLE, sw=1.6)

    # ---------------------------------------------------------- centre middle: autolab
    yl = 295
    band(X0, yl, XW, 480, "lab", "autolab – the research lab",
         "the controller, not any AI, owns the truth")
    rect(X0 + 20, yl + 42, XW - 40, 92, "#ffffff", L["lab"][1], rx=10, sw=2)
    text(X0 + 36, yl + 68, "Controller (plain code, no AI)", size=16, weight=800)
    badge(X0 + XW - 28, yl + 50, "BUILT")
    text(X0 + 36, yl + 92, "owns project state · research + engineering state machines · "
         "schema-checked task packets · one git worktree per agent task", size=13)
    text(X0 + 36, yl + 114, "runs tests and trials itself · controlled merges with provenance · "
         "mechanical verdicts (CI, p) · approval gates · hash-chained ledger", size=13)
    aw, ay = 290, yl + 170
    agents = [("Scientist", ["ChatGPT via Codex (read-only)", "questions, hypotheses, designs,",
                             "interpretation"], "BUILT"),
              ("Engineer", ["Claude (claude -p)", "writes code + tests in its", "own worktree"],
               "BUILT"),
              ("Verifier", ["Codex (sandboxed)", "adversarial review +", "independent tests"],
               "BUILT"),
              ("Independent reviewer", ["different model family", "scientific review",
                                        "(off by default, D29)"], "OPTIONAL")]
    for i, (t, s, st) in enumerate(agents):
        ax = X0 + 20 + i * (aw + 13.3)
        card(ax, ay, aw, 105, t, s, "lab", st, ts=14.5, ss=12, lh=15)
        line([(ax + aw / 2, yl + 136), (ax + aw / 2, ay - 2)], BLUE, start=True, sw=1.8)
    tag(X0 + 20 + aw / 2 + 92, ay - 18, "task packets ⇄ completions", BLUE)
    # tracks
    ty, tw = yl + 300, 600
    rect(X0 + 20, ty, tw, 165, "#ffffff", L["lab"][1], rx=10, sw=1.4)
    text(X0 + 36, ty + 26, "Engineering track (gate tasks)", size=15, weight=700)
    steps_e = ["spec + acceptance", "build", "tests", "adversarial review",
               "[safety/contracts review]", "merge → delivery"]
    for i, s in enumerate(steps_e):
        row, col = divmod(i, 3)
        px, py = X0 + 36 + col * 195, ty + 48 + row * 55
        rect(px, py, 180, 36, L["lab"][0], L["lab"][1], rx=18, sw=1.2)
        text(px + 90, py + 23, s, size=12.2, weight=600, anchor="middle")
        if col < 2:
            line([(px + 180, py + 18), (px + 193, py + 18)], INK, sw=1.4)
    line([(X0 + 36 + 2 * 195 + 90, ty + 84), (X0 + 36 + 2 * 195 + 90, ty + 90),
          (X0 + 36 + 90, ty + 90), (X0 + 36 + 90, ty + 101)], INK, sw=1.4)
    text(X0 + 36, ty + 155, "fail → patch (×3) → redesign · queue: docs/gates/*.toml",
         size=11.5, fill=MUTED, italic=True)
    rx0 = X0 + 40 + tw
    rect(rx0, ty, tw, 165, "#ffffff", L["lab"][1], rx=10, sw=1.4)
    text(rx0 + 16, ty + 26, "Research track (experiments WM-1, E1–E6)", size=15, weight=700)
    steps_r = ["question → hypothesis", "design ⇄ review", "FREEZE protocol",
               "engineering track", "run trials (all seeds)", "verdict → challenge → report"]
    for i, s in enumerate(steps_r):
        row, col = divmod(i, 3)
        px, py = rx0 + 16 + col * 195, ty + 48 + row * 55
        rect(px, py, 180, 36, L["lab"][0], L["lab"][1], rx=18, sw=1.2)
        text(px + 90, py + 23, s, size=12.2, weight=600, anchor="middle")
        if col < 2:
            line([(px + 180, py + 18), (px + 193, py + 18)], INK, sw=1.4)
    line([(rx0 + 16 + 2 * 195 + 90, ty + 84), (rx0 + 16 + 2 * 195 + 90, ty + 90),
          (rx0 + 16 + 90, ty + 90), (rx0 + 16 + 90, ty + 101)], INK, sw=1.4)
    text(rx0 + 16, ty + 155, "pilot, then one confirmatory study · negative results kept",
         size=11.5, fill=MUTED, italic=True)

    # ---------------------------------------------------------- centre bottom: robolab
    yb = 800
    band(X0, yb, XW, 385, "brain", "robolab – the robot brain (code built by the lab)",
         "same brain code for every body")
    mods = [("State estimator", "belief state", "INTERFACE"), ("World Model", "predicts, learns",
                                                              "PLANNED"),
            ("System 1", "fast reflex policy", "PLANNED"), ("Awareness", "decides when to think",
                                                            "PLANNED"),
            ("System 2", "planner · LLM slot", "PLANNED"), ("Memory & learning", "skills, replay",
                                                            "PLANNED")]
    mw = 196
    for i, (t, s, st) in enumerate(mods):
        pill(X0 + 20 + i * (mw + 8.8), yb + 45, mw, 78, t, s, "brain", st)
    rect(X0 + 20, yb + 140, XW - 40, 52, L["safe"][0], L["safe"][1], rx=10, sw=2)
    text(X0 + 36, yb + 172, "Safety Kernel – deterministic, final say: limits · workspace · "
         "stopping distance · watchdog · e-stop · nothing reaches a motor without it",
         size=13.5, weight=700)
    badge(X0 + XW - 28, yb + 157, "BUILT")
    card(X0 + 20, yb + 208, 600, 62, "Embodiment adapter (thin, one per body)",
         ["generic action/observation vectors ↔ body I/O, reflexes"], "adapt", "NEXT", ts=14)
    card(X0 + 640, yb + 208, 600, 62, "MHS – Model Hardware Standard",
         ["declares actuators, sensors, body, timing, safety envelope"], "adapt",
         "IN PROGRESS · G1-5", ts=14)
    line([(X0 + 640, yb + 239), (X0 + 624, yb + 239)], ORANGE)
    bodies = [("Puck2D", "BUILT"), ("Car2D", "NEXT"), ("Diff-drive", "PLANNED"),
              ("Arm", "LATER"), ("Humanoid (sim)", "LATER"), ("RC car (real)", "HUMAN")]
    bw = 196
    for i, (t, st) in enumerate(bodies):
        pill(X0 + 20 + i * (bw + 8.8), yb + 285, bw, 82, t, "", "brain", st)
    line([(X0 + 12, yb + 326), (X0 + 4, yb + 326), (X0 + 4, yb + 84), (X0 + 18, yb + 84)],
         BLUE, sw=2.4)
    tag(X0 + 4, yb + 205, "sensors", BLUE)
    line([(X0 + XW - 8, yb + 84), (X0 + XW + 6, yb + 84), (X0 + XW + 6, yb + 326),
          (X0 + XW - 18, yb + 326)], RED, sw=2.4)
    tag(X0 + XW + 6, yb + 205, "commands", RED)

    # ---------------------------------------------------------- cross-section flows
    line([(X0 + XW / 2, 270), (X0 + XW / 2, yl - 2)], PURPLE, sw=2.6)
    tag(X0 + XW / 2 + 70, 284, "next gate → task queue", PURPLE)
    line([(X0 + XW / 2, yl + 480), (X0 + XW / 2, yb - 2)], GREEN, sw=2.6)
    tag(X0 + XW / 2 + 95, yl + 494, "builds, tests, merges, runs trials", GREEN)
    line([(325, 405), (X0 + 18, 405)], ORANGE, sw=2.4)
    tag(347, 395, "specs", ORANGE)
    line([(325, 595), (X0 + 18, 595)], ORANGE, sw=2.4)
    tag(347, 585, "runs", ORANGE)
    line([(325, 785), (X0 - 8, 785), (X0 - 8, 182), (X0 + 12, 182)], PURPLE, dash="6 4")
    line([(X0 + XW + 2, 382), (1673, 382)], MUTED, sw=2.2)
    tag(1645, 372, "ledger", MUTED)
    line([(X0 + XW + 2, yl + 230), (1650, yl + 230), (1650, 595), (1673, 595)], MUTED,
         dash="6 4")

    # ---------------------------------------------------------- footer
    fy = 1210
    rect(30, fy, 1270, 220, "#fafafa", "#d1d5db", rx=12, sw=1.4)
    text(48, fy + 30, "How the project flows", size=17, weight=700)
    steps = [
        "1. You set the direction: the mandate, the north star (one brain, any MHS body), key choices.",
        "2. Claude Code turns the next gate into a task queue (specs + acceptance criteria) and records decisions.",
        "3. The autopilot runs the queue; the controller dispatches each task to the agents in isolated worktrees.",
        "4. Engineer builds, controller tests, verifier attacks, review gates check safety/contracts, controller merges.",
        "5. Experiments run from the exact merged commit; verdicts are computed, challenged and reported.",
        "6. Stops go to Claude Code; anything that needs you is escalated. Everything is recorded and pushed.",
    ]
    for i, s in enumerate(steps):
        text(48, fy + 58 + i * 25, s, size=13.5)
    rect(1320, fy, 650, 220, "#fafafa", "#d1d5db", rx=12, sw=1.4)
    text(1338, fy + 30, "Legend", size=17, weight=700)
    flows = [(PURPLE, "programme → work", None), (ORANGE, "people / control", None),
             (BLUE, "agent messages · sensor data", None), (RED, "motor commands", None),
             (GREEN, "lab builds the brain", None), (MUTED, "records / backup", None)]
    for i, (c, s, d) in enumerate(flows):
        y = fy + 56 + i * 26
        line([(1340, y), (1385, y)], c, dash=d)
        text(1395, y + 4, s, size=13)
    for i, st in enumerate(["PASSED", "IN PROGRESS", "INTERFACE", "PLANNED", "LATER", "HUMAN"]):
        y = fy + 46 + i * 26
        fill, ink = STATUS[st]
        w = len(st) * 6.4 + 14
        rect(1640, y, w, 17, fill, fill, rx=8, sw=1)
        text(1640 + w / 2, y + 12.5, st, size=10.5, weight=700, anchor="middle", fill=ink)
    for i, s in enumerate(["done / built", "running now", "interface, stub", "later gate",
                           "beyond current plan", "needs you"]):
        text(1765, fy + 59 + i * 26, s, size=12.5, fill=MUTED)

    out.append("</svg>")
    return "\n".join(out)


def find_browser():
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(c).exists():
            return c
    return shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("msedge")


def main() -> int:
    here = Path(__file__).resolve().parent
    svg = here / "project.svg"
    svg.write_bytes(build().encode("utf-8"))
    print(f"wrote {svg}")
    browser = find_browser()
    if not browser:
        print("no Edge/Chrome found; PNG not rendered", file=sys.stderr)
        return 1
    png = here / "project.png"
    png.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", f"--window-size={W},{H}",
                        f"--user-data-dir={profile}", f"--screenshot={png}", svg.as_uri()],
                       check=True, capture_output=True, timeout=120)
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
