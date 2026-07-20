import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ActionMetrics:
    """Record action-level performance metrics for Matrix G2 workflows.

    An action represents a user-intent operation such as "route source to display",
    "change layout to PIP", or "move camera up". Each action captures the time
    from intent to API response and optionally to a verified UI state change.
    """

    name: str
    action_type: str
    start_time: float = 0.0
    end_time: float = 0.0
    api_duration_ms: Optional[float] = None
    ui_duration_ms: Optional[float] = None
    total_duration_ms: Optional[float] = None
    api_calls: List[str] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    before_state: Dict[str, Any] = field(default_factory=dict)
    after_state: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ActionCollector:
    """Collects and summarizes action metrics for a workflow run."""

    def __init__(self):
        self.actions: List[ActionMetrics] = []
        self._current: Optional[ActionMetrics] = None

    def reset(self) -> None:
        self.actions = []
        self._current = None

    def start_action(
        self,
        name: str,
        action_type: str,
        before_state: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> ActionMetrics:
        action = ActionMetrics(
            name=name,
            action_type=action_type,
            start_time=time.perf_counter(),
            before_state=before_state or {},
            details=details or {},
        )
        self._current = action
        self.actions.append(action)
        return action

    def end_action(
        self,
        success: bool = True,
        error: Optional[str] = None,
        after_state: Optional[Dict[str, Any]] = None,
        api_calls: Optional[List[str]] = None,
        api_duration_ms: Optional[float] = None,
        ui_duration_ms: Optional[float] = None,
    ) -> ActionMetrics:
        if self._current is None:
            raise RuntimeError("end_action called without start_action")
        action = self._current
        action.end_time = time.perf_counter()
        action.total_duration_ms = (action.end_time - action.start_time) * 1000
        action.success = success
        action.error = error
        action.after_state = after_state or {}
        action.api_calls = api_calls or []
        action.api_duration_ms = api_duration_ms
        action.ui_duration_ms = ui_duration_ms
        self._current = None
        return action

    def get_summary(self) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self.actions]
