# Minimum viable brain (MVB)

Decision D65 (2026-10-08, human: "remove unnecessary steps for G1-6; a minimum viable brain is
enough"). The MVB is the mandate's first milestone made concrete: **E1, an S1 baseline -- a
minimal predictive agent with a reproducible baseline** (MANDATE.md, "Sequencing"). Nothing
above it is built before it exists and is measured.

## What the MVB is

One brain, the same code for every body, that:

1. reads a body's Model Hardware Standard (MHS) to learn its actions, sensors and limits;
2. observes the body through the cycle runner (already built: G0-4, G1-5);
3. predicts the next observation with a minimal learned forward model (fitted online from its
   own observations and actions only; it never sees ground truth -- G1-4);
4. chooses an action toward the goal by using that prediction (one-step lookahead over a small
   set of candidate actions within the MHS limits);
5. sends every action through the Safety Kernel (G0-3, G1-3, G1-6), which may clamp or replace it.

## Built already (Gates 0-1)

| Part | Task |
|---|---|
| Message contracts, telemetry | G0-1, G0-2 |
| Safety Kernel (stopping distance, body-agnostic after G1-6) | G0-3, G1-3, G1-6 |
| Cycle runner, harness, scripted baselines (random, PD) | G0-4, G1-2 |
| Puck2D, Car2D simulated bodies | G1-1, G1-6 |
| Ground-truth isolation | G1-4 |
| MHS v0 | G1-5 |

## Still to build (the MVB increment)

| # | Task | Done when |
|---|---|---|
| MVB-1 | S1 predictive controller in `src/system1/` (forward model + one-step lookahead), configured only from the MHS | it drives Puck2D and Car2D with no body-specific code; all actions pass the kernel |
| MVB-2 | E1 experiment: MVB vs the PD baseline and a random policy on the frozen evaluation set, both bodies | a reproducible result with the pre-registered decision rule (success rate, time to goal, safety interventions) |

## Deliberately out of scope until E1 exists

World-model learning beyond the one-step model, System 2 (LLM planner), awareness, memory and
skills, perception, ROS 2, hardware, packaging/lint/coverage work (G1-7) and the licence task
(G1-8, deferred_queue.toml).

## Process kept lean (robolab, D65)

* Kept: independent adversarial review and tests on every change; the Safety Kernel gate.
* Dropped for robolab: architecture stage, security and performance pre-merge reviews, the
  contracts gate. Other labs keep the full engineering workflow (D56).
