import pytest

from scanner.security import UnsafeDestinationError, validate_url


class TestSchemeAndPort:
    def test_rejects_non_http_scheme(self):
        with pytest.raises(UnsafeDestinationError, match="Unsupported scheme"):
            validate_url("ftp://example.com/file")

    def test_rejects_disallowed_port(self):
        with pytest.raises(UnsafeDestinationError, match="Port not allowed"):
            validate_url("http://example.com:22/")

    def test_allows_default_https_port(self):
        result = validate_url("https://93.184.216.34/")
        assert result.port == 443

    def test_allows_default_http_port(self):
        result = validate_url("http://93.184.216.34/")
        assert result.port == 80


class TestBlockedAddressRanges:
    """
    These use IP literals directly (no DNS lookup needed) so the tests
    run offline and deterministically — this is exactly the SSRF
    surface: a request that LOOKS like it targets a normal-shaped host
    but resolves somewhere it shouldn't.
    """

    def test_blocks_loopback(self):
        with pytest.raises(UnsafeDestinationError, match="blocked address range"):
            validate_url("http://127.0.0.1/")

    def test_blocks_localhost_hostname(self):
        with pytest.raises(UnsafeDestinationError, match="blocked address range"):
            validate_url("http://localhost/")

    def test_blocks_private_10_range(self):
        with pytest.raises(UnsafeDestinationError, match="blocked address range"):
            validate_url("http://10.0.0.5/")

    def test_blocks_private_192_168_range(self):
        with pytest.raises(UnsafeDestinationError, match="blocked address range"):
            validate_url("http://192.168.1.1/")

    def test_blocks_private_172_16_range(self):
        with pytest.raises(UnsafeDestinationError, match="blocked address range"):
            validate_url("http://172.16.0.1/")

    def test_blocks_link_local(self):
        with pytest.raises(UnsafeDestinationError, match="blocked address range"):
            validate_url("http://169.254.1.1/")

    def test_blocks_cloud_metadata_address(self):
        with pytest.raises(UnsafeDestinationError, match="blocked address range"):
            validate_url("http://169.254.169.254/latest/meta-data/")

    def test_allows_public_address(self):
        # 93.184.216.34 was the long-standing example.com address; used
        # here purely as a stable public IP literal, not a live fetch.
        result = validate_url("http://93.184.216.34/")
        assert result.resolved_ip == "93.184.216.34"


class TestMissingHostname:
    def test_rejects_url_with_no_hostname(self):
        with pytest.raises(UnsafeDestinationError, match="no hostname"):
            validate_url("https:///path-only")
