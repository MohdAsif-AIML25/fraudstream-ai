"""Entry point of the scoring worker: build the real dependencies, then start the loop.

Run from the project root (inside .venv):
    python -m app.worker.main

Composition root: the ONLY place that knows about real Postgres, Redis and Kafka.
Everything else receives its dependencies, which is why the tests need no Docker.
"""

import logging
from datetime import timedelta

from redis import Redis
from prometheus_client import start_http_server


from app.config import get_settings
from app.db.session import make_engine, make_session_factory
from app.features.online import RedisFeatureStore
from app.models.scorer import Scorer
from app.streaming.producer import KafkaPublisher
from app.worker.consumer import ScoringWorker, make_consumer
from app.worker.processor import TransactionProcessor


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()

    # Load the model FIRST: if the artifact is missing or doesn't match the code, fail before
    # joining the consumer group (otherwise we'd take partitions and then crash).
    scorer = Scorer.from_files(settings.model_path, settings.model_meta_path)
    logging.info("loaded model %s thresholds=%s", scorer.model_version, scorer.thresholds)

    store = RedisFeatureStore(Redis.from_url(settings.redis_url),
                              ttl=timedelta(days=settings.history_ttl_days))
    if not store.healthy():
        raise SystemExit(f"Redis is not reachable at {settings.redis_url}")

    session_factory = make_session_factory(make_engine(settings.sqlalchemy_url))
    processor = TransactionProcessor(session_factory, store, scorer)

    # Day 6: serve /metrics on a background thread so Prometheus can scrape the worker.
    start_http_server(settings.worker_metrics_port, addr=settings.worker_metrics_host)
    logging.info("metrics on http://%s:%s/metrics", settings.worker_metrics_host, settings.worker_metrics_port)

    worker = ScoringWorker(
        consumer=make_consumer(settings.kafka_bootstrap_servers, settings.consumer_group),
        processor=processor,
        dlq=KafkaPublisher(settings.kafka_bootstrap_servers),
    )
    worker.run()


if __name__ == "__main__":
    main()