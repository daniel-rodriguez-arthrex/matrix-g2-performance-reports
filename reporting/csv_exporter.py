import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class CsvExporter:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _write_csv(self, filename: str, rows: List[Dict[str, Any]], fieldnames: List[str]) -> Path:
        path = self.output_dir / filename
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
        return path

    def export_api_calls(self, calls: List[Dict[str, Any]], timestamp: str, room: str, workflow: str) -> Path:
        fieldnames = [
            "Timestamp", "Room", "Workflow", "Method", "Url", "Status",
            "DurationMs", "DnsMs", "ConnectMs", "TlsMs", "RequestMs", "ResponseMs",
            "RequestPayload", "ResponseBody", "IsValid", "ApiError", "Error",
        ]
        rows = []
        for call in calls:
            rows.append({
                "Timestamp": timestamp,
                "Room": room,
                "Workflow": workflow,
                "Method": call.get("method"),
                "Url": call.get("url"),
                "Status": call.get("status"),
                "DurationMs": call.get("duration_ms"),
                "DnsMs": call.get("dns_ms"),
                "ConnectMs": call.get("connect_ms"),
                "TlsMs": call.get("tls_ms"),
                "RequestMs": call.get("request_ms"),
                "ResponseMs": call.get("response_ms"),
                "RequestPayload": _safe_json(call.get("request_payload")),
                "ResponseBody": _safe_json(call.get("response_body")),
                "IsValid": call.get("is_valid"),
                "ApiError": call.get("api_error"),
                "Error": call.get("error"),
            })
        return self._write_csv("api_calls.csv", rows, fieldnames)

    def export_endpoints(self, endpoints: List[Dict[str, Any]]) -> Path:
        fieldnames = ["Endpoint", "Method", "Count", "SamplePayload", "SampleResponse"]
        rows = []
        for ep in endpoints:
            rows.append({
                "Endpoint": ep.get("url"),
                "Method": ep.get("method"),
                "Count": ep.get("count"),
                "SamplePayload": _safe_json(ep.get("sample_payload")),
                "SampleResponse": _safe_json(ep.get("sample_response")),
            })
        return self._write_csv("endpoints.csv", rows, fieldnames)

    def export_selectors(self, results: List[Dict[str, Any]]) -> Path:
        fieldnames = ["Selector", "Strategy", "Found", "Visible", "Count", "Suggested", "Error"]
        rows = []
        for r in results:
            rows.append({
                "Selector": r.get("selector"),
                "Strategy": r.get("strategy"),
                "Found": r.get("found"),
                "Visible": r.get("visible"),
                "Count": r.get("count"),
                "Suggested": r.get("suggested"),
                "Error": r.get("error"),
            })
        return self._write_csv("selectors.csv", rows, fieldnames)

    def export_ui_timings(self, timings: List[Dict[str, Any]], timestamp: str, room: str, workflow: str) -> Path:
        fieldnames = ["Timestamp", "Room", "Workflow", "Label", "Selector", "DurationMs", "Success", "Error"]
        rows = []
        for t in timings:
            rows.append({
                "Timestamp": timestamp,
                "Room": room,
                "Workflow": workflow,
                "Label": t.get("label"),
                "Selector": t.get("selector"),
                "DurationMs": t.get("duration_ms"),
                "Success": t.get("success"),
                "Error": t.get("error"),
            })
        return self._write_csv("ui_timings.csv", rows, fieldnames)

    def export_websocket_frames(
        self,
        frames: List[Dict[str, Any]],
        timestamp: str,
        room: str,
        workflow: str,
    ) -> Path:
        fieldnames = ["Timestamp", "Room", "Workflow", "Direction", "Url", "Payload"]
        rows = []
        for frame in frames:
            rows.append({
                "Timestamp": timestamp,
                "Room": room,
                "Workflow": workflow,
                "Direction": frame.get("direction"),
                "Url": frame.get("url"),
                "Payload": _safe_json(frame.get("payload")),
            })
        return self._write_csv("websocket_frames.csv", rows, fieldnames)

    def export_summary(
        self,
        summary: Dict[str, Any],
        timestamp: str,
        room: str,
        workflow: str,
    ) -> Path:
        fieldnames = [
            "Timestamp", "Room", "Workflow", "Runs", "AvgTotalMs",
            "MinTotalMs", "MaxTotalMs", "P95TotalMs", "TotalApiCalls",
            "ApiThresholdMs", "ApiPass", "ValidationFailures",
        ]
        rows = [{
            "Timestamp": timestamp,
            "Room": room,
            "Workflow": workflow,
            "Runs": summary.get("runs"),
            "AvgTotalMs": summary.get("avg_total_ms"),
            "MinTotalMs": summary.get("min_total_ms"),
            "MaxTotalMs": summary.get("max_total_ms"),
            "P95TotalMs": summary.get("p95_total_ms"),
            "TotalApiCalls": summary.get("total_api_calls"),
            "ApiThresholdMs": summary.get("api_threshold_ms"),
            "ApiPass": summary.get("api_pass"),
            "ValidationFailures": summary.get("validation_failures"),
        }]
        return self._write_csv("summary.csv", rows, fieldnames)


def _safe_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)
