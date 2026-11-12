"""Public-Future ownership and bounded joins; cannot kill a running Python thread."""
import threading
import time


class ProducerDeadline(TimeoutError):
    pass


class ProducerGroup:
    def __init__(self, executor):
        self.executor = executor
        self.condition = threading.Condition(threading.RLock())
        self.futures = set()
        self.stopping = False

    def submit(self, fn, *args, **kwargs):
        with self.condition:
            if self.stopping:
                raise RuntimeError('producer intake closed')
            future = self.executor.submit(fn, *args, **kwargs)
            self.futures.add(future)
            future.add_done_callback(self._done)
            return future

    def _done(self, future):
        with self.condition:
            self.futures.discard(future)
            self.condition.notify_all()

    @property
    def pending(self):
        with self.condition:
            return len(self.futures)

    def request_stop(self):
        with self.condition:
            self.stopping = True
            # Public API only. Cancellation callbacks can run synchronously.
            self.executor.shutdown(wait=False, cancel_futures=True)

    def join_until(self, deadline):
        with self.condition:
            while self.futures:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise ProducerDeadline('producer deadline; supervisor recovery required')
                self.condition.wait(remaining)

    def shutdown(self, wait=True, cancel_futures=True):
        self.request_stop()
        if wait:
            self.join_until(time.monotonic()+2.0)
