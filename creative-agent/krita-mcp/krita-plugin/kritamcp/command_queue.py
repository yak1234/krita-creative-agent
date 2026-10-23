"""Thread-safe hand-off between the HTTP thread and Krita's main thread.

Kept free of krita/PyQt imports so it can be unit-tested outside Krita.
"""

import threading

TIMEOUT_CODE = "timeout"

# Set on Krita's main thread by the panel's Stop button, before the companion hears about it:
# no painting operation starts after the click, and a stroke pass ends after its current
# stroke. Cleared when the panel sees the run end (busy false) or a new session begins.
stop_requested = threading.Event()

# Set on Krita's main thread while the bridge executes a command (a stroke pass handles clicks between its strokes):
# the panel's protection controls wait until it is clear, so an artist's change never lands inside the agent's work.
command_executing = threading.Event()

# Set on Krita's main thread while the artist adjusts a protected area in the panel (a selection tool on the document
# selection): agent writes are held until Done or Cancel, so none lands in the selection or the area being edited.
artist_editing = threading.Event()


class CommandQueue:
    """Thread-safe command queue for passing commands from HTTP thread to main thread."""
    def __init__(self):
        self.queue = []
        self.results = {}
        # Ids whose caller stopped waiting while the command was executing.
        self.abandoned = set()
        self.lock = threading.Lock()
        self.result_event = threading.Event()

    def push(self, command_id, command):
        with self.lock:
            self.queue.append((command_id, command))

    def pop(self):
        with self.lock:
            if self.queue:
                return self.queue.pop(0)
            return None

    def set_result(self, command_id, result):
        with self.lock:
            if command_id in self.abandoned:
                # Nobody will collect this; keeping it would leak.
                self.abandoned.discard(command_id)
                return
            self.results[command_id] = result
        self.result_event.set()

    def get_result(self, command_id, timeout=120):
        """Wait for result with timeout.

        The default timeout of 120s is important — canvas export and save
        operations can take a long time on large canvases. The original 30s
        default caused frequent timeouts. Clients send their own timeout in the
        request body and wait longer than it, so this side always answers first.

        On timeout a still-queued command is removed so it never runs late; a
        command already executing is marked abandoned and its result dropped.
        """
        for _ in range(int(timeout * 10)):  # Check every 100ms
            with self.lock:
                if command_id in self.results:
                    return self.results.pop(command_id)
            self.result_event.wait(0.1)
            self.result_event.clear()
        with self.lock:
            # A result may have landed after the last check.
            if command_id in self.results:
                return self.results.pop(command_id)
            remaining = [(cid, c) for cid, c in self.queue if cid != command_id]
            started = len(remaining) == len(self.queue)
            self.queue = remaining
            if started:
                self.abandoned.add(command_id)
        return {"error": f"Timeout waiting for command execution after {timeout:g}s",
                "error_code": TIMEOUT_CODE,
                "started": started}
