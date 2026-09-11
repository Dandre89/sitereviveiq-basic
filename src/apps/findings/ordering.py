"""
Shared DB-level ordering for Issue priority/severity, used anywhere an
issue table needs to sort by these (the cross-website inbox and each
website's own Open issues table). Case/When so a real column sort
("click Priority to sort") works instead of the old Python-side list.sort.
"""
from django.db.models import Case, IntegerField, Value, When

from .models import Issue

PRIORITY_RANK = Case(
    When(priority_class=Issue.PriorityClass.IMMEDIATE_RISK, then=Value(0)),
    When(priority_class=Issue.PriorityClass.QUICK_WIN, then=Value(1)),
    When(priority_class=Issue.PriorityClass.GROWTH_IMPROVEMENT, then=Value(2)),
    When(priority_class=Issue.PriorityClass.STRATEGIC_RENOVATION, then=Value(3)),
    default=Value(4),
    output_field=IntegerField(),
)
SEVERITY_RANK = Case(
    When(current_severity=Issue.Severity.CRITICAL, then=Value(0)),
    When(current_severity=Issue.Severity.HIGH, then=Value(1)),
    When(current_severity=Issue.Severity.MEDIUM, then=Value(2)),
    When(current_severity=Issue.Severity.LOW, then=Value(3)),
    default=Value(4),
    output_field=IntegerField(),
)
