"""
Deterministic technical and SEO checks, per the spec's Scanner Version
0.2 scope:
  broken internal links, redirect chains, mixed content, slow responses,
  missing sitemap/robots.txt, canonical/indexability issues, viewport,
  titles and meta descriptions, heading structure, missing alt text,
  thin content.

Deferred (need data Build 1's crawler doesn't fetch yet — see README):
  oversized images (needs actual image byte sizes), full resource-level
  mixed-content auditing beyond the same-page check already captured.

Each rule is a pure function: (pages, links, meta) -> list[Finding].
No Django imports here, same boundary as the scanner package.
"""
from collections import Counter

from .models import Finding, LinkData, PageData, ScanMeta

# Only rules against pages that actually rendered content are meaningful.
CONTENT_STATUS_CODES = {200}


def _content_pages(pages: list[PageData]) -> list[PageData]:
    return [
        p for p in pages
        if p.fetch_status == "completed" and p.http_status_code in CONTENT_STATUS_CODES
    ]


def rule_broken_internal_links(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for link in links:
        if link.link_type != "internal":
            continue
        if link.destination_fetch_status == "failed" or link.destination_fetch_status is None:
            findings.append(
                Finding(
                    rule_key="broken_internal_link",
                    title="Broken internal link",
                    category="technical",
                    severity="high",
                    business_impact="user_experience",
                    affected_scope=link.source_normalized_url,
                    evidence={
                        "destination_url": link.destination_url,
                        "anchor_text": link.anchor_text,
                        "destination_status": link.destination_fetch_status or "not_crawled",
                    },
                    recommendation=(
                        f"Fix or remove the link to {link.destination_url} on "
                        f"{link.source_normalized_url}."
                    ),
                    estimated_effort="Small",
                    page_id=link.source_page_id,
                )
            )
    return findings


def rule_redirect_chains(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for page in pages:
        if page.redirect_count >= 4:
            severity = "high"
        elif page.redirect_count >= 2:
            severity = "medium"
        else:
            continue
        findings.append(
            Finding(
                rule_key="redirect_chain",
                title="Multi-hop redirect chain",
                category="technical",
                severity=severity,
                business_impact="performance",
                affected_scope=page.normalized_url,
                evidence={"redirect_count": page.redirect_count},
                recommendation="Point the link/reference directly at the final URL to remove hops.",
                estimated_effort="Small",
                page_id=page.page_id,
            )
        )
    return findings


def rule_mixed_content(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for page in _content_pages(pages):
        if page.has_mixed_content:
            findings.append(
                Finding(
                    rule_key="mixed_content",
                    title="Mixed content on an HTTPS page",
                    category="security_trust",
                    severity="medium",
                    business_impact="security",
                    affected_scope=page.normalized_url,
                    evidence={"note": "Page loads at least one resource over plain HTTP."},
                    recommendation="Serve all page resources (images, scripts, styles) over HTTPS.",
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )
    return findings


def rule_slow_responses(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for page in _content_pages(pages):
        if page.response_time_ms is None:
            continue
        if page.response_time_ms >= 3000:
            severity = "high"
        elif page.response_time_ms >= 1500:
            severity = "medium"
        else:
            continue
        findings.append(
            Finding(
                rule_key="slow_response",
                title="Slow server response time",
                category="technical",
                severity=severity,
                business_impact="performance",
                affected_scope=page.normalized_url,
                evidence={"response_time_ms": page.response_time_ms},
                recommendation="Investigate server/hosting performance for this page.",
                estimated_effort="Medium",
                page_id=page.page_id,
            )
        )
    return findings


def rule_missing_sitemap_or_robots(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    if meta.robots_txt_found and meta.sitemap_found:
        return []
    missing = []
    if not meta.robots_txt_found:
        missing.append("robots.txt")
    if not meta.sitemap_found:
        missing.append("XML sitemap")
    severity = "medium" if len(missing) == 2 else "low"
    return [
        Finding(
            rule_key="missing_sitemap_or_robots",
            title=f"Missing {' and '.join(missing)}",
            category="seo",
            severity=severity,
            business_impact="search_visibility",
            affected_scope="site-wide",
            evidence={"missing": missing},
            recommendation=f"Add a {' and '.join(missing)} at the site root.",
            estimated_effort="Small",
        )
    ]


def rule_indexability(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for page in _content_pages(pages):
        if not page.is_indexable:
            findings.append(
                Finding(
                    rule_key="page_not_indexable",
                    title="Page is blocked from indexing (noindex)",
                    category="seo",
                    severity="high",
                    business_impact="search_visibility",
                    affected_scope=page.normalized_url,
                    evidence={"note": "robots meta tag includes noindex"},
                    recommendation="Confirm this is intentional; remove noindex if the page should rank.",
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )
        elif not page.canonical_url:
            findings.append(
                Finding(
                    rule_key="missing_canonical",
                    title="Missing canonical tag",
                    category="seo",
                    severity="low",
                    business_impact="search_visibility",
                    affected_scope=page.normalized_url,
                    evidence={},
                    recommendation="Add a self-referencing canonical tag to this page.",
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )
    return findings


def rule_viewport(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for page in _content_pages(pages):
        if not page.has_viewport:
            findings.append(
                Finding(
                    rule_key="missing_viewport",
                    title="Missing mobile viewport tag",
                    category="technical",
                    severity="high",
                    business_impact="user_experience",
                    affected_scope=page.normalized_url,
                    evidence={},
                    recommendation='Add <meta name="viewport" content="width=device-width, initial-scale=1">.',
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )
    return findings


def rule_titles_and_meta_descriptions(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    content_pages = _content_pages(pages)

    for page in content_pages:
        if not page.page_title.strip():
            findings.append(
                Finding(
                    rule_key="missing_title",
                    title="Missing page title",
                    category="seo",
                    severity="high",
                    business_impact="search_visibility",
                    affected_scope=page.normalized_url,
                    evidence={},
                    recommendation="Add a unique, descriptive <title> tag.",
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )
        elif len(page.page_title) > 60:
            findings.append(
                Finding(
                    rule_key="title_too_long",
                    title="Page title likely to be truncated in search results",
                    category="seo",
                    severity="low",
                    business_impact="search_visibility",
                    affected_scope=page.normalized_url,
                    evidence={"length": len(page.page_title)},
                    recommendation="Shorten the title to roughly 50-60 characters.",
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )

        if not page.meta_description.strip():
            findings.append(
                Finding(
                    rule_key="missing_meta_description",
                    title="Missing meta description",
                    category="seo",
                    severity="medium",
                    business_impact="search_visibility",
                    affected_scope=page.normalized_url,
                    evidence={},
                    recommendation="Add a unique meta description summarizing the page (~150-160 characters).",
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )

    # Duplicate titles across pages — a site-wide pattern, one finding per
    # duplicated title rather than one per affected page.
    title_counts = Counter(p.page_title.strip() for p in content_pages if p.page_title.strip())
    for title, count in title_counts.items():
        if count > 1:
            affected_urls = [p.normalized_url for p in content_pages if p.page_title.strip() == title]
            findings.append(
                Finding(
                    rule_key="duplicate_title",
                    title=f'Duplicate title used on {count} pages: "{title[:80]}"',
                    category="seo",
                    severity="medium",
                    business_impact="search_visibility",
                    affected_scope="site-wide",
                    evidence={"title": title, "affected_urls": affected_urls},
                    recommendation="Give each page a unique, descriptive title.",
                    estimated_effort="Medium",
                )
            )

    return findings


def rule_heading_structure(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for page in _content_pages(pages):
        if page.h1_count == 0:
            findings.append(
                Finding(
                    rule_key="missing_h1",
                    title="Missing H1 heading",
                    category="seo",
                    severity="high",
                    business_impact="search_visibility",
                    affected_scope=page.normalized_url,
                    evidence={},
                    recommendation="Add a single, descriptive H1 to the page.",
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )
        elif page.h1_count > 1:
            findings.append(
                Finding(
                    rule_key="multiple_h1",
                    title=f"Multiple H1 headings ({page.h1_count})",
                    category="seo",
                    severity="low",
                    business_impact="search_visibility",
                    affected_scope=page.normalized_url,
                    evidence={"h1_count": page.h1_count},
                    recommendation="Use a single H1 per page; demote the rest to H2/H3.",
                    estimated_effort="Small",
                    page_id=page.page_id,
                )
            )
    return findings


def rule_missing_alt_text(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for page in _content_pages(pages):
        if page.images_without_alt_count == 0:
            continue
        severity = "medium" if page.images_without_alt_count > 2 else "low"
        findings.append(
            Finding(
                rule_key="missing_alt_text",
                title=f"{page.images_without_alt_count} image(s) missing alt text",
                category="accessibility",
                severity=severity,
                business_impact="accessibility",
                affected_scope=page.normalized_url,
                evidence={
                    "images_without_alt": page.images_without_alt_count,
                    "total_images": page.image_count,
                },
                recommendation="Add descriptive alt text to every meaningful image.",
                estimated_effort="Small",
                page_id=page.page_id,
            )
        )
    return findings


def rule_thin_content(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    findings = []
    for page in _content_pages(pages):
        if not page.is_indexable:
            continue  # noindex pages aren't competing for rankings
        if page.word_count < 100:
            severity = "high"
        elif page.word_count < 300:
            severity = "medium"
        else:
            continue
        findings.append(
            Finding(
                rule_key="thin_content",
                title="Thin page content",
                category="content",
                severity=severity,
                business_impact="search_visibility",
                affected_scope=page.normalized_url,
                evidence={"word_count": page.word_count},
                recommendation="Expand this page's content, or consolidate it with a related page.",
                estimated_effort="Medium",
                page_id=page.page_id,
            )
        )
    return findings


def rule_missing_conversion_path(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    """
    Build 7's "improved conversion heuristics": does a page give a
    visitor an obvious way to take action — a phone link, a contact
    form, or a keyword-matched call-to-action link? A page with none of
    these is a missed conversion opportunity, not a technical defect,
    which is why this lives in the "conversion" category rather than
    "technical" or "seo".
    """
    findings = []
    for page in _content_pages(pages):
        if page.has_phone_link or page.has_contact_form or page.has_cta_link:
            continue
        findings.append(
            Finding(
                rule_key="missing_conversion_path",
                title="No clear call-to-action on this page",
                category="conversion",
                severity="low",
                business_impact="conversion",
                affected_scope=page.normalized_url,
                evidence={},
                recommendation=(
                    "Add a clear next step — a phone link, contact form, or "
                    "call-to-action button — so visitors know what to do next."
                ),
                estimated_effort="Small",
                page_id=page.page_id,
            )
        )
    return findings


def rule_site_missing_contact_info(
    pages: list[PageData], links: list[LinkData], meta: ScanMeta
) -> list[Finding]:
    """Site-wide: if NO page anywhere has a phone link or contact form, that's
    a bigger problem than any one page's missing CTA — flagged separately
    and at higher severity."""
    content_pages = _content_pages(pages)
    if not content_pages:
        return []
    has_any_contact_path = any(p.has_phone_link or p.has_contact_form for p in content_pages)
    if has_any_contact_path:
        return []
    return [
        Finding(
            rule_key="site_missing_contact_info",
            title="No phone link or contact form found anywhere on the site",
            category="conversion",
            severity="medium",
            business_impact="conversion",
            affected_scope="site-wide",
            evidence={},
            recommendation="Add a phone link (tel:) and/or a contact form so visitors can reach you directly.",
            estimated_effort="Small",
        )
    ]


ALL_RULES = [
    rule_broken_internal_links,
    rule_redirect_chains,
    rule_mixed_content,
    rule_slow_responses,
    rule_missing_sitemap_or_robots,
    rule_indexability,
    rule_viewport,
    rule_titles_and_meta_descriptions,
    rule_heading_structure,
    rule_missing_alt_text,
    rule_thin_content,
    rule_missing_conversion_path,
    rule_site_missing_contact_info,
]
