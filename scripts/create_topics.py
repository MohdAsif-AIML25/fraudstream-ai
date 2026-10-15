"""Create the Kafka topics explicitly (auto-creation is disabled in docker-compose).

Run from project root:  python -m scripts.create_topics
Safe to run twice: existing topics are reported, not recreated.
"""
from re import I
import sys 
from confluent_kafka.admin import AdminClient,NewTopic 
from app.config import get_settings 
from app.streaming.topics import DLQ_TOPIC,RAW_PARTITIONS,RAW_TOPIC


def main() ->int:
    admin=AdminClient({"bootstrap.servers":get_settings().kafka_bootstrap_servers})
    topics=[
        NewTopic(RAW_TOPIC,num_partitions=RAW_PARTITIONS,replication_factor=1),
        NewTopic(DLQ_TOPIC, num_partitions=1, replication_factor=1),
    ]

    failed=False 

    for name,future in admin.create_topics(topics).items():
        try:
            future.result()
            print(f"[OK]  created {name}")
        except Exception as exc:
            if "TOPIC_ALREADY_EXISTS" in str(exc):
                print(f"[OK] {name} already exists")

            else:
                print(f"[FAIL] {name}:{exc}")
                failed=True
    return 1 if failed else 0

if __name__=="__main__":
    sys.exit(main())