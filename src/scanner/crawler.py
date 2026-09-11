"""
Breadth-first crawl orchestration. Deliberately has no Django or database
imports — per the repo layout note in Appendix C, this package accepts a
scan configuration and reports results through callbacks. apps.scans
supplies the callbacks that persist to Postgres.

Discovery priority (section 11.2): root page, robots.txt-declared
sitemaps, /sitemap.xml, then breadth-first internal links — so
high-value pages near the homepage are captured before the page limit
is spent on deep/obscure URLs.
"""
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx

from .fetcher import FetchError, fetch_page
from .normalizer import is_same_registrable_host, normalize_url
from .parser import ParsedPage, parse_page
from .security import UnsafeDestinationError, validate_url


@dataclass
class ScanConfig:
    root_url: str
    max_pages: int
    max_depth: int
    max_scan_seconds: int
    user_agent: str


@dataclass
class PageResult:
    requested_url: str
    normalized_url: str
    parent_url: str
    depth: int
    fetch_status: str  # completed | failed | skipped
    http_status_code: int | None = None
    content_type: str = ""
    response_time_ms: int | None = None
    response_size_bytes: int | None = None
    redirect_chain: list[str] = field(default_factory=list)
    parsed: ParsedPage | None = None
    error_code: str = ""
    error_message: str = ""


@dataclass
class CrawlSummary:
    root_url: str
    pages_discovered: int
    pages_attempted: int
    pages_completed: int
    pages_failed: int
    ended_reason: str  # "exhausted_queue" | "page_limit" | "time_limit"
    robots_txt_found: bool = False
    sitemap_found: bool = False


def _fetch_sitemap_page_urls(
    sitemap_url: str, user_agent: str, limit: int, remaining_depth: int = 2
) -> list[str]:
    """
    Fetches one sitemap document and returns the actual page URLs it
    contains. Handles both kinds of sitemap XML:
      - <urlset>: a normal sitemap — every <loc> is a real page.
      - <sitemapindex>: a sitemap OF sitemaps (very common on WordPress
        via Yoast — e.g. sitemap_index.xml listing category-sitemap.xml,
        page-sitemap.xml, post-sitemap.xml). Every <loc> here is another
        sitemap to fetch, NOT a page — treating them as pages was the
        original bug (they'd get queued and fail as "not HTML").
    remaining_depth guards against a pathological index-of-index loop;
    two levels covers every real-world case seen in practice.
    """
    if remaining_depth <= 0:
        return []
    try:
        resp = httpx.get(sitemap_url, timeout=10, headers={"User-Agent": user_agent})
        if resp.status_code != 200:
            return []
        root = ElementTree.fromstring(resp.content)
    except (httpx.HTTPError, UnsafeDestinationError, ElementTree.ParseError):
        return []

    root_tag = root.tag.rsplit("}", 1)[-1]  # strip XML namespace if present
    locs = [loc.text.strip() for loc in root.iter() if loc.tag.endswith("loc") and loc.text]

    if root_tag == "sitemapindex":
        page_urls: list[str] = []
        for sub_sitemap_url in locs:
            if len(page_urls) >= limit:
                break
            try:
                validate_url(sub_sitemap_url)
            except UnsafeDestinationError:
                continue
            page_urls.extend(
                _fetch_sitemap_page_urls(
                    sub_sitemap_url, user_agent, limit - len(page_urls), remaining_depth - 1
                )
            )
        return page_urls[:limit]

    # root_tag == "urlset" (or anything else) — treat entries as real pages.
    return locs[:limit]


def _discover_sitemap_urls(
    root_url: str, user_agent: str, limit: int
) -> tuple[list[str], bool, bool]:
    """
    Best-effort sitemap discovery. Failures here never abort the crawl.
    Returns (discovered_urls, robots_txt_found, sitemap_found) — the two
    booleans back the "missing sitemap or robots.txt" site-wide finding
    in Build 2's analyzer.
    """
    candidates: list[str] = []
    robots_txt_found = False
    try:
        robots_url = urljoin(root_url, "/robots.txt")
        validate_url(robots_url)
        resp = httpx.get(robots_url, timeout=10, headers={"User-Agent": user_agent})
        if resp.status_code == 200:
            robots_txt_found = True
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    candidates.append(line.split(":", 1)[1].strip())
    except (httpx.HTTPError, UnsafeDestinationError):
        pass

    fallback_used = not candidates
    if fallback_used:
        candidates.append(urljoin(root_url, "/sitemap.xml"))

    discovered: list[str] = []
    sitemap_found = False
    for sitemap_url in candidates:
        try:
            validate_url(sitemap_url)
        except UnsafeDestinationError:
            continue
        page_urls = _fetch_sitemap_page_urls(sitemap_url, user_agent, limit - len(discovered))
        if page_urls:
            sitemap_found = True
            discovered.extend(page_urls)
        if len(discovered) >= limit:
            break
    return discovered[:limit], robots_txt_found, sitemap_found


def run_crawl(
    config: ScanConfig,
    on_page_result: Callable[[PageResult], None],
    on_event: Callable[[str, str, dict], None],
) -> CrawlSummary:
    """
    Runs the bounded breadth-first crawl, invoking on_page_result for
    every attempted page (so callers can persist immediately per section
    11.1 stage 8) and on_event for lifecycle events (level, event_type,
    data).
    """
    start_time = time.monotonic()
    root_normalized = normalize_url(config.root_url)
    if not root_normalized:
        raise ValueError(f"Root URL could not be normalized: {config.root_url}")

    seen: set[str] = {root_normalized}
    queue: deque[tuple[str, str, int]] = deque()  # (url, parent_url, depth)
    queue.append((root_normalized, "", 0))

    discovered_count = 1
    attempted = 0
    completed = 0
    failed = 0
    ended_reason = "exhausted_queue"

    sitemap_seeded = False
    robots_txt_found = False
    sitemap_found = False

    while queue:
        if time.monotonic() - start_time > config.max_scan_seconds:
            ended_reason = "time_limit"
            on_event("warning", "scan_time_limit_reached", {"elapsed_seconds": config.max_scan_seconds})
            break
        if attempted >= config.max_pages:
            ended_reason = "page_limit"
            break

        url, parent_url, depth = queue.popleft()
        attempted += 1

        try:
            fetch_result = fetch_page(url)
            parsed = parse_page(fetch_result.body, fetch_result.final_url)
            completed += 1
            on_page_result(
                PageResult(
                    requested_url=url,
                    normalized_url=url,
                    parent_url=parent_url,
                    depth=depth,
                    fetch_status="completed",
                    http_status_code=fetch_result.status_code,
                    content_type=fetch_result.content_type,
                    response_time_ms=fetch_result.response_time_ms,
                    response_size_bytes=fetch_result.response_size_bytes,
                    redirect_chain=fetch_result.redirect_chain,
                    parsed=parsed,
                )
            )

            # Seed sitemap discovery once, after the homepage succeeds.
            if depth == 0 and not sitemap_seeded:
                sitemap_seeded = True
                remaining = config.max_pages - discovered_count
                if remaining > 0:
                    sitemap_links, robots_txt_found, sitemap_found = _discover_sitemap_urls(
                        url, config.user_agent, remaining
                    )
                    for sitemap_link in sitemap_links:
                        norm = normalize_url(sitemap_link)
                        if (
                            norm
                            and norm not in seen
                            and is_same_registrable_host(norm, root_normalized)
                            and discovered_count < config.max_pages
                        ):
                            seen.add(norm)
                            discovered_count += 1
                            queue.append((norm, url, depth + 1))

            if depth < config.max_depth:
                for link in parsed.links:
                    if discovered_count >= config.max_pages:
                        break
                    norm = normalize_url(link.destination_url, base_url=fetch_result.final_url)
                    if not norm or norm in seen:
                        continue
                    if not is_same_registrable_host(norm, root_normalized):
                        continue
                    seen.add(norm)
                    discovered_count += 1
                    queue.append((norm, url, depth + 1))

        except FetchError as exc:
            failed += 1
            on_page_result(
                PageResult(
                    requested_url=url,
                    normalized_url=url,
                    parent_url=parent_url,
                    depth=depth,
                    fetch_status="failed",
                    error_code=exc.code,
                    error_message=exc.message,
                )
            )
            on_event("warning", "page_fetch_failed", {"url": url, "code": exc.code})

    return CrawlSummary(
        root_url=config.root_url,
        pages_discovered=discovered_count,
        pages_attempted=attempted,
        pages_completed=completed,
        pages_failed=failed,
        ended_reason=ended_reason,
        robots_txt_found=robots_txt_found,
        sitemap_found=sitemap_found,
    )
