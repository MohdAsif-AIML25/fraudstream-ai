"""Print every message in the dead-letter queue (transactions.dlq). Read-only.

Run from project root:  python -m scripts.inspect_dlq

Unlike consume_debug, this script:
  - does NOT decode messages (DLQ messages are broken by definition; decoding would crash)
  - does NOT commit offsets, so every run shows the whole DLQ from the beginning
It stops by itself after 5 seconds without new messages.
"""

import time

from confluent_kafka import Consumer

from app.config import get_settings
from app.streaming.topics import DLQ_TOPIC

IDLE_SECONDS = 5


def main() -> None:
    consumer = Consumer({
        "bootstrap.servers": get_settings().kafka_bootstrap_servers,
        "group.id": "fraudstream-dlq-inspector",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,   # never move the group forward: always read from the start
    })
    consumer.subscribe([DLQ_TOPIC])
    count, last_message = 0, time.monotonic()
    try:
        while time.monotonic() - last_message < IDLE_SECONDS:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            count += 1
            last_message = time.monotonic()
            key = msg.key().decode("utf-8", errors="replace") if msg.key() else "-"
            # errors="replace": show broken bytes as � instead of crashing
            print(f"offset={msg.offset()} key={key} value={msg.value()[:300].decode('utf-8', errors='replace')}")
    finally:
        consumer.close()
    print(f"{count} message(s) in {DLQ_TOPIC}")


if __name__ == "__main__":
    main()
    