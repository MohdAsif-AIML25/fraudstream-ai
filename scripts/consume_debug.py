"""Debug consumer: prints every message on transactions.raw. Stop with Ctrl+C.

Run from project root:  python -m scripts.consume_debug

It belongs to a consumer GROUP and commits offsets after each message.
Experiment: stop it, send more transactions, start it again -> it continues
exactly where it stopped (no message lost, none repeated). That is the Day 4 goal.
The real scoring worker on Day 5 uses the same pattern.
"""

from confluent_kafka import Consumer

from app.config import get_settings
from app.streaming.messages import decode_transaction
from app.streaming.topics import RAW_TOPIC


def main() -> None:
    consumer = Consumer({
        "bootstrap.servers": get_settings().kafka_bootstrap_servers,
        "group.id": "fraudstream-debug",   # Kafka stores this group's position (offset) per partition
        "auto.offset.reset": "earliest",   # first run ever: start from the oldest message
        "enable.auto.commit": False,       # we commit manually, only after handling a message
    })
    consumer.subscribe([RAW_TOPIC])
    print(f"listening on {RAW_TOPIC} ... (Ctrl+C to stop)")
    try:
        while True:
            msg = consumer.poll(1.0)  # wait up to 1 s for the next message
            if msg is None:
                continue
            if msg.error():
                print("error:", msg.error())
                continue
            txn = decode_transaction(msg.value())
            print(f"partition={msg.partition()} offset={msg.offset()} key={msg.key().decode()} "
                  f"txn={txn.transaction_id} amount=₹{txn.amount_minor / 100:,.2f}")
            consumer.commit(message=msg, asynchronous=False)  # "I have handled up to here"
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()  # leave the group cleanly so partitions are released at once


if __name__ == "__main__":
    main()