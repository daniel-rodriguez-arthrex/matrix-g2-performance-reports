from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass
class WorkflowSLA:
    api_ms: int = 500
    ui_ms: int = 2000
    total_ms: int = 2500


@dataclass
class WorkflowConfig:
    name: str
    description: str
    expected_endpoints: List[str]
    sla: WorkflowSLA
    selectors: List[str]


WORKFLOWS: Dict[str, WorkflowConfig] = {
    "routing": WorkflowConfig(
        name="routing",
        description="Route a source to a destination display",
        expected_endpoints=[
            "/api/devices/videoSources",
            "/api/devices/displays",
            "/api/room/settings",
            "/api/room/route",
            "/api/room/unroute",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#control-tab", "#control-webview-container"],
    ),
    "audio_routing": WorkflowConfig(
        name="audio_routing",
        description="Route an audio source to a speaker and unroute it",
        expected_endpoints=[
            "/api/devices/audioSources",
            "/api/devices/speakers",
            "/api/room/route",
            "/api/room/unroute",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#control-tab", "#control-webview-container"],
    ),
    "presets": WorkflowConfig(
        name="presets",
        description="Apply a preset to recall a room configuration",
        expected_endpoints=[
            "/api/room/presets",
            "/api/room/settings",
            "/api/devices/displays",
            "/api/devices/videoSources",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#control-tab", "#control-webview-container"],
    ),
    "camera": WorkflowConfig(
        name="camera",
        description="Move camera and recall camera preset",
        expected_endpoints=[
            "/api/cameras/{id}",
            "/api/cameras/{id}/status",
            "/api/cameras/{id}/move",
            "/api/cameras/{id}/presets/call",
            "/api/cameras/{id}/previewImg",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#control-tab", "#control-webview-container"],
    ),
    "layouts": WorkflowConfig(
        name="layouts",
        description="Change display layout",
        expected_endpoints=[
            "/api/devices/displays",
            "/api/room/settings",
            "/api/devices/displays/{id}/changeLayout",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#control-tab", "#control-webview-container"],
    ),
    "speakers": WorkflowConfig(
        name="speakers",
        description="Mute/unmute and change speaker volume",
        expected_endpoints=[
            "/api/devices/speakers",
            "/api/devices/audioSources",
            "/api/room/settings",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#control-tab", "#control-webview-container"],
    ),
    "settings": WorkflowConfig(
        name="settings",
        description="Rename a display, speaker, audio source, and video source via the admin room-settings endpoint, and revert each",
        expected_endpoints=[
            "/api/devices/displays",
            "/api/room/settings",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#settings-icon"],
    ),
    "sharing": WorkflowConfig(
        name="sharing",
        description="Grant then revoke sharing of a local video source with another room",
        expected_endpoints=[
            "/api/room",
            "/api/room/list",
            "/api/devices/videoSources",
            "/api/room/share",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#control-tab", "#control-webview-container"],
    ),
    "room_camera": WorkflowConfig(
        name="room_camera",
        description="Test the room camera's connection and round-trip its settings save",
        expected_endpoints=[
            "/api/room/settings",
            "/api/cameras/{id}/testConnection",
        ],
        sla=WorkflowSLA(api_ms=500, ui_ms=2000, total_ms=2500),
        selectors=["#settings-icon"],
    ),
}


def get_workflow(name: str) -> WorkflowConfig:
    if name not in WORKFLOWS:
        raise ValueError(f"Unknown workflow '{name}'. Available: {list_workflows()}")
    return WORKFLOWS[name]


def list_workflows() -> List[str]:
    return list(WORKFLOWS.keys())
