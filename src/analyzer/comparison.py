"""
Scan-to-scan comparison logic, per spec section 8.8: detect new,
resolved, worsened, improved, and returned issues between a baseline
scan and a later scan. No Django imports — same boundary as scanner/
and the rest of analyzer/, so this can be unit tested without a
database and reused wherever comparisons run.

Definitions (matching the spec's five states):
  new        — present in the later scan, and this is the issue's very
               first-ever appearance (Issue.first_seen_scan == later scan).
  returned   — present in the later scan, absent from the baseline, but
               it existed before the baseline (a previously-fixed issue
               that came back — different from genuinely new).
  resolved   — present in the baseline, absent from the later scan.
  worsened   — present in both, severity got worse.
  improved   — present in both, severity got better.
  unchanged  — present in both, same severity (tracked for completeness,
               not one of the spec's five headline states).
"""
from dataclasses import dataclass, field

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class IssueSnapshot:
    """One issue's state as observed in a specific scan."""
    issue_id: str
    severity: str
    is_first_appearance: bool  # True if THIS scan is where the issue was first ever detected


@dataclass
class ComparisonResult:
    new_issue_ids: list[str] = field(default_factory=list)
    resolved_issue_ids: list[str] = field(default_factory=list)
    returned_issue_ids: list[str] = field(default_factory=list)
    worsened_issue_ids: list[str] = field(default_factory=list)
    improved_issue_ids: list[str] = field(default_factory=list)
    unchanged_issue_ids: list[str] = field(default_factory=list)


def compare(
    baseline_issues: list[IssueSnapshot], later_issues: list[IssueSnapshot]
) -> ComparisonResult:
    baseline_by_id = {s.issue_id: s for s in baseline_issues}
    later_by_id = {s.issue_id: s for s in later_issues}

    result = ComparisonResult()

    for issue_id, snapshot in later_by_id.items():
        if issue_id not in baseline_by_id:
            if snapshot.is_first_appearance:
                result.new_issue_ids.append(issue_id)
            else:
                result.returned_issue_ids.append(issue_id)
            continue

        baseline_rank = SEVERITY_RANK.get(baseline_by_id[issue_id].severity, 0)
        later_rank = SEVERITY_RANK.get(snapshot.severity, 0)
        if later_rank > baseline_rank:
            result.worsened_issue_ids.append(issue_id)
        elif later_rank < baseline_rank:
            result.improved_issue_ids.append(issue_id)
        else:
            result.unchanged_issue_ids.append(issue_id)

    for issue_id in baseline_by_id:
        if issue_id not in later_by_id:
            result.resolved_issue_ids.append(issue_id)

    return result
