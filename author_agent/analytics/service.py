from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone

from author_agent.persistence import AutomationStore

DEFAULT_WEIGHTS = {
    "shares": 3.0,
    "comments": 2.0,
    "saves": 2.5,
    "clicks": 3.0,
    "reach": 1.0,
    "likes": 0.5,
}


def performance_score(metrics: dict[str, float], weights: dict[str, float] | None = None) -> float:
    weights = weights or DEFAULT_WEIGHTS
    total_weight = sum(max(value, 0.0) for value in weights.values()) or 1.0
    score = 0.0
    for key, weight in weights.items():
        value = max(float(metrics.get(key, 0.0)), 0.0)
        score += weight * (value / (1.0 + value))
    return 100.0 * score / total_weight


class AnalyticsService:
    def __init__(
        self,
        store: AutomationStore,
        *,
        weights: dict[str, float] | None = None,
        minimum_samples: int = 10,
    ):
        self.store = store
        self.weights = weights or DEFAULT_WEIGHTS
        self.minimum_samples = minimum_samples

    def store_snapshot(
        self,
        workflow_id: str,
        metrics: dict[str, float],
        measured_at: str | None = None,
    ) -> float:
        score = performance_score(metrics, self.weights)
        measured_at = measured_at or datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            con.execute(
                "INSERT INTO metric_snapshots(workflow_id,measured_at,metrics_json,score) VALUES(?,?,?,?)",
                (workflow_id, measured_at, self.store.dumps(metrics), score),
            )
        return score

    def store_features(self, workflow_id: str, features: dict) -> None:
        with self.store.connect() as con:
            con.execute(
                "INSERT INTO post_features(workflow_id,features_json) VALUES(?,?) "
                "ON CONFLICT(workflow_id) DO UPDATE SET features_json=excluded.features_json",
                (workflow_id, self.store.dumps(features)),
            )

    def guidance(self, feature: str) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT p.features_json, m.score FROM post_features p "
                "JOIN metric_snapshots m ON m.workflow_id=p.workflow_id"
            ).fetchall()
        groups: dict[str, list[float]] = {}
        for row in rows:
            value = json.loads(row["features_json"]).get(feature)
            if value not in (None, ""):
                groups.setdefault(str(value), []).append(float(row["score"]))
        result = []
        for value, scores in groups.items():
            if len(scores) >= self.minimum_samples:
                result.append(
                    {
                        "feature": feature,
                        "value": value,
                        "samples": len(scores),
                        "median_score": statistics.median(scores),
                    }
                )
        return sorted(result, key=lambda item: item["median_score"], reverse=True)
    def recommend_variant(self, feature: str, candidates: list[str]) -> dict:
        """Choose a bounded experiment variant using measured history with exploration.

        Variants below ``minimum_samples`` are explored first (fewest samples wins).
        Once all candidates have enough evidence, the highest median score wins.
        Ties are deterministic so scheduled campaigns remain reproducible.
        """
        if not candidates:
            raise ValueError("At least one experiment candidate is required")
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT p.features_json, m.score FROM post_features p "
                "JOIN metric_snapshots m ON m.workflow_id=p.workflow_id"
            ).fetchall()
        groups: dict[str, list[float]] = {str(value): [] for value in candidates}
        for row in rows:
            value = json.loads(row["features_json"]).get(feature)
            key = str(value) if value is not None else ""
            if key in groups:
                groups[key].append(float(row["score"]))
        under_sampled = [value for value in candidates if len(groups[str(value)]) < self.minimum_samples]
        if under_sampled:
            chosen = min(under_sampled, key=lambda value: (len(groups[str(value)]), candidates.index(value)))
            return {
                "feature": feature,
                "value": str(chosen),
                "mode": "explore",
                "samples": len(groups[str(chosen)]),
                "median_score": None,
            }
        ranked = []
        for value in candidates:
            scores = groups[str(value)]
            ranked.append((statistics.median(scores), -candidates.index(value), str(value), len(scores)))
        median_score, _, chosen, samples = max(ranked)
        return {
            "feature": feature,
            "value": chosen,
            "mode": "exploit",
            "samples": samples,
            "median_score": median_score,
        }

