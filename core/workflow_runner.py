from typing import Any, Dict, List, Optional

from config.workflows import get_workflow, list_workflows
from metrics.action_metrics import ActionCollector
from metrics.api_interceptor import ApiInterceptor
from workflows import run as run_workflow


class WorkflowRunner:
    def __init__(
        self,
        session,
        interceptor: ApiInterceptor,
        ui_monitor=None,
    ):
        self.session = session
        self.interceptor = interceptor
        self.ui_monitor = ui_monitor
        self.action_collector = ActionCollector()

    async def run(self, workflow_name: str, iterations: int = 1, **kwargs: Any) -> List[Dict[str, Any]]:
        if workflow_name == "all":
            workflow_names = list_workflows()
        else:
            workflow_names = [workflow_name]
        results = []
        for i in range(iterations):
            self.interceptor.reset()
            self.action_collector.reset()
            if self.ui_monitor is not None:
                self.ui_monitor.reset()
            for name in workflow_names:
                await run_workflow(
                    name,
                    self.session,
                    self.interceptor,
                    self.ui_monitor,
                    action_collector=self.action_collector,
                    **kwargs,
                )
            summary = self.interceptor.get_summary()
            summary["actions"] = self.action_collector.get_summary()
            results.append(summary)
        return results
