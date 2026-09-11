from analyzer.models import Finding
from analyzer.scoring import (
    ASSESSED_CATEGORIES,
    NOT_YET_ASSESSED_CATEGORIES,
    compute_category_scores,
    compute_overall_score,
    scores_to_dict,
)


def make_finding(**overrides) -> Finding:
    defaults = dict(
        rule_key="missing_title",
        title="Missing title",
        category="seo",
        severity="high",
        business_impact="search_visibility",
        affected_scope="https://example.com/",
        estimated_effort="Small",
    )
    defaults.update(overrides)
    return Finding(**defaults)


class TestCategoryScores:
    def test_no_findings_yields_perfect_scores_for_assessed_categories(self):
        scores = compute_category_scores([])
        for category in ASSESSED_CATEGORIES:
            assert scores[category].score == 100
            assert scores[category].assessed is True

    def test_unassessed_categories_are_marked_not_assessed(self):
        scores = compute_category_scores([])
        for category in NOT_YET_ASSESSED_CATEGORIES:
            assert scores[category].assessed is False

    def test_critical_finding_applies_30_point_penalty(self):
        finding = make_finding(category="technical", severity="critical")
        scores = compute_category_scores([finding])
        assert scores["technical"].score == 70
        assert scores["technical"].penalty_applied == 30

    def test_high_finding_applies_15_point_penalty(self):
        finding = make_finding(category="seo", severity="high")
        scores = compute_category_scores([finding])
        assert scores["seo"].score == 85

    def test_multiple_findings_in_same_category_stack_penalties(self):
        findings = [
            make_finding(category="accessibility", severity="medium"),
            make_finding(category="accessibility", severity="medium"),
        ]
        scores = compute_category_scores(findings)
        assert scores["accessibility"].score == 86  # 100 - 7 - 7
        assert scores["accessibility"].finding_count == 2

    def test_score_floors_at_zero(self):
        findings = [make_finding(category="content", severity="critical") for _ in range(10)]
        scores = compute_category_scores(findings)
        assert scores["content"].score == 0

    def test_competitive_findings_ignored_in_scoring(self):
        # Even if a future rule somehow tagged a finding as competitive,
        # today's scoring must not silently score that category.
        finding = make_finding(category="competitive", severity="critical")
        scores = compute_category_scores([finding])
        assert scores["competitive"].assessed is False
        assert scores["competitive"].finding_count == 0

    def test_conversion_is_now_an_assessed_category(self):
        # Build 7 added real conversion-heuristic rules, so unlike
        # competitive, conversion findings DO count now.
        finding = make_finding(category="conversion", severity="high")
        scores = compute_category_scores([finding])
        assert scores["conversion"].assessed is True
        assert scores["conversion"].score == 85


class TestOverallScore:
    def test_perfect_categories_yield_perfect_overall(self):
        scores = compute_category_scores([])
        assert compute_overall_score(scores) == 100

    def test_overall_score_reflects_weighted_categories(self):
        finding = make_finding(category="technical", severity="critical")  # -30 in technical
        scores = compute_category_scores([finding])
        # technical: 70 * 0.25 = 17.5; others perfect: seo 25 + accessibility 12.5
        # + content 12.5 + security_trust 10 + conversion 15 = 75. Total = 92.5 -> rounds to 92.
        assert compute_overall_score(scores) == 92


class TestScoresToDict:
    def test_serializes_cleanly(self):
        scores = compute_category_scores([make_finding(category="seo", severity="low")])
        data = scores_to_dict(scores)
        assert data["seo"]["score"] == 97
        assert data["seo"]["assessed"] is True
        assert data["competitive"]["score"] is None
        assert data["competitive"]["assessed"] is False
