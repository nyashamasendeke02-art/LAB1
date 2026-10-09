# Reviewing the minimum viable brain (MVB-1)

For a manual review of robolab at `d7af0da` (MVB-1 merged, Gate 1 complete). Code:
`labs/robolab/repo/` (its own git repository; `main` is the integration branch).

## 1. See it working first (no agents, free)

```powershell
.venv\Scripts\python.exe scripts\mvb_demo.py          # writes labs\robolab\review\mvb_demo.html
```

Informal results (seed 2026, 8 tasks per body; NOT evidence -- MVB-2 is the pre-registered test):

| Body | MVB-1 brain | PD baseline | Random |
|---|---|---|---|
| Puck2D | 7/8 goals, mean 116 steps, 9 kernel interventions | 7/8, mean 59 steps, 0 | 2/8, 469 |
| Car2D | **0/8** (370 interventions) | n/a (PD outputs 2-D forces) | 0/8 |

What the drawings show:

* **Puck:** the brain reaches goals but loops and spirals while its model is still learning
  (overshoot), twice as slow as PD. It learned the physics itself; PD was hand-tuned.
* **Car:** the brain drives almost straight and never turns toward the goal. Cause (design, not a
  bug): one-step lookahead. Steering changes heading first and position only later, so over one
  0.02 s step turning shows no benefit and is never chosen. A non-holonomic body needs a
  multi-step lookahead. This is the first real test of "one brain for any body" (D28): safe
  operation transfers; competence does not yet.

## 2. Read the code in this order

| # | File | Lines | What to check |
|---|---|---|---|
| 1 | `src/system1/predictive.py` | 289 | The brain. `RidgeForwardModel` (online least squares: next observation from observation + action); `PredictiveController.candidates` (MHS-bounded action grid) and `propose` (pick the candidate whose predicted position is closest to the goal; random for the first 10 steps). Look for: any body-specific code (there should be none), how the goal is used, warm-up behaviour. |
| 2 | `src/contracts/mhs.py` | 423 | The body description the brain and kernel read. Check what a body must declare (actuators, sensors, safety envelope). |
| 3 | `src/robot/runner.py` | 616 | One control cycle: observe -> estimate -> (predict) -> propose -> kernel check -> actuate. Check that no action can reach the body without `SafetyKernel.check`. |
| 4 | `src/safety/kernel.py` | 1554 | The Safety Kernel v1.3: command validation, limits, workspace + stopping-distance check, braking safe action, watchdog, e-stop. Largest and most important file. |
| 5 | `src/simulation/puck2d.py`, `car2d.py` | 572, 625 | The two bodies and the MHS each publishes (`mhs()`). |
| 6 | `src/simulation/harness.py`, `policies.py` | 695, 176 | Evaluation sets, episode loop, metrics; the PD and random baselines. |
| 7 | `tests/test_predictive.py`, `test_body_agnostic_safety.py`, `test_isolation.py` | - | What is actually guaranteed by tests. |

## 3. Run the tests yourself

```powershell
cd labs\robolab\repo
..\..\..\.venv\Scripts\python.exe -m pytest -q                         # all 33 test files
..\..\..\.venv\Scripts\python.exe -m pytest -q tests\test_predictive.py # the brain only
```

## 4. Provenance (who wrote what)

`git log --oneline -8` in the repo: MVB-1 was built by `claude_opus` (commit 1fc6412), verified by
`claude_sonnet` with independent tests (90777fd), merged by the controller (d7af0da). Every agent
step, including tool calls, is in the dashboard (`autolab ui labs\robolab`) or terminal UI
(`autolab tui labs\robolab`) under PRJ-0014.

## 5. Known limits found so far

1. Car2D: no goal reached (one-step lookahead; see above).
2. Puck2D: slower and loopier than PD while learning.
3. Safety: a sustained full push plus an undeclared external impulse can exceed the workspace by
   up to 0.14 m (APR-0007); G1-9 (declared disturbance margin) is required before hardware.
