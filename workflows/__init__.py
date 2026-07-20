"""Workflow registry for Matrix G2 automated scenarios."""

from typing import Any, Dict, List

from . import audio_routing, camera, layouts, presets, routing, settings, speakers

WORKFLOW_FUNCTIONS = {
    "routing": routing.run,
    "audio_routing": audio_routing.run,
    "presets": presets.run,
    "camera": camera.run,
    "layouts": layouts.run,
    "speakers": speakers.run,
    "settings": settings.run,
}


def list_workflows() -> List[str]:
    return list(WORKFLOW_FUNCTIONS.keys())


def run(
    name: str,
    session,
    interceptor,
    ui_monitor=None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Dispatch a workflow by name."""
    if name not in WORKFLOW_FUNCTIONS:
        raise ValueError(f"Unknown workflow '{name}'. Available: {list_workflows()}")
    return WORKFLOW_FUNCTIONS[name](session, interceptor, ui_monitor, **kwargs)
