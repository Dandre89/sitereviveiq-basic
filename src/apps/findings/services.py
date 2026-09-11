"""
Bridges analyzer.engine (no DB imports) to Postgres, the same pattern
apps.scans.services uses for the crawler. Issues are deduped by a
fingerprint of (website, rule_key, affected_scope) so a rule re-firing
on a rescan updates the existing Issue's last_seen/severity instead of
creating a duplicate — this is what makes before/after tracking
possible in a later build.
"""
import hashlib

from django.db import transaction
from django.utils import timezone

from analyzer.engine import analyze
from analyzer.models import Finding, LinkData, PageData, ScanMeta
from analyzer.priority import classify as classify_priority
from analyzer.scoring import compute_category_scores, compute_overall_score, scores_to_dict

from .models import BASIC_ISSUE_CATEGORIES, FindingOccurrence, Issue


def _fingerprint(website_id, rule_key: str, affected_scope: str) -> str:
    raw = f"{website_id}:{rule_key}:{affected_scope}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_page_data(scan) -> tuple[list[PageData], dict]:
    pages = list(scan.pages.all())
    page_data = [
        PageData(
            page_id=str(p.id),
            normalized_url=p.normalized_url,
            fetch_status=p.fetch_status,
            http_status_code=p.http_status_code,
            page_title=p.page_title,
            meta_description=p.meta_description,
            canonical_url=p.canonical_url,
            h1_count=p.h1_count,
            h2_count=p.h2_count,
            word_count=p.word_count,
            image_count=p.image_count,
            images_without_alt_count=p.images_without_alt_count,
            has_viewport=p.has_viewport,
            has_mixed_content=p.has_mixed_content,
            is_indexable=p.is_indexable,
            has_phone_link=p.has_phone_link,
            has_contact_form=p.has_contact_form,
            has_cta_link=p.has_cta_link,
            response_time_ms=p.response_time_ms,
            redirect_count=p.redirect_count,
        )
        for p in pages
    ]
    pages_by_normalized_url = {p.normalized_url: p for p in pages}
    return page_data, pages_by_normalized_url


def _build_link_data(scan, pages_by_normalized_url: dict) -> list[LinkData]:
    links = scan.links.select_related("source_page", "destination_page").all()
    link_data = []
    for link in links:
        destination_status = None
        if link.destination_page_id:
            destination_status = link.destination_page.fetch_status
        elif link.normalized_destination_url in pages_by_normalized_url:
            destination_status = pages_by_normalized_url[link.normalized_destination_url].fetch_status

        link_data.append(
            LinkData(
                source_page_id=str(link.source_page_id),
                source_normalized_url=link.source_page.normalized_url,
                destination_url=link.destination_url,
                normalized_destination_url=link.normalized_destination_url,
                link_type=link.link_type,
                anchor_text=link.anchor_text,
                destination_fetch_status=destination_status,
            )
        )
    return link_data


# This tier's issue detection is narrowed to "baseline site health" —
# same four categories BASIC_ISSUE_CATEGORIES uses for the UI filters.
# Filtering happens here, before findings ever become Issue rows or feed
# the score, so a category that's hidden from the UI can't still
# silently affect the visible overall_score (see analyzer.scoring for
# the matching CATEGORY_WEIGHTS change).
ALLOWED_ISSUE_CATEGORIES = {value for value, _label in BASIC_ISSUE_CATEGORIES}


def analyze_scan(scan) -> int:
    """
    Runs the deterministic analyzer against a completed scan's pages and
    links, and upserts Issue/FindingOccurrence rows. Returns the number
    of findings produced. Safe to call multiple times for the same scan
    (re-running just creates fresh FindingOccurrence rows, though in
    practice this runs once per scan from apps.scans.services).
    """
    page_data, pages_by_normalized_url = _build_page_data(scan)
    link_data = _build_link_data(scan, pages_by_normalized_url)
    meta = ScanMeta(
        website_name=scan.website.name,
        robots_txt_found=bool(scan.summary_data.get("robots_txt_found")),
        sitemap_found=bool(scan.summary_data.get("sitemap_found")),
    )

    findings: list[Finding] = [
        f for f in analyze(page_data, link_data, meta) if f.category in ALLOWED_ISSUE_CATEGORIES
    ]

    page_id_map = {str(p.id): p for p in scan.pages.all()}
    seen_fingerprints = set()

    with transaction.atomic():
        for finding in findings:
            fingerprint = _fingerprint(scan.website_id, finding.rule_key, finding.affected_scope)
            seen_fingerprints.add(fingerprint)
            priority_class = classify_priority(finding)
            issue, created = Issue.objects.get_or_create(
                website_id=scan.website_id,
                fingerprint=fingerprint,
                defaults={
                    "workspace": scan.workspace,
                    "rule_key": finding.rule_key,
                    "title": finding.title,
                    "category": finding.category,
                    "current_severity": finding.severity,
                    "business_impact": finding.business_impact,
                    "affected_scope": finding.affected_scope,
                    "recommendation": finding.recommendation,
                    "estimated_effort": finding.estimated_effort,
                    "priority_class": priority_class,
                    "first_seen_scan": scan,
                    "last_seen_scan": scan,
                },
            )
            if not created:
                issue.current_severity = finding.severity
                issue.title = finding.title
                issue.recommendation = finding.recommendation
                issue.priority_class = priority_class
                issue.last_seen_scan = scan
                issue.last_seen_at = timezone.now()
                if issue.status == Issue.Status.RESOLVED:
                    # A resolved issue re-appearing is a regression — reopen it.
                    issue.status = Issue.Status.OPEN
                    issue.resolved_at = None
                issue.save()

            FindingOccurrence.objects.create(
                issue=issue,
                scan=scan,
                page=page_id_map.get(finding.page_id) if finding.page_id else None,
                severity=finding.severity,
                evidence=finding.evidence,
            )

        # A previously-active issue that didn't fire this run is fixed —
        # auto-resolve it. Issues someone deliberately marked Ignored are
        # left alone (that was an intentional call, not a bug to track),
        # and already-Resolved issues are handled by the reopen branch
        # above if they resurface.
        active_statuses = [
            Issue.Status.OPEN,
            Issue.Status.ACCEPTED,
            Issue.Status.PLANNED,
            Issue.Status.IN_PROGRESS,
        ]
        Issue.objects.filter(
            website_id=scan.website_id, status__in=active_statuses
        ).exclude(fingerprint__in=seen_fingerprints).update(
            status=Issue.Status.RESOLVED, resolved_at=timezone.now()
        )

        category_scores = compute_category_scores(findings)
        scan.category_scores = scores_to_dict(category_scores)
        scan.overall_score = compute_overall_score(category_scores)
        scan.save(update_fields=["category_scores", "overall_score"])

    return len(findings)
