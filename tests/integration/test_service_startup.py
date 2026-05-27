"""Integration test: service.py t4_worker_body smoke pass (Task 11.2).

Verifies the T4 boot pass:
- runs each smoke probe (state_paths.ensure_dirs, atomic-rename, redactor
  canary, tool-registry probe, audit-log size warn, health/recovery boot)
  without aborting on any single failure;
- sets startup_complete_event;
- exits the work-queue drain loop cleanly when abort_event is signalled.

Does NOT exercise service.main() (which spawns 3 OS threads + xbmc.Monitor)
— instead drives t4_worker_body directly with bot=None and a fake abort
timer. This keeps the test deterministic and fast (sub-3s) while still
covering the full Phase-11 boot sequence.

Spec: §1.14, §7 (smoke/boot).
"""
from __future__ import annotations
import os
import sys
import threading
import time
import pytest

pytestmark = pytest.mark.integration


# Ensure the addon root is on sys.path so `import service` resolves.
_ADDON_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "service.kodi.ai")
)
if _ADDON_ROOT not in sys.path:
    sys.path.insert(0, _ADDON_ROOT)


def test_t4_worker_body_completes_boot_pass():
    """t4_worker_body runs full boot pass, sets startup_complete_event, and
    exits cleanly when abort_event is signalled mid-loop."""
    from service import t4_worker_body
    from lib.concurrency import abort_event, startup_complete_event, work_queue

    # The integration conftest's set_startup_complete fixture sets this event
    # eagerly so other tests don't deadlock — we must clear it so our assertion
    # actually proves t4_worker_body set it.
    startup_complete_event.clear()
    abort_event.clear()

    def stop_after_delay():
        time.sleep(1.5)
        abort_event.set()
        # Push a sentinel so the work_queue.get(timeout=1.0) wakes promptly.
        try:
            work_queue.put_nowait((100, 99999, None))
        except Exception:
            pass

    stopper = threading.Thread(target=stop_after_delay, daemon=True)
    stopper.start()

    started = time.time()
    t4_worker_body(bot=None)
    elapsed = time.time() - started

    assert startup_complete_event.is_set(), (
        "startup_complete_event should have been set during boot pass"
    )
    assert elapsed < 8, (
        f"t4_worker_body took too long to exit after abort: {elapsed:.2f}s"
    )

    # Cleanup so subsequent tests aren't poisoned by leftover abort state.
    abort_event.clear()
    # Restore startup_complete_event so other tests' set_startup_complete
    # assumption holds. (autouse fixture won't re-run for tests in this same
    # pytest invocation after this point until pytest dispatches a new test.)
    startup_complete_event.set()
