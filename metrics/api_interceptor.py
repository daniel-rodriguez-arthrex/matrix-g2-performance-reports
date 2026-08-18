import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Page, Route


@dataclass
class ApiCall:
    method: str
    url: str
    status: Optional[int]
    request_headers: Dict[str, str] = field(default_factory=dict)
    request_payload: Optional[str] = None
    response_body: Optional[str] = None
    response_headers: Dict[str, str] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    dns_ms: Optional[float] = None
    connect_ms: Optional[float] = None
    tls_ms: Optional[float] = None
    request_ms: Optional[float] = None
    response_ms: Optional[float] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    is_valid: Optional[bool] = None
    api_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ApiInterceptor:
    def __init__(
        self,
        page: Page,
        base_url: str,
        api_patterns: Optional[List[str]] = None,
        api_threshold_ms: Optional[float] = None,
    ):
        from metrics.api_validator import ApiResponseValidator
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.api_patterns = api_patterns or ["/api/", "/ic/", "/ws/"]
        self.api_threshold_ms = api_threshold_ms
        self.validator = ApiResponseValidator()
        self.calls: List[ApiCall] = []
        self._handler: Optional[Callable] = None

        parsed_base = urlsplit(self.base_url)
        self._base_host = parsed_base.hostname
        self._base_port = parsed_base.port
        self.dropped_port_fixes = 0

    def _fix_dropped_port(self, url: str) -> str:
        """Work around a Matrix G2 app bug where some reconnect/status-polling calls
        rebuild the request URL without the room's real host and/or custom port,
        causing them to hit the default scheme port (e.g. 443) or localhost (e.g.
        ECONNREFUSED ::1) and fail forever - which leaves the app stuck on its loading
        splash. Two cases are rewritten back to the room's real host:port:
          1. Host matches the room but the port was dropped/defaulted.
          2. Host was rebuilt as localhost/127.0.0.1/[::1] instead of the room's host
             (seen when the app's reconnect logic falls back to a hardcoded default).
        """
        if not self._base_port or not self._base_host:
            return url
        parsed = urlsplit(url)
        same_host_wrong_port = parsed.hostname == self._base_host and parsed.port != self._base_port
        dropped_to_localhost = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if not (same_host_wrong_port or dropped_to_localhost):
            return url
        netloc = f"{self._base_host}:{self._base_port}"
        self.dropped_port_fixes += 1
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    async def start(self) -> None:
        self._handler = lambda route: self._on_route(route)
        await self.page.route("**/*", self._handler)

    async def stop(self) -> None:
        if self._handler:
            try:
                await self.page.unroute("**/*", self._handler)
            except Exception:
                # Page/context/browser may already be closed (e.g. user closed the
                # window before Ctrl+C) - nothing to unroute at that point, and we
                # still want report generation below to proceed with what we captured.
                pass
            self._handler = None

    def reset(self) -> None:
        self.calls = []

    def _is_api_call(self, url: str) -> bool:
        return any(pattern in url for pattern in self.api_patterns)

    async def _on_route(self, route: Route) -> None:
        request = route.request
        url = request.url

        if not self._is_api_call(url):
            await route.continue_()
            return

        start = time.perf_counter()
        request_payload = None
        if request.post_data:
            request_payload = request.post_data

        call = ApiCall(
            method=request.method,
            url=url,
            status=None,
            request_headers=dict(request.headers) if request.headers else {},
            request_payload=request_payload,
            start_time=start,
        )

        fixed_url = self._fix_dropped_port(url)
        try:
            response = await route.fetch(url=fixed_url) if fixed_url != url else await route.fetch()
            end = time.perf_counter()
            call.end_time = end
            call.status = response.status
            call.response_headers = dict(response.headers) if response.headers else {}
            try:
                body = await response.body()
                content_type = (response.headers or {}).get("content-type", "")
                if body and content_type and (
                    content_type.startswith("image/")
                    or content_type.startswith("audio/")
                    or content_type.startswith("video/")
                    or "application/octet-stream" in content_type
                    or "application/zip" in content_type
                ):
                    call.response_body = None
                else:
                    call.response_body = body.decode("utf-8", errors="replace")
            except Exception:
                body = b""
                call.response_body = None

            timing = (request.timing if hasattr(request, "timing") else None) or {}
            call.duration_ms = self._timing_ms(timing, "endTime", "startTime") or (end - start) * 1000
            call.dns_ms = self._timing_ms(timing, "domainLookupEnd", "domainLookupStart")
            call.connect_ms = self._timing_ms(timing, "connectEnd", "connectStart")
            call.tls_ms = self._timing_ms(timing, "secureConnectionEnd", "secureConnectionStart")
            call.request_ms = self._timing_ms(timing, "responseStart", "requestStart")
            call.response_ms = self._timing_ms(timing, "responseEnd", "responseStart")

            validation = self.validator.validate(
                call.status,
                call.response_body,
                call.response_headers,
            )
            call.is_valid = validation["is_valid"]
            call.api_error = validation["api_error"]

            await route.fulfill(status=response.status, headers=response.headers, body=body)
        except Exception as exc:
            call.error = str(exc)
            call.end_time = time.perf_counter()
            call.duration_ms = (call.end_time - call.start_time) * 1000
            call.is_valid = False
            call.api_error = str(exc)
            try:
                await (route.continue_(url=fixed_url) if fixed_url != url else route.continue_())
            except Exception:
                pass  # Route may already be handled if page closed

        self.calls.append(call)

    def get_calls(self) -> List[ApiCall]:
        return self.calls

    def get_summary(self) -> Dict[str, Any]:
        api_calls = [c for c in self.calls if self._is_api_call(c.url)]
        threshold = self.api_threshold_ms
        violations = []
        if threshold is not None:
            violations = [c.to_dict() for c in api_calls if (c.duration_ms or 0) > threshold]
        return {
            "total_calls": len(api_calls),
            "total_duration_ms": round(sum(c.duration_ms or 0 for c in api_calls), 2),
            "avg_duration_ms": round(
                sum(c.duration_ms or 0 for c in api_calls) / len(api_calls), 2
            ) if api_calls else 0,
            "api_threshold_ms": threshold,
            "api_pass": (not violations) if threshold is not None else None,
            "api_violations": violations,
            "validation_errors": [c.to_dict() for c in api_calls if c.is_valid is False],
            "validation_failures": sum(1 for c in api_calls if c.is_valid is False),
            "errors": [c.to_dict() for c in api_calls if c.error or (c.status and c.status >= 400)],
            "calls": [c.to_dict() for c in api_calls],
        }

    @staticmethod
    def _timing_ms(timing: Dict[str, Any], end_key: str, start_key: str) -> Optional[float]:
        end = timing.get(end_key)
        start = timing.get(start_key)
        if end is None or start is None:
            return None
        return max(0.0, float(end) - float(start))

    def get_unique_endpoints(self) -> List[Dict[str, Any]]:
        endpoints: Dict[str, Dict[str, Any]] = {}
        for call in self.calls:
            if not self._is_api_call(call.url):
                continue
            key = f"{call.method} {call.url}"
            if key not in endpoints:
                endpoints[key] = {
                    "method": call.method,
                    "url": call.url,
                    "count": 0,
                    "sample_payload": call.request_payload,
                    "sample_response": call.response_body,
                }
            endpoints[key]["count"] += 1
        return list(endpoints.values())
