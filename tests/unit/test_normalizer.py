from scanner.normalizer import is_same_registrable_host, normalize_url


class TestNormalizeUrl:
    def test_removes_fragment(self):
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_lowercases_hostname(self):
        assert normalize_url("https://EXAMPLE.com/Page") == "https://example.com/Page"

    def test_removes_default_https_port(self):
        assert normalize_url("https://example.com:443/page") == "https://example.com/page"

    def test_removes_default_http_port(self):
        assert normalize_url("http://example.com:80/page") == "http://example.com/page"

    def test_keeps_nondefault_port(self):
        assert normalize_url("https://example.com:8443/page") == "https://example.com:8443/page"

    def test_strips_trailing_slash_except_root(self):
        assert normalize_url("https://example.com/page/") == "https://example.com/page"
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_rejects_unsupported_scheme(self):
        assert normalize_url("ftp://example.com/file") is None
        assert normalize_url("javascript:void(0)") is None

    def test_rejects_asset_extensions(self):
        assert normalize_url("https://example.com/logo.png") is None
        assert normalize_url("https://example.com/app.js") is None
        assert normalize_url("https://example.com/report.pdf") is None

    def test_keeps_query_string(self):
        assert normalize_url("https://example.com/search?q=widgets") == (
            "https://example.com/search?q=widgets"
        )

    def test_resolves_relative_against_base(self):
        assert normalize_url("/about", base_url="https://example.com/home") == (
            "https://example.com/about"
        )

    def test_no_hostname_returns_none(self):
        assert normalize_url("https:///path") is None


class TestIsSameRegistrableHost:
    def test_exact_match(self):
        assert is_same_registrable_host(
            "https://example.com/a", "https://example.com/b"
        )

    def test_www_prefix_ignored(self):
        assert is_same_registrable_host(
            "https://www.example.com/a", "https://example.com/b"
        )

    def test_different_hosts_rejected(self):
        assert not is_same_registrable_host(
            "https://example.com/a", "https://evil.com/b"
        )

    def test_subdomain_is_different_host(self):
        assert not is_same_registrable_host(
            "https://example.com/a", "https://blog.example.com/b"
        )
