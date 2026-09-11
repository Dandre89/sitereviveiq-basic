from dataclasses import dataclass, field


@dataclass
class PageData:
    """Mirrors the ScanPage fields the analyzer rules need."""
    page_id: str
    normalized_url: str
    fetch_status: str  # completed | failed | skipped
    http_status_code: int | None
    page_title: str
    meta_description: str
    canonical_url: str
    h1_count: int
    h2_count: int
    word_count: int
    image_count: int
    images_without_alt_count: int
    has_viewport: bool
    has_mixed_content: bool
    is_indexable: bool
    has_phone_link: bool
    has_contact_form: bool
    has_cta_link: bool
    response_time_ms: int | None
    redirect_count: int


@dataclass
class LinkData:
    source_page_id: str
    source_normalized_url: str
    destination_url: str
    normalized_destination_url: str
    link_type: str  # internal | external | mailto | telephone | fragment | asset
    anchor_text: str
    destination_fetch_status: str | None  # None if not resolved to a crawled page


@dataclass
class ScanMeta:
    website_name: str
    robots_txt_found: bool
    sitemap_found: bool


@dataclass
class Finding:
    rule_key: str
    title: str
    category: str  # matches Issue.Category values
    severity: str  # matches Issue.Severity values
    business_impact: str
    affected_scope: str  # a page URL, or a site-wide label like "site-wide"
    evidence: dict = field(default_factory=dict)
    recommendation: str = ""
    estimated_effort: str = "Small"
    page_id: str | None = None  # set when the finding is page-scoped
