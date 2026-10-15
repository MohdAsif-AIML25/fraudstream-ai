"""The wrong topic, so every producer and consumer imports these constants."""

RAW_TOPIC = "transactions.raw"   # every accepted transaction
DLQ_TOPIC = "transactions.dlq"   # dead-letter queue: events the worker could not process (Day 5)

RAW_PARTITIONS = 3  # 3 partitions -> up to 3 workers can consume in parallel later