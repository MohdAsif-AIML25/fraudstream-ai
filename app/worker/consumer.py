"""The Kafka loop: poll -> process -> (DLQ) -> commit offset. Repeat until Ctrl+C.

Delivery guarantee: AT LEAST ONCE.
    We commit the offset only AFTER the message was fully handled (scored, skipped as a
    duplicate, or parked in the DLQ). If the worker crashes before committing, Kafka sends
    the message again -> the processor's duplicate check makes the retry harmless.
    (auto-commit would commit on a timer, possibly BEFORE processing -> a crash loses the event.)

Run:  python -m app.worker.main
"""

import logging
import signal
import time

from confluent_kafka import Consumer, KafkaError, Message

from app.monitoring.metrics import QUEUE_TO_SCORE, RISK_BANDS, RISK_SCORE, WORKER_MESSAGES, WORKER_PROCESSING
from app.streaming.producer import Publisher
from app.streaming.topics import DLQ_TOPIC, RAW_TOPIC
from app.worker.processor import Outcome, ProcessResult, TransactionProcessor

log = logging.getLogger("fraudstream.worker")


def make_consumer(bootstrap_servers: str, group_id: str) -> Consumer:
    return Consumer({
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,                # workers with the same group SHARE the partitions
        "enable.auto.commit": False,         # we commit manually, after processing
        "auto.offset.reset": "earliest",     # a brand-new group starts from the oldest message
        "enable.partition.eof": False,
    })


class ScoringWorker:
    def __init__(self, consumer: Consumer, processor: TransactionProcessor, dlq: Publisher) -> None:
        self._consumer = consumer
        self._processor = processor
        self._dlq = dlq
        self._running = True

    def stop(self, *_args) -> None:
        """Signal handler: finish the current message, then leave the loop cleanly."""
        log.info("shutdown requested, finishing current message")
        self._running = False

    def handle(self, msg: Message) -> ProcessResult:
        start = time.perf_counter()
        result = self._processor.process(msg.value())
        WORKER_PROCESSING.observe(time.perf_counter() - start)
        self._record_metrics(result)

        if result.outcome is Outcome.DEAD_LETTER:
            # Keep the ORIGINAL bytes so someone can inspect and replay it later; the reason goes to the log.
            self._dlq.publish(DLQ_TOPIC, key=msg.key() or b"", value=msg.value())
            log.warning("dead-lettered offset=%s partition=%s reason=%s",
                        msg.offset(), msg.partition(), result.reason)
        elif result.outcome is Outcome.SCORED:
            log.info("scored %s score=%.4f band=%s", result.transaction_id, result.result.score, result.result.band)
        else:
            log.info("duplicate %s skipped", result.transaction_id)

        # asynchronous=False: wait until Kafka stored the new offset before taking the next message.
        self._consumer.commit(message=msg, asynchronous=False)
        return result

    @staticmethod
    def _record_metrics(result: ProcessResult) -> None:
        """Day 6: numbers for Prometheus. Only cheap in-memory increments, no I/O."""
        WORKER_MESSAGES.labels(outcome=result.outcome.value).inc()
        if result.outcome is Outcome.SCORED:
            RISK_SCORE.observe(result.result.score)           # score distribution -> drift
            RISK_BANDS.labels(band=result.result.band).inc()  # high-risk rate -> alert
            if result.queue_seconds is not None:
                QUEUE_TO_SCORE.observe(max(result.queue_seconds, 0.0))

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)   # Ctrl+C
        signal.signal(signal.SIGTERM, self.stop)  # docker stop / Kubernetes
        self._consumer.subscribe([RAW_TOPIC])
        log.info("worker started, consuming %s", RAW_TOPIC)
        try:
            while self._running:
                msg = self._consumer.poll(1.0)  # wait up to 1 s; returns None if nothing arrived
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        log.error("kafka error: %s", msg.error())
                    continue
                # If handle() raises (e.g. Postgres is down), we do NOT commit. The process stops,
                # and on restart Kafka redelivers this message. Crashing loudly beats losing data.
                self.handle(msg)
        finally:
            self._consumer.close()  # leave the group cleanly -> fast rebalance for other workers
            self._dlq.close()
            log.info("worker stopped")