import sys
import time

from autolab.procs import run_tree

PARENT = """\
import subprocess, sys, time
child = "import sys, time, pathlib; time.sleep(4); pathlib.Path(sys.argv[1]).write_text('orphan')"
subprocess.Popen([sys.executable, "-c", child, sys.argv[1]])
print("started", flush=True)
time.sleep(60)
"""


def test_timeout_kills_the_whole_process_tree(tmp_path):
    """R9 regression: like codex.CMD -> node, the agent's child must die with it."""
    marker = tmp_path / "marker.txt"
    t0 = time.monotonic()
    res = run_tree([sys.executable, "-c", PARENT, str(marker)], timeout=2)
    assert res.timed_out and res.returncode == -1
    assert time.monotonic() - t0 < 30
    time.sleep(5)  # the grandchild would have written the marker by now
    assert not marker.exists()


def test_normal_completion_returns_output():
    res = run_tree([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
                   input="hello", timeout=60)
    assert res.returncode == 0 and res.stdout.strip() == "HELLO" and not res.timed_out


def test_output_cap_terminates_a_still_running_tree(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    child = ("import pathlib, sys, time; p=pathlib.Path(sys.argv[1]) / 'large.bin'; "
             "f=p.open('wb'); f.write(b'x' * 200000); f.flush(); time.sleep(5)")
    res = run_tree([sys.executable, "-c", child, str(out)], timeout=10,
                   output_dir=str(out), output_cap_bytes=100000)
    assert res.output_limit_exceeded and res.returncode == -1
