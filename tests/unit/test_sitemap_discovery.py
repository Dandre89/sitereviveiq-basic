from unittest.mock import Mock, patch

from scanner.crawler import _discover_sitemap_urls, _fetch_sitemap_page_urls

SITEMAP_INDEX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/category-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://example.com/page-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://example.com/post-sitemap.xml</loc></sitemap>
</sitemapindex>"""

PAGE_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/contact</loc></url>
</urlset>"""

POST_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/blog/post-1</loc></url>
</urlset>"""

CATEGORY_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/category/news</loc></url>
</urlset>"""

FLAT_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
</urlset>"""


def _mock_response(content: bytes, status_code: int = 200):
    resp = Mock()
    resp.status_code = status_code
    resp.content = content
    return resp


class TestSitemapIndexExpansion:
    def test_sitemap_index_urls_are_not_returned_as_pages(self):
        """
        This is the regression test for the original bug: an index's
        <loc> entries (the sub-sitemap URLs themselves) must never end
        up in the returned page list.
        """
        responses = {
            "https://example.com/sitemap_index.xml": _mock_response(SITEMAP_INDEX_XML),
            "https://example.com/category-sitemap.xml": _mock_response(CATEGORY_SITEMAP_XML),
            "https://example.com/page-sitemap.xml": _mock_response(PAGE_SITEMAP_XML),
            "https://example.com/post-sitemap.xml": _mock_response(POST_SITEMAP_XML),
        }

        def fake_get(url, **kwargs):
            return responses[url]

        with patch("scanner.crawler.httpx.get", side_effect=fake_get):
            urls = _fetch_sitemap_page_urls(
                "https://example.com/sitemap_index.xml", "TestBot/1.0", limit=100
            )

        assert "https://example.com/category-sitemap.xml" not in urls
        assert "https://example.com/page-sitemap.xml" not in urls
        assert "https://example.com/post-sitemap.xml" not in urls

    def test_sitemap_index_returns_real_pages_from_sub_sitemaps(self):
        responses = {
            "https://example.com/sitemap_index.xml": _mock_response(SITEMAP_INDEX_XML),
            "https://example.com/category-sitemap.xml": _mock_response(CATEGORY_SITEMAP_XML),
            "https://example.com/page-sitemap.xml": _mock_response(PAGE_SITEMAP_XML),
            "https://example.com/post-sitemap.xml": _mock_response(POST_SITEMAP_XML),
        }

        def fake_get(url, **kwargs):
            return responses[url]

        with patch("scanner.crawler.httpx.get", side_effect=fake_get):
            urls = _fetch_sitemap_page_urls(
                "https://example.com/sitemap_index.xml", "TestBot/1.0", limit=100
            )

        assert "https://example.com/about" in urls
        assert "https://example.com/contact" in urls
        assert "https://example.com/blog/post-1" in urls
        assert "https://example.com/category/news" in urls

    def test_plain_urlset_sitemap_still_works(self):
        with patch(
            "scanner.crawler.httpx.get",
            return_value=_mock_response(FLAT_SITEMAP_XML),
        ):
            urls = _fetch_sitemap_page_urls(
                "https://example.com/sitemap.xml", "TestBot/1.0", limit=100
            )

        assert set(urls) == {"https://example.com/", "https://example.com/about"}

    def test_respects_limit_across_sub_sitemaps(self):
        responses = {
            "https://example.com/sitemap_index.xml": _mock_response(SITEMAP_INDEX_XML),
            "https://example.com/category-sitemap.xml": _mock_response(CATEGORY_SITEMAP_XML),
            "https://example.com/page-sitemap.xml": _mock_response(PAGE_SITEMAP_XML),
            "https://example.com/post-sitemap.xml": _mock_response(POST_SITEMAP_XML),
        }

        def fake_get(url, **kwargs):
            return responses[url]

        with patch("scanner.crawler.httpx.get", side_effect=fake_get):
            urls = _fetch_sitemap_page_urls(
                "https://example.com/sitemap_index.xml", "TestBot/1.0", limit=2
            )

        assert len(urls) <= 2

    def test_failed_sub_sitemap_does_not_abort_the_others(self):
        responses = {
            "https://example.com/sitemap_index.xml": _mock_response(SITEMAP_INDEX_XML),
            "https://example.com/category-sitemap.xml": _mock_response(b"not valid xml"),
            "https://example.com/page-sitemap.xml": _mock_response(PAGE_SITEMAP_XML),
            "https://example.com/post-sitemap.xml": _mock_response(POST_SITEMAP_XML),
        }

        def fake_get(url, **kwargs):
            return responses[url]

        with patch("scanner.crawler.httpx.get", side_effect=fake_get):
            urls = _fetch_sitemap_page_urls(
                "https://example.com/sitemap_index.xml", "TestBot/1.0", limit=100
            )

        # category-sitemap.xml failed to parse, but the other two still contribute.
        assert "https://example.com/about" in urls
        assert "https://example.com/blog/post-1" in urls


class TestDiscoverSitemapUrls:
    def test_sitemap_found_true_for_valid_index(self):
        responses = {
            "https://example.com/robots.txt": _mock_response(b"", status_code=404),
            "https://example.com/sitemap.xml": _mock_response(SITEMAP_INDEX_XML),
            "https://example.com/category-sitemap.xml": _mock_response(CATEGORY_SITEMAP_XML),
            "https://example.com/page-sitemap.xml": _mock_response(PAGE_SITEMAP_XML),
            "https://example.com/post-sitemap.xml": _mock_response(POST_SITEMAP_XML),
        }

        def fake_get(url, **kwargs):
            return responses[url]

        with patch("scanner.crawler.httpx.get", side_effect=fake_get):
            urls, robots_found, sitemap_found = _discover_sitemap_urls(
                "https://example.com/", "TestBot/1.0", limit=100
            )

        assert sitemap_found is True
        assert robots_found is False
        assert "https://example.com/category-sitemap.xml" not in urls
