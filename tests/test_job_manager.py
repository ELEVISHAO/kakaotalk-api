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


def test_wait_timeout_does_not_stop_running_job():
    """Timed-out waiter must not cancel an already-running job's work."""
    mgr = JobManager(wait_timeout_sec=0.2, exec_timeout_sec=30)
    mgr.start()
    events: list[str] = []
    release = threading.Event()

    def long_job():
        events.append("started")
        release.wait(timeout=5)
        events.append("finished")
        return "done"

    result_box: list[str] = []

    def run_long():
        result_box.append(mgr.submit(long_job))

    t = threading.Thread(target=run_long)
    t.start()
    time.sleep(0.05)
    assert "started" in events

    with pytest.raises(JobWaitTimeout):
        mgr.submit(lambda: "other", wait_timeout_sec=0.1)

    release.set()
    t.join(timeout=5)
    assert result_box == ["done"]
    assert "finished" in events
    mgr.stop()
