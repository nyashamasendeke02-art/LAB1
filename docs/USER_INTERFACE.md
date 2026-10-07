# LAB1 dashboard

Start the local dashboard for a lab with:

```powershell
autolab ui .\lab
```

Then open `http://127.0.0.1:8765/`. Change the port with `--port`; `--host` may
select another loopback IP address, but the server rejects non-loopback
addresses. Stop it with Ctrl+C.

The dashboard reads project and approval state from the lab's existing SQLite
ledger. It can create research and engineering projects, show recent
project-ledger events, and approve or reject pending gates as the human user.
Those decisions use the same `Gates` API as the CLI and are recorded in the
append-only ledger.

The operations panels show configured scientist, engineer, verifier and
optional reviewer roles; backend and model; currently dispatched work; and
the latest task outcome. Recent task calls expose the stored task packet,
validated response, protocol rejections and errors. These are ledger/handoff
indicators, not live provider health probes. Future research questions appear
with their stored priority; Autolab's current rule selects the lowest numeric
priority first. The dashboard also lists study protocols with their status,
freeze state/hash, conditions, seeds, metrics and decision rule.

Autolab does not currently assign priority to agent calls or engineering
projects. The dashboard labels research-question priority separately rather
than inventing those missing fields.

The first version is a monitor and gate-review surface. It does not run or stop
projects or queues; use `autolab run` or `autolab queue` for execution. This
avoids introducing a second controller loop that could race a CLI queue.

The server binds only to localhost, uses a per-process request token for state
changes, checks same-origin browser requests, and does not enable CORS. It adds
no runtime dependency and is launched with `autolab ui <lab>`.

Safety rules (D48):

- **DNS rebinding:** every request must be addressed to `127.0.0.1`, `localhost` or `[::1]`
  (the `Host` header); a page on another hostname that resolves to loopback gets `421`.
- **No writes during agent work:** approving a gate or creating a project is refused while
  an agent call is in flight. The controller treats any ledger change during an agent call as
  possible tampering and would HALT the project. A dispatch with no result after 2 hours is
  treated as abandoned by a stopped controller, not as running.
- **Decisions made here are recorded as the human's** (`decided_by = "human"`), so only the
  human should use the approval buttons; delegated reviews by Claude Code use the CLI with
  `--as claude-code` and evidence in the note.
- Long task specs show their first sentence as the title; click the text to expand it.
