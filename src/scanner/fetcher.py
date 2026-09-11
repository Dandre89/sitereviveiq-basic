"""
Fetches a single URL under the bounds in section 11.3: 15s timeout, 5
redirects max, 5MB response cap, HTML/XHTML only, SiteReviveIQBot user
agent. Every hop — including each redirect — is revalidated through
scanner.security before a socket is opened.
"""
from dataclasses import dataclass

import httpx

from django.conf import settings

from .security import UnsafeDestinationError, validate_url

ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


class FetchError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class FetchResult:
    final_url: str
    status_code: int
    content_type: str
    body: str
    response_time_ms: int
    response_size_bytes: int
    redirect_chain: list[str]


def fetch_page(url: str) -> FetchResult:
    timeout = settings.SCANNER_REQUEST_TIMEOUT
    max_redirects = settings.SCANNER_MAX_REDIRECTS
    max_bytes = settings.SCANNER_MAX_RESPONSE_BYTES
    user_agent = settings.SCANNER_USER_AGENT

    redirect_chain: list[str] = []
    current_url = url

    try:
        validate_url(current_url)
    except UnsafeDestinationError as exc:
        raise FetchError("unsafe_destination", str(exc)) from exc

    with httpx.Client(
        follow_redirects=False,
        timeout=timeout,
        headers={"User-Agent": user_agent},
    ) as client:
        for _hop in range(max_redirects + 1):
            try:
                response = client.get(current_url)
            except httpx.TimeoutException as exc:
                raise FetchError("timeout", f"Request timed out after {timeout}s") from exc
            except httpx.HTTPError as exc:
                raise FetchError("connection_error", str(exc)) from exc

            if response.is_redirect:
                redirect_chain.append(current_url)
                next_url = str(response.next_request.url) if response.next_request else None
                if not next_url:
                    raise FetchError("redirect_error", "Redirect with no location header")
                try:
                    validate_url(next_url)
                except UnsafeDestinationError as exc:
                    raise FetchError(
                        "unsafe_redirect", f"Redirect target rejected: {exc}"
                    ) from exc
                current_url = next_url
                continue

            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type and not any(
                content_type.startswith(allowed) for allowed in ALLOWED_CONTENT_TYPES
            ):
                raise FetchError("unsupported_content_type", f"Skipped content type: {content_type}")

            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise FetchError("response_too_large", "Response exceeds maximum size")

            body_bytes = response.content
            if len(body_bytes) > max_bytes:
                raise FetchError("response_too_large", "Response exceeds maximum size")

            return FetchResult(
                final_url=str(response.url),
                status_code=response.status_code,
                content_type=content_type,
                body=response.text,
                response_time_ms=int(response.elapsed.total_seconds() * 1000),
                response_size_bytes=len(body_bytes),
                redirect_chain=redirect_chain,
            )

    raise FetchError("too_many_redirects", f"Exceeded {max_redirects} redirects")
