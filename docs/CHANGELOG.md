# Changelog

## 2026-10-07 — Autolab process and CLI reliability

- Trial output limits are now checked while the trial is running. When files in
  the trial output directory plus captured stdout/stderr exceed the configured
  limit, Autolab terminates the process tree and records the trial as failed.
  A final directory-size check also catches output written just before exit.
- `run_tree` reports POSIX peak memory as unavailable. POSIX's
  `RUSAGE_CHILDREN.ru_maxrss` is a cumulative high-water mark, so it cannot be
  attributed accurately to an individual run. Windows Job Object measurements
  remain available.
- The autopilot now runs timed Claude sessions through `run_tree`, so timeout
  handling also cleans up child processes.
- The CLI configures stdout to escape characters unsupported by the active
  console encoding, preventing project objectives from crashing `autolab
  status` on Windows.
- Regression coverage verifies process-tree termination at the output limit.
