from __future__ import annotations

import ipaddress
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

MAX_REDIRECTS = 5


class UnsafeUrlError(ValueError):
    pass


class ResponseTooLargeError(ValueError):
    pass


class _StreamingHttpClient(Protocol):
    def stream(self, method: str, url: str, **kwargs: Any) -> Any: ...

    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...


def validate_public_http_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise UnsafeUrlError("invalid URL") from exc

    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("only HTTP(S) URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed")
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("URL hostname is required")

    normalized_host = hostname.rstrip(".").casefold()
    if normalized_host == "localhost" or normalized_host.endswith(
        (".localhost", ".local", ".internal", ".home", ".lan")
    ):
        raise UnsafeUrlError("local network hostnames are not allowed")

    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        if "." not in normalized_host:
            raise UnsafeUrlError("single-label hostnames are not allowed") from None
    else:
        if not address.is_global:
            raise UnsafeUrlError("non-public IP addresses are not allowed")

    return value


def safe_url_for_log(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<invalid-url>"
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def filename_from_url(value: str, default: str = "download.bin") -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return default
    return PurePosixPath(parsed.path).name or default


async def fetch_limited_bytes(
    client: _StreamingHttpClient,
    url: str,
    *,
    timeout: httpx.Timeout | float,
    max_bytes: int,
    max_redirects: int = MAX_REDIRECTS,
) -> tuple[bytes, str, str | None]:
    current = validate_public_http_url(url)

    for redirect_count in range(max_redirects + 1):
        if hasattr(client, "stream"):
            async with client.stream(
                "GET",
                current,
                timeout=timeout,
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        response.raise_for_status()
                    if redirect_count >= max_redirects:
                        raise UnsafeUrlError("too many redirects")
                    current = validate_public_http_url(urljoin(current, location))
                    continue

                response.raise_for_status()
                declared_length = response.headers.get("content-length")
                content_length_too_large = (
                    declared_length is not None
                    and declared_length.isdigit()
                    and int(declared_length) > max_bytes
                )
                if content_length_too_large:
                    raise ResponseTooLargeError("response exceeds size limit")

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ResponseTooLargeError("response exceeds size limit")
                    chunks.append(chunk)
                return b"".join(chunks), current, response.headers.get("content-type")

        response = await client.get(current, timeout=timeout, follow_redirects=False)
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                response.raise_for_status()
            if redirect_count >= max_redirects:
                raise UnsafeUrlError("too many redirects")
            current = validate_public_http_url(urljoin(current, location))
            continue
        response.raise_for_status()
        if len(response.content) > max_bytes:
            raise ResponseTooLargeError("response exceeds size limit")
        return response.content, current, response.headers.get("content-type")

    raise UnsafeUrlError("too many redirects")
