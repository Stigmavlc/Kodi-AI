import threading
import time
import pytest


def test_atomic_counter_increments():
    from lib.concurrency import AtomicCounter
    c = AtomicCounter()
    assert c.get() == 0
    c.inc()
    c.inc()
    assert c.get() == 2


def test_atomic_counter_reset_and_get():
    from lib.concurrency import AtomicCounter
    c = AtomicCounter()
    for _ in range(5):
        c.inc()
    assert c.reset_and_get() == 5
    assert c.get() == 0


def test_atomic_counter_thread_safe():
    from lib.concurrency import AtomicCounter
    c = AtomicCounter()
    def worker():
        for _ in range(1000):
            c.inc()
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert c.get() == 10_000


def test_work_queue_priority_resume_first():
    from lib.concurrency import work_queue, enqueue, ResumeWork, LogIncident
    # Clear any existing items
    while not work_queue.empty():
        work_queue.get_nowait()
    enqueue(LogIncident(cluster_id="c1", first_seen=None, last_seen=None,
                        occurrences=1, raw_lines=[], severity_hint="ERROR",
                        likely_addon=None, likely_action=None, backdated=False,
                        from_previous_session=False, triage_deferred=True))
    enqueue(ResumeWork(session_id="s1", user_reply=True))
    prio, seq, item = work_queue.get_nowait()
    assert isinstance(item, ResumeWork)


def test_enqueue_rejects_unknown_type():
    from lib.concurrency import enqueue
    class WeirdType: pass
    with pytest.raises(KeyError):
        enqueue(WeirdType())


def test_abort_event_global():
    from lib.concurrency import abort_event
    abort_event.clear()
    assert not abort_event.is_set()
    abort_event.set()
    assert abort_event.is_set()
    abort_event.clear()  # cleanup
