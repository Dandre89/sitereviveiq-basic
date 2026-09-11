"""
Weighted category scoring, per the spec's "scoring credibility"
principle: explainable category scores, with the findings behind each
score preserved (not just a black-box number).

Only categories Build 2's rules actually check get scored. Competitive
is deferred to a later build (Scanner Version 0.3+). In this build,
Accessibility and Conversion are also excluded from scoring — not
because the rules can't check them, but because this tier's issue
detection is narrowed to Technical/SEO/Content/Security-Trust only (see
apps.findings.services.analyze_scan), so no Accessibility/Conversion
findings ever reach this module. Weighting them anyway would silently
score those categories a fake perfect 100 while still counting that
100 toward overall_score — inflating it with categories nobody's
issues were ever checked against. All three excluded categories are
reported as not_assessed instead, same treatment Competitive already
got.
"""
from dataclasses import dataclass

from .models import Finding

SEVERITY_PENALTY = {"critical": 30, "high": 15, "medium": 7, "low": 3}

# Weights must sum to 1.0 across ASSESSED_CATEGORIES. Renormalized from
# the full 6-category weighting (technical .25, seo .25, accessibility
# .125, content .125, security_trust .10, conversion .15) down to just
# the 4 categories this tier actually assesses, preserving the same
# relative ordering (technical/seo highest, security_trust lowest).
CATEGORY_WEIGHTS = {
    "technical": 0.35,
    "seo": 0.35,
    "content": 0.17,
    "security_trust": 0.13,
}

ASSESSED_CATEGORIES = set(CATEGORY_WEIGHTS)
NOT_YET_ASSESSED_CATEGORIES = {"competitive", "accessibility", "conversion"}


@dataclass
class CategoryScore:
    category: str
    score: int  # 0-100
    penalty_applied: int
    finding_count: int
    assessed: bool = True


def compute_category_scores(findings: list[Finding]) -> dict[str, CategoryScore]:
    penalties: dict[str, int] = {c: 0 for c in ASSESSED_CATEGORIES}
    counts: dict[str, int] = {c: 0 for c in ASSESSED_CATEGORIES}

    for finding in findings:
        if finding.category not in ASSESSED_CATEGORIES:
            continue
        penalties[finding.category] += SEVERITY_PENALTY.get(finding.severity, 0)
        counts[finding.category] += 1

    scores = {}
    for category in ASSESSED_CATEGORIES:
        score = max(0, 100 - penalties[category])
        scores[category] = CategoryScore(
            category=category,
            score=score,
            penalty_applied=penalties[category],
            finding_count=counts[category],
        )
    for category in NOT_YET_ASSESSED_CATEGORIES:
        scores[category] = CategoryScore(
            category=category, score=0, penalty_applied=0, finding_count=0, assessed=False
        )
    return scores


def compute_overall_score(category_scores: dict[str, CategoryScore]) -> int:
    total = 0.0
    for category, weight in CATEGORY_WEIGHTS.items():
        total += category_scores[category].score * weight
    return round(total)


def scores_to_dict(category_scores: dict[str, CategoryScore]) -> dict:
    """JSON-serializable form for storing on Scan.category_scores."""
    return {
        category: {
            "score": cs.score if cs.assessed else None,
            "assessed": cs.assessed,
            "penalty_applied": cs.penalty_applied,
            "finding_count": cs.finding_count,
        }
        for category, cs in category_scores.items()
    }
