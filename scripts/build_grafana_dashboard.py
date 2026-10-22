"""Generate the Grafana dashboard JSON from Python ("dashboards as code").

Run from project root:   python -m scripts.build_grafana_dashboard
Output:                  infra/grafana/dashboards/fraudstream-overview.json  (commit it)

Why generate instead of hand-writing JSON? A Grafana dashboard is ~12 KB of repetitive JSON.
Here each panel is ONE line: type, title, PromQL query, position. Easy to read and review.
"""

import json
from pathlib import Path

OUT = Path("infra/grafana/dashboards/fraudstream-overview.json")
DS = {"type": "prometheus", "uid": "prometheus"}  # must match uid in provisioning/datasources/prometheus.yml

# Colour rules reused by several panels
UP_DOWN = {"mappings": [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"},
                                                       "1": {"text": "UP", "color": "green"}}}],
           "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 1}]}}
HIGH_RATE = {"thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None},
                                                          {"color": "orange", "value": 0.04},
                                                          {"color": "red", "value": 0.06}]}}
ANY_IS_BAD = {"thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 1}]}}

panels: list[dict] = []


def panel(kind, title, targets, x, y, w, h, unit=None, desc="", defaults=None, options=None):
    """targets = [(PromQL, legend), ...];  x, y, w, h = position on a 24-column grid."""
    fc_defaults = dict(defaults or {})
    if unit:
        fc_defaults["unit"] = unit
    panels.append({
        "id": len(panels) + 1, "type": kind, "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": chr(65 + i), "datasource": DS, "expr": expr, "legendFormat": legend}
                    for i, (expr, legend) in enumerate(targets)],
        "fieldConfig": {"defaults": fc_defaults, "overrides": []},
        "options": options or {},
    })


# ---- row 1: is everything alive? (stat tiles) ----
panel("stat", "API", [('max(up{job="fraudstream-api"})', "")], 0, 0, 4, 4,
      desc="Is Prometheus able to scrape the API?", defaults=UP_DOWN)
panel("stat", "Worker", [('max(up{job="fraudstream-worker"})', "")], 4, 0, 4, 4,
      desc="Is Prometheus able to scrape the worker?", defaults=UP_DOWN)
panel("stat", "Scored / s", [('sum(rate(fraudstream_worker_messages_total{outcome="scored"}[1m]))', "")],
      8, 0, 4, 4, unit="reqps")
panel("stat", "High-risk rate (10m)",
      [('sum(rate(fraudstream_risk_band_total{band="high"}[10m])) / sum(rate(fraudstream_risk_band_total[10m]))', "")],
      12, 0, 6, 4, unit="percentunit", defaults=HIGH_RATE,
      desc="Share of scored transactions in the high band. Thresholds target about 2%.")
panel("stat", "Dead letters (1h)",
      [('sum(increase(fraudstream_worker_messages_total{outcome="dead_letter"}[1h])) or vector(0)', "")],
      18, 0, 6, 4, defaults=ANY_IS_BAD)

# ---- row 2-3: service and pipeline health ----
panel("timeseries", "Worker throughput by outcome",
      [('sum by (outcome) (rate(fraudstream_worker_messages_total[1m]))', "{{outcome}}")], 0, 4, 12, 8, unit="reqps")
panel("timeseries", "API latency p95 by route",
      [('histogram_quantile(0.95, sum by (le, route) (rate(fraudstream_http_request_duration_seconds_bucket[5m])))',
        "{{route}}")], 12, 4, 12, 8, unit="s")
panel("timeseries", "Acceptance to score (queue time)",
      [('histogram_quantile(0.50, sum by (le) (rate(fraudstream_queue_to_score_seconds_bucket[5m])))', "p50"),
       ('histogram_quantile(0.95, sum by (le) (rate(fraudstream_queue_to_score_seconds_bucket[5m])))', "p95")],
      0, 12, 12, 8, unit="s",
      desc="How long a transaction waits between the API's 202 and its saved score. Rising = worker falling behind.")
panel("timeseries", "Risk bands per second",
      [('sum by (band) (rate(fraudstream_risk_band_total[5m]))', "{{band}}")], 12, 12, 12, 8, unit="reqps")

# ---- row 4: model health ----
panel("bargauge", "Score distribution (last 1h)",
      [('sum by (le) (increase(fraudstream_risk_score_bucket[1h]))', "≤ {{le}}")], 0, 20, 12, 8,
      desc="Cumulative buckets: how many scores were at or below each value. A shift to the right = model drift or attack.",
      options={"orientation": "horizontal", "displayMode": "basic"})
panel("timeseries", "Analyst decisions",
      [('sum by (decision) (increase(fraudstream_review_decisions_total[1h]))', "{{decision}}")], 12, 20, 6, 8)
panel("stat", "Precision on reviewed cases",
      [('sum(fraudstream_review_decisions_total{decision="confirmed_fraud"}) / sum(fraudstream_review_decisions_total)', "")],
      18, 20, 6, 8, unit="percentunit",
      desc="Of the high-risk cases analysts reviewed, the share that was real fraud. This is the model's REAL precision in production.")

dashboard = {
    "uid": "fraudstream-overview", "title": "FraudStream overview", "tags": ["fraudstream"], "timezone": "browser",
    "schemaVersion": 39, "version": 1, "refresh": "10s", "time": {"from": "now-30m", "to": "now"},
    "panels": panels,
}

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} with {len(panels)} panels")