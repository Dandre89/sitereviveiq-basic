"""
Generates a ready-to-use fix for a subset of detection rules, and honest
"here's what to do, but not exact code" guidance for the rest.

SiteRevive IQ audits sites over HTTP — it never has write access to a
client's actual source repo or CMS. So "fix" here never means "we
applied this." It means: the exact snippet to paste, and precisely
where it goes. For rules where the correct fix is unambiguous (a
missing viewport tag, a missing canonical link, a missing robots.txt/
sitemap.xml), that snippet is exact and copy-paste ready. For rules
where the fix needs real judgment or original copy (titles, meta
descriptions, alt text, headings), we return a clearly-labeled starter
template instead of pretending to know the right words — those are
flagged "draft" so nobody mistakes a placeholder for a finished fix.
Everything else falls back to the existing free-text recommendation
with no snippet at all, rather than fabricate one.
"""

CONFIDENCE_EXACT = "exact"
CONFIDENCE_DRAFT = "draft"
CONFIDENCE_NONE = "none"


def _latest_evidence(issue) -> dict:
    occurrence = issue.occurrences.order_by("-created_at").first()
    return occurrence.evidence if occurrence else {}


def _host(issue) -> str:
    return issue.website.normalized_host or issue.website.submitted_url


def _fix_missing_viewport(issue):
    return {
        "snippet": '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "language": "html",
        "instructions": f"Add this inside the <head> element on {issue.affected_scope}.",
        "confidence": CONFIDENCE_EXACT,
    }


def _fix_missing_canonical(issue):
    return {
        "snippet": f'<link rel="canonical" href="{issue.affected_scope}">',
        "language": "html",
        "instructions": f"Add this inside the <head> element on {issue.affected_scope}.",
        "confidence": CONFIDENCE_EXACT,
    }


def _fix_missing_sitemap_or_robots(issue):
    evidence = _latest_evidence(issue)
    missing = evidence.get("missing", [])
    host = _host(issue)
    blocks = []

    if "robots.txt" in missing:
        blocks.append(
            (
                "robots.txt",
                f"User-agent: *\nAllow: /\nSitemap: https://{host}/sitemap.xml",
            )
        )

    if "sitemap.xml" in missing:
        urls = []
        scan = issue.last_seen_scan
        if scan is not None:
            urls = list(
                scan.pages.filter(is_indexable=True, fetch_status="completed")
                .order_by("normalized_url")
                .values_list("normalized_url", flat=True)[:200]
            )
        if not urls:
            urls = [issue.website.canonical_url or issue.website.submitted_url]
        entries = "\n".join(f"  <url><loc>{url}</loc></url>" for url in urls)
        blocks.append(
            (
                "sitemap.xml",
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"{entries}\n"
                "</urlset>",
            )
        )

    snippet = "\n\n".join(f"# {name}\n{content}" for name, content in blocks)
    return {
        "snippet": snippet,
        "language": "text",
        "instructions": f"Upload each file to the root of your domain — e.g. https://{host}/robots.txt.",
        "confidence": CONFIDENCE_EXACT,
    }


def _fix_missing_title(issue):
    return {
        "snippet": f"<title>[Write a concise, page-specific title — 50-60 characters] | {issue.website.name}</title>",
        "language": "html",
        "instructions": f"Replace the bracketed part with real copy, then add this inside <head> on {issue.affected_scope}.",
        "confidence": CONFIDENCE_DRAFT,
    }


def _fix_missing_meta_description(issue):
    return {
        "snippet": '<meta name="description" content="[Write a 150-160 character summary of this page for search results]">',
        "language": "html",
        "instructions": f"Replace the bracketed part with real copy, then add this inside <head> on {issue.affected_scope}.",
        "confidence": CONFIDENCE_DRAFT,
    }


def _fix_missing_h1(issue):
    return {
        "snippet": "<h1>[Write one clear heading describing this page's main topic]</h1>",
        "language": "html",
        "instructions": f"Add exactly one <h1> near the top of the main content on {issue.affected_scope}.",
        "confidence": CONFIDENCE_DRAFT,
    }


def _fix_missing_alt_text(issue):
    evidence = _latest_evidence(issue)
    count = evidence.get("images_without_alt", "some")
    return {
        "snippet": 'alt="[Describe what the image shows — e.g. \'Blue widget on a white background\']"',
        "language": "html",
        "instructions": f"Add a descriptive alt attribute to each of the {count} image(s) missing one on {issue.affected_scope}.",
        "confidence": CONFIDENCE_DRAFT,
    }


FIX_GENERATORS = {
    "missing_viewport": _fix_missing_viewport,
    "missing_canonical": _fix_missing_canonical,
    "missing_sitemap_or_robots": _fix_missing_sitemap_or_robots,
    "missing_title": _fix_missing_title,
    "missing_meta_description": _fix_missing_meta_description,
    "missing_h1": _fix_missing_h1,
    "missing_alt_text": _fix_missing_alt_text,
}


def generate_fix(issue) -> dict:
    """
    Returns {"snippet", "language", "instructions", "confidence"}.
    confidence is "exact" (copy-paste ready), "draft" (real template,
    needs real copy dropped in), or "none" (no rule-specific generator
    yet — falls back to the issue's free-text recommendation).
    """
    generator = FIX_GENERATORS.get(issue.rule_key)
    if generator is None:
        return {
            "snippet": "",
            "language": "",
            "instructions": issue.recommendation,
            "confidence": CONFIDENCE_NONE,
        }
    return generator(issue)
