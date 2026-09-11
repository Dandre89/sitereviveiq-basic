"""
Parses fetched HTML into the structured fields ScanPage stores. Uses
selectolax (fast, tolerant of malformed HTML) rather than hand-rolled
regex parsing.
"""
import hashlib
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser


@dataclass
class ParsedLink:
    destination_url: str
    anchor_text: str
    rel_value: str
    is_nofollow: bool
    link_type: str = "external"


@dataclass
class ParsedPage:
    title: str = ""
    meta_description: str = ""
    canonical_url: str = ""
    robots_directives: str = ""
    h1_count: int = 0
    h2_count: int = 0
    word_count: int = 0
    image_count: int = 0
    images_without_alt_count: int = 0
    has_viewport: bool = False
    is_indexable: bool = True
    has_mixed_content: bool = False
    has_phone_link: bool = False
    has_contact_form: bool = False
    has_cta_link: bool = False
    links: list[ParsedLink] = field(default_factory=list)
    html_hash: str = ""
    text_hash: str = ""


def parse_page(html: str, page_url: str) -> ParsedPage:
    tree = HTMLParser(html)
    result = ParsedPage()

    title_node = tree.css_first("title")
    if title_node:
        result.title = title_node.text(strip=True)[:1024]

    meta_desc = tree.css_first('meta[name="description"]')
    if meta_desc:
        result.meta_description = meta_desc.attributes.get("content", "") or ""

    canonical = tree.css_first('link[rel="canonical"]')
    if canonical:
        result.canonical_url = canonical.attributes.get("href", "") or ""

    robots_meta = tree.css_first('meta[name="robots"]')
    if robots_meta:
        result.robots_directives = robots_meta.attributes.get("content", "") or ""

    result.h1_count = len(tree.css("h1"))
    result.h2_count = len(tree.css("h2"))

    body = tree.css_first("body")
    body_text = body.text(separator=" ", strip=True) if body else ""
    result.word_count = len(body_text.split())

    images = tree.css("img")
    result.image_count = len(images)
    result.images_without_alt_count = sum(
        1 for img in images if not (img.attributes.get("alt") or "").strip()
    )

    viewport = tree.css_first('meta[name="viewport"]')
    result.has_viewport = viewport is not None

    robots_lower = result.robots_directives.lower()
    result.is_indexable = "noindex" not in robots_lower

    if page_url.startswith("https://"):
        for tag, attr in (("img", "src"), ("script", "src"), ("link", "href")):
            for node in tree.css(tag):
                src = (node.attributes.get(attr) or "").strip()
                if src.startswith("http://"):
                    result.has_mixed_content = True
                    break
            if result.has_mixed_content:
                break

    hostname = urlsplit(page_url).hostname or ""
    CTA_KEYWORDS = (
        "contact", "call", "get a quote", "get quote", "request a quote", "free quote",
        "book now", "schedule", "get started", "sign up", "buy now", "shop now",
        "learn more", "request a consultation", "get in touch",
    )
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href", "") or "")
        if href.startswith("tel:"):
            result.has_phone_link = True
        anchor_text_lower = a.text(strip=True).lower()
        if any(keyword in anchor_text_lower for keyword in CTA_KEYWORDS):
            result.has_cta_link = True

    if tree.css_first("form"):
        result.has_contact_form = True

    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "") or ""
        if not href:
            continue
        rel_value = a.attributes.get("rel", "") or ""
        link_type = _classify_link(href, hostname)
        result.links.append(
            ParsedLink(
                destination_url=href,
                anchor_text=a.text(strip=True)[:1024],
                rel_value=rel_value,
                is_nofollow="nofollow" in rel_value.lower(),
                link_type=link_type,
            )
        )

    result.html_hash = hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()
    result.text_hash = hashlib.sha256(body_text.encode("utf-8", errors="ignore")).hexdigest()

    return result


def _classify_link(href: str, source_hostname: str) -> str:
    if href.startswith("mailto:"):
        return "mailto"
    if href.startswith("tel:"):
        return "telephone"
    if href.startswith("#"):
        return "fragment"
    parsed = urlsplit(href)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return "asset"
    dest_host = (parsed.hostname or source_hostname).lower()
    return "internal" if dest_host == source_hostname.lower() else "external"
