# Autolab control room (local web dashboard)

Start it for a lab and open the printed address:

```powershell
.venv\Scripts\autolab.exe ui labs\robolab        # http://127.0.0.1:8765/
```

`--port` changes the port; `--host` may pick another loopback address (non-loopback is
refused). Stop it with Ctrl+C. The queue log shown on the Overview is read from
`<lab>-run.log` next to the lab folder when it exists.

## Views

| View | What it shows |
|---|---|
| **Overview** | Alerts (blocked agents with a readable reason, unresolved halts, waiting approvals); counters; **gate progress board** (each gate's tasks, newest attempt per task); the active task with a **live pipeline stepper** (spec → implementing → testing → adversarial review → merge → merged) and its review/patch/redesign/test counts; the task-queue log; agents; recent ledger activity |
| **Projects** | Searchable, filterable table (state, kind, free text). A project page has tabs: overview (spec, acceptance criteria, facts, deliveries, gate decisions), pipeline timeline, verifier reviews with findings by severity, failures, agent calls (each opens the task packet and validated response) and its ledger events |
| **Approvals** | Waiting review gates; each opens a per-file colored diff, context and the decision form (a note is required; you confirm before it is recorded) |
| **Agents** | Each role's backend and model, status, call counts, a strip of recent call outcomes, and the last error in plain words (raw error expandable) |
| **Activity** | The tamper-evident ledger, newest first, filterable by event type |

Keyboard: **Ctrl+K** search and commands (jump to any project, approval or view), **/** search
projects, **g o / g p / g a / g g / g e** go to overview, projects, approvals, agents, activity,
**n** new project, **Esc** closes panels. Light and dark themes follow the system setting; the
sidebar button switches and remembers the choice.

## How it stays current

The page holds one Server-Sent Events connection (`/api/stream`). The server announces when the
ledger head or the queue log changes and the page reloads its data; it does not re-render while
you are typing a note or have a dialog open. The sidebar shows **Live** when connected and the
result of a ledger hash-chain verification.

## Architecture (D49)

- **Backend** (`src/autolab/web.py`, standard library only): `ThreadingHTTPServer` with a
  per-thread `Lab` (SQLite connections are per thread); JSON API: `/api/overview`,
  `/api/projects[/<id>]`, `/api/approvals[/<id>]`, `/api/agents`, `/api/activity`,
  `/api/tasks/<id>`, `/api/stream`; `/api/state` kept for v1 clients.
- **Frontend** (`src/autolab/web/index.html`, `app.css`, `app.js`): dependency-free ES module,
  hash routing, design tokens for both themes, ARIA roles and visible focus, reduced-motion
  support, responsive layout. All content is built with DOM APIs and `textContent`, never
  `innerHTML`, so ledger text cannot inject markup.

## Safety rules

- **Loopback only**, and every request must be addressed to `127.0.0.1`, `localhost` or `[::1]`
  (`Host` check against DNS rebinding; others get `421`).
- **Strict Content-Security-Policy**: scripts and styles only from the dashboard itself, no inline
  code; plus `nosniff`, `no-referrer`, same-origin opener/resource policies.
- **Writes** (create a project, record a gate decision) need the per-process token and a
  same-origin request, and are refused while an agent call is in flight: the controller treats
  any ledger change during an agent call as possible tampering and would HALT the project. A
  dispatch with no result after 2 hours counts as abandoned, not running.
- **Decisions made here are the human's** (`decided_by = "human"`) and need a note. Delegated
  reviews by Claude Code use the CLI with `--as claude-code`.
- The dashboard never starts or stops agents or queues; use `autolab run` / `autolab queue`.
