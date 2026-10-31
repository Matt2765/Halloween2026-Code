"""One Basement reservation at a time; room state belongs to its own worker."""
import threading

BASEMENT_CLEAR_SECONDS = 10.0
BASEMENT_EXIT_MIN_SECONDS = 15.0


class GroupFlow:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.running = True
            self.ready = False
            self.reserved = False
            self.group = 0
            self.basement_arrival = self.hallway_arrival = None
            self.exit_seen = self.forest_seen = False
            self.clear_since = None

    def stop(self):
        with self.lock:
            self.running = self.ready = self.reserved = False
            self.basement_arrival = self.hallway_arrival = None

    def basement_available(self):
        with self.lock:
            return self.running and self.ready and not self.reserved

    def basement_ready(self):
        with self.lock:
            if self.running:
                self.ready = True
                self.reserved = False

    def reserve_basement(self):
        with self.lock:
            if not self.basement_available():
                return False
            self.ready = False
            self.reserved = True
            self.group += 1
            return True

    def arrive(self):
        with self.lock:
            if not self.running or not self.reserved:
                return False
            self.basement_arrival = self.hallway_arrival = self.group
            return True

    def take_basement_arrival(self):
        with self.lock:
            value = self.basement_arrival if self.running else None
            self.basement_arrival = None
            return value

    def take_hallway_arrival(self):
        with self.lock:
            value = self.hallway_arrival if self.running else None
            self.hallway_arrival = None
            return value

    def start_exit(self):
        with self.lock:
            self.exit_seen = self.forest_seen = False
            self.clear_since = None

    def update_exit(self, now, exit_triggered, forest_triggered):
        """Unknown exit readings reset the quiet timer; PIR7 never clears it alone."""
        with self.lock:
            if forest_triggered is True:
                self.forest_seen = True
            if exit_triggered is True:
                self.exit_seen = True
            if exit_triggered is not False:
                self.clear_since = None
            elif self.exit_seen and self.clear_since is None:
                self.clear_since = now
            return (self.running and self.exit_seen and self.clear_since is not None
                    and now - self.clear_since >= BASEMENT_CLEAR_SECONDS)

    def status(self):
        with self.lock:
            return dict(ready=self.running and self.ready, reserved=self.reserved,
                        group=self.group, exit_seen=self.exit_seen, forest_seen=self.forest_seen)


flow = GroupFlow()
