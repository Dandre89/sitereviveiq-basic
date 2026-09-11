from analyzer.engine import analyze
from analyzer.models import LinkData, PageData, ScanMeta

DEFAULT_META = ScanMeta(website_name="Test Site", robots_txt_found=True, sitemap_found=True)


def make_page(**overrides) -> PageData:
    defaults = dict(
        page_id="page-1",
        normalized_url="https://example.com/",
        fetch_status="completed",
        http_status_code=200,
        page_title="A Perfectly Fine Title",
        meta_description="A perfectly fine description of this page's content here.",
        canonical_url="https://example.com/",
        h1_count=1,
        h2_count=2,
        word_count=500,
        image_count=2,
        images_without_alt_count=0,
        has_viewport=True,
        has_mixed_content=False,
        is_indexable=True,
        has_phone_link=False,
        has_contact_form=False,
        has_cta_link=False,
        response_time_ms=300,
        redirect_count=0,
    )
    defaults.update(overrides)
    return PageData(**defaults)


class TestMissingTitle:
    def test_flags_missing_title(self):
        page = make_page(page_title="")
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "missing_title" for f in findings)

    def test_clean_page_has_no_title_finding(self):
        page = make_page()
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key == "missing_title" for f in findings)

    def test_flags_overly_long_title(self):
        page = make_page(page_title="X" * 80)
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "title_too_long" for f in findings)


class TestMissingMetaDescription:
    def test_flags_missing_description(self):
        page = make_page(meta_description="")
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "missing_meta_description" for f in findings)


class TestDuplicateTitles:
    def test_flags_duplicate_titles_across_pages(self):
        pages = [
            make_page(page_id="1", normalized_url="https://example.com/a", page_title="Same Title"),
            make_page(page_id="2", normalized_url="https://example.com/b", page_title="Same Title"),
        ]
        findings = analyze(pages, [], DEFAULT_META)
        dup = [f for f in findings if f.rule_key == "duplicate_title"]
        assert len(dup) == 1
        assert set(dup[0].evidence["affected_urls"]) == {
            "https://example.com/a", "https://example.com/b",
        }

    def test_unique_titles_not_flagged(self):
        pages = [
            make_page(page_id="1", normalized_url="https://example.com/a", page_title="Title A"),
            make_page(page_id="2", normalized_url="https://example.com/b", page_title="Title B"),
        ]
        findings = analyze(pages, [], DEFAULT_META)
        assert not any(f.rule_key == "duplicate_title" for f in findings)


class TestHeadingStructure:
    def test_flags_missing_h1(self):
        page = make_page(h1_count=0)
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "missing_h1" for f in findings)

    def test_flags_multiple_h1(self):
        page = make_page(h1_count=3)
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "multiple_h1" for f in findings)

    def test_single_h1_not_flagged(self):
        page = make_page(h1_count=1)
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key in ("missing_h1", "multiple_h1") for f in findings)


class TestViewport:
    def test_flags_missing_viewport(self):
        page = make_page(has_viewport=False)
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "missing_viewport" for f in findings)


class TestThinContent:
    def test_flags_very_thin_content_as_high(self):
        page = make_page(word_count=50)
        findings = analyze([page], [], DEFAULT_META)
        thin = [f for f in findings if f.rule_key == "thin_content"]
        assert len(thin) == 1
        assert thin[0].severity == "high"

    def test_flags_moderately_thin_content_as_medium(self):
        page = make_page(word_count=200)
        findings = analyze([page], [], DEFAULT_META)
        thin = [f for f in findings if f.rule_key == "thin_content"]
        assert len(thin) == 1
        assert thin[0].severity == "medium"

    def test_substantial_content_not_flagged(self):
        page = make_page(word_count=800)
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key == "thin_content" for f in findings)

    def test_noindex_pages_excluded_from_thin_content(self):
        page = make_page(word_count=50, is_indexable=False)
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key == "thin_content" for f in findings)


class TestMissingAltText:
    def test_flags_missing_alt_text(self):
        page = make_page(images_without_alt_count=1)
        findings = analyze([page], [], DEFAULT_META)
        alt = [f for f in findings if f.rule_key == "missing_alt_text"]
        assert len(alt) == 1
        assert alt[0].severity == "low"

    def test_many_missing_alt_texts_escalates_severity(self):
        page = make_page(images_without_alt_count=5)
        findings = analyze([page], [], DEFAULT_META)
        alt = [f for f in findings if f.rule_key == "missing_alt_text"]
        assert alt[0].severity == "medium"


class TestIndexability:
    def test_flags_noindex_page(self):
        page = make_page(is_indexable=False)
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "page_not_indexable" for f in findings)

    def test_flags_missing_canonical(self):
        page = make_page(canonical_url="")
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "missing_canonical" for f in findings)


class TestMixedContent:
    def test_flags_mixed_content(self):
        page = make_page(has_mixed_content=True)
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "mixed_content" for f in findings)


class TestSlowResponse:
    def test_flags_high_severity_slow_response(self):
        page = make_page(response_time_ms=3500)
        findings = analyze([page], [], DEFAULT_META)
        slow = [f for f in findings if f.rule_key == "slow_response"]
        assert slow[0].severity == "high"

    def test_flags_medium_severity_slow_response(self):
        page = make_page(response_time_ms=2000)
        findings = analyze([page], [], DEFAULT_META)
        slow = [f for f in findings if f.rule_key == "slow_response"]
        assert slow[0].severity == "medium"

    def test_fast_response_not_flagged(self):
        page = make_page(response_time_ms=200)
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key == "slow_response" for f in findings)


class TestRedirectChains:
    def test_single_redirect_not_flagged(self):
        page = make_page(redirect_count=1)
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key == "redirect_chain" for f in findings)

    def test_multi_hop_redirect_flagged(self):
        page = make_page(redirect_count=3)
        findings = analyze([page], [], DEFAULT_META)
        chain = [f for f in findings if f.rule_key == "redirect_chain"]
        assert chain[0].severity == "medium"


class TestMissingSitemapOrRobots:
    def test_both_present_not_flagged(self):
        findings = analyze([], [], DEFAULT_META)
        assert not any(f.rule_key == "missing_sitemap_or_robots" for f in findings)

    def test_both_missing_is_medium_severity(self):
        meta = ScanMeta(website_name="Test", robots_txt_found=False, sitemap_found=False)
        findings = analyze([], [], meta)
        finding = [f for f in findings if f.rule_key == "missing_sitemap_or_robots"][0]
        assert finding.severity == "medium"
        assert set(finding.evidence["missing"]) == {"robots.txt", "XML sitemap"}

    def test_one_missing_is_low_severity(self):
        meta = ScanMeta(website_name="Test", robots_txt_found=True, sitemap_found=False)
        findings = analyze([], [], meta)
        finding = [f for f in findings if f.rule_key == "missing_sitemap_or_robots"][0]
        assert finding.severity == "low"


class TestBrokenInternalLinks:
    def test_flags_link_to_failed_page(self):
        link = LinkData(
            source_page_id="1",
            source_normalized_url="https://example.com/",
            destination_url="/broken",
            normalized_destination_url="https://example.com/broken",
            link_type="internal",
            anchor_text="Broken page",
            destination_fetch_status="failed",
        )
        findings = analyze([], [link], DEFAULT_META)
        assert any(f.rule_key == "broken_internal_link" for f in findings)

    def test_working_link_not_flagged(self):
        link = LinkData(
            source_page_id="1",
            source_normalized_url="https://example.com/",
            destination_url="/about",
            normalized_destination_url="https://example.com/about",
            link_type="internal",
            anchor_text="About",
            destination_fetch_status="completed",
        )
        findings = analyze([], [link], DEFAULT_META)
        assert not any(f.rule_key == "broken_internal_link" for f in findings)

    def test_external_links_never_checked(self):
        link = LinkData(
            source_page_id="1",
            source_normalized_url="https://example.com/",
            destination_url="https://other-site.example/",
            normalized_destination_url="https://other-site.example/",
            link_type="external",
            anchor_text="Other site",
            destination_fetch_status=None,
        )
        findings = analyze([], [link], DEFAULT_META)
        assert not any(f.rule_key == "broken_internal_link" for f in findings)


class TestFailedAndSkippedPagesExcludedFromContentRules:
    def test_failed_page_not_checked_for_thin_content_or_title(self):
        page = make_page(fetch_status="failed", http_status_code=None, word_count=0, page_title="")
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key in ("thin_content", "missing_title") for f in findings)


class TestMissingConversionPath:
    def test_flags_page_with_no_contact_signal(self):
        page = make_page(has_phone_link=False, has_contact_form=False, has_cta_link=False)
        findings = analyze([page], [], DEFAULT_META)
        assert any(f.rule_key == "missing_conversion_path" for f in findings)

    def test_phone_link_satisfies_the_rule(self):
        page = make_page(has_phone_link=True)
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key == "missing_conversion_path" for f in findings)

    def test_contact_form_satisfies_the_rule(self):
        page = make_page(has_contact_form=True)
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key == "missing_conversion_path" for f in findings)

    def test_cta_link_satisfies_the_rule(self):
        page = make_page(has_cta_link=True)
        findings = analyze([page], [], DEFAULT_META)
        assert not any(f.rule_key == "missing_conversion_path" for f in findings)


class TestSiteMissingContactInfo:
    def test_flags_when_no_page_has_any_contact_path(self):
        pages = [
            make_page(page_id="1", normalized_url="https://example.com/a"),
            make_page(page_id="2", normalized_url="https://example.com/b"),
        ]
        findings = analyze(pages, [], DEFAULT_META)
        site_wide = [f for f in findings if f.rule_key == "site_missing_contact_info"]
        assert len(site_wide) == 1
        assert site_wide[0].affected_scope == "site-wide"

    def test_not_flagged_if_any_page_has_phone_link(self):
        pages = [
            make_page(page_id="1", normalized_url="https://example.com/a", has_phone_link=True),
            make_page(page_id="2", normalized_url="https://example.com/b"),
        ]
        findings = analyze(pages, [], DEFAULT_META)
        assert not any(f.rule_key == "site_missing_contact_info" for f in findings)
