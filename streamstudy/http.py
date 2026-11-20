"""Small, dependency-free HTTP client with caching and retries."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


class HttpError(RuntimeError):
    """Raised when a request fails after retries."""

    def __init__(self, message: str, url: str = "", status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class HttpClient:
    """A polite JSON/text fetcher.

    Responses are cached in memory for ``cache_ttl`` seconds so switching
    tabs or re-rendering never re-hits the providers, and a single retry
    smooths over transient 5xx/network blips.
    """

    def __init__(
        self,
        user_agent: str,
        *,
        timeout: float = 25.0,
        cache_ttl: float = 300.0,
        max_retries: int = 1,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self._cache: dict[str, tuple[float, str]] = {}

    def build_url(self, url: str, params: dict | None = None) -> str:
        if not params:
            return url
        clean = {k: v for k, v in params.items() if v is not None}
        joiner = "&" if "?" in url else "?"
        return f"{url}{joiner}{urllib.parse.urlencode(clean)}"

    def get_text(self, url: str, params: dict | None = None) -> str:
        full = self.build_url(url, params)
        cached = self._cache.get(full)
        if cached and time.monotonic() - cached[0] < self.cache_ttl:
            return cached[1]

        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                full,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json, text/plain, */*",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    text = response.read().decode(charset, "replace")
                self._cache[full] = (time.monotonic(), text)
                return text
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (408, 429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(1.0 + attempt)
                    continue
                raise HttpError(
                    f"HTTP {exc.code} from {urllib.parse.urlsplit(full).netloc}",
                    url=full,
                    status=exc.code,
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt < self.max_retries:
                    time.sleep(1.0 + attempt)
                    continue
                raise HttpError(
                    f"Network error talking to {urllib.parse.urlsplit(full).netloc}: {exc}",
                    url=full,
                ) from exc
        raise HttpError(f"Request failed: {last}", url=full)  # pragma: no cover

    def get_json(self, url: str, params: dict | None = None) -> dict:
        text = self.get_text(url, params)
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise HttpError(f"Invalid JSON from {urllib.parse.urlsplit(url).netloc}") from exc
        if not isinstance(data, dict):
            raise HttpError(f"Unexpected JSON payload from {url}")
        return data

    def clear_cache(self) -> None:
        self._cache.clear()
