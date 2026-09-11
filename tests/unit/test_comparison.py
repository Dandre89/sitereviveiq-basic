from analyzer.comparison import IssueSnapshot, compare


def snap(issue_id, severity="high", first_appearance=False):
    return IssueSnapshot(issue_id=issue_id, severity=severity, is_first_appearance=first_appearance)


class TestNewIssues:
    def test_first_appearance_in_later_scan_is_new(self):
        result = compare([], [snap("1", first_appearance=True)])
        assert result.new_issue_ids == ["1"]
        assert result.returned_issue_ids == []

    def test_not_first_appearance_but_absent_from_baseline_is_returned(self):
        # The issue existed before the baseline, was fixed, and is back —
        # that's "returned", not "new".
        result = compare([], [snap("1", first_appearance=False)])
        assert result.returned_issue_ids == ["1"]
        assert result.new_issue_ids == []


class TestResolvedIssues:
    def test_present_in_baseline_absent_in_later_is_resolved(self):
        result = compare([snap("1")], [])
        assert result.resolved_issue_ids == ["1"]


class TestWorsenedAndImproved:
    def test_severity_increase_is_worsened(self):
        result = compare(
            [snap("1", severity="low")],
            [snap("1", severity="high")],
        )
        assert result.worsened_issue_ids == ["1"]
        assert result.improved_issue_ids == []

    def test_severity_decrease_is_improved(self):
        result = compare(
            [snap("1", severity="critical")],
            [snap("1", severity="medium")],
        )
        assert result.improved_issue_ids == ["1"]
        assert result.worsened_issue_ids == []

    def test_unchanged_severity_is_unchanged(self):
        result = compare(
            [snap("1", severity="medium")],
            [snap("1", severity="medium")],
        )
        assert result.unchanged_issue_ids == ["1"]
        assert result.worsened_issue_ids == []
        assert result.improved_issue_ids == []


class TestRealisticMixedScenario:
    def test_full_set_of_states_in_one_comparison(self):
        baseline = [
            snap("resolved-1", severity="high"),
            snap("worsened-1", severity="low"),
            snap("improved-1", severity="critical"),
            snap("unchanged-1", severity="medium"),
        ]
        later = [
            snap("new-1", severity="high", first_appearance=True),
            snap("returned-1", severity="medium", first_appearance=False),
            snap("worsened-1", severity="high"),
            snap("improved-1", severity="low"),
            snap("unchanged-1", severity="medium"),
        ]

        result = compare(baseline, later)

        assert result.new_issue_ids == ["new-1"]
        assert result.returned_issue_ids == ["returned-1"]
        assert result.resolved_issue_ids == ["resolved-1"]
        assert result.worsened_issue_ids == ["worsened-1"]
        assert result.improved_issue_ids == ["improved-1"]
        assert result.unchanged_issue_ids == ["unchanged-1"]


class TestEmptyInputs:
    def test_both_empty_yields_empty_result(self):
        result = compare([], [])
        assert result.new_issue_ids == []
        assert result.resolved_issue_ids == []
        assert result.returned_issue_ids == []
        assert result.worsened_issue_ids == []
        assert result.improved_issue_ids == []
        assert result.unchanged_issue_ids == []

    def test_identical_snapshots_yield_all_unchanged(self):
        issues = [snap("1"), snap("2", severity="critical")]
        result = compare(issues, issues)
        assert set(result.unchanged_issue_ids) == {"1", "2"}
