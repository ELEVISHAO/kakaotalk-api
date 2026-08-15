"""Tests for JobManager serial queue."""
import threading
import time

import pytest

from kakao_mcp.job_manager import JobManager, JobWaitTimeout


def test_jobs_do_not_interleave():
    mgr = JobManager(wait_timeout_sec=5, exec_timeout_sec=30)
    mgr.start()
    order: list[str] = []
    lock = threading.Lock()

    def job(name: str, delay: float):
        with lock:
            order.append(f"start-{name}")
        time.sleep(delay)
        with lock:
            order.append(f"end-{name}")
        return name

    results: list[str] = []

    def run_a():
        results.append(mgr.submit(job, "A", 0.2))

    def run_b():
        results.append(mgr.submit(job, "B", 0.05))

    t1 = threading.Thread(target=run_a)
    t2 = threading.Thread(target=run_b)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    mgr.stop()

    assert set(results) == {"A", "B"}
    # No interleaving: one job fully completes before the other starts
    assert order in (
        ["start-A", "end-A", "start-B", "end-B"],
        ["start-B", "end-B", "start-A", "end-A"],
    )


def test_wait_timeout_when_worker_busy():
    mgr = JobManager(wait_timeout_sec=0.2, exec_timeout_sec=30)
    mgr.start()
    barrier = threading.Event()
    done = threading.Event()

    def blocker():
        barrier.wait(timeout=5)
        return "ok"

    def run_blocker():
        try:
            mgr.submit(blocker)
        finally:
            done.set()

    threading.Thread(target=run_blocker).start()
    time.sleep(0.05)

    with pytest.raises(JobWaitTimeout):
        mgr.submit(lambda: "second", wait_timeout_sec=0.15)

    barrier.set()
    done.wait(timeout=5)
    mgr.stop()
