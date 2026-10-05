# Failures during lab development (retained)

- F1 (2026-10-04): Initial controller treated "engineer made no code changes" as a
  failure, which halted legitimate scenarios (disputed review findings; main already
  implements a revised protocol). Fixed by re-verifying instead (D6).
- F2 (2026-10-04): Test scenario's redesign handler returned an implement-shaped
  payload; the protocol validator correctly rejected it. Fixed in the test.
- F3 (2026-10-04): The live smoke test exposed locale (cp1252) decoding of
  subprocess output on Windows. Experiment, test and merge subprocesses now decode UTF-8.
