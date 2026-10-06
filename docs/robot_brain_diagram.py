"""Generate docs/robot_brain.svg (and docs/robot_brain.png via headless Edge/Chrome).

    python docs/robot_brain_diagram.py

The schematic mirrors docs/ROBOT_BRAIN_ARCHITECTURE.md; update both together.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

W, H = 1800, 1250
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
INK, MUTED = "#1f2937", "#5b6472"

L = {  # layer (fill, stroke)
    "goal": ("#f1ebff", "#7a5cc9"),
    "cog": ("#e8f1fd", "#3b78c4"),
    "safe": ("#fde8e8", "#c43c3c"),
    "adapt": ("#fff1e0", "#d98a2b"),
    "body": ("#eaf6ec", "#3f9a55"),
    "side": ("#eef0f3", "#7b8594"),
}
STATUS = {  # badge fill, text
    "BUILT": ("#2e8f57", "#ffffff"),
    "INTERFACE": ("#5a9bd8", "#ffffff"),
    "NEXT": ("#e0a100", "#ffffff"),
    "PLANNED": ("#9aa3af", "#ffffff"),
    "LATER": ("#c9ced6", INK),
    "OUT OF SCOPE": ("#e5e7eb", MUTED),
}
SENSE, CMD, LEARN, CFG = "#2f6fd0", "#c43c3c", "#2e8f57", "#d98a2b"

out: list[str] = []


def esc(s: str) -> str:
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
    fill, ink = STATUS[label.split(" ·")[0]] if label.split(" ·")[0] in STATUS else STATUS["PLANNED"]
    w = len(label) * 6.4 + 14
    rect(x_right - w, y, w, 18, fill, fill, rx=9, sw=1)
    text(x_right - w / 2, y + 13, label, size=10.5, weight=700, anchor="middle", fill=ink)


def card(x, y, w, h, title, sub, layer, status=None, title_size=15):
    rect(x, y, w, h, "#ffffff", L[layer][1], rx=10, sw=1.6)
    text(x + 12, y + 24, title, size=title_size, weight=700)
    for i, s in enumerate(sub):
        text(x + 12, y + 44 + i * 16, s, size=12.2, fill=MUTED)
    if status:
        badge(x + w - 8, y + 8, status)


def layer(x, y, w, h, key, title):
    rect(x, y, w, h, L[key][0], L[key][1], rx=14, sw=2.2)
    text(x + 16, y + 26, title, size=18, weight=700)


def line(points, color, dash=None, sw=2.0, start=False, end=True):
    d = "M " + " L ".join(f"{px},{py}" for px, py in points)
    da = f' stroke-dasharray="{dash}"' if dash else ""
    m = (f' marker-end="url(#m{color[1:]})"' if end else "") + \
        (f' marker-start="url(#s{color[1:]})"' if start else "")
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da}{m}/>')


def tag(x, y, s, color):
    w = len(s) * 6.3 + 10
    rect(x - w / 2, y - 12, w, 17, "#ffffff", color, rx=4, sw=1)
    text(x, y + 1, s, size=10.5, weight=700, anchor="middle", fill=color)


def build() -> str:
    out.clear()
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
               f'viewBox="0 0 {W} {H}">')
    out.append("<defs>")
    for c in (SENSE, CMD, LEARN, CFG, INK):
        k = c[1:]
        out.append(f'<marker id="m{k}" markerUnits="userSpaceOnUse" markerWidth="12" '
                   f'markerHeight="12" refX="10" refY="6" orient="auto">'
                   f'<path d="M0,0 L12,6 L0,12 z" fill="{c}"/></marker>')
        out.append(f'<marker id="s{k}" markerUnits="userSpaceOnUse" markerWidth="12" '
                   f'markerHeight="12" refX="2" refY="6" orient="auto">'
                   f'<path d="M12,0 L0,6 L12,12 z" fill="{c}"/></marker>')
    out.append("</defs>")
    rect(0, 0, W, H, "#ffffff", "#ffffff", rx=0, sw=0)
    text(W / 2, 46, "Generalised Robot Brain (robolab) – Schematic", size=32, weight=800,
         anchor="middle")
    text(W / 2, 70, "One brain for any body described by a Model Hardware Standard (MHS) · "
         "v0.1, 2026-10-05 · see docs/ROBOT_BRAIN_ARCHITECTURE.md",
         size=13.5, anchor="middle", fill=MUTED)

    # ------------------------------------------------ side column: development
    layer(30, 95, 280, 880, "side", "Development & Evidence")
    side_l = [
        ("Simulation", ["Puck2D (built), Car2D (G1-6);", "seeded, deterministic;",
                        "disturbances, sensor noise"], "BUILT"),
        ("Episode harness", ["N seeded episodes through", "the full cycle; frozen task",
                             "sets; random + PD baselines"], "NEXT"),
        ("Experiments", ["pre-registered, pilot then", "confirmatory: WM-1, E1, E4,",
                         "E3a, E2, E3, E5, WM-2, E6"], "PLANNED"),
        ("autolab", ["scientist, engineer, verifier;", "tests, adversarial review,",
                     "provenance ledger, merges"], "BUILT"),
        ("Evidence rules", ["each component must beat", "its ablation; negative", "results are kept"],
         None),
    ]
    for i, (t, s, st) in enumerate(side_l):
        card(45, 140 + i * 165, 250, 145, t, s, "side", st)

    # ------------------------------------------------ side column: observability
    layer(1490, 95, 280, 880, "side", "Contracts & Observability")
    side_r = [
        ("Contracts", ["typed, versioned messages;", "envelope + 13 types;",
                       "uncertainty kept by kind"], "BUILT"),
        ("Telemetry", ["append-only JSONL per cycle;", "decision, reason, latency;",
                       "p50/p95 per component"], "BUILT"),
        ("Cycle runner", ["deterministic loop; modules", "swapped by config; kernel",
                          "spy proves no bypass"], "BUILT"),
        ("Episode visualiser", ["trajectories, decisions,", "surprises, interventions"],
         "PLANNED"),
        ("Configuration", ["module selection, seeds,", "MHS per body, eval sets"], "BUILT"),
    ]
    for i, (t, s, st) in enumerate(side_r):
        card(1505, 140 + i * 165, 250, 145, t, s, "side", st)

    # ------------------------------------------------ 1 goal interface
    X0, XW = 340, 1120
    layer(X0, 95, XW, 100, "goal", "1. Goal Interface")
    goals = [("Task specification", ["goal region, constraints, deadline"], "NEXT"),
             ("Language instructions", ["via System 2 (LLM slot)"], "LATER"),
             ("Operator UI / app", ["monitoring and remote control"], "LATER")]
    for i, (t, s, st) in enumerate(goals):
        card(560 + i * 300, 106, 285, 78, t, s, "goal", st, title_size=14)

    # ------------------------------------------------ 2 cognition
    layer(X0, 215, XW, 400, "cog", "2. Robot Brain: Cognition")
    text(X0 + XW - 18, 241, "identical code for every body · reads the MHS · never sees "
         "simulator ground truth", size=12.5, fill=MUTED, italic=True, anchor="end")
    cw, ch = 330, 96
    cx = [X0 + 25, X0 + 395, X0 + 765]
    ry = [260, 380, 500]
    card(cx[0], ry[0], cw, ch, "State Estimator",
         ["noisy sensors → belief state", "layers: physical, belief, task, meta",
          "+ estimation uncertainty"], "cog", "INTERFACE")
    card(cx[1], ry[0], cw, ch, "World Model",
         ["predicts next state + uncertainty", "physics step + learned residual",
          "estimates mass/friction; surprise"], "cog", "PLANNED · GATE 2")
    card(cx[2], ry[0], cw, ch, "Awareness Harness",
         ["self-monitoring arbiter: accept,", "ask S2, replan, abstain, escalate",
          "inputs: surprise, novelty, stakes"], "cog", "PLANNED · GATE 4")
    card(cx[0], ry[1], cw, ch, "Memory & Skills",
         ["episodic memory, retrieval,", "replay; versioned skill library",
          "with provenance"], "cog", "PLANNED · GATE 6")
    card(cx[1], ry[1], cw, ch, "System 1 (fast)",
         ["reflexive policy every cycle", "action + confidence, bounded",
          "latency, safe fallback"], "cog", "PLANNED · GATE 3")
    card(cx[2], ry[1], cw, ch, "System 2 (slow)",
         ["plans, skill choice, reasoning", "LLM slot · runs async",
          "never commands actuators"], "cog", "PLANNED · GATE 5")
    card(cx[0], ry[2], cw, ch, "Continual Learning",
         ["experience → replay → update →", "validate → deploy; rollback,",
          "forgetting control"], "cog", "PLANNED · GATE 6")
    rect(cx[1], ry[2], cw * 2 + 40, ch, "#ffffff", L["cog"][1], rx=10, sw=1.2, dash="5 4")
    text(cx[1] + 12, ry[2] + 24, "Timing", size=15, weight=700)
    text(cx[1] + 12, ry[2] + 46, "Reflex loop (in body/adapter): 500 Hz+ · balance, motor loops, ABS",
         size=12.2, fill=MUTED)
    text(cx[1] + 12, ry[2] + 64, "Fast loop (MHS control period, e.g. 50 Hz): estimator → World Model "
         "→ S1 → Awareness → Kernel", size=12.2, fill=MUTED)
    text(cx[1] + 12, ry[2] + 82, "Slow loop (async, 0.1–10 s): System 2, memory consolidation, "
         "learning", size=12.2, fill=MUTED)

    # internal flows
    yA = ry[0] + ch / 2
    line([(cx[0] + cw, yA), (cx[1] - 4, yA)], SENSE)
    tag((cx[0] + cw + cx[1]) / 2, yA - 10, "state", SENSE)
    line([(cx[1] + cw, yA), (cx[2] - 4, yA)], SENSE)
    tag((cx[1] + cw + cx[2]) / 2, yA - 10, "prediction", SENSE)
    line([(cx[1] + cw / 2, ry[0] + ch), (cx[1] + cw / 2, ry[1] - 4)], SENSE)
    line([(cx[1] + cw, ry[1] + 30), (cx[2] - 18, ry[1] + 30), (cx[2] - 18, ry[0] + ch - 14),
          (cx[2] - 4, ry[0] + ch - 14)], CMD)
    tag(cx[1] + cw + 20, ry[1] + 48, "proposal", CMD)
    line([(cx[2] + cw / 2, ry[0] + ch + 2), (cx[2] + cw / 2, ry[1] - 4)], INK, start=True)
    tag(cx[2] + cw / 2 + 62, ry[0] + ch + 14, "escalate / plan", INK)
    line([(cx[0] + cw, ry[1] + 60), (cx[1] - 4, ry[1] + 60)], LEARN, start=True)
    line([(cx[0] + cw / 2, ry[1] + ch + 2), (cx[0] + cw / 2, ry[2] - 4)], LEARN, start=True)
    line([(cx[0] + cw, ry[2] + 20), (cx[0] + cw + 20, ry[2] + 20), (cx[0] + cw + 20, ry[0] + ch - 14),
          (cx[1] - 4, ry[0] + ch - 14)], LEARN, dash="5 4")
    tag(cx[0] + cw + 20, ry[1] - 12, "updates", LEARN)

    # ------------------------------------------------ 3 safety
    ys = 640
    layer(X0, ys, XW, 112, "safe", "3. Safety Kernel — deterministic, final authority")
    badge(X0 + XW - 12, ys + 10, "BUILT")
    text(X0 + 16, ys + 52, "per-axis limits (clamp/reject) · workspace & stopping distance (v1.1, G1-3) · "
         "stale/malformed rejection · watchdog → safe action", size=13)
    text(X0 + 16, ys + 72, "e-stop latch, reset by operator only · limits immutable · no learned module "
         "can change it · configured from the MHS safety envelope", size=13)
    text(X0 + 16, ys + 94, "never ablated in experiments that actuate; validated by fault injection",
         size=12.5, fill=MUTED, italic=True)

    # ------------------------------------------------ 4 embodiment adapter + MHS
    ya = 775
    layer(X0, ya, XW, 118, "adapt", "4. Embodiment Layer")
    card(X0 + 20, ya + 38, 590, 70, "Embodiment Adapter (one per body)",
         ["maps generic action/observation vectors ↔ body I/O; hosts fast reflexes"],
         "adapt", "NEXT · G1-5", title_size=14)
    card(X0 + 640, ya + 38, 460, 70, "MHS: Model Hardware Standard",
         ["actuators · sensors · body · timing · reflexes · safety envelope"],
         "adapt", "NEXT · G1-5", title_size=14)
    line([(X0 + 640, ya + 73), (X0 + 614, ya + 73)], CFG)

    # ------------------------------------------------ 5 bodies
    yb = 915
    layer(X0, yb, XW, 140, "body", "5. Bodies (simulated first, then real)")
    bodies = [("Puck2D", "2D point mass", "BUILT"), ("Car2D", "RC-car-like", "NEXT"),
              ("Diff-drive", "2nd body, E6", "PLANNED"), ("Arm", "manipulation", "LATER"),
              ("Humanoid", "sim, MuJoCo", "LATER"), ("RC car", "real, Gate 7", "LATER"),
              ("Road car", "public roads", "OUT OF SCOPE")]
    bw = 148
    for i, (t, s, st) in enumerate(bodies):
        bx = X0 + 18 + i * (bw + 6)
        rect(bx, yb + 40, bw, 88, "#ffffff", L["body"][1], rx=10, sw=1.4)
        text(bx + bw / 2, yb + 68, t, size=14.5, weight=700, anchor="middle")
        text(bx + bw / 2, yb + 88, s, size=12, anchor="middle", fill=MUTED)
        sfill, sink = STATUS[st]
        w = len(st) * 6.4 + 14
        rect(bx + bw / 2 - w / 2, yb + 98, w, 18, sfill, sfill, rx=9, sw=1)
        text(bx + bw / 2, yb + 111, st, size=10.5, weight=700, anchor="middle", fill=sink)

    # ------------------------------------------------ cross-layer flows
    # goal -> cognition
    line([(790, 184), (790, 258)], INK)
    tag(790, 222, "goal", INK)
    # command path: awareness -> safety -> adapter -> body
    xa = cx[2] + cw + 12
    line([(cx[2] + cw, yA + 20), (xa, yA + 20), (xa, ys - 4)], CMD, sw=2.6)
    tag(xa - 40, ys - 14, "chosen action", CMD)
    line([(xa, ys + 112), (xa, ya + 30), (X0 + 560, ya + 30), (X0 + 560, ya + 36)], CMD, sw=2.6)
    tag(xa - 90, ya + 22, "approved command only", CMD)
    line([(X0 + 520, ya + 108), (X0 + 520, yb + 38)], CMD, sw=2.6)
    tag(X0 + 520, yb - 3, "actuators", CMD)
    # sensor path: body -> adapter -> state estimator
    line([(X0 + 400, yb + 38), (X0 + 400, ya + 110)], SENSE, sw=2.6)
    tag(X0 + 400, yb - 3, "sensors", SENSE)
    line([(X0 + 20, ya + 73), (X0 - 15, ya + 73), (X0 - 15, yA + 20), (cx[0] - 4, yA + 20)],
         SENSE, sw=2.6)
    out.append(f'<text x="{X0 - 21}" y="560" font-family="{FONT}" font-size="11" '
               f'font-weight="700" fill="{SENSE}" text-anchor="middle" '
               f'transform="rotate(-90 {X0 - 21} 560)">observations</text>')
    # MHS configures kernel and is read by the brain
    xm = X0 + XW + 15
    line([(X0 + 1100, ya + 60), (xm, ya + 60), (xm, ys + 56), (X0 + XW + 4, ys + 56)], CFG,
         dash="6 4")
    line([(xm, ys + 56), (xm, ry[1] + 50), (X0 + XW + 4, ry[1] + 50)], CFG, dash="6 4")
    tag(xm, ys - 30, "MHS", CFG)
    # side columns

    # ------------------------------------------------ rules + legend
    yl = 1080
    rect(30, yl, 1100, 150, "#fafafa", "#d1d5db", rx=12, sw=1.4)
    text(48, yl + 30, "Three rules that hold the design together", size=17, weight=700)
    rules = ["1. The brain knows its body only through the MHS: no body constants in brain code "
             "(test-enforced, G1-5).",
             "2. Nothing reaches an actuator except through the Safety Kernel; no learned module "
             "can change its limits (audited, Gate 0).",
             "3. The brain learns physics only from consequences: observations and its own actions, "
             "never simulator ground truth (G1-4).",
             "Every component is a HYPOTHESIS until it beats its ablation in a pre-registered "
             "experiment."]
    for i, r in enumerate(rules):
        text(48, yl + 58 + i * 22, r, size=13.5, weight=600 if i < 3 else 400,
             fill=INK if i < 3 else MUTED, italic=i == 3)

    rect(1150, yl, 620, 150, "#fafafa", "#d1d5db", rx=12, sw=1.4)
    text(1168, yl + 30, "Legend", size=17, weight=700)
    flows = [(SENSE, "sensor / state data", None), (CMD, "action / command", None),
             (LEARN, "learning / development", "5 4"), (CFG, "MHS configuration", "6 4")]
    for i, (c, s, d) in enumerate(flows):
        y = yl + 56 + i * 24
        line([(1170, y), (1215, y)], c, dash=d)
        text(1225, y + 4, s, size=13)
    for i, st in enumerate(["BUILT", "INTERFACE", "NEXT", "PLANNED", "LATER"]):
        y = yl + 46 + i * 20
        fill, ink = STATUS[st]
        w = len(st) * 6.4 + 14
        rect(1460, y, w, 17, fill, fill, rx=8, sw=1)
        text(1460 + w / 2, y + 12.5, st, size=10.5, weight=700, anchor="middle", fill=ink)
    text(1560, yl + 58, "built and merged", size=12.5, fill=MUTED)
    text(1560, yl + 78, "interface, default stub", size=12.5, fill=MUTED)
    text(1560, yl + 98, "Gate 1 tasks", size=12.5, fill=MUTED)
    text(1560, yl + 118, "later gate", size=12.5, fill=MUTED)
    text(1560, yl + 138, "beyond current plan", size=12.5, fill=MUTED)

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
    svg = here / "robot_brain.svg"
    svg.write_bytes(build().encode("utf-8"))
    print(f"wrote {svg}")
    browser = find_browser()
    if not browser:
        print("no Edge/Chrome found; PNG not rendered", file=sys.stderr)
        return 1
    png = here / "robot_brain.png"
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
