"""Subprocesses that never outlive the controller.

Agent CLIs on Windows are often ``.CMD`` shims: ``cmd.exe`` starts ``node``.
``subprocess.run(timeout=...)`` kills only ``cmd.exe`` and the agent keeps
running as an orphan. :func:`run_tree` instead

* on Windows, puts the child in a Job Object with KILL_ON_JOB_CLOSE, so the
  whole tree dies on timeout *and* when the controller process itself dies
  (the OS closes the job handle);
* on POSIX, starts the child in its own session and kills the process group.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

if sys.platform != "win32":
    import resource
from dataclasses import dataclass


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    # Controller-measured resources of the whole process tree (None if unavailable).
    wall_s: float | None = None
    cpu_s: float | None = None
    peak_mb: float | None = None


class _Job:
    """Windows Job Object that kills every assigned process when closed."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._k32 = k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                                  wintypes.DWORD, wintypes.LPVOID]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class ACCOUNTING(ctypes.Structure):
            _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                        ("ThisPeriodTotalUserTime", ctypes.c_int64),
                        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                        ("TotalPageFaultCount", wintypes.DWORD),
                        ("TotalProcesses", wintypes.DWORD), ("ActiveProcesses", wintypes.DWORD),
                        ("TotalTerminatedProcesses", wintypes.DWORD)]

        self._ctypes, self._EXTENDED, self._ACCOUNTING = ctypes, EXTENDED, ACCOUNTING
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info),
                                           ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def assign(self, proc: subprocess.Popen) -> None:
        if not self._k32.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise OSError("AssignProcessToJobObject failed")

    def kill(self) -> None:
        self._k32.TerminateJobObject(self.handle, 1)

    def usage(self) -> tuple[float | None, float | None]:
        """(CPU seconds, peak job memory in MB) for every process that ran in the job."""
        ct = self._ctypes
        acc, ext = self._ACCOUNTING(), self._EXTENDED()
        cpu = peak = None
        if self._k32.QueryInformationJobObject(self.handle, 1, ct.byref(acc), ct.sizeof(acc), None):
            cpu = (acc.TotalUserTime + acc.TotalKernelTime) / 1e7  # 100 ns units
        if self._k32.QueryInformationJobObject(self.handle, 9, ct.byref(ext), ct.sizeof(ext), None):
            peak = ext.PeakJobMemoryUsed / 2**20
        return cpu, peak

    def close(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)  # kills anything still in the job
            self.handle = None


def _kill_tree(proc: subprocess.Popen, job: _Job | None) -> None:
    if job is not None:
        job.kill()
    elif sys.platform != "win32":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    proc.kill()


def run_tree(cmd: list[str], *, cwd: str | None = None, input: str | None = None,
             timeout: float | None = None, env: dict | None = None) -> ProcResult:
    """Run ``cmd`` to completion; kill its whole process tree on timeout or interrupt."""
    win = sys.platform == "win32"
    t0 = time.perf_counter()
    ru0 = None if win else resource.getrusage(resource.RUSAGE_CHILDREN)
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=not win)
    job = None
    if win:
        job = _Job()
        try:
            job.assign(proc)
        except OSError:
            job.close()
            job = None
    def finish(rc: int, out: str, err: str, timed_out: bool = False) -> ProcResult:
        res = ProcResult(rc, out or "", err or "", timed_out,
                         wall_s=round(time.perf_counter() - t0, 4))
        if job is not None:
            res.cpu_s, res.peak_mb = job.usage()
        elif ru0 is not None:
            ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
            res.cpu_s = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)
            res.peak_mb = ru1.ru_maxrss / (2**20 if sys.platform == "darwin" else 2**10)
        if res.cpu_s is not None:
            res.cpu_s = round(res.cpu_s, 4)
        if res.peak_mb is not None:
            res.peak_mb = round(res.peak_mb, 2)
        return res

    try:
        try:
            out, err = proc.communicate(input=input, timeout=timeout)
            return finish(proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            _kill_tree(proc, job)
            out, err = proc.communicate()
            return finish(-1, out, err, timed_out=True)
        except BaseException:  # KeyboardInterrupt etc.: never leave the tree behind
            _kill_tree(proc, job)
            proc.wait()
            raise
    finally:
        if job is not None:
            job.close()
