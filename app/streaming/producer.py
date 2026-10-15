"""Kafka producer used by the API.

Publisher is a small interface (Protocol). The API depends on the INTERFACE, not on Kafka:
production passes KafkaPublisher, tests pass a fake. This is dependency injection.
"""

from typing import Protocol

from confluent_kafka import KafkaException, Producer


class PublishError(Exception):
    """Raised when we cannot confirm Kafka stored the message."""


class Publisher(Protocol):
    def publish(self, topic: str, key: bytes, value: bytes) -> None: ...
    def healthy(self) -> bool: ...
    def close(self) -> None: ...


class KafkaPublisher:
    def __init__(self, bootstrap_servers: str, delivery_timeout_s: float = 5.0) -> None:
        self._timeout = delivery_timeout_s
        self._producer = Producer({
            "bootstrap.servers": bootstrap_servers,
            "acks": "all",                 # broker confirms only after the write is durable
            "enable.idempotence": True,    # producer retries never create duplicate messages
            "message.timeout.ms": int(delivery_timeout_s * 1000),
        })

    def publish(self, topic: str, key: bytes, value: bytes) -> None:
        """Send ONE message and wait for the broker's confirmation.

        Waiting (flush) per message is slower than batching, but at ~5 TPS it's fine, and it lets
        the API answer 202 only when Kafka really has the event. Trade-off: latency vs. certainty.
        """
        errors: list[str] = []

        def on_delivery(err, msg) -> None:  # called by confluent-kafka when the broker answers
            if err is not None:
                errors.append(str(err))

        try:
            self._producer.produce(topic, key=key, value=value, on_delivery=on_delivery)
        except (BufferError, KafkaException) as exc:  # local queue full / client error
            raise PublishError(str(exc)) from exc

        still_waiting = self._producer.flush(self._timeout)  # returns how many messages are unconfirmed
        if still_waiting or errors:
            raise PublishError(errors[0] if errors else "timed out waiting for Kafka")

    def healthy(self) -> bool:
        """True if the broker answers a metadata request within 2 seconds."""
        try:
            self._producer.list_topics(timeout=2)
            return True
        except KafkaException:
            return False

    def close(self) -> None:
        self._producer.flush(10)  # deliver anything still buffered before shutdown