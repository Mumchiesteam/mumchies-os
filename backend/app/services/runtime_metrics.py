"""PII-free process and background-work instrumentation."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from threading import Lock
from typing import AsyncIterator

LOGGER = logging.getLogger(__name__)
_jobs_lock = Lock()
_active_jobs: dict[str, int] = {}
heavy_background_lock = asyncio.Lock()


def rss_bytes() -> int | None:
    """Current RSS without adding a production dependency."""
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError, AttributeError):
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                class ProcessMemoryCounters(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ]

                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
                get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
                get_memory.restype = wintypes.BOOL
                if get_memory(handle, ctypes.byref(counters), counters.cb):
                    return int(counters.WorkingSetSize)
            except (AttributeError, OSError, ValueError):
                pass
        return None


def rss_mb() -> float | None:
    value = rss_bytes()
    return round(value / 1024 / 1024, 2) if value is not None else None


def active_background_jobs() -> dict[str, int]:
    with _jobs_lock:
        return dict(_active_jobs)


@asynccontextmanager
async def background_job(name: str, *, heavy: bool = False) -> AsyncIterator[None]:
    lock = heavy_background_lock if heavy else None
    if lock is not None:
        await lock.acquire()
    with _jobs_lock:
        _active_jobs[name] = _active_jobs.get(name, 0) + 1
    before = rss_mb()
    LOGGER.info("background_job_started name=%s rss_mb=%s active_jobs=%s", name, before, active_background_jobs())
    try:
        yield
    finally:
        after = rss_mb()
        with _jobs_lock:
            remaining = _active_jobs.get(name, 1) - 1
            if remaining > 0:
                _active_jobs[name] = remaining
            else:
                _active_jobs.pop(name, None)
        if lock is not None:
            lock.release()
        LOGGER.info("background_job_completed name=%s rss_mb_before=%s rss_mb_after=%s active_jobs=%s", name, before, after, active_background_jobs())


async def event_loop_watchdog(interval_seconds: float = 0.5, warn_after_seconds: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    expected = loop.time() + interval_seconds
    while True:
        await asyncio.sleep(interval_seconds)
        now = loop.time()
        lag = max(0.0, now - expected)
        if lag >= warn_after_seconds:
            LOGGER.warning("event_loop_lag lag_ms=%.2f rss_mb=%s active_jobs=%s", lag * 1000, rss_mb(), active_background_jobs())
        expected = now + interval_seconds
