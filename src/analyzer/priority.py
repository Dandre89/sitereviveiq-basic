"""
Priority classes per spec section 6.3:
  Immediate risks         Critical/high-severity issues that can damage
                          security, availability, indexing, trust, or
                          core functionality.
  Quick wins              High-value improvements needing relatively
                          low implementation effort.
  Growth improvements     SEO, content, and conversion work likely to
                          increase business value.
  Strategic renovations   Larger initiatives (info architecture,
                          service-page redevelopment, mobile redesign,
                          broad renovation).

Classification is ordered — first matching rule wins — so every
finding lands in exactly one class.
"""
from .models import Finding

IMMEDIATE_RISK_CATEGORIES = {"technical", "security_trust", "seo"}
GROWTH_CATEGORIES = {"seo", "content", "conversion"}


def classify(finding: Finding) -> str:
    if finding.severity == "critical":
        return "immediate_risk"
    if finding.severity == "high" and finding.category in IMMEDIATE_RISK_CATEGORIES:
        return "immediate_risk"

    if finding.estimated_effort == "Small" and finding.severity in ("high", "medium"):
        return "quick_win"

    if finding.estimated_effort == "Large":
        return "strategic_renovation"

    if finding.category in GROWTH_CATEGORIES:
        return "growth_improvement"

    # Fallback for anything left (e.g. a Medium-effort accessibility/technical
    # finding that isn't a quick win) — treat as a growth improvement rather
    # than leaving it unclassified.
    return "growth_improvement"
