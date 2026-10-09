"""See the minimum viable brain work: python scripts/mvb_demo.py [--episodes 8] [--seed 2026]

Runs MVB-1 (PredictiveController), the PD baseline and a random policy on the same tasks for
Puck2D and Car2D, through robolab's real harness, cycle runner and Safety Kernel, and writes
labs/robolab/review/mvb_demo.html: a results table and every episode's true path drawn on the
workspace (start, goal, obstacles). No AI agents run; nothing is merged or recorded in the ledger.

This is an informal look, not evidence: the pre-registered experiment (MVB-2) must use fresh
seeds and tasks decided before results are seen.
"""

from __future__ import annotations

import argparse
import html
import sys
import tempfile
from pathlib import Path

LAB1 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB1 / "labs" / "robolab" / "repo" / "src"))

import numpy as np  # noqa: E402

from simulation import car2d, puck2d  # noqa: E402
from simulation.harness import (EvalSetSpec, HarnessConfig, _body, build_eval_set,  # noqa: E402
                                run_episodes)
from simulation.policies import PDController, RandomPolicy  # noqa: E402
from state.telemetry import TelemetryLog  # noqa: E402
from system1.predictive import PredictiveController  # noqa: E402

PATHS: list[list[tuple[float, float]]] = []


def _record(cls):
    reset, step = cls.reset, cls.step

    def rec_reset(self, *a, **k):
        out = reset(self, *a, **k)
        PATHS.append([tuple(float(x) for x in self.pos)])
        return out

    def rec_step(self, action):
        out = step(self, action)
        PATHS[-1].append(tuple(float(x) for x in self.pos))
        return out
    cls.reset, cls.step = rec_reset, rec_step


_record(puck2d.Puck2D)
_record(car2d.Car2D)


def run(body: str, policy_name: str, episodes: int, seed: int):
    ev = build_eval_set(seed, EvalSetSpec(n_tasks=episodes), name=f"demo-{body}", body=body)
    env_cls, _ = _body(body)
    cfg0 = ev.tasks[0].env_config(ev.env_params, body)
    mhs = HarnessConfig().mhs(env_cls(cfg0))
    policy = {"MVB-1 brain": lambda: PredictiveController(mhs), "PD": PDController,
              "random": RandomPolicy}[policy_name]()
    PATHS.clear()
    metrics = run_episodes(ev, policy, TelemetryLog(Path(tempfile.mkdtemp()) / "t.jsonl"),
                           seed=seed, n_episodes=episodes)
    goal_r = float(getattr(cfg0, "goal_radius", 0.1))
    return ev, metrics, [list(p) for p in PATHS], goal_r


def svg(task, path, goal_r, success):
    s, half = 150, 2.0  # workspace +-2 m drawn in 150 px
    tx = lambda v: (v + half) / (2 * half) * s  # noqa: E731
    ty = lambda v: s - (v + half) / (2 * half) * s  # noqa: E731
    pts = " ".join(f"{tx(x):.1f},{ty(y):.1f}" for x, y in path[::2])
    obs = "".join(f'<circle cx="{tx(o.center[0]):.1f}" cy="{ty(o.center[1]):.1f}" r="{o.radius / (2 * half) * s:.1f}" class="obs"/>'
                  for o in task.obstacles)
    return (f'<svg viewBox="0 0 {s} {s}" class="ep {"ok" if success else "fail"}">'
            f'<rect x="0" y="0" width="{s}" height="{s}" class="ws"/>'
            f'<rect x="{tx(-1):.1f}" y="{ty(1):.1f}" width="{s / 2:.1f}" height="{s / 2:.1f}" class="arena"/>{obs}'
            f'<circle cx="{tx(task.goal[0]):.1f}" cy="{ty(task.goal[1]):.1f}" r="{max(2.5, goal_r / (2 * half) * s):.1f}" class="goal"/>'
            f'<polyline points="{pts}" class="path"/>'
            f'<circle cx="{tx(path[0][0]):.1f}" cy="{ty(path[0][1]):.1f}" r="2.5" class="start"/></svg>')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=8)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default=str(LAB1 / "labs" / "robolab" / "review" / "mvb_demo.html"))
    a = ap.parse_args()
    rows, sections = [], []
    for body in ("puck2d", "car2d"):
        for name in ("MVB-1 brain", "PD", "random"):
            if body == "car2d" and name == "PD":
                rows.append((body, name, "n/a: PD outputs 2-D forces; the car takes throttle/brake/steer",
                             "", "", ""))
                continue
            ev, m, paths, goal_r = run(body, name, a.episodes, a.seed)
            succ = sum(x.success for x in m)
            steps = [x.steps for x in m if x.success]
            rows.append((body, name, f"{succ}/{len(m)}",
                         f"{np.mean(steps):.0f}" if steps else "–",
                         str(sum(x.safety_interventions for x in m)), str(sum(x.collisions for x in m))))
            cells = "".join(f'<figure>{svg(ev.tasks[i], paths[i], goal_r, m[i].success)}'
                            f'<figcaption>{"reached" if m[i].success else "missed"} · {m[i].steps} steps</figcaption></figure>'
                            for i in range(len(m)))
            sections.append(f"<h2>{body} · {html.escape(name)}</h2><div class='grid'>{cells}</div>")
            print(f"{body:7} {name:12} success {succ}/{len(m)}")
    table = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in rows)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>MVB demo</title><style>
body{{font:14px system-ui,sans-serif;margin:24px;color:#1b2430;background:#f6f8fb}} table{{border-collapse:collapse;background:#fff}}
td,th{{border:1px solid #dde3ea;padding:6px 10px;text-align:left}} .grid{{display:flex;flex-wrap:wrap;gap:10px}}
figure{{margin:0;background:#fff;border:1px solid #dde3ea;border-radius:8px;padding:6px}} figcaption{{font-size:12px;color:#5a6676;text-align:center}}
svg.ep{{width:150px;height:150px}} .ws{{fill:#fff;stroke:#c33;stroke-width:1.5}} .arena{{fill:#f2f5f9;stroke:#cdd5df;stroke-dasharray:3 3}}
.obs{{fill:#9aa6b6}} .goal{{fill:#2e9e5b;opacity:.75}} .path{{fill:none;stroke:#2463eb;stroke-width:1.4}} .fail .path{{stroke:#d97706}}
.start{{fill:#111}} .note{{color:#5a6676;max-width:900px}}</style></head><body>
<h1>Minimum viable brain: informal demo</h1>
<p class="note">Same tasks for every controller (seed {a.seed}, {a.episodes} per body). Red frame = the ±2 m workspace
the Safety Kernel enforces; dashed = the task arena; grey = obstacles; green = goal; black dot = start; blue path = reached,
orange = missed. Through robolab's real harness, runner and Safety Kernel. Not evidence: MVB-2 is the pre-registered test.</p>
<table><tr><th>Body</th><th>Controller</th><th>Goals reached</th><th>Mean steps (reached)</th><th>Safety interventions</th><th>Collisions</th></tr>{table}</table>
{"".join(sections)}</body></html>"""
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
