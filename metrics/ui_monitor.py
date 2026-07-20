import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from playwright.async_api import Page


@dataclass
class UiTiming:
    label: str
    start_time: float
    end_time: float
    duration_ms: float
    selector: Optional[str] = None
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "selector": self.selector,
            "success": self.success,
            "error": self.error,
        }


class UiMonitor:
    def __init__(self, page: Page):
        self.page = page
        self.timings: List[UiTiming] = []

    def reset(self) -> None:
        self.timings = []

    async def measure(self, label: str, selector: str, timeout: int = 10000) -> UiTiming:
        start = time.perf_counter()
        try:
            await self.page.locator(selector).wait_for(state="visible", timeout=timeout)
            end = time.perf_counter()
            timing = UiTiming(
                label=label,
                start_time=start,
                end_time=end,
                duration_ms=round((end - start) * 1000, 2),
                selector=selector,
                success=True,
            )
        except Exception as exc:
            end = time.perf_counter()
            timing = UiTiming(
                label=label,
                start_time=start,
                end_time=end,
                duration_ms=round((end - start) * 1000, 2),
                selector=selector,
                success=False,
                error=str(exc),
            )
        self.timings.append(timing)
        return timing

    async def detect_state_change(self, label: str, selector: str, attribute: str, expected: str, timeout: int = 10000) -> UiTiming:
        start = time.perf_counter()
        try:
            await self.page.wait_for_function(
                f"(selector, attr, expected) => document.querySelector(selector)?.getAttribute(attr) === expected",
                [selector, attribute, expected],
                timeout=timeout,
            )
            end = time.perf_counter()
            timing = UiTiming(
                label=label,
                start_time=start,
                end_time=end,
                duration_ms=round((end - start) * 1000, 2),
                selector=selector,
                success=True,
            )
        except Exception as exc:
            end = time.perf_counter()
            timing = UiTiming(
                label=label,
                start_time=start,
                end_time=end,
                duration_ms=round((end - start) * 1000, 2),
                selector=selector,
                success=False,
                error=str(exc),
            )
        self.timings.append(timing)
        return timing

    async def screenshot(self, name: str) -> str:
        path = f"results/{name}.png"
        await self.page.screenshot(path=path)
        return path

    def get_summary(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self.timings]
