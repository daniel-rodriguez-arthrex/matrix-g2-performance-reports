import json
import os
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config import get_room_config
from core.matrix_client import MatrixClient


class SessionManager:
    def __init__(
        self,
        room_id: Optional[str] = None,
        headless: Optional[bool] = None,
        output_dir: str = "results",
        channel: Optional[str] = None,
        skip_auth_injection: bool = False,
    ):
        self.room = get_room_config(room_id)
        self.headless = (
            headless
            if headless is not None
            else os.getenv("HEADLESS", "false").lower() == "true"
        )
        self.channel = channel
        self.skip_auth_injection = skip_auth_injection
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self) -> "SessionManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            await self._capture_failure_screenshot()
        await self.stop()

    async def start(self) -> Page:
        self.playwright = await async_playwright().start()
        launch_kwargs: dict = {"headless": self.headless}
        if self.channel:
            launch_kwargs["channel"] = self.channel
        if not self.headless:
            launch_kwargs["args"] = ["--start-maximized"]
        self.browser = await self.playwright.chromium.launch(**launch_kwargs)
        self.context = await self.browser.new_context(
            ignore_https_errors=True,
            record_video_dir=str(self.output_dir / "videos") if not self.headless else None,
            viewport={"width": 1920, "height": 1080} if self.headless else None,
            no_viewport=not self.headless,
        )
        self.page = await self.context.new_page()
        if not self.skip_auth_injection:
            await self._authenticate()
        await self.page.goto(self.room.login_url(), wait_until="domcontentloaded", timeout=30000)
        return self.page

    async def _authenticate(self) -> None:
        """Log in via the API and inject the access token into the browser."""
        try:
            client = MatrixClient(
                self.room.base_url,
                self.room.username,
                self.room.password,
                self.room.id,
                passcode=self.room.passcode,
            )
            token = client.authenticate()
            client.close()
            if token:
                script = f"""
                localStorage.setItem('accessToken', {json.dumps(token)});
                sessionStorage.setItem('accessToken', {json.dumps(token)});
                localStorage.setItem('roomId', {json.dumps(self.room.id)});
                sessionStorage.setItem('roomId', {json.dumps(self.room.id)});
                """
                await self.context.add_init_script(script)
        except Exception:
            # If authentication fails, let the tool proceed so the failure is captured
            pass

    async def stop(self) -> None:
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def _capture_failure_screenshot(self) -> None:
        if self.page:
            try:
                path = self.output_dir / "failure_screenshot.png"
                await self.page.screenshot(path=str(path), full_page=True)
            except Exception:
                pass

    def screenshot_path(self, name: str) -> Path:
        return self.output_dir / name
