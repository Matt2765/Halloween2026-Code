"""Cancellable waits for sequential room scripts; never fall through on shutdown."""
import time
from utils.tools import BreakCheck


class SequenceStopped(Exception):
    pass


def sequence_wait(seconds):
    end = time.monotonic() + seconds
    while True:
        if BreakCheck():
            raise SequenceStopped()
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(.05, remaining))
