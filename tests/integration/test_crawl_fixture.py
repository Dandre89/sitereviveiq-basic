"""
Controlled fixture crawl per section 16.1. Rather than hitting a live
server, this monkeypatches scanner.crawler.fetch_page with a small
in-memory site graph that includes duplicate links, a broken page, and
a page beyond the depth limit — the same categories the spec calls out
under "Integration tests".
"""
import pytest

from scanner.crawler import PageResult, ScanConfig, run_crawl
from scanner.fetcher import FetchError, FetchResult
from scanner.parser import parse_page

FIXTURE_SITE = {
    "https://example.com/": """
        <html><head><title>Home</title></head>
        <body>
            <h1>Welcome</h1>
            <a href="/about">About</a>
            <a href="/about">About again (duplicate link)</a>
            <a href="/broken">Broken page</a>
            <a href="https://external-site.example/">External</a>
        </body></html>
    """,
    "https://example.com/about": """
        <html><head><title>About</title></head>
        <body><h1>About us</h1><a href="/deep">Deep page</a></body></html>
    """,
    "https://example.com/deep": """
        <html><head><title>Deep</title></head>
        <body><h1>Deep page</h1><a href="/deeper">Deeper still</a></body></html>
    """,
}


def fake_fetch_page(url: str) -> FetchResult:
    if url == "https://example.com/broken":
        raise FetchError("http_error", "404 Not Found")
    html = FIXTURE_SITE.get(url)
    if html is None:
        raise FetchError("http_error", "404 Not Found")
    return FetchResult(
        final_url=url,
        status_code=200,
        content_type="text/html",
        body=html,
        response_time_ms=10,
        response_size_bytes=len(html),
        redirect_chain=[],
    )


@pytest.fixture(autouse=True)
def patch_fetch(monkeypatch):
    monkeypatch.setattr("scanner.crawler.fetch_page", fake_fetch_page)
    # example.com is a real, reserved-for-documentation domain — stub
    # sitemap discovery so these tests never make a real network call.
    monkeypatch.setattr(
        "scanner.crawler._discover_sitemap_urls", lambda *a, **k: ([], False, False)
    )


class TestCrawlFixtureSite:
    def test_completes_and_deduplicates_links(self):
        results: list[PageResult] = []
        events: list[tuple] = []

        config = ScanConfig(
            root_url="https://example.com/",
            max_pages=25,
            max_depth=4,
            max_scan_seconds=60,
            user_agent="SiteReviveIQBot/0.1",
        )
        summary = run_crawl(
            config,
            on_page_result=results.append,
            on_event=lambda level, event_type, data: events.append((level, event_type, data)),
        )

        completed_urls = [r.normalized_url for r in results if r.fetch_status == "completed"]
        # /about must appear exactly once despite being linked twice from the homepage.
        assert completed_urls.count("https://example.com/about") == 1
        assert "https://example.com/deep" in completed_urls
        assert summary.pages_completed == 3  # home, about, deep

    def test_broken_page_recorded_as_failed_without_aborting_crawl(self):
        results: list[PageResult] = []
        config = ScanConfig(
            root_url="https://example.com/",
            max_pages=25,
            max_depth=4,
            max_scan_seconds=60,
            user_agent="SiteReviveIQBot/0.1",
        )
        summary = run_crawl(config, on_page_result=results.append, on_event=lambda *a: None)

        broken = [r for r in results if r.normalized_url == "https://example.com/broken"]
        assert len(broken) == 1
        assert broken[0].fetch_status == "failed"
        assert broken[0].error_code == "http_error"
        assert summary.pages_failed == 1
        # The crawl must continue past the failure and still complete other pages.
        assert summary.pages_completed >= 3

    def test_external_links_are_not_crawled(self):
        results: list[PageResult] = []
        config = ScanConfig(
            root_url="https://example.com/",
            max_pages=25,
            max_depth=4,
            max_scan_seconds=60,
            user_agent="SiteReviveIQBot/0.1",
        )
        run_crawl(config, on_page_result=results.append, on_event=lambda *a: None)

        crawled_urls = {r.normalized_url for r in results}
        assert not any("external-site.example" in url for url in crawled_urls)

    def test_page_limit_enforced(self):
        results: list[PageResult] = []
        config = ScanConfig(
            root_url="https://example.com/",
            max_pages=2,
            max_depth=4,
            max_scan_seconds=60,
            user_agent="SiteReviveIQBot/0.1",
        )
        summary = run_crawl(config, on_page_result=results.append, on_event=lambda *a: None)

        assert summary.pages_attempted <= 2
        assert summary.ended_reason == "page_limit"

    def test_depth_limit_enforced(self):
        results: list[PageResult] = []
        config = ScanConfig(
            root_url="https://example.com/",
            max_pages=25,
            max_depth=1,  # home (0) and about (1) only — deep (2) excluded
            max_scan_seconds=60,
            user_agent="SiteReviveIQBot/0.1",
        )
        run_crawl(config, on_page_result=results.append, on_event=lambda *a: None)

        completed_urls = {r.normalized_url for r in results if r.fetch_status == "completed"}
        assert "https://example.com/deep" not in completed_urls


class TestParserFixture:
    def test_extracts_title_and_headings(self):
        parsed = parse_page(FIXTURE_SITE["https://example.com/"], "https://example.com/")
        assert parsed.title == "Home"
        assert parsed.h1_count == 1

    def test_counts_links_including_duplicates(self):
        parsed = parse_page(FIXTURE_SITE["https://example.com/"], "https://example.com/")
        about_links = [link for link in parsed.links if link.destination_url == "/about"]
        assert len(about_links) == 2  # parser sees both; dedup happens in the crawler
