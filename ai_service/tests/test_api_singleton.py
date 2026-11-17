import threading
import time

from ayumitra_ai.api import singleton


def test_concurrent_first_calls_build_once():
    """Regression: two threads building RagPipeline at once opened two Chroma clients and crashed."""
    calls = []

    @singleton
    def heavy():
        calls.append(1)
        time.sleep(0.2)  # slow construction widens the race window
        return object()

    results = []
    threads = [threading.Thread(target=lambda: results.append(heavy())) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert len({id(r) for r in results}) == 1


def test_nested_singletons_do_not_deadlock():
    @singleton
    def inner():
        return 1

    @singleton
    def outer():
        return inner() + 1

    assert outer() == 2
