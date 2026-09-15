from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path


@dataclass(frozen=True)
class EvaluationReport:
    overall_score: float
    factual_precision: float
    unsupported_claim_rate: float
    duplicate_rate: float
    instagram_compliance: float
    platform_differentiation: float
    cases: int


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def evaluate_fixture(fixture: dict) -> dict[str, float]:
    evidence = [str(item).lower() for item in fixture.get("evidence", [])]
    claims = [str(item).lower() for item in fixture.get("claims", [])]
    supported = sum(any(claim in item or item in claim for item in evidence) for claim in claims)
    factual_precision = supported / len(claims) if claims else 1.0
    prior = [str(item) for item in fixture.get("prior_posts", [])]
    drafts = fixture.get("drafts", {})
    texts = [str(value) for value in drafts.values()]
    duplicate_rate = 0.0
    if texts and prior:
        duplicate_rate = sum(
            max((_similarity(text, previous) for previous in prior), default=0.0) >= 0.86
            for text in texts
        ) / len(texts)
    instagram = str(drafts.get("instagram", ""))
    facebook = str(drafts.get("facebook", ""))
    instagram_ok = 1.0 if len(instagram) <= int(fixture.get("instagram_max_length", 2200)) else 0.0
    differentiation = 1.0 - _similarity(instagram, facebook) if instagram and facebook else 1.0
    return {
        "factual_precision": factual_precision,
        "unsupported_claim_rate": 1.0 - factual_precision,
        "duplicate_rate": duplicate_rate,
        "instagram_compliance": instagram_ok,
        "platform_differentiation": differentiation,
    }


def run_evaluation(fixtures_dir: Path | None = None) -> EvaluationReport:
    package_fixtures = Path(__file__).resolve().parent / "fixtures"
    requested = fixtures_dir or package_fixtures
    if not requested.is_absolute() and not requested.exists():
        requested = package_fixtures
    files = sorted(requested.glob("*.json"))
    scores = [evaluate_fixture(json.loads(path.read_text(encoding="utf-8"))) for path in files]
    if not scores:
        raise ValueError(f"No evaluation fixtures found in {requested}")
    average = {
        key: sum(item[key] for item in scores) / len(scores)
        for key in scores[0]
    }
    overall = 100.0 * (
        0.55 * average["factual_precision"]
        + 0.15 * (1 - average["duplicate_rate"])
        + 0.15 * average["instagram_compliance"]
        + 0.15 * average["platform_differentiation"]
    )
    rounded = {key: round(value, 4) for key, value in average.items()}
    return EvaluationReport(overall_score=round(overall, 2), cases=len(scores), **rounded)


def report_dict(report: EvaluationReport) -> dict:
    return asdict(report)
