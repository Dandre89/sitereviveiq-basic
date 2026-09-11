"""
Bridges scanner.crawler (no DB imports) to Postgres. Every page is
persisted as soon as it completes — per section 11.1 stage 8 — so a
mid-scan failure still leaves useful partial data.
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.websites.models import Website
from scanner.crawler import CrawlSummary, PageResult, ScanConfig, run_crawl
from scanner.normalizer import normalize_url

from .models import PageLink, Scan, ScanEvent, ScanPage


class DuplicateActiveScanError(Exception):
    pass


def start_scan(website: Website, requested_by, trigger: str = Scan.Trigger.MANUAL) -> Scan:
    """
    Creates a queued Scan row. Must be called inside the view/task
    boundary that then hands the scan ID to Celery — this function does
    not touch the network.
    """
    if website.has_active_scan():
        raise DuplicateActiveScanError(
            f"Website {website.id} already has an active scan"
        )

    return Scan.objects.create(
        workspace=website.workspace,
        website=website,
        status=Scan.Status.QUEUED,
        trigger=trigger,
        max_pages=website.max_pages,
        max_depth=website.max_depth,
        requested_by=requested_by,
    )


def _log_event(scan: Scan, level: str, event_type: str, message: str, data: dict | None = None):
    ScanEvent.objects.create(
        scan=scan, level=level, event_type=event_type, message=message, event_data=data or {}
    )


def execute_scan(scan_id) -> None:
    """
    The Celery task body. Runs entirely inside a worker — never inside a
    web request, per section 8.2. Persists pages immediately as they
    complete via on_page_result, so a crash mid-crawl leaves partial data
    rather than nothing.
    """
    try:
        scan = Scan.objects.select_related("website").get(id=scan_id)
    except Scan.DoesNotExist:
        return

    if scan.website.status == "archived":
        scan.status = Scan.Status.FAILED
        scan.failure_code = "website_archived"
        scan.failure_message = "Website was archived before the scan started."
        scan.save(update_fields=["status", "failure_code", "failure_message"])
        return

    scan.status = Scan.Status.VALIDATING
    scan.started_at = timezone.now()
    scan.root_url = scan.website.submitted_url
    scan.save(update_fields=["status", "started_at", "root_url"])
    _log_event(scan, ScanEvent.Level.INFO, "scan_started", "Scan started")

    page_seq = {"count": 0}

    def on_page_result(result: PageResult) -> None:
        page_seq["count"] += 1
        with transaction.atomic():
            page = ScanPage.objects.create(
                workspace=scan.workspace,
                scan=scan,
                website=scan.website,
                requested_url=result.requested_url,
                normalized_url=result.normalized_url,
                final_url=result.requested_url,
                parent_url=result.parent_url,
                crawl_depth=result.depth,
                fetch_status=result.fetch_status,
                http_status_code=result.http_status_code,
                content_type=result.content_type,
                response_time_ms=result.response_time_ms,
                response_size_bytes=result.response_size_bytes,
                redirect_count=len(result.redirect_chain),
                redirect_chain=result.redirect_chain,
                error_code=result.error_code,
                error_message=result.error_message,
                fetched_at=timezone.now(),
            )
            if result.parsed:
                parsed = result.parsed
                page.page_title = parsed.title
                page.meta_description = parsed.meta_description
                page.canonical_url = parsed.canonical_url
                page.robots_directives = parsed.robots_directives
                page.h1_count = parsed.h1_count
                page.h2_count = parsed.h2_count
                page.word_count = parsed.word_count
                page.image_count = parsed.image_count
                page.images_without_alt_count = parsed.images_without_alt_count
                page.has_viewport = parsed.has_viewport
                page.has_mixed_content = parsed.has_mixed_content
                page.is_indexable = parsed.is_indexable
                page.has_phone_link = parsed.has_phone_link
                page.has_contact_form = parsed.has_contact_form
                page.has_cta_link = parsed.has_cta_link
                page.html_hash = parsed.html_hash
                page.text_hash = parsed.text_hash
                page.save()

                for link in parsed.links:
                    PageLink.objects.create(
                        scan=scan,
                        source_page=page,
                        destination_url=link.destination_url,
                        normalized_destination_url=normalize_url(
                            link.destination_url, base_url=result.requested_url
                        ) or "",
                        link_type=link.link_type,
                        anchor_text=link.anchor_text,
                        rel_value=link.rel_value,
                        is_nofollow=link.is_nofollow,
                    )

            scan.pages_attempted = page_seq["count"]
            if result.fetch_status == "completed":
                scan.pages_completed += 1
            elif result.fetch_status == "failed":
                scan.pages_failed += 1
            scan.save(update_fields=["pages_attempted", "pages_completed", "pages_failed"])

    def on_event(level: str, event_type: str, data: dict) -> None:
        _log_event(scan, level, event_type, event_type.replace("_", " "), data)

    scan.status = Scan.Status.CRAWLING
    scan.save(update_fields=["status"])

    config = ScanConfig(
        root_url=scan.website.submitted_url,
        max_pages=scan.max_pages,
        max_depth=scan.max_depth,
        max_scan_seconds=settings.SCANNER_MAX_SCAN_SECONDS,
        user_agent=settings.SCANNER_USER_AGENT,
    )

    try:
        summary: CrawlSummary = run_crawl(config, on_page_result, on_event)
    except Exception as exc:  # noqa: BLE001 — must never crash the worker
        scan.status = Scan.Status.FAILED
        scan.failure_code = "crawler_exception"
        scan.failure_message = str(exc)[:2000]
        scan.completed_at = timezone.now()
        scan.save(update_fields=["status", "failure_code", "failure_message", "completed_at"])
        _log_event(scan, ScanEvent.Level.ERROR, "scan_failed", str(exc)[:2000])
        return

    scan.pages_discovered = summary.pages_discovered
    scan.summary_data = {
        "ended_reason": summary.ended_reason,
        "robots_txt_found": summary.robots_txt_found,
        "sitemap_found": summary.sitemap_found,
    }
    scan.save(update_fields=["pages_discovered", "summary_data"])

    _resolve_internal_link_destinations(scan)

    scan.status = Scan.Status.ANALYZING
    scan.save(update_fields=["status"])
    _log_event(scan, ScanEvent.Level.INFO, "analysis_started", "Deterministic analysis started")

    try:
        from apps.findings.services import analyze_scan

        analyze_scan(scan)
    except Exception as exc:  # noqa: BLE001 — analysis failures shouldn't lose crawl data
        _log_event(scan, ScanEvent.Level.ERROR, "analysis_failed", str(exc)[:2000])

    scan.status = (
        Scan.Status.COMPLETED if summary.pages_failed == 0 else Scan.Status.COMPLETED_WITH_ERRORS
    )
    scan.completed_at = timezone.now()
    scan.save(update_fields=["status", "completed_at"])

    scan.website.last_scan = scan
    scan.website.save(update_fields=["last_scan"])

    _log_event(
        scan,
        ScanEvent.Level.INFO,
        "scan_completed",
        f"Scan completed: {summary.pages_completed} pages, {summary.pages_failed} failed",
        {"ended_reason": summary.ended_reason},
    )

    try:
        from apps.monitoring.notifications import (
            notify_critical_findings,
            notify_from_previous_scan,
            notify_scan_completed,
        )

        recipient = scan.requested_by
        notify_scan_completed(scan, recipient=recipient)
        notify_critical_findings(scan, recipient=recipient)
        # No pinned Baseline in this build (Pro+ only) — compare against
        # whichever scan ran immediately before this one instead.
        notify_from_previous_scan(scan, recipient=recipient)
    except Exception as exc:  # noqa: BLE001 — notifications must never break the scan pipeline
        _log_event(scan, ScanEvent.Level.ERROR, "notification_failed", str(exc)[:2000])


def _resolve_internal_link_destinations(scan: Scan) -> None:
    """
    PageLink rows are created as pages are fetched, before every page in
    the scan necessarily exists yet — so destination_page can't always be
    set at creation time. This one pass, after the crawl finishes,
    matches internal links to the ScanPage they point at (used by the
    broken-internal-link rule in apps.findings).
    """
    pages_by_url = {p.normalized_url: p for p in scan.pages.all()}
    unresolved = scan.links.filter(
        link_type=PageLink.LinkType.INTERNAL, destination_page__isnull=True
    ).exclude(normalized_destination_url="")

    to_update = []
    for link in unresolved:
        target = pages_by_url.get(link.normalized_destination_url)
        if target:
            link.destination_page = target
            to_update.append(link)
    if to_update:
        PageLink.objects.bulk_update(to_update, ["destination_page"])
