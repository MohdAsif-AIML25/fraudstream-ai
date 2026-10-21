"""Kafka loop tests with fake consumer/messages: checks the ORDER of side effects.

The rule we protect: the offset is committed only AFTER the message was handled,
and poison messages go to the DLQ instead of blocking the partition forever.
"""

from app.streaming.topics import DLQ_TOPIC
from app.worker.consumer import ScoringWorker
from app.worker.processor import Outcome, ProcessResult


class FakeMessage:
    def __init__(self, value: bytes, key: bytes = b"acct_1", offset: int = 7) -> None:
        self._value, self._key, self._offset = value, key, offset

    def value(self): return self._value
    def key(self): return self._key
    def offset(self): return self._offset
    def partition(self): return 0
    def error(self): return None


class FakeConsumer:
    def __init__(self, log: list) -> None:
        self.log = log

    def commit(self, message, asynchronous):
        assert asynchronous is False  # we wait for the commit before the next message
        self.log.append(("commit", message.offset()))


class FakeDLQ:
    def __init__(self, log: list) -> None:
        self.log = log

    def publish(self, topic, key, value):
        self.log.append(("dlq", topic, value))

    def close(self): pass


class FixedProcessor:
    def __init__(self, result: ProcessResult, log: list) -> None:
        self.result, self.log = result, log

    def process(self, raw):
        self.log.append(("process", raw))
        return self.result


def make_worker(result: ProcessResult):
    log: list = []
    return ScoringWorker(FakeConsumer(log), FixedProcessor(result, log), FakeDLQ(log)), log


def test_poison_message_goes_to_dlq_then_offset_is_committed():
    worker, log = make_worker(ProcessResult(Outcome.DEAD_LETTER, reason="invalid message"))
    worker.handle(FakeMessage(b"garbage"))
    assert log == [("process", b"garbage"), ("dlq", DLQ_TOPIC, b"garbage"), ("commit", 7)]


def test_duplicate_is_committed_without_dlq():
    worker, log = make_worker(ProcessResult(Outcome.DUPLICATE, "txn_1"))
    worker.handle(FakeMessage(b"{}"))
    assert [entry[0] for entry in log] == ["process", "commit"]


def test_failure_during_processing_does_not_commit():
    log: list = []

    class Exploding:
        def process(self, raw):
            raise ConnectionError("postgres down")

    worker = ScoringWorker(FakeConsumer(log), Exploding(), FakeDLQ(log))
    try:
        worker.handle(FakeMessage(b"{}"))
    except ConnectionError:
        pass
    assert log == []  # no commit -> Kafka redelivers after restart -> no data loss