import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from playwright.async_api import Page


@dataclass
class WebSocketFrame:
    direction: str
    url: str
    payload: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WebSocketMonitor:
    """Capture WebSocket frames sent and received during a session."""

    def __init__(self, page: Page):
        self.page = page
        self.frames: List[WebSocketFrame] = []
        self._handler: Optional[Callable] = None

    def start(self) -> None:
        self._handler = self._on_websocket
        self.page.on("websocket", self._handler)

    def stop(self) -> None:
        # Playwright does not expose a simple remove_listener for page-level events
        # in the generated Python API; the page/context will be closed by SessionManager.
        pass

    def reset(self) -> None:
        self.frames = []

    def _on_websocket(self, ws) -> None:
        def log(direction: str, payload: Union[bytes, str]) -> None:
            text = self._decode_payload(payload)
            self.frames.append(
                WebSocketFrame(
                    direction=direction,
                    url=ws.url,
                    payload=text,
                )
            )

        ws.on("framereceived", lambda payload: log("received", payload))
        ws.on("framesent", lambda payload: log("sent", payload))

    @staticmethod
    def _decode_payload(payload: Union[bytes, str, Any]) -> str:
        if isinstance(payload, bytes):
            try:
                return payload.decode("utf-8", errors="replace")
            except Exception:
                return str(payload)
        if isinstance(payload, str):
            return payload
        return str(payload)

    def get_frames(self) -> List[Dict[str, Any]]:
        return [f.to_dict() for f in self.frames]

    def get_summary(self) -> Dict[str, Any]:
        return {
            "frames": len(self.frames),
            "urls": sorted({f.url for f in self.frames}),
        }
