from analyzer.models import Finding
from analyzer.priority import classify


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


class TestImmediateRisk:
    def test_critical_severity_always_immediate_risk(self):
        finding = make_finding(severity="critical", category="content")
        assert classify(finding) == "immediate_risk"

    def test_high_severity_technical_is_immediate_risk(self):
        finding = make_finding(severity="high", category="technical", estimated_effort="Medium")
        assert classify(finding) == "immediate_risk"

    def test_high_severity_security_is_immediate_risk(self):
        finding = make_finding(severity="high", category="security_trust", estimated_effort="Medium")
        assert classify(finding) == "immediate_risk"

    def test_high_severity_content_is_not_immediate_risk(self):
        # High severity but content isn't in the immediate-risk category set,
        # and it's Small effort -> should fall to quick_win instead.
        finding = make_finding(severity="high", category="content", estimated_effort="Small")
        assert classify(finding) != "immediate_risk"


class TestQuickWin:
    def test_immediate_risk_takes_priority_over_quick_win(self):
        # SEO + high severity + Small effort matches both immediate_risk and
        # quick_win criteria — immediate_risk must win since it's checked first.
        finding = make_finding(severity="high", category="seo", estimated_effort="Small")
        assert classify(finding) == "immediate_risk"

    def test_small_effort_medium_severity_accessibility_is_quick_win(self):
        finding = make_finding(severity="medium", category="accessibility", estimated_effort="Small")
        assert classify(finding) == "quick_win"

    def test_small_effort_low_severity_is_not_quick_win(self):
        finding = make_finding(severity="low", category="accessibility", estimated_effort="Small")
        assert classify(finding) != "quick_win"


class TestGrowthImprovement:
    def test_medium_severity_seo_medium_effort_is_growth(self):
        finding = make_finding(severity="medium", category="seo", estimated_effort="Medium")
        assert classify(finding) == "growth_improvement"

    def test_low_severity_content_is_growth(self):
        finding = make_finding(severity="low", category="content", estimated_effort="Medium")
        assert classify(finding) == "growth_improvement"


class TestStrategicRenovation:
    def test_large_effort_is_strategic_renovation(self):
        finding = make_finding(severity="medium", category="technical", estimated_effort="Large")
        assert classify(finding) == "strategic_renovation"

    def test_large_effort_overrides_growth_category(self):
        finding = make_finding(severity="low", category="seo", estimated_effort="Large")
        assert classify(finding) == "strategic_renovation"


class TestEveryFindingGetsExactlyOneClass:
    def test_classification_is_always_one_of_the_four_valid_classes(self):
        valid = {"immediate_risk", "quick_win", "growth_improvement", "strategic_renovation"}
        severities = ["critical", "high", "medium", "low"]
        categories = ["technical", "seo", "content", "accessibility", "security_trust"]
        efforts = ["Small", "Medium", "Large"]

        for severity in severities:
            for category in categories:
                for effort in efforts:
                    finding = make_finding(severity=severity, category=category, estimated_effort=effort)
                    assert classify(finding) in valid
