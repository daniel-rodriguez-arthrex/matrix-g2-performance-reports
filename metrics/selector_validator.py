import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Page


@dataclass
class SelectorResult:
    selector: str
    strategy: str
    found: bool
    visible: bool
    count: int
    suggested: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selector": self.selector,
            "strategy": self.strategy,
            "found": self.found,
            "visible": self.visible,
            "count": self.count,
            "suggested": self.suggested,
            "error": self.error,
        }


class SelectorValidator:
    def __init__(self, page: Page):
        self.page = page

    async def validate(self, selector: str, strategy: str = "css") -> SelectorResult:
        try:
            locators = {
                "css": lambda s: self.page.locator(s),
                "xpath": lambda s: self.page.locator(f"xpath={s}"),
                "id": lambda s: self.page.locator(f"#{s}"),
                "text": lambda s: self.page.get_by_text(s),
                "role": lambda s: self.page.get_by_role(s),
                "testid": lambda s: self.page.get_by_test_id(s),
            }
            locator_fn = locators.get(strategy, locators["css"])
            locator = locator_fn(selector)
            count = await locator.count()
            visible = False
            if count > 0:
                try:
                    visible = await locator.first.is_visible()
                except Exception:
                    visible = False
            suggested = None
            if count == 0:
                # Basic fallback: try by text content
                try:
                    text_locator = self.page.get_by_text(selector)
                    if await text_locator.count() > 0:
                        suggested = f"get_by_text('{selector}')"
                except Exception:
                    pass
            return SelectorResult(
                selector=selector,
                strategy=strategy,
                found=count > 0,
                visible=visible,
                count=count,
                suggested=suggested,
            )
        except Exception as exc:
            return SelectorResult(
                selector=selector,
                strategy=strategy,
                found=False,
                visible=False,
                count=0,
                error=str(exc),
            )

    async def validate_list(self, selectors: List[Dict[str, str]]) -> List[SelectorResult]:
        results = []
        for item in selectors:
            selector = item.get("selector", "")
            strategy = item.get("strategy", "css")
            results.append(await self.validate(selector, strategy))
        return results

    @staticmethod
    def parse_csharp_page_objects(file_path: Path) -> List[Dict[str, str]]:
        """Extract selectors from C# PageObject files."""
        content = file_path.read_text()
        selectors = []
        patterns = [
            (r"By\.Id\(\"([^\"]+)\"\)", "id"),
            (r"By\.CssSelector\(\"([^\"]+)\"\)", "css"),
            (r"By\.XPath\(\"([^\"]+)\"\)", "xpath"),
            (r"By\.Name\(\"([^\"]+)\"\)", "name"),
        ]
        for regex, strategy in patterns:
            for match in re.findall(regex, content):
                selectors.append({"selector": match, "strategy": strategy})
        return selectors
