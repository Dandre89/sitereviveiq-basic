from apps.findings.services import _fingerprint


class TestFingerprint:
    def test_same_inputs_produce_same_fingerprint(self):
        fp1 = _fingerprint("website-123", "missing_title", "https://example.com/about")
        fp2 = _fingerprint("website-123", "missing_title", "https://example.com/about")
        assert fp1 == fp2

    def test_different_rule_key_produces_different_fingerprint(self):
        fp1 = _fingerprint("website-123", "missing_title", "https://example.com/about")
        fp2 = _fingerprint("website-123", "missing_h1", "https://example.com/about")
        assert fp1 != fp2

    def test_different_website_produces_different_fingerprint(self):
        fp1 = _fingerprint("website-123", "missing_title", "https://example.com/about")
        fp2 = _fingerprint("website-456", "missing_title", "https://example.com/about")
        assert fp1 != fp2

    def test_different_scope_produces_different_fingerprint(self):
        fp1 = _fingerprint("website-123", "missing_title", "https://example.com/about")
        fp2 = _fingerprint("website-123", "missing_title", "https://example.com/contact")
        assert fp1 != fp2
