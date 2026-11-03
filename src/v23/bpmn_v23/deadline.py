"""Candidate deadlines on Windows as well as Unix; v22 stays unchanged."""
from contextlib import contextmanager
import signal
import sys
import threading
import time

from bpmn_universal.cli import deadline as unix_deadline


@contextmanager
def deadline(seconds):
    if hasattr(signal, 'SIGALRM') and threading.current_thread() is threading.main_thread():
        with unix_deadline(seconds):
            yield
        return
    # Windows has no SIGALRM. Routing is Python code with frequent function
    # calls, so a cooperative profile hook can unwind it at a safe boundary.
    # Native blocking calls retain their own subprocess timeouts.
    finish = time.monotonic() + seconds
    previous = sys.getprofile()
    ticks = 0

    def check(frame, event, arg):
        nonlocal ticks
        ticks += 1
        if previous:
            previous(frame, event, arg)
        if ticks % 128 == 0 and time.monotonic() >= finish:
            raise TimeoutError('Layout candidate deadline exceeded')

    sys.setprofile(check)
    try:
        yield
    finally:
        sys.setprofile(previous)
