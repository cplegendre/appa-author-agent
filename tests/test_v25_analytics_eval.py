from author_agent.analytics import AnalyticsService, performance_score
from author_agent.evaluation import evaluate_fixture, run_evaluation
from author_agent.persistence import AutomationStore


def test_weighted_score_rewards_high_value_actions():
    assert performance_score({"shares": 10}) > performance_score({"likes": 10})


def test_analytics_snapshots_and_minimum_sample(tmp_path):
    store = AutomationStore(tmp_path / "a.sqlite3")
    analytics = AnalyticsService(store, minimum_samples=2)
    for idx, score_metrics in enumerate(({"shares": 1}, {"shares": 10})):
        wid = f"w{idx}"
        analytics.store_features(wid, {"hook_style": "question"})
        analytics.store_snapshot(wid, score_metrics)
    guidance = analytics.guidance("hook_style")
    assert guidance[0]["value"] == "question"
    assert guidance[0]["samples"] == 2


def test_analytics_threshold_blocks_tiny_samples(tmp_path):
    store = AutomationStore(tmp_path / "a.sqlite3")
    analytics = AnalyticsService(store, minimum_samples=2)
    analytics.store_features("w", {"theme": "behind-scenes"})
    analytics.store_snapshot("w", {"reach": 5})
    assert analytics.guidance("theme") == []


def test_fixture_scoring_detects_unsupported_claim():
    result = evaluate_fixture(
        {
            "evidence": ["Yok is green"],
            "claims": ["Yok is green", "Yok flies"],
            "drafts": {"instagram": "a", "facebook": "b"},
        }
    )
    assert result["factual_precision"] == 0.5
    assert result["unsupported_claim_rate"] == 0.5


def test_deterministic_eval_fixture_corpus():
    report = run_evaluation(__import__("pathlib").Path("evaluation/fixtures"))
    assert report.cases >= 2
    assert report.factual_precision == 1.0
    assert report.overall_score > 85
